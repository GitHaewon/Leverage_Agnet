from fastapi import APIRouter

from app.api.v1 import auth, binance, health, journals, risk, signals, sizing

router = APIRouter()

router.include_router(health.router)
router.include_router(auth.router)      # prefix="/auth"
router.include_router(binance.router)   # prefix="/binance"
router.include_router(risk.router)      # prefix="/risk"
router.include_router(sizing.router)    # prefix="/sizing"
router.include_router(signals.router)   # prefix="/signals"
router.include_router(journals.router)  # prefix="/journals"

# 구현 예정 라우터 — Epic별 순서로 추가
# from app.api.v1 import users, positions, orders, trading, notifications, billing
# router.include_router(users.router, prefix="/users", tags=["users"])
# router.include_router(positions.router, prefix="/positions", tags=["positions"])
# router.include_router(orders.router, prefix="/orders", tags=["orders"])
# router.include_router(trading.router, prefix="/trading", tags=["trading"])
# router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
# router.include_router(billing.router, prefix="/billing", tags=["billing"])
