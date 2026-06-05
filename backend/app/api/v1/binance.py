"""
Binance API 라우터.

레이어 규칙: Route는 요청 파싱과 응답 직렬화만 담당.
모든 비즈니스 로직은 BinanceService에 위임.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUserDep, DbDep
from app.schemas.binance import (
    AccountBalanceData,
    AccountStatusData,
    CancelOrderData,
    CancelOrderRequest,
    ConnectData,
    ConnectRequest,
    MarketOrderData,
    MarketOrderRequest,
    ModeInfo,
    PositionInfo,
)
from app.schemas.common import DataResponse
from app.services.binance_service import BinanceService

router = APIRouter(prefix="/binance", tags=["binance"])
logger = logging.getLogger(__name__)


# ── 모드 정보 ─────────────────────────────────────────────────────────────────

@router.get(
    "/mode",
    response_model=DataResponse[ModeInfo],
    summary="거래 모드 정보 (Testnet/Mock/Live)",
)
async def get_mode(current_user: CurrentUserDep, db: DbDep) -> DataResponse[ModeInfo]:
    svc = BinanceService(db=db)
    return DataResponse(data=svc.get_mode_info())


# ── API Key 연결 ──────────────────────────────────────────────────────────────

@router.post(
    "/connect",
    response_model=DataResponse[ConnectData],
    status_code=status.HTTP_201_CREATED,
    summary="Binance API Key 등록 및 검증",
)
async def connect(
    body: ConnectRequest,
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[ConnectData]:
    svc = BinanceService(db=db)
    data = await svc.connect_account(
        user=current_user,
        api_key=body.api_key,
        api_secret=body.api_secret,
        label=body.label,
        is_testnet=body.is_testnet,
    )
    return DataResponse(data=data)


@router.get(
    "/status",
    response_model=DataResponse[AccountStatusData],
    summary="거래소 계좌 연결 상태 조회",
)
async def get_status(
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[AccountStatusData]:
    svc = BinanceService(db=db)
    data = await svc.get_account_status(user=current_user)
    return DataResponse(data=data)


@router.delete(
    "/disconnect",
    response_model=DataResponse[dict],
    summary="API Key 삭제 (자동매매 중단 후)",
)
async def disconnect(
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[dict]:
    svc = BinanceService(db=db)
    await svc.disconnect_account(user=current_user)
    return DataResponse(data={"message": "Binance API 연결이 해제되었습니다."})


# ── 잔고 조회 ─────────────────────────────────────────────────────────────────

@router.get(
    "/balance",
    response_model=DataResponse[AccountBalanceData],
    summary="USDT-M 잔고 상세 조회",
)
async def get_balance(
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[AccountBalanceData]:
    svc = BinanceService(db=db)
    data = await svc.get_balance(user=current_user)
    return DataResponse(data=data)


# ── 포지션 조회 ───────────────────────────────────────────────────────────────

@router.get(
    "/positions",
    response_model=DataResponse[list[PositionInfo]],
    summary="오픈 포지션 목록 조회",
)
async def get_positions(
    current_user: CurrentUserDep,
    db: DbDep,
    symbol: str | None = Query(None, description="특정 심볼 필터 (예: BTCUSDT)"),
) -> DataResponse[list[PositionInfo]]:
    svc = BinanceService(db=db)
    positions = await svc.get_positions(user=current_user, symbol=symbol)
    return DataResponse(data=positions)


# ── 주문 생성 ─────────────────────────────────────────────────────────────────

@router.post(
    "/orders",
    response_model=DataResponse[MarketOrderData],
    status_code=status.HTTP_201_CREATED,
    summary="시장가 주문 생성 (TP/SL 포함)",
    description=(
        "**주의**: stop_loss는 필수입니다. SL 없는 주문은 시스템이 거부합니다.\n\n"
        "LIVE_TRADING_ENABLED=false (기본값) 환경에서는 Testnet 계좌만 주문 가능합니다."
    ),
)
async def create_order(
    body: MarketOrderRequest,
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[MarketOrderData]:
    svc = BinanceService(db=db)
    data = await svc.create_market_order_with_tpsl(
        user=current_user,
        symbol=body.symbol,
        side=body.side,
        quantity=body.quantity,
        leverage=body.leverage,
        stop_loss=body.stop_loss,
        take_profit=body.take_profit,
    )
    return DataResponse(data=data)


# ── 주문 취소 ─────────────────────────────────────────────────────────────────

@router.delete(
    "/orders/{order_id}",
    response_model=DataResponse[CancelOrderData],
    summary="주문 취소",
)
async def cancel_order(
    order_id: str,
    symbol: str,
    current_user: CurrentUserDep,
    db: DbDep,
) -> DataResponse[CancelOrderData]:
    svc = BinanceService(db=db)
    data = await svc.cancel_order(
        user=current_user,
        symbol=symbol,
        order_id=order_id,
    )
    return DataResponse(data=data)
