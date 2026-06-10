"""015_create_triggers

DB 트리거 함수 생성:
  - update_updated_at_column()  : updated_at 자동 갱신
  - check_login_lockout()       : 5회 실패 시 15분 계정 잠금
  - sync_user_plan_on_subscription_change() : 구독 상태 → users.plan 동기화
  - auto_deactivate_on_failures(): 3회 API 실패 시 exchange_account 비활성화
  - set_order_executed_at()     : 주문 체결 시 executed_at 자동 설정
  - prevent_audit_modification(): audit_logs append-only 강제

Revision ID: 015
Revises: 014
Create Date: 2026-06-05
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. updated_at 자동 갱신 ──────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    for table in ["users", "subscriptions", "exchange_accounts", "user_settings", "orders"]:
        op.execute(f"""
            CREATE TRIGGER {table}_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)

    # ── 2. 로그인 실패 자동 잠금 ─────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION check_login_lockout()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.login_attempts >= 5 AND OLD.login_attempts < 5 THEN
                NEW.locked_until = NOW() + INTERVAL '15 minutes';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER users_login_lockout
            BEFORE UPDATE OF login_attempts ON users
            FOR EACH ROW EXECUTE FUNCTION check_login_lockout();
    """)

    # ── 3. 구독 상태 → users.plan 동기화 ────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_user_plan_on_subscription_change()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.status IN ('cancelled', 'incomplete_expired') THEN
                UPDATE users SET plan = 'free', updated_at = NOW()
                WHERE id = NEW.user_id;
            ELSIF NEW.status IN ('active', 'trialing') THEN
                UPDATE users SET plan = NEW.plan, updated_at = NOW()
                WHERE id = NEW.user_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER subscriptions_sync_user_plan
            AFTER UPDATE OF status, plan ON subscriptions
            FOR EACH ROW EXECUTE FUNCTION sync_user_plan_on_subscription_change();
    """)

    # ── 4. exchange_account 3회 실패 시 자동 비활성화 ───────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION auto_deactivate_on_failures()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.consecutive_failures >= 3 THEN
                NEW.is_active = FALSE;
                NEW.health_status = 'disconnected';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER exchange_accounts_auto_deactivate
            BEFORE UPDATE OF consecutive_failures ON exchange_accounts
            FOR EACH ROW EXECUTE FUNCTION auto_deactivate_on_failures();
    """)

    # ── 5. 주문 체결 시 executed_at 자동 설정 ───────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION set_order_executed_at()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.status = 'filled' AND OLD.status != 'filled' THEN
                NEW.executed_at = NOW();
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER orders_set_executed_at
            BEFORE UPDATE OF status ON orders
            FOR EACH ROW EXECUTE FUNCTION set_order_executed_at();
    """)

    # ── 6. audit_logs append-only 강제 ──────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only. Modification not allowed.';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER audit_logs_no_update
            BEFORE UPDATE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();
    """)
    op.execute("""
        CREATE TRIGGER audit_logs_no_delete
            BEFORE DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_modification()")
    op.execute("DROP TRIGGER IF EXISTS orders_set_executed_at ON orders")
    op.execute("DROP FUNCTION IF EXISTS set_order_executed_at()")
    op.execute("DROP TRIGGER IF EXISTS exchange_accounts_auto_deactivate ON exchange_accounts")
    op.execute("DROP FUNCTION IF EXISTS auto_deactivate_on_failures()")
    op.execute("DROP TRIGGER IF EXISTS subscriptions_sync_user_plan ON subscriptions")
    op.execute("DROP FUNCTION IF EXISTS sync_user_plan_on_subscription_change()")
    op.execute("DROP TRIGGER IF EXISTS users_login_lockout ON users")
    op.execute("DROP FUNCTION IF EXISTS check_login_lockout()")
    for table in ["orders", "user_settings", "exchange_accounts", "subscriptions", "users"]:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")
