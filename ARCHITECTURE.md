# AI Trading Copilot — Architecture Document

> 작성일: 2026-06-04
> 버전: v1.0
> 참조: CLAUDE.md, PROJECT_CHARTER.md, PRD.md

---

## 목차

1. [전체 시스템 구조](#1-전체-시스템-구조)
2. [Frontend Architecture](#2-frontend-architecture)
3. [Backend Architecture](#3-backend-architecture)
4. [Agent Architecture](#4-agent-architecture)
5. [Database Architecture](#5-database-architecture)
6. [Queue Architecture](#6-queue-architecture)
7. [Redis Usage](#7-redis-usage)
8. [Security Architecture](#8-security-architecture)
9. [Deployment Architecture](#9-deployment-architecture)
10. [Monitoring Architecture](#10-monitoring-architecture)

---

## 1. 전체 시스템 구조

### 1.1 시스템 레이어 다이어그램

```mermaid
graph TD
    subgraph CLIENT["CLIENT LAYER"]
        WEB["Web App\nNext.js 14"]
        TG["Telegram Bot\npython-telegram-bot"]
    end

    subgraph GATEWAY["API GATEWAY"]
        NGX["Nginx\nRate Limit / SSL / Proxy"]
    end

    subgraph BACKEND["BACKEND SERVICES (FastAPI)"]
        AUTH["auth-service\nJWT / 2FA / Session"]
        USER["user-service\nProfile / Subscription"]
        TRADE["trading-service\nOrder / Position"]
        AI["ai-engine\nSignal Generation"]
        NOTIFY["notification-service\nTelegram / Email"]
    end

    subgraph BROKER["MESSAGE BROKER"]
        RS["Redis Streams\nSignal Queue\nOrder Queue\nNotify Queue"]
    end

    subgraph WORKERS["ASYNC WORKERS (Celery)"]
        AW["Analysis Worker\n5min cycle"]
        OW["Order Executor\norder processor"]
        NW["Notification Worker\nalert dispatcher"]
    end

    subgraph EXTERNAL["EXTERNAL APIs"]
        BN["Binance\nREST + WebSocket"]
        ANT["Anthropic\nClaude Sonnet API"]
        STR["Stripe\nSubscription"]
        TGAPI["Telegram API"]
        NEWS["CryptoCompare\nNews API"]
    end

    subgraph DATA["DATA LAYER"]
        PG["PostgreSQL 16\nMain DB"]
        TS["TimescaleDB\nOHLCV Time-series"]
        RD["Redis 7.2\nCache / Session / Pub-Sub"]
        R2["Cloudflare R2\nReports / PDFs"]
    end

    WEB -->|HTTPS| NGX
    TG -->|HTTPS| NGX
    NGX --> AUTH
    NGX --> USER
    NGX --> TRADE
    NGX --> AI
    NGX --> NOTIFY

    TRADE -->|publish| RS
    AI -->|publish| RS
    NOTIFY -->|publish| RS

    RS --> AW
    RS --> OW
    RS --> NW

    AW -->|OHLCV request| BN
    AW -->|Claude API| ANT
    AW -->|news| NEWS
    OW -->|place order| BN
    NW -->|send message| TGAPI

    AUTH --- PG
    USER --- PG
    TRADE --- PG
    AI --- TS
    AW --- TS
    OW --- PG

    AUTH --- RD
    TRADE --- RD
    AI --- RD

    USER --- STR
    NOTIFY --- R2
```

### 1.2 실시간 데이터 흐름

```mermaid
graph LR
    BNS["Binance\nWebSocket Stream"]
    MDP["Market Data\nProcessor"]
    TSB[("TimescaleDB\nOHLCV")]
    RC[("Redis\nPrice Cache")]
    AQ["Analysis\nQueue"]
    AIE["AI Engine\n5min cycle"]
    SQ["Signal\nQueue"]
    OQ["Order\nQueue"]
    OE["Order\nExecutor"]
    BNAPI["Binance\nREST API"]
    PU["Position\nUpdate"]
    PDB[("PostgreSQL\nPositions")]
    WSC["WebSocket\nClients"]

    BNS -->|price / OI / funding| MDP
    MDP --> TSB
    MDP --> RC
    MDP --> AQ
    AQ --> AIE
    AIE -->|signal| SQ
    SQ -->|full_auto mode| OQ
    SQ -->|semi_auto mode| WSC
    OQ --> OE
    OE -->|place order| BNAPI
    BNAPI -->|order filled| PU
    PU --> PDB
    PU -->|pub/sub| RC
    RC -->|subscribe| WSC
```

---

## 2. Frontend Architecture

### 2.1 Next.js App Router 구조

```
frontend/
├── app/
│   ├── layout.tsx                  # Root layout (폰트, 프로바이더)
│   ├── page.tsx                    # 랜딩 페이지
│   ├── (auth)/                     # 인증 불필요 그룹
│   │   ├── login/page.tsx
│   │   ├── signup/page.tsx
│   │   ├── verify-email/page.tsx
│   │   └── forgot-password/page.tsx
│   ├── (onboarding)/               # 온보딩 플로우
│   │   ├── survey/page.tsx
│   │   ├── risk-profile/page.tsx
│   │   ├── connect-binance/page.tsx
│   │   └── select-plan/page.tsx
│   └── (dashboard)/                # 인증 필요 그룹
│       ├── layout.tsx              # 사이드바 + 헤더
│       ├── dashboard/page.tsx
│       ├── signals/
│       │   ├── page.tsx
│       │   └── [id]/page.tsx
│       ├── positions/
│       │   ├── page.tsx
│       │   └── [id]/page.tsx
│       ├── journal/page.tsx
│       ├── analytics/page.tsx
│       └── settings/
│           ├── profile/page.tsx
│           ├── binance-api/page.tsx
│           ├── trading/page.tsx
│           ├── notifications/page.tsx
│           └── subscription/page.tsx
│
├── components/
│   ├── ui/                         # shadcn/ui 기본 컴포넌트
│   ├── dashboard/
│   │   ├── AccountSummaryCards.tsx
│   │   ├── PositionsTable.tsx
│   │   ├── PnlChart.tsx            # TradingView Lightweight Charts
│   │   └── RecentTradesTable.tsx
│   ├── signals/
│   │   ├── SignalCard.tsx
│   │   ├── SignalFeed.tsx
│   │   └── SignalCalculator.tsx
│   ├── positions/
│   │   ├── PositionRow.tsx
│   │   └── ClosePositionModal.tsx
│   └── common/
│       ├── AutoTradingToggle.tsx
│       └── PlanGate.tsx            # 플랜 제한 게이트
│
├── hooks/
│   ├── useWebSocket.ts             # WebSocket 연결 관리
│   ├── usePositions.ts             # 포지션 실시간 구독
│   ├── useSignals.ts               # 시그널 스트림
│   └── useAuth.ts                  # 인증 상태
│
├── store/
│   ├── authStore.ts                # Zustand: 사용자 / JWT
│   ├── positionStore.ts            # Zustand: 오픈 포지션
│   └── signalStore.ts              # Zustand: 활성 시그널
│
└── lib/
    ├── api.ts                      # TanStack Query + axios 클라이언트
    ├── websocket.ts                # WS 연결 / 재연결 로직
    └── schemas/                    # Zod 스키마 (API 응답 검증)
        ├── signal.schema.ts
        └── position.schema.ts
```

### 2.2 상태 관리 및 데이터 흐름

```mermaid
graph TD
    subgraph SERVER["Server Side (Next.js)"]
        SC["Server Components\n초기 데이터 fetch"]
        SA["Server Actions\n민감 작업 처리"]
    end

    subgraph CLIENT_STATE["Client State"]
        ZU["Zustand Store\nauth / position / signal"]
        TQ["TanStack Query\nAPI 캐시 / refetch"]
        WS["WebSocket\n실시간 이벤트"]
    end

    subgraph UI["UI Components"]
        DASH["Dashboard\nAccountSummary"]
        POS["PositionsTable\n실시간 PnL"]
        SIG["SignalFeed\n신규 시그널"]
        CHT["PnlChart\nTradingView"]
    end

    SC -->|초기 데이터 주입| DASH
    SA -->|form submit| TQ
    TQ -->|GET /api/v1/*| DASH
    TQ -->|GET /api/v1/*| POS
    WS -->|position.updated| ZU
    WS -->|signal.new| ZU
    ZU -->|subscribe| POS
    ZU -->|subscribe| SIG
    TQ -->|historical data| CHT
```

### 2.3 WebSocket 클라이언트 설계

```typescript
// hooks/useWebSocket.ts — 핵심 연결 로직
const WS_EVENTS = {
  POSITION_UPDATED: 'position.updated',
  POSITION_CLOSED:  'position.closed',
  POSITION_WARNING: 'position.warning',
  SIGNAL_NEW:       'signal.new',
  SIGNAL_EXPIRED:   'signal.expired',
} as const

// 재연결 전략: Exponential backoff (1s, 2s, 4s, 8s, max 30s)
// 백그라운드 탭: visibility API로 재연결 일시정지
// 연결 끊김: TanStack Query REST 폴백 자동 전환
```

---

## 3. Backend Architecture

### 3.1 서비스 레이어 다이어그램

```mermaid
graph TD
    subgraph API["API Layer (FastAPI Routers)"]
        AR["api/v1/auth.py"]
        UR["api/v1/users.py"]
        BR["api/v1/binance.py"]
        SR["api/v1/signals.py"]
        PR["api/v1/positions.py"]
        TR["api/v1/trading.py"]
        BLR["api/v1/billing.py"]
    end

    subgraph SVC["Service Layer (Business Logic)"]
        AS["AuthService"]
        US["UserService"]
        BS["BinanceService"]
        SS["SignalService"]
        OS["OrderService"]
        PS["PositionService"]
        BLS["BillingService"]
        NS["NotificationService"]
    end

    subgraph REPO["Repository Layer (DB Queries)"]
        UR2["UserRepository"]
        SR2["SignalRepository"]
        PR2["PositionRepository"]
        TR2["TradeRepository"]
        ALR["AuditLogRepository"]
    end

    subgraph MODEL["Model Layer (SQLAlchemy ORM)"]
        UM["User"]
        SM["Signal"]
        PM["Position"]
        TM["Trade"]
        SUB["Subscription"]
    end

    AR --> AS
    UR --> US
    BR --> BS
    SR --> SS
    PR --> OS
    PR --> PS
    TR --> OS
    BLR --> BLS

    AS --> UR2
    US --> UR2
    BS --> UR2
    SS --> SR2
    OS --> PR2
    OS --> TR2
    PS --> PR2

    UR2 --> UM
    SR2 --> SM
    PR2 --> PM
    TR2 --> TM
```

### 3.2 폴더 구조

```
backend/
├── main.py                     # FastAPI app 인스턴스, 미들웨어 등록
├── config.py                   # pydantic-settings: 환경변수 로드
├── dependencies.py             # 공통 의존성 (get_current_user 등)
│
├── api/
│   └── v1/
│       ├── __init__.py
│       ├── auth.py
│       ├── users.py
│       ├── binance.py
│       ├── signals.py
│       ├── positions.py
│       ├── trading.py
│       ├── billing.py
│       └── websocket.py        # WebSocket 핸들러
│
├── services/
│   ├── auth_service.py         # JWT 생성, 2FA, 이메일 인증
│   ├── user_service.py         # 프로파일, 리스크 설정
│   ├── binance_service.py      # Key 암호화, 권한 검증, 잔고 조회
│   ├── order_service.py        # 주문 실행, Pre-check, 포지션 사이징
│   ├── position_service.py     # 포지션 모니터링, 청산가 계산
│   ├── signal_service.py       # 시그널 CRUD, 만료 처리
│   ├── notification_service.py # 텔레그램, 이메일 발송
│   └── billing_service.py      # Stripe 구독, 플랜 동기화
│
├── repositories/
│   ├── base.py                 # 공통 CRUD 베이스
│   ├── user_repo.py
│   ├── signal_repo.py
│   ├── position_repo.py
│   ├── trade_repo.py
│   └── audit_log_repo.py
│
├── models/                     # SQLAlchemy ORM 모델
│   ├── base.py                 # Base, TimestampMixin
│   ├── user.py
│   ├── signal.py
│   ├── position.py
│   ├── trade.py
│   ├── subscription.py
│   ├── refresh_token.py
│   └── audit_log.py
│
├── schemas/                    # Pydantic v2 요청/응답 스키마
│   ├── auth.py
│   ├── user.py
│   ├── signal.py
│   ├── position.py
│   ├── order.py
│   └── billing.py
│
├── agents/                     # LangGraph AI 에이전트
│   ├── orchestrator.py         # LangGraph 그래프 정의
│   ├── technical_analyst.py
│   ├── sentiment_agent.py
│   ├── market_structure.py
│   ├── synthesis_agent.py      # Claude Sonnet 호출
│   └── risk_manager.py
│
├── workers/                    # Celery 태스크
│   ├── celery_app.py           # Celery 인스턴스
│   ├── analysis_worker.py      # 5분 주기 분석 태스크
│   ├── order_worker.py         # 주문 실행 태스크
│   └── notification_worker.py  # 알림 발송 태스크
│
├── utils/
│   ├── encryption.py           # AES-256-GCM
│   ├── jwt_handler.py          # JWT 생성/검증
│   ├── totp.py                 # TOTP 2FA
│   ├── rate_limiter.py         # Redis 기반 Rate Limit
│   └── circuit_breaker.py      # 외부 API Circuit Breaker
│
├── middleware/
│   ├── auth_middleware.py      # JWT 검증
│   ├── plan_middleware.py      # 구독 플랜 RBAC
│   └── logging_middleware.py   # 요청 로깅 (민감정보 마스킹)
│
├── migrations/                 # Alembic 마이그레이션
│   └── versions/
│
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

### 3.3 Order Execution — 핵심 경로

```mermaid
sequenceDiagram
    participant RS as Redis Streams
    participant OW as OrderWorker
    participant OS as OrderService
    participant PR as PositionRepo
    participant RD as Redis Cache
    participant BN as Binance API

    RS->>OW: consume signal event
    OW->>OS: execute_signal(user_id, signal)

    Note over OS: Pre-execution 체크 (6종)
    OS->>RD: get user balance (cache)
    OS->>RD: get daily_loss (cache)
    OS->>PR: count open positions

    alt 체크 통과
        OS->>OS: calculate position sizing
        Note over OS: size = balance × risk% / |entry - sl|
        OS->>BN: POST /fapi/v1/order (MARKET)
        BN-->>OS: order filled response

        OS->>BN: POST /fapi/v1/order (TP - TAKE_PROFIT_MARKET)
        OS->>BN: POST /fapi/v1/order (SL - STOP_MARKET)

        OS->>PR: insert position record
        OS->>RD: update position cache
        OS->>RS: publish notification event
    else 체크 실패
        OS->>RS: publish skip + alert event
    end
```

---

## 4. Agent Architecture

### 4.1 LangGraph 파이프라인

```mermaid
graph TD
    START(["START\nCelery Task\n5min trigger"])

    subgraph PARALLEL["병렬 실행 (asyncio.gather)"]
        TA["Technical Analyst\nAgent\n\nInput: OHLCV 6 timeframes\nTools: pandas-ta\nRSI / MACD / BB / EMA\nVolume / ATR / SR Lines\n\nOutput: tech_score -1.0~1.0"]
        SA["Sentiment\nAgent\n\nInput: News / Fear&Greed\nTools: FinBERT transformer\nCryptoCompare API\n\nOutput: sentiment_score -1.0~1.0"]
        MA["Market Structure\nAgent\n\nInput: Binance Futures data\nTools: Binance REST API\nOI / Funding Rate\nLong-Short Ratio\n\nOutput: market_score -1.0~1.0"]
    end

    SYN["Synthesis\nAgent\n\nModel: claude-sonnet-4-6\nInput: 3 agent scores + raw data\nTask: weighted aggregation\nConfidence calculation\n3-line reason generation\n\nOutput: direction + confidence + reasons"]

    RM["Risk Manager\nAgent\n\nInput: signal + user account state\nValidation:\n  SL existence check\n  R:R >= 2.0 check\n  leverage cap (min of AI vs user max)\n  portfolio risk check\n  daily loss limit check\n\nOutput: APPROVED signal OR REJECTED"]

    PUBLISH["Publish to\nRedis Streams\nsignal queue"]

    DROP["DROP\nno publish"]

    START --> PARALLEL
    TA --> SYN
    SA --> SYN
    MA --> SYN
    SYN --> RM
    RM -->|approved| PUBLISH
    RM -->|rejected| DROP
```

### 4.2 에이전트별 구현 상세

#### Technical Analyst Agent
```python
# agents/technical_analyst.py

INDICATORS = {
    "rsi":      {"period": 14, "timeframes": ["1h", "4h"]},
    "macd":     {"fast": 12, "slow": 26, "signal": 9},
    "bb":       {"period": 20, "std": 2},
    "ema":      {"periods": [9, 21, 50, 200]},
    "atr":      {"period": 14},
    "volume":   {"ma_period": 20},
}

# 점수 계산 로직
# +1.0 → 강한 LONG 신호
# -1.0 → 강한 SHORT 신호
# 0.0  → 중립
```

#### Synthesis Agent (Claude Sonnet)
```python
# agents/synthesis_agent.py

SYSTEM_PROMPT = """
You are a professional crypto futures trading analyst.
Given technical, sentiment, and market structure scores with raw data,
provide a trading signal with:
1. Direction: LONG / SHORT / HOLD
2. Confidence: 0.0 to 1.0
3. Entry, TP, SL prices with exact values
4. Leverage recommendation (1-20x)
5. Three specific reasons based on evidence

Rules:
- Minimum confidence to publish: 0.60
- Minimum R:R ratio: 2.0
- If R:R < 2.0, output HOLD regardless of direction
- Reasons must reference specific indicator values
"""
```

#### Risk Manager Agent
```python
# agents/risk_manager.py

def validate_signal(signal: RawSignal, account: AccountState) -> ApprovedSignal:
    assert signal.stop_loss is not None
    assert signal.rr_ratio >= 2.0
    assert signal.confidence >= 0.60

    leverage = min(signal.leverage, account.max_leverage, 20)

    size = (account.balance * account.risk_per_trade) / abs(
        signal.entry - signal.stop_loss
    )
    quantity = (size * leverage) / signal.entry

    assert account.daily_loss < account.daily_loss_limit
    assert account.open_positions < account.max_concurrent_positions

    return ApprovedSignal(quantity=quantity, leverage=leverage, ...)
```

### 4.3 LangGraph State Schema

```python
class AgentState(TypedDict):
    # 입력
    coin: str
    ohlcv: dict[str, pd.DataFrame]      # timeframe → OHLCV
    market_data: MarketData              # OI, funding, L/S ratio
    news_data: list[NewsItem]
    fear_greed_index: int

    # 에이전트 출력
    tech_score: float
    sentiment_score: float
    market_score: float

    # Synthesis 출력
    direction: Literal["LONG", "SHORT", "HOLD"]
    confidence: float
    entry_price: float
    take_profit: float
    stop_loss: float
    leverage: int
    reasons: list[str]
    rr_ratio: float

    # Risk Manager 출력
    approved: bool
    quantity: float
    rejection_reason: str | None
```

---

## 5. Database Architecture

### 5.1 ERD (핵심 테이블)

```mermaid
erDiagram
    users {
        uuid id PK
        varchar email UK
        varchar password_hash
        varchar display_name
        enum plan "free|pro|elite"
        boolean is_email_verified
        boolean is_2fa_enabled
        varchar totp_secret
        enum risk_profile "conservative|moderate|aggressive"
        varchar timezone
        timestamptz created_at
        timestamptz updated_at
    }

    user_settings {
        uuid id PK
        uuid user_id FK
        enum mode "full_auto|semi_auto|signal_only"
        text[] coins
        decimal risk_per_trade
        int max_leverage
        decimal daily_loss_limit
        int max_concurrent_positions
        time allowed_hours_start
        time allowed_hours_end
        boolean is_trading_active
        timestamptz updated_at
    }

    binance_connections {
        uuid id PK
        uuid user_id FK
        text encrypted_api_key
        text encrypted_api_secret
        text key_iv
        boolean is_testnet
        boolean is_active
        timestamptz last_health_check_at
        timestamptz created_at
    }

    signals {
        uuid id PK
        varchar coin
        enum direction "LONG|SHORT|HOLD"
        decimal confidence
        decimal entry_price
        decimal take_profit
        decimal stop_loss
        int leverage
        decimal rr_ratio
        text[] reasons
        enum status "active|expired|executed"
        timestamptz created_at
        timestamptz expires_at
    }

    positions {
        uuid id PK
        uuid user_id FK
        uuid signal_id FK
        varchar binance_order_id
        varchar coin
        enum direction "LONG|SHORT"
        decimal entry_price
        decimal quantity
        int leverage
        decimal take_profit
        decimal stop_loss
        enum status "open|closed|liquidated"
        decimal close_price
        decimal realized_pnl
        enum close_reason "tp_hit|sl_hit|manual|liquidated"
        timestamptz opened_at
        timestamptz closed_at
    }

    trades {
        uuid id PK
        uuid user_id FK
        uuid position_id FK
        decimal realized_pnl
        decimal fee
        int duration_seconds
        boolean is_ai_trade
        timestamptz created_at
    }

    subscriptions {
        uuid id PK
        uuid user_id FK
        varchar stripe_customer_id
        varchar stripe_subscription_id
        enum plan "free|pro|elite"
        enum status "active|past_due|cancelled|trialing"
        timestamptz current_period_start
        timestamptz current_period_end
        boolean cancel_at_period_end
        timestamptz updated_at
    }

    refresh_tokens {
        uuid id PK
        uuid user_id FK
        varchar token_hash
        varchar device_info
        varchar ip_address
        timestamptz expires_at
        timestamptz created_at
    }

    audit_logs {
        uuid id PK
        uuid user_id FK
        varchar action
        jsonb details
        varchar ip_address
        timestamptz created_at
    }

    users ||--o{ user_settings : "has"
    users ||--o{ binance_connections : "owns"
    users ||--o{ positions : "opens"
    users ||--o{ trades : "executes"
    users ||--o{ subscriptions : "subscribes"
    users ||--o{ refresh_tokens : "holds"
    users ||--o{ audit_logs : "generates"
    positions ||--|| trades : "produces"
    signals ||--o{ positions : "triggers"
```

### 5.2 TimescaleDB OHLCV 스키마

```sql
-- TimescaleDB 하이퍼테이블 (시계열 최적화)
CREATE TABLE ohlcv (
    time        TIMESTAMPTZ NOT NULL,
    coin        VARCHAR(10) NOT NULL,   -- 'BTC', 'ETH'
    interval    VARCHAR(5) NOT NULL,    -- '1m', '5m', '15m', '1h', '4h', '1d'
    open        DECIMAL(18, 8) NOT NULL,
    high        DECIMAL(18, 8) NOT NULL,
    low         DECIMAL(18, 8) NOT NULL,
    close       DECIMAL(18, 8) NOT NULL,
    volume      DECIMAL(24, 8) NOT NULL
);

SELECT create_hypertable('ohlcv', 'time');
CREATE INDEX ON ohlcv (coin, interval, time DESC);

-- 보존 정책
SELECT add_retention_policy('ohlcv', INTERVAL '90 days');

-- 집계 정책 (1m → 5m → 1h 자동 롤업)
SELECT add_continuous_aggregate_policy('ohlcv_5m', ...);
```

### 5.3 인덱스 전략

```sql
-- 핵심 조회 패턴별 인덱스

-- 사용자별 오픈 포지션 조회 (대시보드 핵심 쿼리)
CREATE INDEX idx_positions_user_status
    ON positions (user_id, status)
    WHERE status = 'open';

-- 활성 시그널 조회
CREATE INDEX idx_signals_status_expires
    ON signals (status, expires_at)
    WHERE status = 'active';

-- 사용자별 거래 통계 (수익률 계산)
CREATE INDEX idx_trades_user_created
    ON trades (user_id, created_at DESC);

-- Audit Log 조회
CREATE INDEX idx_audit_logs_user_action
    ON audit_logs (user_id, action, created_at DESC);
```

---

## 6. Queue Architecture

### 6.1 Redis Streams 구조

```mermaid
graph TD
    subgraph PRODUCERS["이벤트 생산자"]
        AW2["Analysis Worker\n분석 완료"]
        OS2["Order Service\n주문 이벤트"]
        PS2["Position Service\n포지션 이벤트"]
    end

    subgraph STREAMS["Redis Streams"]
        SIG_S["stream:signals\n신규 시그널 이벤트"]
        ORD_S["stream:orders\n주문 실행 요청"]
        NOT_S["stream:notifications\n알림 발송 요청"]
        DLQ["stream:dlq\nDead Letter Queue\n처리 실패 이벤트"]
    end

    subgraph CONSUMERS["Consumer Groups"]
        OW2["order-executor-group\nOrder Worker (x2)"]
        NW2["notification-group\nNotification Worker (x2)"]
    end

    AW2 -->|XADD| SIG_S
    OS2 -->|XADD| ORD_S
    PS2 -->|XADD| NOT_S

    SIG_S -->|XREADGROUP| OW2
    ORD_S -->|XREADGROUP| OW2
    NOT_S -->|XREADGROUP| NW2

    OW2 -->|max retry 3| DLQ
    NW2 -->|max retry 3| DLQ
```

### 6.2 Celery Beat 스케줄 (정기 태스크)

```python
# workers/celery_app.py

CELERYBEAT_SCHEDULE = {
    # AI 분석 (5분 주기)
    "analyze-btc": {
        "task": "workers.analysis_worker.run_analysis",
        "schedule": crontab(minute="*/5"),
        "args": ("BTC",),
    },
    "analyze-eth": {
        "task": "workers.analysis_worker.run_analysis",
        "schedule": crontab(minute="*/5"),
        "args": ("ETH",),
    },

    # Binance API 헬스체크 (30초 주기)
    "binance-healthcheck": {
        "task": "workers.analysis_worker.check_binance_connections",
        "schedule": 30.0,
    },

    # 일일 성과 요약 알림 (매일 22:00 KST = 13:00 UTC)
    "daily-summary": {
        "task": "workers.notification_worker.send_daily_summary",
        "schedule": crontab(hour=13, minute=0),
    },

    # 만료 시그널 처리 (1분 주기)
    "expire-signals": {
        "task": "workers.analysis_worker.expire_old_signals",
        "schedule": crontab(minute="*/1"),
    },
}
```

### 6.3 Order Worker 상세 처리 흐름

```mermaid
flowchart TD
    START(["Redis Streams\nConsume Order Event"])
    LOCK["Redis SETNX\n분산 락 획득\nkey: lock:order:{user_id}"]
    LOCK_FAIL["다른 워커가 처리 중\n→ ACK + skip"]

    CHECK1{"잔고 충분?"}
    CHECK2{"일일 손실 한도\n초과?"}
    CHECK3{"최대 포지션\n초과?"}
    CHECK4{"동일 코인\n포지션 존재?"}
    CHECK5{"거래 허용\n시간대?"}
    CHECK6{"API 연결\n정상?"}

    SKIP["Skip + Alert\n→ Notification Queue"]
    SIZE["포지션 사이징 계산"]
    ORDER["Binance 시장가 주문\nPOST /fapi/v1/order"]
    RETRY{"실패?\n재시도 횟수?"}
    TPSL["OCO 주문 설정\nTP + SL"]
    DB["PostgreSQL\n포지션 레코드 생성"]
    CACHE["Redis Cache\n포지션 상태 업데이트"]
    NOTIFY["Notification Queue\n체결 알림 발행"]
    UNLOCK["Redis 락 해제"]
    DLQ2["Dead Letter Queue\n수동 처리 필요"]

    START --> LOCK
    LOCK -->|실패| LOCK_FAIL
    LOCK -->|성공| CHECK1
    CHECK1 -->|NO| SKIP
    CHECK1 -->|YES| CHECK2
    CHECK2 -->|YES| SKIP
    CHECK2 -->|NO| CHECK3
    CHECK3 -->|YES| SKIP
    CHECK3 -->|NO| CHECK4
    CHECK4 -->|YES DCA| SIZE
    CHECK4 -->|NO| CHECK5
    CHECK5 -->|NO| SKIP
    CHECK5 -->|YES| CHECK6
    CHECK6 -->|NO| SKIP
    CHECK6 -->|YES| SIZE
    SIZE --> ORDER
    ORDER --> RETRY
    RETRY -->|성공| TPSL
    RETRY -->|3회 실패| DLQ2
    TPSL --> DB
    DB --> CACHE
    CACHE --> NOTIFY
    NOTIFY --> UNLOCK
    SKIP --> UNLOCK
```

---

## 7. Redis Usage

### 7.1 Redis Key Space 설계

```
# 인증 / 세션
session:refresh:{user_id}:{token_hash}   TTL: 7d
session:active_count:{user_id}            TTL: 7d
email_verify:{email}                      TTL: 5min
password_reset:{token}                    TTL: 30min

# Rate Limiting
rate_limit:api:{user_id}                  TTL: 1min   (슬라이딩 윈도우)
rate_limit:login:{ip}                     TTL: 15min  (실패 횟수)

# 사용자 상태 캐시
user:plan:{user_id}                       TTL: 5min   (플랜 정보)
user:settings:{user_id}                   TTL: 1min   (거래 설정)
user:daily_loss:{user_id}:{date}          TTL: 25h    (일일 손실 합계)

# Binance 데이터 캐시
price:{coin}                              TTL: 1s     (실시간 가격)
balance:{user_id}                         TTL: 30s    (계좌 잔고)
positions:open:{user_id}                  TTL: 5s     (오픈 포지션)

# 시그널 캐시
signal:active:{coin}                      TTL: 1h     (활성 시그널)
signal:count:free:{user_id}:{date}        TTL: 25h    (Free 플랜 일일 카운트)

# 분산 락
lock:order:{user_id}                      TTL: 10s    (주문 실행 중복 방지)
lock:analysis:{coin}                      TTL: 60s    (분석 중복 실행 방지)

# Pub/Sub 채널
channel:positions:{user_id}              (WebSocket 브로드캐스트)
channel:signals:global                   (신규 시그널 브로드캐스트)

# Redis Streams
stream:signals                           (시그널 이벤트)
stream:orders                            (주문 요청)
stream:notifications                     (알림 요청)
stream:dlq                               (실패 이벤트)
```

### 7.2 Redis 데이터 흐름

```mermaid
graph LR
    subgraph WRITE["쓰기 경로 (Write-Through)"]
        PG2[("PostgreSQL\nSource of Truth")]
        RD2[("Redis Cache")]
        API2["API Layer"]

        API2 -->|1 write| PG2
        PG2 -->|2 invalidate| RD2
    end

    subgraph READ["읽기 경로 (Cache-Aside)"]
        CL["Client Request"]
        SVC2["Service Layer"]
        RD3[("Redis Cache")]
        PG3[("PostgreSQL")]

        CL --> SVC2
        SVC2 -->|1 cache hit?| RD3
        RD3 -->|miss| PG3
        PG3 -->|2 write cache| RD3
        RD3 -->|3 return| SVC2
    end

    subgraph PUBSUB["실시간 Push (Pub/Sub)"]
        BNW["Binance\nWebSocket"]
        PB["Redis\nPublisher"]
        SUB["Redis\nSubscribers"]
        WS2["Client\nWebSockets"]

        BNW -->|price update| PB
        PB -->|channel:positions:*| SUB
        SUB --> WS2
    end
```

---

## 8. Security Architecture

### 8.1 인증 플로우

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI
    participant RD as Redis
    participant PG as PostgreSQL

    Note over C,PG: 로그인 플로우
    C->>API: POST /auth/login {email, password, totp_code?}
    API->>PG: verify password_hash (bcrypt)
    API->>PG: check is_2fa_enabled
    alt 2FA 활성화
        API->>API: verify TOTP code (pyotp)
    end
    API->>API: generate Access Token (JWT, 15min)
    API->>API: generate Refresh Token (opaque, 7d)
    API->>RD: SETEX session:refresh:{user_id}:{hash} 7d
    API->>PG: insert refresh_tokens record
    API-->>C: {access_token} + Set-Cookie: refresh_token (HttpOnly)

    Note over C,PG: API 요청 플로우
    C->>API: GET /positions (Authorization: Bearer {token})
    API->>API: verify JWT signature + expiry
    API->>PG: load user + plan (or Redis cache)
    API->>API: check plan permissions (RBAC)
    API-->>C: 200 response

    Note over C,PG: Token 갱신 플로우
    C->>API: POST /auth/refresh (Cookie: refresh_token)
    API->>RD: verify session:refresh:{user_id}:{hash}
    API->>API: generate new Access Token
    API-->>C: {access_token}
```

### 8.2 Binance API Key 보안 플로우

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant BN as Binance
    participant PG as PostgreSQL

    Note over U,PG: API Key 등록
    U->>API: POST /binance/connect {api_key, api_secret}
    API->>BN: GET /api/v3/account (권한 조회)
    BN-->>API: {permissions: [...]}

    alt 출금 권한 포함
        API-->>U: 400 BINANCE_002 (출금 권한 차단)
    end

    alt Futures 권한 없음
        API-->>U: 400 BINANCE_003
    end

    API->>API: AES-256-GCM 암호화
    Note over API: key=BINANCE_ENCRYPT_KEY (env)\niv=random 12bytes\nciphertext=encrypt(api_key, key, iv)
    API->>PG: INSERT binance_connections\n{encrypted_key, encrypted_secret, iv}
    API->>PG: INSERT audit_logs {action: "api_key_added"}
    API-->>U: 201 {status: "connected", balance_usdt: ...}

    Note over U,PG: 주문 실행 시 복호화
    API->>PG: SELECT encrypted_key, iv
    API->>API: decrypt(encrypted_key, BINANCE_ENCRYPT_KEY, iv)
    API->>BN: 주문 API 호출 (복호화된 키 사용)
    API->>API: 메모리에서 평문 키 즉시 삭제 (del 변수)
```

### 8.3 보안 레이어 구조

```mermaid
graph TD
    subgraph TRANSPORT["전송 보안"]
        TLS["TLS 1.3\n모든 통신 암호화"]
    end

    subgraph GATEWAY["게이트웨이 보안"]
        RL["Rate Limiting\nFree:60/min Pro:300/min Elite:1000/min"]
        IP["IP Blocking\n로그인 5회 실패 시 15분 차단"]
    end

    subgraph AUTH_LAYER["인증/인가"]
        JWT2["JWT 검증 미들웨어\nHS256 + expiry check"]
        RBAC["RBAC 미들웨어\nplan 권한 검증"]
    end

    subgraph INPUT["입력 검증"]
        PDN["Pydantic v2\n모든 요청 스키마 검증"]
        SQL["SQLAlchemy ORM\nSQL Injection 방지"]
        XSS2["Next.js Auto-escape\nXSS 방지"]
    end

    subgraph STORAGE["저장 보안"]
        AES["AES-256-GCM\nBinance API Key 암호화"]
        BCR["bcrypt\n비밀번호 해시"]
        ENV["환경변수\n비밀값 관리"]
    end

    subgraph AUDIT["감사"]
        LOG["Audit Log\n민감 액션 영구 기록"]
        MASK["로그 마스킹\nAPI Key 출력 차단"]
    end

    TLS --> GATEWAY
    GATEWAY --> AUTH_LAYER
    AUTH_LAYER --> INPUT
    INPUT --> STORAGE
    STORAGE --> AUDIT
```

---

## 9. Deployment Architecture

### 9.1 Docker Compose (개발/스테이징)

```yaml
# docker-compose.yml

services:
  # ─── Frontend ───────────────────────────
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    environment:
      - NEXT_PUBLIC_API_URL=http://backend:8000
      - NEXT_PUBLIC_WS_URL=ws://backend:8000
    depends_on: [backend]

  # ─── Backend ────────────────────────────
  backend:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [postgres, redis]
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

  # ─── Celery Workers ─────────────────────
  worker-analysis:
    build: ./backend
    env_file: .env
    depends_on: [redis, postgres]
    command: celery -A workers.celery_app worker -Q analysis -c 2

  worker-order:
    build: ./backend
    env_file: .env
    depends_on: [redis, postgres]
    command: celery -A workers.celery_app worker -Q orders -c 4

  worker-notification:
    build: ./backend
    env_file: .env
    depends_on: [redis, postgres]
    command: celery -A workers.celery_app worker -Q notifications -c 2

  celery-beat:
    build: ./backend
    env_file: .env
    depends_on: [redis]
    command: celery -A workers.celery_app beat --loglevel=info

  # ─── Databases ──────────────────────────
  postgres:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: trading_copilot
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: [postgres_data:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  redis:
    image: redis:7.2-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 512mb
    volumes: [redis_data:/data]
    ports: ["6379:6379"]

  # ─── Monitoring ─────────────────────────
  prometheus:
    image: prom/prometheus
    volumes: [./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml]
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana
    ports: ["3001:3000"]
    volumes: [grafana_data:/var/lib/grafana]
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
```

### 9.2 CI/CD 파이프라인

```mermaid
graph TD
    PR["PR 생성\nfeature/* → develop"]

    subgraph CI["CI (GitHub Actions: pr.yml)"]
        LINT["Lint\nmypy / eslint / ruff"]
        TEST["Unit Tests\npytest / jest"]
        COV["Coverage Check\n80%+ required\n주문경로 95%+"]
        BUILD["Docker Build\n빌드 가능 여부"]
    end

    subgraph STAGING["Staging Deploy (staging.yml)"]
        STAG_DEPLOY["Staging 배포\nDocker Compose"]
        INTEG["Integration Tests\nBinance Testnet"]
        LOAD["Load Test\nLocust 100 users"]
        MANUAL["수동 QA 확인"]
    end

    subgraph PROD["Production Deploy (deploy.yml)"]
        MIGRATE["DB Migration\nalembic upgrade head"]
        HEALTH_PRE["Pre-deploy\nHealth Check"]
        DEPLOY["Production 배포\nDocker rolling update"]
        HEALTH_POST["Post-deploy\nHealth Check"]
        ROLLBACK["자동 롤백\n(Health Check 실패 시)"]
        NOTIFY2["Slack 알림\n배포 성공/실패"]
    end

    PR --> CI
    CI -->|All pass| STAGING
    CI -->|Fail| BLOCK["PR Merge 차단"]

    STAGING -->|48h 안정 확인| MANUAL
    MANUAL -->|승인| PROD

    MIGRATE --> HEALTH_PRE
    HEALTH_PRE --> DEPLOY
    DEPLOY --> HEALTH_POST
    HEALTH_POST -->|통과| NOTIFY2
    HEALTH_POST -->|실패| ROLLBACK
    ROLLBACK --> NOTIFY2
```

### 9.3 프로덕션 서버 구성

```
Production 서버 (단일 서버 — MVP):

┌─────────────────────────────────────────────┐
│               Ubuntu 22.04 LTS              │
│                                             │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Nginx  │  │ Frontend │  │ Backend  │  │
│  │ :80/443 │  │  :3000   │  │  :8000   │  │
│  └────┬────┘  └──────────┘  └──────────┘  │
│       │                                     │
│  ┌────┴────────────────────────────────┐   │
│  │           Docker Network            │   │
│  │                                     │   │
│  │  ┌──────┐  ┌──────┐  ┌─────────┐  │   │
│  │  │ PG   │  │Redis │  │Workers  │  │   │
│  │  │:5432 │  │:6379 │  │Celery   │  │   │
│  │  └──────┘  └──────┘  └─────────┘  │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │  Monitoring (separate port)          │   │
│  │  Prometheus :9090 │ Grafana :3001   │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘

SSL: Let's Encrypt (자동 갱신)
백업: 매일 01:00 PostgreSQL dump → Cloudflare R2
로그: /var/log/trading-copilot/ → Loki
```

---

## 10. Monitoring Architecture

### 10.1 관측성 스택

```mermaid
graph TD
    subgraph APP["애플리케이션 계층"]
        FE["Next.js\n(Vercel Analytics)"]
        BE["FastAPI\n(prometheus-fastapi-instrumentator)"]
        WK["Celery Workers\n(custom metrics)"]
    end

    subgraph METRICS["메트릭 수집"]
        PM["Prometheus\n:9090\n15s 스크랩 간격"]
    end

    subgraph LOGS["로그 수집"]
        LK["Loki\n구조화 로그 집계"]
        PT["Promtail\n로그 파일 수집"]
    end

    subgraph VIZ["시각화 / 알림"]
        GF["Grafana\n:3001"]
        AM["AlertManager\nSlack / Email 알림"]
    end

    BE -->|/metrics| PM
    WK -->|/metrics| PM
    BE -->|JSON logs| PT
    WK -->|JSON logs| PT
    PT --> LK
    PM --> GF
    LK --> GF
    PM --> AM
    GF -->|alert rules| AM
    AM -->|webhook| SLACK["Slack\n#ops-alerts"]
```

### 10.2 핵심 모니터링 지표

```yaml
# Grafana 대시보드 — 비즈니스 메트릭
business_metrics:
  - trading_signal_generated_total          # 시그널 생성 횟수
  - trading_order_executed_total            # 주문 실행 횟수
  - trading_order_success_rate              # 주문 성공률 (목표: >99.5%)
  - trading_position_liquidated_total       # 강제청산 발생 횟수
  - active_auto_trading_users               # 자동매매 활성 사용자 수
  - subscription_mrr_usd                    # 월간 구독 수익

# Grafana 대시보드 — 시스템 메트릭
system_metrics:
  - http_request_duration_seconds           # API 응답시간 (목표: p95 < 500ms)
  - http_requests_total                     # 요청 총량 / 에러율
  - order_execution_duration_ms             # 주문 실행 지연 (목표: p99 < 200ms)
  - signal_generation_duration_seconds      # 시그널 생성 시간 (목표: < 3s)
  - websocket_connections_active            # 활성 WebSocket 연결 수
  - celery_task_queue_length                # 태스크 큐 대기 길이
  - redis_memory_used_bytes                 # Redis 메모리 사용량
  - postgresql_slow_queries_total           # 슬로우 쿼리 (> 100ms)

# AlertManager 알림 규칙
alert_rules:
  critical:
    - order_success_rate < 0.99             # 주문 성공률 99% 미만
    - service_uptime < 0.999               # 가용성 99.9% 미만
    - liquidation_count > 0               # 강제청산 발생 즉시
    - api_error_rate > 0.01               # 에러율 1% 초과

  warning:
    - p95_latency > 300ms                 # API 지연 경고
    - celery_queue_length > 100           # 큐 적체 경고
    - redis_memory_usage > 80%            # Redis 메모리 경고
    - signal_generation_time > 2s         # 시그널 생성 지연 경고
```

### 10.3 로그 구조화 포맷

```python
# 모든 로그는 JSON 구조화 형식으로 출력
# 민감 정보(API Key, Token)는 자동 마스킹

import structlog

logger = structlog.get_logger()

# 주문 실행 로그 예시
logger.info(
    "order_executed",
    user_id=str(user_id),        # UUID만 (이메일 금지)
    coin="BTC",
    direction="LONG",
    quantity=0.015,
    entry_price=67450.0,
    latency_ms=142,
    binance_order_id="...",
    # api_key: 절대 로깅 금지
)

# 에러 로그 예시
logger.error(
    "order_failed",
    user_id=str(user_id),
    error_code="BINANCE_001",
    retry_count=2,
    exc_info=True,
)
```

### 10.4 헬스체크 엔드포인트

```python
# GET /health — 로드밸런서용 빠른 체크
# 응답: {"status": "ok"} 200 or 503

# GET /health/detailed — 상세 의존성 체크
# 응답:
{
  "status": "ok",
  "checks": {
    "postgresql":         {"status": "ok", "latency_ms": 3},
    "redis":              {"status": "ok", "latency_ms": 1},
    "binance_api":        {"status": "ok", "latency_ms": 45},
    "anthropic_api":      {"status": "ok", "latency_ms": 120},
    "celery_workers":     {"status": "ok", "active_workers": 4}
  },
  "version": "1.0.0",
  "uptime_seconds": 86400
}
```

---

## 부록: 핵심 의존성 버전

```toml
# backend/pyproject.toml (핵심)
[tool.poetry.dependencies]
python = "^3.12"
fastapi = "^0.115"
uvicorn = {extras = ["standard"], version = "^0.32"}
sqlalchemy = {extras = ["asyncio"], version = "^2.0"}
alembic = "^1.14"
pydantic = {extras = ["email"], version = "^2.10"}
pydantic-settings = "^2.7"
celery = {extras = ["redis"], version = "^5.4"}
redis = {extras = ["hiredis"], version = "^5.2"}
langgraph = "^0.2"
anthropic = "^0.40"
pandas-ta = "^0.3"
transformers = "^4.47"          # FinBERT
python-jose = "^3.3"            # JWT
passlib = {extras = ["bcrypt"], version = "^1.7"}
pyotp = "^2.9"                  # TOTP 2FA
cryptography = "^44.0"          # AES-256-GCM
stripe = "^11.3"
python-telegram-bot = "^21.9"
prometheus-fastapi-instrumentator = "^7.0"
structlog = "^24.4"
```

```json
// frontend/package.json (핵심)
{
  "dependencies": {
    "next": "14.2.x",
    "react": "^18.3",
    "typescript": "^5.6",
    "tailwindcss": "^3.4",
    "@shadcn/ui": "latest",
    "lightweight-charts": "^4.2",
    "zustand": "^5.0",
    "@tanstack/react-query": "^5.62",
    "zod": "^3.23",
    "axios": "^1.7"
  }
}
```

---

> 이 문서는 구현 가이드다.
> 각 컴포넌트의 인터페이스가 변경될 때 반드시 이 문서를 함께 업데이트한다.
> 아키텍처 결정의 최종 권한은 CLAUDE.md와 PROJECT_CHARTER.md에 있다.
