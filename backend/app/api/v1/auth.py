"""
Auth API — POST /auth/* 엔드포인트 모음.

레이어 규칙: Route는 요청 파싱과 응답 직렬화만 담당한다.
모든 로직은 AuthService에 위임한다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUserDep, DbDep, RedisDep
from app.core.config import settings
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageData,
    RefreshData,
    RegisterData,
    RegisterRequest,
    ResendData,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenData,
    TwoFactorDisableRequest,
    TwoFactorEnableData,
    TwoFactorStatusData,
    TwoFactorVerifyRequest,
    VerifyEmailRequest,
)
from app.schemas.common import DataResponse
from app.services.auth_service import AuthService, _build_user_in_token

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

_REFRESH_COOKIE_KEY = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"
_REFRESH_COOKIE_MAX_AGE = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE_KEY,
        value=raw_token,
        httponly=True,
        secure=settings.is_production,   # 개발 환경: http 허용
        samesite="strict",
        path=_REFRESH_COOKIE_PATH,
        max_age=_REFRESH_COOKIE_MAX_AGE,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE_KEY,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
    )


def _get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _get_device_info(request: Request) -> str | None:
    ua = request.headers.get("User-Agent", "")
    return ua[:500] if ua else None


# ════════════════════════════════════════════════════════════════
# 공개 엔드포인트 (인증 불필요)
# ════════════════════════════════════════════════════════════════

@router.post(
    "/register",
    response_model=DataResponse[RegisterData],
    status_code=status.HTTP_201_CREATED,
    summary="회원가입",
)
async def register(
    body: RegisterRequest,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[RegisterData]:
    svc = AuthService(db=db, redis=redis)
    user = await svc.register(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
    )
    return DataResponse(
        data=RegisterData(
            user_id=user.id,
            email=user.email,
            message="인증 이메일이 발송되었습니다. 5분 내에 확인해주세요.",
        )
    )


@router.post(
    "/verify-email",
    response_model=DataResponse[TokenData],
    summary="이메일 인증 코드 확인",
)
async def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    db: DbDep,
    redis: RedisDep,
) -> Response:
    svc = AuthService(db=db, redis=redis)
    access_token, raw_refresh, user = await svc.verify_email(
        email=body.email,
        code=body.code,
        request_ip=_get_client_ip(request),
        device_info=_get_device_info(request),
    )
    content = DataResponse(
        data=TokenData(
            access_token=access_token,
            user=_build_user_in_token(user),
        )
    ).model_dump(mode="json")

    response = JSONResponse(content=content)
    _set_refresh_cookie(response, raw_refresh)
    return response


@router.post(
    "/resend-verification",
    response_model=DataResponse[ResendData],
    summary="인증 이메일 재발송",
)
async def resend_verification(
    body: ResendVerificationRequest,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[ResendData]:
    svc = AuthService(db=db, redis=redis)
    await svc.resend_verification(email=body.email)
    return DataResponse(
        data=ResendData(
            message="인증 이메일이 재발송되었습니다.",
            expires_in=300,
        )
    )


@router.post(
    "/login",
    response_model=DataResponse[TokenData],
    summary="로그인",
)
async def login(
    body: LoginRequest,
    request: Request,
    db: DbDep,
    redis: RedisDep,
) -> Response:
    svc = AuthService(db=db, redis=redis)
    access_token, raw_refresh, user = await svc.login(
        email=body.email,
        password=body.password,
        totp_code=body.totp_code,
        request_ip=_get_client_ip(request),
        device_info=_get_device_info(request),
    )
    content = DataResponse(
        data=TokenData(
            access_token=access_token,
            user=_build_user_in_token(user),
        )
    ).model_dump(mode="json")

    response = JSONResponse(content=content)
    _set_refresh_cookie(response, raw_refresh)
    return response


@router.post(
    "/refresh",
    response_model=DataResponse[RefreshData],
    summary="Access Token 갱신",
)
async def refresh(
    db: DbDep,
    redis: RedisDep,
    refresh_token: str | None = Cookie(None, alias=_REFRESH_COOKIE_KEY),
) -> DataResponse[RefreshData]:
    from app.utils.exceptions import UnauthorizedError

    if not refresh_token:
        raise UnauthorizedError(
            code="AUTH_004", message="세션이 만료되었습니다. 다시 로그인해주세요."
        )

    svc = AuthService(db=db, redis=redis)
    new_access_token = await svc.refresh_access_token(refresh_token)
    return DataResponse(data=RefreshData(access_token=new_access_token))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="로그아웃",
)
async def logout(
    db: DbDep,
    redis: RedisDep,
    refresh_token: str | None = Cookie(None, alias=_REFRESH_COOKIE_KEY),
) -> Response:
    svc = AuthService(db=db, redis=redis)
    await svc.logout(refresh_token)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.post(
    "/forgot-password",
    response_model=DataResponse[MessageData],
    summary="비밀번호 재설정 요청",
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[MessageData]:
    svc = AuthService(db=db, redis=redis)
    await svc.forgot_password(email=body.email)
    return DataResponse(
        data=MessageData(message="비밀번호 재설정 링크가 발송되었습니다.")
    )


@router.post(
    "/reset-password",
    response_model=DataResponse[MessageData],
    summary="비밀번호 재설정",
)
async def reset_password(
    body: ResetPasswordRequest,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[MessageData]:
    svc = AuthService(db=db, redis=redis)
    await svc.reset_password(token=body.token, new_password=body.new_password)
    return DataResponse(
        data=MessageData(message="비밀번호가 재설정되었습니다. 다시 로그인해주세요.")
    )


# ════════════════════════════════════════════════════════════════
# 인증 필요 엔드포인트 — 2FA
# ════════════════════════════════════════════════════════════════

@router.post(
    "/2fa/enable",
    response_model=DataResponse[TwoFactorEnableData],
    summary="2FA 활성화 요청 (QR 코드 반환)",
)
async def enable_2fa(
    current_user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[TwoFactorEnableData]:
    svc = AuthService(db=db, redis=redis)
    uri, qr_image, secret, plain_codes = await svc.enable_2fa_start(current_user)
    return DataResponse(
        data=TwoFactorEnableData(
            qr_code_url=uri,
            qr_code_image=qr_image,
            secret=secret,
            backup_codes=plain_codes,
        )
    )


@router.post(
    "/2fa/verify",
    response_model=DataResponse[TwoFactorStatusData],
    summary="2FA 활성화 확인 (TOTP 코드 검증)",
)
async def verify_2fa(
    body: TwoFactorVerifyRequest,
    current_user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[TwoFactorStatusData]:
    svc = AuthService(db=db, redis=redis)
    await svc.verify_2fa_setup(user=current_user, totp_code=body.totp_code)
    return DataResponse(
        data=TwoFactorStatusData(
            is_2fa_enabled=True,
            message="2단계 인증이 활성화되었습니다.",
        )
    )


@router.post(
    "/2fa/disable",
    response_model=DataResponse[TwoFactorStatusData],
    summary="2FA 비활성화",
)
async def disable_2fa(
    body: TwoFactorDisableRequest,
    current_user: CurrentUserDep,
    db: DbDep,
    redis: RedisDep,
) -> DataResponse[TwoFactorStatusData]:
    svc = AuthService(db=db, redis=redis)
    await svc.disable_2fa(
        user=current_user,
        totp_code=body.totp_code,
        password=body.password,
    )
    return DataResponse(
        data=TwoFactorStatusData(
            is_2fa_enabled=False,
            message="2단계 인증이 비활성화되었습니다.",
        )
    )
