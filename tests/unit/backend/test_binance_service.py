"""
BinanceService 단위 테스트.
MOCK_TRADING_MODE=true로 실제 API 호출 없이 검증.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.binance_base import BinanceAPIError, KeyValidationResult
from app.models.enums import HealthStatusType, PlanType, RiskProfileType
from app.utils.exceptions import AppError, ForbiddenError


def _make_user(plan: PlanType = PlanType.FREE) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.plan = plan
    user.settings = MagicMock()
    user.settings.max_leverage = 5
    return user


def _make_account(is_testnet: bool = True) -> MagicMock:
    account = MagicMock()
    account.id = uuid.uuid4()
    account.is_testnet = is_testnet
    account.is_active = True
    account.health_status = HealthStatusType.HEALTHY
    account.consecutive_failures = 0
    account.encrypted_api_key = "encrypted_key"
    account.encrypted_api_secret = "encrypted_secret"
    account.cached_balance_usdt = Decimal("10000.00")
    account.last_health_check_at = None
    account.label = "Test Account"
    return account


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def mock_account_repo():
    repo = AsyncMock()
    repo.get_active_by_user = AsyncMock(return_value=None)
    repo.exists_for_user = AsyncMock(return_value=False)
    repo.create = AsyncMock()
    repo.update_cached_balance = AsyncMock()
    repo.update_health = AsyncMock()
    repo.record_failure = AsyncMock()
    repo.reset_failures = AsyncMock()
    repo.soft_delete = AsyncMock()
    return repo


def _make_service(mock_db, mock_account_repo):
    from app.services.binance_service import BinanceService
    svc = BinanceService(db=mock_db)
    svc._accounts = mock_account_repo
    return svc


# ════════════════════════════════════════════════════════════════
# 모드 정보 테스트
# ════════════════════════════════════════════════════════════════

class TestModeInfo:
    def test_mode_info_mock_warning(self, mock_db, mock_account_repo) -> None:
        svc = _make_service(mock_db, mock_account_repo)
        with patch("app.services.binance_service.settings") as mock_settings:
            mock_settings.MOCK_TRADING_MODE = True
            mock_settings.BINANCE_TESTNET = True
            mock_settings.LIVE_TRADING_ENABLED = False
            info = svc.get_mode_info()
        assert info.mock_mode is True
        assert "MOCK" in info.warning

    def test_mode_info_testnet_only_warning(self, mock_db, mock_account_repo) -> None:
        svc = _make_service(mock_db, mock_account_repo)
        with patch("app.services.binance_service.settings") as mock_settings:
            mock_settings.MOCK_TRADING_MODE = False
            mock_settings.BINANCE_TESTNET = True
            mock_settings.LIVE_TRADING_ENABLED = False
            info = svc.get_mode_info()
        assert "Testnet" in info.warning


# ════════════════════════════════════════════════════════════════
# API Key 검증 테스트
# ════════════════════════════════════════════════════════════════

class TestConnectAccount:
    async def test_withdraw_permission_blocks_registration(
        self, mock_db, mock_account_repo
    ) -> None:
        user = _make_user()
        mock_account_repo.exists_for_user.return_value = False
        svc = _make_service(mock_db, mock_account_repo)

        mock_validation = KeyValidationResult(
            can_trade=True,
            can_futures_trade=True,
            has_withdraw=True,         # 출금 권한 있음 → 등록 차단
            ip_restrict=False,
            balance_usdt=Decimal("10000"),
        )

        with patch("app.services.binance_service.create_binance_client") as mock_factory, \
             patch("app.utils.crypto.encrypt", return_value="encrypted"):
            mock_client = AsyncMock()
            mock_client.validate_api_key.return_value = mock_validation
            mock_client.aclose = AsyncMock()
            mock_factory.return_value = mock_client

            with pytest.raises(AppError) as exc:
                await svc.connect_account(
                    user=user,
                    api_key="test_key",
                    api_secret="test_secret",
                    label="Test",
                    is_testnet=True,
                )
        assert exc.value.code == "BINANCE_002"

    async def test_mainnet_blocked_when_live_trading_disabled(
        self, mock_db, mock_account_repo
    ) -> None:
        user = _make_user()
        mock_account_repo.exists_for_user.return_value = False
        svc = _make_service(mock_db, mock_account_repo)

        with patch("app.services.binance_service.settings") as mock_settings:
            mock_settings.LIVE_TRADING_ENABLED = False
            mock_settings.SYSTEM_MAX_LEVERAGE = 20
            mock_settings.MOCK_TRADING_MODE = False

            with pytest.raises(ForbiddenError) as exc:
                await svc.connect_account(
                    user=user,
                    api_key="key",
                    api_secret="secret",
                    label="Main",
                    is_testnet=False,   # mainnet 시도
                )
        assert exc.value.code == "BINANCE_007"

    async def test_duplicate_account_raises_conflict(
        self, mock_db, mock_account_repo
    ) -> None:
        user = _make_user()
        mock_account_repo.exists_for_user.return_value = True  # 이미 계좌 있음
        svc = _make_service(mock_db, mock_account_repo)

        from app.utils.exceptions import ConflictError
        with pytest.raises(ConflictError) as exc:
            await svc.connect_account(
                user=user, api_key="key", api_secret="secret",
                label="Main", is_testnet=True,
            )
        assert exc.value.code == "BINANCE_005"


# ════════════════════════════════════════════════════════════════
# 주문 생성 안전 체크 테스트
# ════════════════════════════════════════════════════════════════

class TestCreateMarketOrder:
    async def test_order_without_stop_loss_raises(
        self, mock_db, mock_account_repo
    ) -> None:
        user = _make_user()
        account = _make_account()
        mock_account_repo.get_active_by_user.return_value = account
        svc = _make_service(mock_db, mock_account_repo)

        with pytest.raises(AppError) as exc:
            await svc.create_market_order_with_tpsl(
                user=user,
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("0.01"),
                leverage=5,
                stop_loss=None,   # SL 없음 → 즉시 거부
            )
        assert exc.value.code == "ORDER_003"

    async def test_mainnet_order_blocked_without_feature_flag(
        self, mock_db, mock_account_repo
    ) -> None:
        user = _make_user()
        account = _make_account(is_testnet=False)   # mainnet 계좌
        mock_account_repo.get_active_by_user.return_value = account
        svc = _make_service(mock_db, mock_account_repo)

        with patch("app.services.binance_service.settings") as mock_settings:
            mock_settings.LIVE_TRADING_ENABLED = False
            mock_settings.SYSTEM_MAX_LEVERAGE = 20
            mock_settings.MOCK_TRADING_MODE = False

            with pytest.raises(ForbiddenError) as exc:
                await svc.create_market_order_with_tpsl(
                    user=user,
                    symbol="BTCUSDT",
                    side="BUY",
                    quantity=Decimal("0.01"),
                    leverage=5,
                    stop_loss=Decimal("65000"),
                )
        assert exc.value.code == "TRADING_DISABLED"

    async def test_leverage_capped_by_system_max(
        self, mock_db, mock_account_repo
    ) -> None:
        from app.services.binance_service import _resolve_leverage
        # Elite 플랜, user_max=20, requested=25 → capped to 20
        result = _resolve_leverage(25, 20, PlanType.ELITE)
        assert result == 20

    async def test_leverage_capped_by_plan(self, mock_db, mock_account_repo) -> None:
        from app.services.binance_service import _resolve_leverage
        # Free 플랜 최대 5x
        result = _resolve_leverage(10, 10, PlanType.FREE)
        assert result == 5

    async def test_leverage_capped_by_user_setting(
        self, mock_db, mock_account_repo
    ) -> None:
        from app.services.binance_service import _resolve_leverage
        # 사용자 max=3
        result = _resolve_leverage(10, 3, PlanType.PRO)
        assert result == 3

    async def test_mock_mode_full_order_flow(
        self, mock_db, mock_account_repo
    ) -> None:
        """MOCK_TRADING_MODE에서 전체 주문 플로우 실행."""
        user = _make_user()
        account = _make_account(is_testnet=True)
        mock_account_repo.get_active_by_user.return_value = account
        svc = _make_service(mock_db, mock_account_repo)

        from app.clients.binance_mock import BinanceMockClient

        with patch("app.services.binance_service.create_binance_client") as mock_factory, \
             patch("app.utils.crypto.decrypt", return_value="decrypted_value"), \
             patch("app.services.binance_service.settings") as mock_settings:

            mock_settings.LIVE_TRADING_ENABLED = False
            mock_settings.SYSTEM_MAX_LEVERAGE = 20
            mock_settings.MOCK_TRADING_MODE = True

            mock_client = BinanceMockClient()
            mock_factory.return_value = mock_client

            result = await svc.create_market_order_with_tpsl(
                user=user,
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("0.01"),
                leverage=5,
                stop_loss=Decimal("65000"),
                take_profit=Decimal("70000"),
            )

        assert result.entry_order.status == "FILLED"
        assert result.sl_order.status == "NEW"
        assert result.tp_order is not None
        assert result.leverage_set == 5


# ════════════════════════════════════════════════════════════════
# 주문 취소 테스트
# ════════════════════════════════════════════════════════════════

class TestCancelOrder:
    async def test_cancel_nonexistent_order_raises(
        self, mock_db, mock_account_repo
    ) -> None:
        user = _make_user()
        account = _make_account()
        mock_account_repo.get_active_by_user.return_value = account
        svc = _make_service(mock_db, mock_account_repo)

        from app.clients.binance_mock import BinanceMockClient
        with patch("app.services.binance_service.create_binance_client") as mock_factory, \
             patch("app.utils.crypto.decrypt", return_value="decrypted"):
            mock_factory.return_value = BinanceMockClient()
            from app.utils.exceptions import NotFoundError
            with pytest.raises(NotFoundError):
                await svc.cancel_order(user, "BTCUSDT", "nonexistent_order_id")


# ════════════════════════════════════════════════════════════════
# 잔고 & 상태 테스트
# ════════════════════════════════════════════════════════════════

class TestAccountStatus:
    async def test_no_account_returns_disconnected(
        self, mock_db, mock_account_repo
    ) -> None:
        user = _make_user()
        mock_account_repo.get_active_by_user.return_value = None
        svc = _make_service(mock_db, mock_account_repo)

        status = await svc.get_account_status(user)
        assert status.is_connected is False
        assert status.status == "disconnected"

    async def test_healthy_account_returns_connected(
        self, mock_db, mock_account_repo
    ) -> None:
        user = _make_user()
        account = _make_account()
        mock_account_repo.get_active_by_user.return_value = account
        svc = _make_service(mock_db, mock_account_repo)

        status = await svc.get_account_status(user)
        assert status.is_connected is True
        assert status.status == "healthy"
