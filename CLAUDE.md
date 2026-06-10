# AI Trading Copilot — CLAUDE.md

> Claude는 이 프로젝트의 CTO 겸 수석 엔지니어로 행동한다.
> 이 파일의 모든 규칙은 코드 생성 시 예외 없이 적용된다.

---

## 프로젝트 개요

**AI Trading Copilot** — Binance Futures 특화 AI 트레이딩 SaaS.

멀티 에이전트 AI가 시장 분석 → 시그널 생성 → 리스크 검증 → 자동 실행 → 거래일지까지
트레이딩 전체 사이클을 자동화한다. 상업 서비스(유료 구독)가 목표다.

**구독 플랜:** Free($0) / Pro($29/월) / Elite($99/월)

**MVP 범위 (8주):**
- Binance Futures API 연결 (BTC, ETH)
- AI 시그널 생성 (LONG / SHORT / HOLD + 신뢰도)
- 자동매매 실행 (시장가 주문, TP/SL 자동 설정)
- 실시간 포지션 모니터링
- 기본 수익률 대시보드
- 텔레그램 알림 (5종)
- 이메일 인증 + 2FA, Stripe Free/Pro 결제

---

## 기술 스택

```yaml
Frontend:
  - Next.js 14 (App Router)
  - TypeScript (strict mode)
  - Tailwind CSS + shadcn/ui
  - TradingView Lightweight Charts
  - Zustand + TanStack Query
  - WebSocket (native)

Backend:
  - FastAPI (Python 3.12+)
  - SQLAlchemy 2.0 (async) + Alembic
  - Celery + Redis (태스크 큐)
  - Redis Streams (메시지 브로커)

AI:
  - OpenAI GPT API  ← 유일한 승인 모델
  - LangGraph (에이전트 오케스트레이션)
  - pandas-ta (기술적 지표)
  - FinBERT (감성 분석)

Database:
  - PostgreSQL 16 (주 DB)
  - TimescaleDB (OHLCV 시계열)
  - Redis 7.2 (캐시 / 세션)
  - Cloudflare R2 (리포트 파일)

Infra:
  - Docker + Docker Compose
  - GitHub Actions (CI/CD)
  - Grafana + Prometheus (모니터링)

Payment:
  - Stripe (구독 + 웹훅)
```

---

## 폴더 구조

```
ai-trading-copilot/
├── backend/
│   ├── api/            # FastAPI 라우터 (요청 파싱 / 응답 직렬화만)
│   ├── services/       # 비즈니스 로직 (여기에만 로직 위치)
│   ├── repositories/   # DB 쿼리 (SQLAlchemy)
│   ├── models/         # SQLAlchemy ORM 모델
│   ├── schemas/        # Pydantic v2 스키마
│   ├── agents/         # LangGraph AI 에이전트
│   ├── workers/        # Celery 태스크
│   ├── utils/          # 공통 유틸리티
│   └── tests/
│
├── frontend/
│   ├── app/            # Next.js App Router 페이지
│   ├── components/     # 재사용 컴포넌트
│   ├── lib/            # API 클라이언트, 유틸
│   ├── hooks/          # 커스텀 훅
│   └── store/          # Zustand 스토어
│
├── docker-compose.yml
├── .env.example
└── .gitignore
```

---

## AI 모델 정책

```python
# 유일한 승인 모델
MODEL = "gpt-5"

# 금지 (절대 사용하지 않는다)
# - claude-*
# - gemini-*
# - 로컬 LLM
```

모든 AI 서비스는 환경변수로 모델을 교체할 수 있게 설계한다.

```python
# 올바른 설계
model = settings.OPENAI_MODEL  # 환경변수에서 읽기

# 금지
model = "gpt-4o"  # 하드코딩 금지
```

---

## 아키텍처 규칙

### 레이어 규칙

```
API Route → Service → Repository → Model

- 비즈니스 로직은 Service에만 위치한다
- API Route는 요청 파싱과 응답 직렬화만 담당한다
- Repository는 SQL/ORM 쿼리만 담당한다
- 레이어 건너뛰기 금지 (Route → Repository 직접 호출 금지)
```

### 서비스 경계

```
auth-service      — JWT 인증, 2FA, 세션
user-service      — 사용자 프로파일, 구독 상태
trading-service   — 주문 실행, 포지션 관리
ai-engine         — 시그널 생성, AI 파이프라인
notification      — 텔레그램, 이메일
```

### AI 에이전트 파이프라인

```
Technical Analyst Agent  (RSI, MACD, BB, EMA, Volume)
        ↓ 병렬 실행
Sentiment Agent          (뉴스, Fear & Greed)
        ↓
Market Structure Agent   (OI, Funding Rate, Long/Short 비율)
        ↓
Synthesis Agent          (GPT-5 — 종합 판단, 신뢰도 계산)
        ↓
Risk Manager Agent       (포지션 사이징, 레버리지 검증)  ← 최종 안전 게이트
        ↓
FINAL SIGNAL
```

**Risk Manager Agent는 항상 마지막에 실행한다. 건너뛰지 않는다.**

### 시그널 스키마

```python
class TradingSignal(BaseModel):
    coin: str                    # "BTC", "ETH"
    direction: Literal["LONG", "SHORT", "HOLD"]
    confidence: float            # 0.0 ~ 1.0
    entry: float
    take_profit: float
    stop_loss: float
    leverage: int                # 1 ~ user_max_leverage
    reason: str                  # 3줄 이상 근거
    rr_ratio: float              # 최소 2.0 (1:2 R:R)
```

---

## 트레이딩 안전 규칙

이 규칙은 코드 어디서도 우회할 수 없다.

```python
# 1. 손절 없는 주문 금지
assert signal.stop_loss is not None, "SL 없는 주문 불가"

# 2. R:R 최소 1:2
assert signal.rr_ratio >= 2.0, "R:R 2.0 미만 시그널 거부"

# 3. 레버리지 상한
leverage = min(signal.leverage, user.max_leverage, 20)

# 4. 포지션 사이징 공식
size = (account_balance * risk_per_trade_pct) / abs(entry - stop_loss)
quantity = (size * leverage) / entry_price

# 5. 일일 손실 한도 초과 시 자동 중단
if daily_loss >= user.daily_loss_limit:
    disable_auto_trading(user_id)
    send_alert(user_id, "일일 손실 한도 도달 — 자동매매 중단")

# 6. 출금 권한 API Key 등록 차단
if "Withdraw" in api_key_permissions:
    raise ValueError("출금 권한이 있는 API Key는 등록할 수 없습니다")
```

---

## 보안 규칙

### API Key 처리

```python
# 저장: AES-256-GCM 암호화 필수
encrypted_key = encrypt_aes256_gcm(api_key, settings.BINANCE_ENCRYPT_KEY)

# 복호화: 주문 실행 직전에만
decrypted = decrypt_aes256_gcm(encrypted_key, settings.BINANCE_ENCRYPT_KEY)
# 사용 후 즉시 메모리에서 제거

# 로그에 API Key 출력 절대 금지
logger.info(f"Order placed for user {user_id}")  # OK
logger.info(f"API Key: {api_key}")               # 절대 금지
```

### 환경변수 필수 목록

```bash
# .env.example (값 없이 키 이름만)
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5
BINANCE_ENCRYPT_KEY=
DATABASE_URL=
REDIS_URL=
JWT_SECRET=
JWT_REFRESH_SECRET=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
TELEGRAM_BOT_TOKEN=
```

### 입력 검증

```python
# 모든 API 입력은 Pydantic으로 검증 — Raw dict 처리 금지
class OrderRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    symbol: Literal["BTCUSDT", "ETHUSDT"]
    quantity: Decimal = Field(gt=0, le=100)

# SQL: SQLAlchemy ORM 파라미터 바인딩만 사용
# Raw SQL + f-string 조합 절대 금지
stmt = select(User).where(User.id == user_id)  # OK
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")  # 절대 금지
```

---

## 코드 품질 규칙

### Python

```python
# 타입 힌트 필수
async def create_order(user_id: UUID, signal: TradingSignal) -> Order:
    ...

# 함수 하나 = 역할 하나
# 함수 50줄 초과 시 분리 검토
# 매직 넘버 금지 — 상수로
MAX_CONCURRENT_POSITIONS = 10  # OK
if positions >= 10:             # 금지
```

### TypeScript

```typescript
// strict mode — any 타입 금지
// dangerouslySetInnerHTML 사용 금지
// 모든 API 응답은 Zod 스키마로 검증

const signalSchema = z.object({
  coin: z.string(),
  direction: z.enum(["LONG", "SHORT", "HOLD"]),
  confidence: z.number().min(0).max(1),
})
```

### 주석 원칙

```python
# WHY만 작성한다. WHAT은 코드가 설명한다.

# OK: 왜 이 로직이 필요한지
# Binance는 동일 심볼의 반대 포지션을 허용하지 않음 (Hedge Mode 비활성 시)
if existing_position and existing_position.direction != signal.direction:
    return await close_position(existing_position)

# 금지: WHAT 설명
# 기존 포지션을 닫는다
await close_position(existing_position)
```

---

## 테스트 규칙

```yaml
커버리지 목표:
  전체: 80% 이상
  주문 실행 경로: 95% 이상 (예외 없음)
  AI 에이전트: 85% 이상

테스트 위치:
  backend/tests/unit/        # 단위 테스트 (외부 의존 Mock)
  backend/tests/integration/ # 통합 테스트 (실제 DB, Testnet)
  backend/tests/e2e/         # E2E (핵심 플로우)

Binance 통합 테스트:
  - 반드시 Testnet 사용 (메인넷 절대 금지)
  - BINANCE_TESTNET=true 환경변수로 제어
```

---

## 절대 규칙 (예외 없음)

```
1. .env 파일 git 커밋 절대 금지
2. API Key, Secret, Token 소스코드 하드코딩 절대 금지
3. AI 모델: gpt-5 (OPENAI_MODEL 환경변수 기준) 외 사용 금지 (CTO 승인 없이)
4. 손절(Stop Loss) 없는 자동 주문 실행 금지
5. 출금 권한 Binance API Key 등록 허용 금지
6. Raw SQL + 문자열 포맷팅 조합 금지 (SQL Injection)
7. 주문 실행 경로 테스트 커버리지 95% 미만 PR merge 금지
8. Binance 통합 테스트는 Testnet에서만 실행
9. 일일 손실 한도 도달 시 자동매매 즉시 중단 로직 항상 포함
10. Risk Manager Agent를 건너뛴 시그널 실행 금지
```

---

## 코드 생성 시 체크리스트

기능을 구현할 때 아래 순서로 진행한다.

```
1. 아키텍처 설계 (레이어 구조, 서비스 경계)
2. Pydantic 스키마 / TypeScript 타입 정의
3. Repository (DB 쿼리)
4. Service (비즈니스 로직)
5. API Route (엔드포인트)
6. 단위 테스트
7. 통합 테스트
8. 환경변수 .env.example 업데이트
```

**주문 실행 로직을 건드릴 때는 반드시 안전 규칙 체크리스트를 먼저 확인한다.**
