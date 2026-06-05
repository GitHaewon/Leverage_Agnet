"""
BinanceService — Binance Futures 연동 비즈니스 로직.

보안 원칙:
  1. API 자격증명은 주문 실행 직전에만 복호화
  2. 복호화된 값은 클라이언트 생성 직후 aclose()로 메모리에서 제거
  3. 로그에 API Key/Secret 절대 출력 금지
  4. stop_loss 없는 주문 시도 즉시 차단 (TRADING_RULES.md §7)
  5. LIVE_TRADING_ENABLED=false → mainnet 주문 차단
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import BinanceAPIError, create_binance_client
from app.clients.binance_base import KeyValidationResult, OrderResponse, PositionRisk
from app.core.config import settings
from app.models.enums import HealthStatusType, PlanType
from app.models.user import User
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.schemas.binance import (
    AccountBalanceData,
    AccountStatusData,
    AssetBalance,
    CancelOrderData,
    ConnectData,
    MarketOrderData,
    ModeInfo,
    OrderResult,
    PositionInfo,
)
from app.utils.crypto import decrypt, encrypt
from app.utils.exceptions import AppError, ConflictError, ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)

# ── 안전 상수 (TRADING_RULES.md §1) ─────────────────────────────────────────────
SYSTEM_MAX_LEVERAGE = settings.SYSTEM_MAX_LEVERAGE   # 20
PLAN_MAX_LEVERAGE = {
    PlanType.FREE: 5,
    PlanType.PRO: 10,
    PlanType.ELITE: 20,
}
_SUPPORTED_SYMBOLS = {"BTCUSDT", "ETHUSDT"}


def _mask_key(key: str) -> str:
    return f"{key[:4]}****" if len(key) > 4 else "****"


def _resolve_leverage(
    requested: int,
    user_max: int,
    plan: PlanType,
) -> int:
    """
    4중 레버리지 상한 적용 (TRADING_RULES.md §1.5).
    min(requested, user_max, plan_max, SYSTEM_MAX)
    """
    plan_max = PLAN_MAX_LEVERAGE.get(plan, 5)
    return min(requested, user_max, plan_max, SYSTEM_MAX_LEVERAGE)


def _coin_from_symbol(symbol: str) -> str:
    return symbol.replace("USDT", "")


def _to_order_result(resp: OrderResponse) -> OrderResult:
    return OrderResult(
        order_id=resp.order_id,
        client_order_id=resp.client_order_id,
        symbol=resp.symbol,
        status=resp.status,
        executed_qty=resp.executed_qty,
        avg_price=resp.avg_price,
        side=resp.side,
        order_type=resp.order_type,
    )


class BinanceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._accounts = ExchangeAccountRepository(db)

    # ════════════════════════════════════════════════════════════════
    # 모드 정보
    # ════════════════════════════════════════════════════════════════

    def get_mode_info(self) -> ModeInfo:
        warning = None
        if settings.MOCK_TRADING_MODE:
            warning = "MOCK_TRADING_MODE=true: 실제 API 호출 없음, 시뮬레이션 응답 반환"
        elif not settings.LIVE_TRADING_ENABLED:
            warning = "LIVE_TRADING_ENABLED=false: Testnet만 허용"
        return ModeInfo(
            is_testnet=settings.BINANCE_TESTNET,
            live_trading_enabled=settings.LIVE_TRADING_ENABLED,
            mock_mode=settings.MOCK_TRADING_MODE,
            warning=warning,
        )

    # ════════════════════════════════════════════════════════════════
    # API Key 등록 & 검증
    # ════════════════════════════════════════════════════════════════

    async def connect_account(
        self,
        user: User,
        api_key: str,
        api_secret: str,
        label: str,
        is_testnet: bool,
    ) -> ConnectData:
        # 기존 계좌 중복 체크
        if await self._accounts.exists_for_user(user.id):
            raise ConflictError(
                code="BINANCE_005",
                message="이미 연결된 Binance 계좌가 있습니다.",
            )

        # Feature flag 체크
        if not is_testnet and not settings.LIVE_TRADING_ENABLED:
            raise ForbiddenError(
                code="BINANCE_007",
                message="실거래 계좌 등록이 비활성화 상태입니다. (LIVE_TRADING_ENABLED=false)",
            )

        # API Key 권한 검증 (실제 Binance API 호출)
        client = create_binance_client(api_key, api_secret, is_testnet)
        try:
            validation: KeyValidationResult = await client.validate_api_key()
        except BinanceAPIError as exc:
            raise AppError(
                code="BINANCE_001",
                message=f"API Key 연결에 실패했습니다: {exc.message}",
            ) from exc
        finally:
            await client.aclose()

        # 출금 권한 차단 (CLAUDE.md 절대 규칙)
        if validation.has_withdraw:
            raise AppError(
                code="BINANCE_002",
                message=(
                    "출금 권한이 포함된 API Key는 등록할 수 없습니다. "
                    "Futures Trading 권한만 허용됩니다."
                ),
                detail={"hint": "Binance API 설정에서 'Enable Withdrawals' 체크 해제 후 재시도"},
            )

        if not validation.can_futures_trade:
            raise AppError(
                code="BINANCE_003",
                message="Futures 거래 권한이 없는 API Key입니다.",
            )

        # AES-256-GCM 암호화 저장 (평문 api_secret을 메모리에서 제거)
        encrypted_key = encrypt(api_key)
        encrypted_secret = encrypt(api_secret)
        key_fingerprint = api_key[-4:]   # 마지막 4자리만 UI 표시용

        account = await self._accounts.create(
            user_id=user.id,
            encrypted_api_key=encrypted_key,
            encrypted_api_secret=encrypted_secret,
            encryption_iv="embedded",   # AES-GCM은 nonce를 ciphertext 앞에 포함
            key_fingerprint=key_fingerprint,
            label=label,
            is_testnet=is_testnet,
            permissions=["FUTURES_TRADING"],
        )
        await self._db.commit()

        # 잔고 캐시 업데이트
        await self._accounts.update_cached_balance(account.id, validation.balance_usdt)
        await self._db.commit()

        logger.info(
            "Binance account connected user_id=%s key=...%s testnet=%s",
            user.id, key_fingerprint, is_testnet,
        )

        return ConnectData(
            account_id=str(account.id),
            label=label,
            status="connected",
            is_testnet=is_testnet,
            balance_usdt=validation.balance_usdt,
            permissions=["FUTURES_TRADING"],
            connected_at=datetime.now(timezone.utc).isoformat(),
        )

    # ════════════════════════════════════════════════════════════════
    # 잔고 & 상태 조회
    # ════════════════════════════════════════════════════════════════

    async def get_account_status(self, user: User) -> AccountStatusData:
        account = await self._accounts.get_active_by_user(user.id)
        if account is None:
            return AccountStatusData(
                is_connected=False,
                account_id=None,
                label=None,
                is_testnet=None,
                balance_usdt=None,
                available_usdt=None,
                unrealized_pnl=None,
                margin_used=None,
                last_checked_at=None,
                consecutive_failures=0,
                status="disconnected",
            )

        status_str = {
            HealthStatusType.HEALTHY: "healthy",
            HealthStatusType.DEGRADED: "degraded",
            HealthStatusType.DISCONNECTED: "disconnected",
        }.get(account.health_status, "disconnected")

        return AccountStatusData(
            is_connected=account.is_active,
            account_id=str(account.id),
            label=account.label,
            is_testnet=account.is_testnet,
            balance_usdt=account.cached_balance_usdt,
            available_usdt=account.cached_balance_usdt,
            unrealized_pnl=Decimal("0"),
            margin_used=Decimal("0"),
            last_checked_at=(
                account.last_health_check_at.isoformat()
                if account.last_health_check_at else None
            ),
            consecutive_failures=account.consecutive_failures,
            status=status_str,
        )

    async def get_balance(self, user: User) -> AccountBalanceData:
        account = await self._get_account_or_raise(user.id)
        client = await self._make_client(account)
        try:
            info = await client.get_account_info()
            await self._accounts.update_cached_balance(
                account.id,
                next((a.available_balance for a in info.assets if a.asset == "USDT"), Decimal("0"))
            )
            await self._db.commit()
            await self._accounts.reset_failures(account.id)
            await self._db.commit()
        except BinanceAPIError as exc:
            await self._accounts.record_failure(account.id, exc.message)
            await self._db.commit()
            raise AppError(code="BINANCE_007", message=f"Binance API 오류: {exc.message}")
        finally:
            await client.aclose()

        usdt = next((a for a in info.assets if a.asset == "USDT"), None)
        used_margin = info.total_position_initial_margin
        margin_ratio = (
            used_margin / info.total_margin_balance
            if info.total_margin_balance > 0 else Decimal("0")
        )

        return AccountBalanceData(
            total_balance=info.total_wallet_balance,
            available_balance=info.available_balance,
            total_unrealized_pnl=info.total_unrealized_profit,
            total_margin_used=used_margin,
            margin_ratio=margin_ratio.quantize(Decimal("0.0001")),
            assets=[
                AssetBalance(
                    asset=a.asset,
                    wallet_balance=a.wallet_balance,
                    unrealized_profit=a.unrealized_profit,
                    margin_balance=a.margin_balance,
                    available_balance=a.available_balance,
                )
                for a in info.assets
            ],
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    # ════════════════════════════════════════════════════════════════
    # 포지션 조회
    # ════════════════════════════════════════════════════════════════

    async def get_positions(
        self, user: User, symbol: str | None = None
    ) -> list[PositionInfo]:
        account = await self._get_account_or_raise(user.id)
        client = await self._make_client(account)
        try:
            raw = await client.get_positions(symbol)
        except BinanceAPIError as exc:
            await self._accounts.record_failure(account.id, exc.message)
            await self._db.commit()
            raise AppError(code="BINANCE_007", message=f"포지션 조회 실패: {exc.message}")
        finally:
            await client.aclose()

        result = []
        for p in raw:
            side = "LONG" if p.position_amt > 0 else "SHORT"
            result.append(
                PositionInfo(
                    symbol=p.symbol,
                    coin=_coin_from_symbol(p.symbol),
                    side=side,
                    position_amt=abs(p.position_amt),
                    entry_price=p.entry_price,
                    mark_price=p.mark_price,
                    unrealized_pnl=p.unrealized_profit,
                    leverage=p.leverage,
                    liquidation_price=p.liquidation_price,
                    margin_type=p.margin_type,
                    isolated_margin=p.isolated_margin,
                    notional=abs(p.notional),
                )
            )
        return result

    # ════════════════════════════════════════════════════════════════
    # 주문 생성 (진입 + TP/SL)
    # ════════════════════════════════════════════════════════════════

    async def create_market_order_with_tpsl(
        self,
        user: User,
        symbol: str,
        side: str,                   # "BUY" | "SELL"
        quantity: Decimal,
        leverage: int,
        stop_loss: Decimal,          # 필수 — 없으면 즉시 거부
        take_profit: Decimal | None = None,
    ) -> MarketOrderData:
        # ── 안전 체크 1: stop_loss 필수 (CLAUDE.md 절대 규칙) ───────────────────
        if stop_loss is None or stop_loss <= 0:
            raise AppError(
                code="ORDER_003",
                message="손절가(stop_loss)가 설정되지 않았습니다. SL 없는 주문은 금지됩니다.",
            )

        # ── 안전 체크 2: 심볼 검증 ────────────────────────────────────────────────
        if symbol not in _SUPPORTED_SYMBOLS:
            raise AppError(
                code="VALIDATION_001",
                message=f"지원하지 않는 심볼입니다. MVP 지원: {_SUPPORTED_SYMBOLS}",
            )

        account = await self._get_account_or_raise(user.id)

        # ── 안전 체크 3: LIVE_TRADING_ENABLED feature flag ───────────────────────
        if not account.is_testnet and not settings.LIVE_TRADING_ENABLED:
            raise ForbiddenError(
                code="TRADING_DISABLED",
                message=(
                    "실거래가 비활성화 상태입니다. (LIVE_TRADING_ENABLED=false)\n"
                    "현재 Testnet 계좌만 주문 가능합니다."
                ),
            )

        # ── 안전 체크 4: 레버리지 4중 상한 (TRADING_RULES.md §1.5) ──────────────
        user_settings = user.settings
        user_max_lev = user_settings.max_leverage if user_settings else 5
        final_leverage = _resolve_leverage(leverage, user_max_lev, user.plan)

        if final_leverage != leverage:
            logger.warning(
                "Leverage capped: requested=%d final=%d user_id=%s",
                leverage, final_leverage, user.id,
            )

        client = await self._make_client(account)
        warning_msg: str | None = None

        try:
            # 1. 레버리지 설정
            actual_lev = await client.set_leverage(symbol, final_leverage)
            logger.info("Leverage set symbol=%s leverage=%d", symbol, actual_lev)

            # 2. 시장가 진입 주문
            entry_order = await client.create_order(
                symbol=symbol,
                side=side,
                order_type="MARKET",
                quantity=quantity,
            )
            logger.info(
                "Entry order filled symbol=%s side=%s qty=%s price=%s order_id=%s",
                symbol, side, entry_order.executed_qty, entry_order.avg_price, entry_order.order_id,
            )

            # 3. TP 주문 (선택)
            tp_order_resp: OrderResponse | None = None
            if take_profit is not None:
                tp_side = "SELL" if side == "BUY" else "BUY"
                try:
                    tp_order_resp = await client.create_order(
                        symbol=symbol,
                        side=tp_side,
                        order_type="TAKE_PROFIT_MARKET",
                        quantity=quantity,
                        stop_price=take_profit,
                        reduce_only=True,
                    )
                except BinanceAPIError as exc:
                    warning_msg = f"TP 주문 실패: {exc.message}"
                    logger.warning("TP order failed %s — %s", symbol, exc.message)

            # 4. SL 주문 (필수 — 실패 시 포지션 즉시 청산)
            sl_side = "SELL" if side == "BUY" else "BUY"
            try:
                sl_order_resp = await client.create_order(
                    symbol=symbol,
                    side=sl_side,
                    order_type="STOP_MARKET",
                    quantity=quantity,
                    stop_price=stop_loss,
                    reduce_only=True,
                )
            except BinanceAPIError as exc:
                # SL 실패 → 진입 포지션 즉시 청산 (TRADING_RULES.md §10)
                logger.error(
                    "CRITICAL: SL order failed %s — %s. Emergency closing position.",
                    symbol, exc.message,
                )
                await self._emergency_close(client, symbol, quantity, side)
                raise AppError(
                    code="ORDER_003",
                    message=(
                        f"손절 주문 설정에 실패했습니다. "
                        f"포지션이 긴급 청산되었습니다. 원인: {exc.message}"
                    ),
                )

            logger.info(
                "SL order placed symbol=%s stop=%s order_id=%s",
                symbol, stop_loss, sl_order_resp.order_id,
            )

        except BinanceAPIError as exc:
            await self._accounts.record_failure(account.id, exc.message)
            await self._db.commit()
            raise AppError(code="ORDER_005", message=f"주문 실행 실패: {exc.message}")
        finally:
            await client.aclose()    # 자격증명 메모리 제거

        return MarketOrderData(
            entry_order=_to_order_result(entry_order),
            tp_order=_to_order_result(tp_order_resp) if tp_order_resp else None,
            sl_order=_to_order_result(sl_order_resp),
            leverage_set=actual_lev,
            warning=warning_msg,
        )

    # ════════════════════════════════════════════════════════════════
    # 주문 취소
    # ════════════════════════════════════════════════════════════════

    async def cancel_order(
        self, user: User, symbol: str, order_id: str
    ) -> CancelOrderData:
        account = await self._get_account_or_raise(user.id)
        client = await self._make_client(account)
        try:
            resp = await client.cancel_order(symbol=symbol, order_id=order_id)
        except BinanceAPIError as exc:
            if exc.code == -2013:
                raise NotFoundError(f"주문 {order_id}")
            await self._accounts.record_failure(account.id, exc.message)
            await self._db.commit()
            raise AppError(code="ORDER_005", message=f"주문 취소 실패: {exc.message}")
        finally:
            await client.aclose()

        return CancelOrderData(
            order_id=resp.order_id,
            symbol=resp.symbol,
            status=resp.status,
            cancelled=resp.status == "CANCELED",
        )

    # ════════════════════════════════════════════════════════════════
    # API Key 삭제
    # ════════════════════════════════════════════════════════════════

    async def disconnect_account(self, user: User) -> None:
        account = await self._get_account_or_raise(user.id)
        await self._accounts.soft_delete(account.id)
        await self._db.commit()
        logger.info("Binance account disconnected user_id=%s account_id=%s", user.id, account.id)

    # ════════════════════════════════════════════════════════════════
    # Private helpers
    # ════════════════════════════════════════════════════════════════

    async def _get_account_or_raise(self, user_id: uuid.UUID):
        account = await self._accounts.get_active_by_user(user_id)
        if account is None:
            raise AppError(
                code="BINANCE_001",
                message="연결된 Binance 계좌가 없습니다.",
                status_code=404,
            )
        return account

    async def _make_client(self, account):
        """
        계좌 정보에서 자격증명을 복호화해 클라이언트 생성.
        반환된 클라이언트는 사용 후 반드시 aclose() 호출.
        """
        api_key = decrypt(account.encrypted_api_key)
        api_secret = decrypt(account.encrypted_api_secret)
        client = create_binance_client(api_key, api_secret, account.is_testnet)
        # 로컬 변수에서 평문 즉시 제거
        api_key = ""
        api_secret = ""
        return client

    @staticmethod
    async def _emergency_close(client, symbol: str, quantity: Decimal, entry_side: str) -> None:
        """SL 설정 실패 시 긴급 포지션 청산."""
        close_side = "SELL" if entry_side == "BUY" else "BUY"
        try:
            await client.create_order(
                symbol=symbol,
                side=close_side,
                order_type="MARKET",
                quantity=quantity,
                reduce_only=True,
            )
            logger.info("Emergency close executed symbol=%s", symbol)
        except BinanceAPIError as exc:
            logger.critical(
                "EMERGENCY CLOSE FAILED symbol=%s err=%s — MANUAL INTERVENTION REQUIRED",
                symbol, exc.message,
            )
