# AI Trading Copilot

> Binance Futures 특화 AI 자동매매 SaaS — 멀티 에이전트 AI가 시장을 분석하고, 주문을 실행하고, 리스크를 관리한다.

---

## 이 프로젝트가 뭔가요?

**AI Trading Copilot**은 암호화폐(BTC, ETH) 선물 거래를 AI가 자동으로 대신해주는 서비스입니다.

직접 차트를 보지 않아도 됩니다. AI가 24시간 시장을 감시하고, 매매 타이밍을 판단하고, 주문을 넣고, 리스크를 관리합니다. 거래가 끝나면 결과 리포트까지 자동으로 생성됩니다.

**수익을 보장하지는 않습니다.** 하지만 인간이 감정적으로 판단하는 것보다 더 규칙에 따라 일관되게 거래합니다.

---

## 어떻게 작동하나요?

```
사용자가 Binance API Key를 등록
           ↓
AI가 15분마다 자동으로 시장을 분석
           ↓
"BTC를 지금 사야 할까? 팔아야 할까?"
           ↓
판단이 서면 자동으로 주문 실행
(손절가·목표가 자동 설정)
           ↓
포지션 실시간 모니터링
           ↓
텔레그램으로 알림 발송
```

AI는 단계별로 작동합니다:

| 단계 | 역할 | 설명 |
|------|------|------|
| 1 | **기술적 분석** | RSI, MACD, 볼린저 밴드 등 지표를 계산 |
| 2 | **감성 분석** | 뉴스 및 공포/탐욕 지수를 분석 |
| 3 | **시장 구조 분석** | 미결제약정, 펀딩비, 롱/숏 비율 체크 |
| 4 | **종합 판단** | Claude AI가 모든 데이터를 보고 최종 의견 생성 |
| 5 | **리스크 검증** | 포지션 크기, 레버리지, 손실 한도 검증 |

5단계를 모두 통과해야만 주문이 실행됩니다. **이 중 하나라도 거부하면 주문은 취소됩니다.**

---

## 구독 플랜

| 플랜 | 가격 | 기능 |
|------|------|------|
| **Free** | $0/월 | 시그널 조회 (주문 실행 없음), 1개 코인 |
| **Pro** | $29/월 | 자동매매, 2개 코인, 텔레그램 알림, 최대 레버리지 10x |
| **Elite** | $99/월 | 모든 기능, 5개 코인, 우선 지원, 최대 레버리지 20x |

---

## 지금까지 만들어진 것

### 백엔드 (Python / FastAPI)

**인증 & 보안**
- 이메일/비밀번호 로그인, TOTP 2FA (Google Authenticator 호환)
- JWT 액세스 토큰 + 리프레시 토큰
- Binance API Key AES-256-GCM 암호화 저장
- 출금 권한이 있는 API Key 등록 차단

**AI 에이전트 (16개 모듈)**

```
agents/
├── technical_analysis/   기술적 지표 계산 (RSI, MACD, BB, EMA, Volume)
├── sentiment/            감성 분석 (FinBERT, Fear & Greed Index, 뉴스)
├── market_structure/     시장 구조 분석 (OI, Funding Rate, Long/Short 비율)
├── synthesis/            Claude AI 종합 판단 — 시그널 생성
├── analyst/              분석 보고서 생성
├── risk/                 리스크 검증 (손실 한도, 레버리지, Kelly 기준)
├── portfolio/            포트폴리오 집중도 & 상관관계 분석
├── execution/            Binance 주문 실행
├── position_manager/     포지션 TP/SL 관리, DCA, 긴급 청산
├── market_data/          OHLCV 데이터 수집 및 저장
├── strategy/             매매 전략 (EMA 추세추종, RSI 반전, 브레이크아웃)
├── backtest/             전략 백테스팅 엔진
├── paper_trading/        모의 거래 (실제 돈 없이 연습)
├── monitoring/           시스템 메트릭 수집 (Prometheus)
└── alert/                텔레그램/이메일 알림
```

**FastAPI 백엔드**

```
backend/app/
├── api/          API 라우터 (인증, Binance, 사용자, 웹소켓)
├── services/     비즈니스 로직
├── repositories/ 데이터베이스 쿼리
├── models/       데이터 모델 (ORM)
├── schemas/      입출력 스키마 (Pydantic v2)
├── clients/      Binance REST/WS 클라이언트
├── core/         설정, 암호화, 보안 유틸
└── workers/      Celery 백그라운드 작업
```

### 프론트엔드 (Next.js 14 / TypeScript)

5개 페이지 완성, 실시간 WebSocket 연결:

| 페이지 | 주소 | 내용 |
|--------|------|------|
| 로그인 | `/login` | 이메일/비밀번호, TOTP 2FA 지원 |
| 대시보드 | `/dashboard` | 잔고, 수익 차트(TradingView), 오픈 포지션 요약 |
| 포지션 | `/positions` | 실시간 미실현 손익, 청산가 거리, 즉시 청산 버튼 |
| 거래 내역 | `/trades` | 전체 주문 이력, 필터·페이지네이션 |
| 리스크 현황 | `/risk` | 승률, 최대 낙폭, 샤프 비율, 일별 수익 그래프 |

**기술 특징:**
- 모든 API 응답 Zod 스키마로 런타임 검증
- WebSocket 자동 재연결 (최대 5회, 3초 간격)
- Zustand 상태 관리 + localStorage 영속성
- TypeScript strict mode — `any` 타입 전면 금지

### 테스트

| 영역 | 테스트 파일 수 | 비고 |
|------|--------------|------|
| Python 백엔드 | ~50개 파일 | unit + integration |
| AI 에이전트 | ~40개 파일 | 각 모듈별 단위 테스트 |
| TypeScript 프론트 | 9개 파일 · 115개 테스트 | Vitest + React Testing Library |

주문 실행 경로 테스트 커버리지 목표: **95% 이상**

---

## 로컬에서 실행하기

> 현재 백엔드 인프라(PostgreSQL, Redis) 없이도 프론트엔드 전체 플로우를 체험할 수 있습니다.

### 1단계 — 소스 받기

```bash
git clone <repo-url>
cd Leverage_Agent/frontend
npm install
```

### 2단계 — Mock API 서버 시작 (별도 터미널)

```bash
node mock-server.mjs
# → http://localhost:8000 에서 실행됨
```

데이터베이스 없이 모든 API 응답을 흉내냅니다.

### 3단계 — 프론트엔드 시작

```bash
npm run dev
# → http://localhost:3000 에서 실행됨
```

### 4단계 — 브라우저에서 접속

```
주소: http://localhost:3000
이메일: demo@trading.com
비밀번호: Demo1234!
```

### 테스트 실행

```bash
# 프론트엔드
cd frontend
npm test

# 백엔드 (Python 환경 필요)
cd ..
pytest tests/ -v
```

---

## 환경변수

`.env.example` 파일을 복사해서 `.env` 파일을 만들고 값을 채웁니다.

```bash
cp .env.example .env
```

```bash
# AI
ANTHROPIC_API_KEY=           # Anthropic 콘솔에서 발급

# Binance
BINANCE_ENCRYPT_KEY=         # API Key 암호화용 32바이트 랜덤 키
BINANCE_TESTNET=true         # 개발 중에는 반드시 true

# Database
DATABASE_URL=                # PostgreSQL 연결 문자열
REDIS_URL=                   # Redis 연결 문자열

# 인증
JWT_SECRET=                  # 랜덤 64바이트 문자열
JWT_REFRESH_SECRET=          # 랜덤 64바이트 문자열

# 결제
STRIPE_SECRET_KEY=           # Stripe 대시보드에서 발급
STRIPE_WEBHOOK_SECRET=       # Stripe 웹훅 서명 키

# 알림
TELEGRAM_BOT_TOKEN=          # @BotFather에서 발급

# AI 모델 (변경 금지)
CLAUDE_MODEL=claude-sonnet-4-6
```

> **주의:** `.env` 파일은 절대 git에 커밋하지 않습니다.

---

## 프로젝트 구조

```
Leverage_Agent/
│
├── agents/                 AI 에이전트 모듈 (Python)
│   ├── technical_analysis/ RSI, MACD, Bollinger Bands 등 지표 계산
│   ├── sentiment/          뉴스 감성 분석 (FinBERT)
│   ├── market_structure/   OI·펀딩비·롱숏 비율
│   ├── synthesis/          Claude AI 최종 판단
│   ├── risk/               리스크 검증 & Kelly Criterion
│   ├── portfolio/          포트폴리오 집중도 & 상관관계
│   ├── execution/          Binance 주문 실행
│   ├── position_manager/   포지션 관리 (TP/SL, DCA)
│   ├── market_data/        OHLCV 수집 & 저장
│   ├── strategy/           매매 전략 엔진
│   ├── backtest/           백테스팅
│   ├── paper_trading/      모의 거래
│   ├── monitoring/         시스템 모니터링
│   └── alert/              알림 발송
│
├── backend/                FastAPI 서버 (Python)
│   └── app/
│       ├── api/            HTTP 엔드포인트
│       ├── services/       비즈니스 로직
│       ├── repositories/   DB 쿼리
│       ├── models/         ORM 모델
│       ├── schemas/        요청/응답 스키마
│       ├── clients/        Binance API 클라이언트
│       ├── core/           설정·보안·암호화
│       └── workers/        Celery 작업
│
├── frontend/               Next.js 14 (TypeScript)
│   ├── app/                페이지 라우트
│   │   ├── (auth)/login    로그인 페이지
│   │   └── (dashboard)/    대시보드·포지션·거래·리스크
│   ├── components/         재사용 컴포넌트
│   ├── hooks/              WebSocket, 데이터 페칭 훅
│   ├── lib/                API 클라이언트, Zod 스키마
│   ├── store/              Zustand 상태 관리
│   ├── tests/              Vitest 테스트 (115개)
│   └── mock-server.mjs     로컬 데모용 Mock API
│
├── tests/                  Python 테스트
│   ├── unit/               단위 테스트
│   └── integration/        통합 테스트 (Testnet)
│
├── docker-compose.yml      전체 스택 실행 설정
├── CLAUDE.md               AI 코딩 규칙 (CTO 역할 가이드)
├── ARCHITECTURE.md         시스템 아키텍처 다이어그램
├── DATABASE.md             PostgreSQL 스키마 & ERD
├── AGENTS.md               AI 에이전트 명세
├── API_SPEC.md             REST API 명세
├── TRADING_RULES.md        리스크 규칙 상수
└── TASKS.md                MVP 태스크 목록
```

---

## 안전 규칙 (절대 우회 불가)

이 규칙들은 코드 어디서도 건드릴 수 없습니다.

```
1. 손절가(Stop Loss) 없는 자동 주문은 절대 실행하지 않는다
2. Risk:Reward 비율이 1:2 미만인 시그널은 거부한다
3. 레버리지 최대 20배 상한 (플랜/설정으로 추가 제한 가능)
4. 일일 손실 한도 도달 시 자동매매를 즉시 중단한다
5. 출금 권한이 있는 Binance API Key는 등록을 막는다
6. Risk Manager Agent를 거치지 않은 시그널은 실행하지 않는다
7. Binance 통합 테스트는 반드시 Testnet에서만 실행한다
8. API Key·Secret은 소스코드에 하드코딩하지 않는다
9. 로그에 API Key가 출력되지 않는다
```

---

## 기술 스택 한눈에 보기

| 영역 | 기술 | 역할 |
|------|------|------|
| **프론트엔드** | Next.js 14, TypeScript, Tailwind CSS | 웹 대시보드 |
| **UI 컴포넌트** | shadcn/ui, TradingView Charts | 차트·테이블·버튼 등 |
| **상태 관리** | Zustand, TanStack Query | 앱 상태·서버 데이터 |
| **백엔드** | FastAPI (Python 3.12) | REST API 서버 |
| **ORM** | SQLAlchemy 2.0 (async) | DB 쿼리 |
| **AI** | Claude Sonnet (Anthropic) | 매매 판단 |
| **AI 오케스트레이션** | LangGraph | 에이전트 파이프라인 |
| **지표 계산** | pandas-ta | RSI, MACD, BB 등 |
| **감성 분석** | FinBERT | 뉴스 감성 점수 |
| **주 DB** | PostgreSQL 16 | 사용자·주문·포지션 |
| **시계열 DB** | TimescaleDB | OHLCV 캔들 데이터 |
| **캐시** | Redis 7.2 | 세션·캐시·메시지 큐 |
| **작업 큐** | Celery + Redis Streams | 백그라운드 작업 |
| **결제** | Stripe | 구독 결제 |
| **알림** | Telegram Bot API | 실시간 알림 |
| **인프라** | Docker Compose | 로컬·스테이징 배포 |
| **모니터링** | Grafana + Prometheus | 시스템 메트릭 |
| **CI/CD** | GitHub Actions | 자동 테스트·배포 |

---

## 개발 로드맵

| 주차 | 목표 | 상태 |
|------|------|------|
| 1주차 | 인프라·Docker·인증 | ✅ 완료 |
| 2주차 | Binance 연동·구독 결제 기반 | ✅ 완료 |
| 3~4주차 | AI 에이전트 엔진·LangGraph 파이프라인 | ✅ 완료 |
| 5~6주차 | 자동매매 실행·포지션 모니터링 | ✅ 완료 |
| 7주차 | 프론트엔드 대시보드·텔레그램 봇 | ✅ 완료 |
| 8주차 | 테스트·QA·베타 런칭 | 🔄 진행 중 |

---

## 참고 문서

| 문서 | 내용 |
|------|------|
| [CLAUDE.md](CLAUDE.md) | AI 코딩 규칙 (이 프로젝트의 개발 헌법) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 시스템 전체 구조도 (Mermaid 다이어그램 포함) |
| [DATABASE.md](DATABASE.md) | PostgreSQL 테이블 설계 및 ERD |
| [AGENTS.md](AGENTS.md) | AI 에이전트 9개 상세 명세 |
| [API_SPEC.md](API_SPEC.md) | REST API 엔드포인트 전체 목록 |
| [TRADING_RULES.md](TRADING_RULES.md) | 리스크 관리 규칙 및 상수 |
| [PRD.md](PRD.md) | 제품 요구사항 문서 |
| [TASKS.md](TASKS.md) | MVP 작업 목록 및 우선순위 |

---

## Docker로 전체 스택 실행하기

> PostgreSQL, Redis, FastAPI, Celery, Next.js를 한 번에 띄웁니다.  
> Docker Desktop이 설치되어 있어야 합니다.

### 1단계 — 환경변수 파일 준비

```bash
cp .env.example .env
# .env 파일을 열어서 비어있는 값들을 채운다
# 최소한 아래 4개는 반드시 설정해야 한다:
#   ANTHROPIC_API_KEY
#   BINANCE_ENCRYPT_KEY
#   JWT_SECRET
#   JWT_REFRESH_SECRET
```

### 2단계 — 전체 스택 시작

```bash
docker compose up -d
```

처음 실행 시 이미지 빌드에 2~3분 소요됩니다.

```
서비스               포트    역할
──────────────────────────────────────────
frontend            :3000   Next.js 대시보드
backend             :8000   FastAPI REST API
postgres            :5432   PostgreSQL DB
redis               :6379   캐시 / 세션 / 큐
celery-worker       -       백그라운드 작업자
grafana             :3001   모니터링 대시보드
prometheus          :9090   메트릭 수집
```

### 3단계 — DB 마이그레이션

```bash
docker compose exec backend alembic upgrade head
```

### 4단계 — 브라우저 접속

```
대시보드:  http://localhost:3000
API 문서:  http://localhost:8000/docs   (Swagger UI)
Grafana:   http://localhost:3001        (admin / admin)
```

### 전체 중지

```bash
docker compose down          # 컨테이너만 중지 (데이터 유지)
docker compose down -v       # 컨테이너 + 볼륨 삭제 (데이터 초기화)
```

---

## 환경변수 상세 설명

`.env.example`을 복사해서 사용합니다. 각 변수의 의미와 발급 방법을 설명합니다.

### 애플리케이션 기본 설정

```bash
APP_ENV=development      # development | staging | production
DEBUG=true               # 프로덕션에서는 반드시 false
APP_VERSION=0.1.0        # 버전 태그
```

### 데이터베이스

```bash
DATABASE_URL=postgresql://trading:trading_pass@localhost:5432/trading_copilot

# Docker 사용 시 위 기본값 그대로 사용 가능
# 외부 DB 사용 시 형식: postgresql://유저:비밀번호@호스트:포트/DB이름
DB_POOL_SIZE=10          # DB 커넥션 풀 크기 (트래픽에 따라 조정)
DB_MAX_OVERFLOW=20       # 풀 초과 시 최대 추가 커넥션 수
DB_ECHO=false            # true로 설정하면 모든 SQL이 로그에 출력됨 (디버깅용)
```

### Redis

```bash
REDIS_URL=redis://localhost:6379/0

# /0 은 Redis DB 번호 (0~15). 환경별로 분리할 때 /1, /2 사용
REDIS_MAX_CONNECTIONS=20
```

### JWT 인증

```bash
JWT_SECRET=...                          # 액세스 토큰 서명 키
JWT_REFRESH_SECRET=...                  # 리프레시 토큰 서명 키
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15      # 액세스 토큰 만료 (15분 권장)
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7         # 리프레시 토큰 만료 (7일)
```

**JWT_SECRET 생성 방법:**

```bash
# 터미널에서 랜덤 64자리 키 생성
python3 -c "import secrets; print(secrets.token_hex(32))"
# 또는
openssl rand -hex 32
```

JWT_SECRET과 JWT_REFRESH_SECRET은 **서로 다른 값**을 사용해야 합니다.

### Binance API

```bash
BINANCE_TESTNET=true          # 개발·테스트 중에는 반드시 true
                               # 실제 돈 거래 시에만 false로 변경
BINANCE_ENCRYPT_KEY=...       # API Key 암호화용 32자리 16진수 키
```

**BINANCE_ENCRYPT_KEY 생성 방법:**

```bash
python3 -c "import secrets; print(secrets.token_hex(16))"
# 결과 예시: 0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d
```

**Binance Testnet API Key 발급:**
1. https://testnet.binancefuture.com 접속
2. 우측 상단 계정 아이콘 → API Key
3. 새 키 생성 (읽기 + 거래 권한만 — **출금 권한 체크 금지**)

### Anthropic AI

```bash
ANTHROPIC_API_KEY=sk-ant-...      # Anthropic Console에서 발급
CLAUDE_MODEL=claude-sonnet-4-6    # 이 값은 변경하지 않는다
```

**API Key 발급:** https://console.anthropic.com → API Keys → Create Key

### Stripe 결제

```bash
STRIPE_SECRET_KEY=sk_test_...     # 개발 환경: sk_test_ 로 시작
                                   # 프로덕션:  sk_live_ 로 시작
STRIPE_WEBHOOK_SECRET=whsec_...   # Stripe 웹훅 서명 검증 키
```

**Stripe 설정 방법:**
1. https://dashboard.stripe.com 접속
2. Developers → API Keys → Secret Key 복사
3. Developers → Webhooks → Add endpoint
   - URL: `https://your-domain.com/api/v1/stripe/webhook`
   - Events: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`
4. Signing secret 복사 → `STRIPE_WEBHOOK_SECRET`

### 텔레그램 알림

```bash
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGhIjKlMnOpQrStUvWxYz
```

**텔레그램 봇 생성:**
1. 텔레그램에서 `@BotFather` 검색
2. `/newbot` 명령어 입력
3. 봇 이름 및 사용자명 설정
4. 발급된 토큰을 `TELEGRAM_BOT_TOKEN`에 입력
5. 자신의 Chat ID 확인: `@userinfobot`에서 `/start` → `Id:` 뒤의 숫자

### 이메일 (SMTP)

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=앱_비밀번호_16자리    # Gmail 앱 비밀번호 (계정 비밀번호 X)
SMTP_FROM=noreply@your-domain.com
```

**Gmail 앱 비밀번호 발급:**
1. Google 계정 → 보안 → 2단계 인증 활성화
2. 앱 비밀번호 → 메일 → 기타 → 이름 입력 → 생성
3. 16자리 비밀번호를 `SMTP_PASSWORD`에 입력

---

## AI 시그널 형식

AI가 분석을 완료하면 아래 형식의 시그널이 생성됩니다. 이 시그널이 Risk Manager를 통과해야만 주문이 실행됩니다.

```json
{
  "coin": "BTC",
  "direction": "LONG",
  "confidence": 0.78,
  "entry": 67500.0,
  "take_profit": 69800.0,
  "stop_loss": 66350.0,
  "leverage": 5,
  "rr_ratio": 2.0,
  "reason": "15분봉 기준 RSI(14)=38로 과매도 구간 진입, MACD 골든크로스 형성 중.\n볼린저 밴드 하단 터치 후 반등 확인, OI 증가 + 펀딩비 음수로 롱 유리.\nFear & Greed 지수 29(극단적 공포)로 단기 반전 가능성 높음."
}
```

| 필드 | 의미 |
|------|------|
| `direction` | LONG (가격 오를 것) / SHORT (가격 내릴 것) / HOLD (진입 안 함) |
| `confidence` | 신뢰도 0.0~1.0 (0.6 미만이면 HOLD로 처리) |
| `take_profit` | 목표가 — 여기서 자동 익절 |
| `stop_loss` | 손절가 — 여기서 자동 손절 (없으면 주문 불가) |
| `rr_ratio` | Risk:Reward 비율 (최소 2.0 이상이어야 실행) |
| `reason` | AI가 생성한 3줄 이상 근거 |

---

## 텔레그램 알림 종류

자동매매 과정에서 아래 5가지 알림이 발송됩니다.

| 알림 | 발송 시점 |
|------|-----------|
| 시그널 생성 | AI가 LONG/SHORT 시그널을 생성했을 때 |
| 주문 체결 | Binance에서 주문이 체결되었을 때 |
| TP 도달 (익절) | 목표가에 도달해 자동 익절됐을 때 |
| SL 도달 (손절) | 손절가에 도달해 자동 손절됐을 때 |
| 일일 손실 한도 | 하루 손실이 설정 한도에 도달했을 때 (자동매매 중단) |

---

## API 엔드포인트 요약

전체 명세는 [API_SPEC.md](API_SPEC.md) 또는 서버 실행 후 http://localhost:8000/docs 참조.

```
인증
  POST /api/v1/auth/register           회원가입
  POST /api/v1/auth/login              로그인
  POST /api/v1/auth/refresh            토큰 갱신
  POST /api/v1/auth/logout             로그아웃
  POST /api/v1/auth/2fa/enable         2FA 활성화
  POST /api/v1/auth/2fa/verify         2FA 검증

사용자
  GET  /api/v1/users/me                내 프로필
  PUT  /api/v1/users/me                프로필 수정
  GET  /api/v1/users/me/stats          수익 통계

Binance 연동
  POST /api/v1/binance/api-key         API Key 등록
  GET  /api/v1/binance/balance         잔고 조회
  GET  /api/v1/binance/positions       포지션 목록

주문
  GET  /api/v1/orders                  주문 내역
  POST /api/v1/orders                  수동 주문
  GET  /api/v1/orders/{id}             주문 상세

포지션
  GET  /api/v1/positions               포지션 목록
  POST /api/v1/positions/{id}/close    포지션 청산

AI 시그널
  GET  /api/v1/signals                 시그널 목록
  POST /api/v1/signals/generate        수동 시그널 생성 요청

결제
  POST /api/v1/stripe/checkout         결제 세션 생성
  POST /api/v1/stripe/webhook          Stripe 웹훅 수신
  GET  /api/v1/stripe/subscription     구독 상태 조회

WebSocket
  WS   /ws/v1/dashboard               실시간 잔고·포지션 업데이트
```

---

## 모니터링

Docker Compose로 실행 시 Grafana가 자동으로 시작됩니다.

```
Grafana 접속: http://localhost:3001
기본 계정:    admin / admin (최초 접속 후 변경 권장)
```

**주요 대시보드:**

| 대시보드 | 내용 |
|----------|------|
| API Latency | 엔드포인트별 응답 시간 |
| Order Pipeline | 시그널 생성 → 주문 체결까지 성공/실패율 |
| Agent Health | 각 AI 에이전트 실행 시간·오류율 |
| System Resources | CPU, 메모리, DB 커넥션 |

---

## 개발 가이드

### 코드 추가 순서

새 기능을 구현할 때는 항상 이 순서를 따릅니다:

```
1. Pydantic 스키마 정의  (backend/app/schemas/)
2. DB 모델 정의          (backend/app/models/)
3. Repository 작성       (backend/app/repositories/)  ← DB 쿼리만
4. Service 작성          (backend/app/services/)       ← 비즈니스 로직만
5. API Route 작성        (backend/app/api/)            ← 요청/응답만
6. 단위 테스트           (tests/unit/)
7. 통합 테스트           (tests/integration/)
8. .env.example 업데이트 (새 환경변수가 있을 경우)
```

### 레이어 경계

```
API Route  →  Service  →  Repository  →  Model(DB)

- Route가 Repository를 직접 호출하면 안 됩니다
- Service에 SQL 쿼리가 있으면 안 됩니다
- Repository에 비즈니스 로직이 있으면 안 됩니다
```

### 주문 실행 코드를 수정할 때

**반드시 먼저 확인:**

```python
# 1. SL이 없으면 실행 불가
assert signal.stop_loss is not None

# 2. R:R 2.0 미만이면 거부
assert signal.rr_ratio >= 2.0

# 3. 레버리지 상한 적용
leverage = min(signal.leverage, user.max_leverage, 20)

# 4. 포지션 크기 계산
size = (balance * risk_pct) / abs(entry - stop_loss)

# 5. 일일 손실 한도 체크
if daily_loss >= user.daily_loss_limit:
    disable_auto_trading(user_id)
```

### Python 코드 스타일

```python
# 타입 힌트 필수
async def create_order(user_id: UUID, signal: TradingSignal) -> Order:
    ...

# 매직 넘버 금지
MAX_LEVERAGE = 20        # 상수로 선언
if leverage > MAX_LEVERAGE:  # OK
if leverage > 20:            # 금지

# Raw SQL + f-string 조합 절대 금지 (SQL Injection)
stmt = select(User).where(User.id == user_id)          # OK
cursor.execute(f"SELECT * FROM users WHERE id={id}")   # 금지
```

### TypeScript 코드 스타일

```typescript
// any 타입 사용 금지
const data: unknown = response.data        // OK
const data: any = response.data            // 금지

// 모든 API 응답은 Zod로 검증
const parsed = signalSchema.parse(response.data)

// dangerouslySetInnerHTML 사용 금지
```

### 브랜치 전략

```
main            프로덕션 배포 브랜치 (직접 push 금지)
develop         통합 브랜치
feat/xxx        새 기능
fix/xxx         버그 수정
refactor/xxx    리팩터링
test/xxx        테스트 추가
```

### PR 머지 조건

```
1. 주문 실행 경로 테스트 커버리지 95% 이상
2. 전체 테스트 커버리지 80% 이상
3. TypeScript 빌드 오류 0개
4. 안전 규칙 위반 없음
5. .env 파일 미포함 확인
```

---

## 자주 묻는 질문 (FAQ)

**Q. 실제 돈으로 거래가 되나요?**

개발 중에는 `BINANCE_TESTNET=true`로 설정되어 있어 가상 자금으로만 거래됩니다. 실제 거래를 원할 경우 `BINANCE_TESTNET=false`로 변경하고 실제 Binance Futures API Key를 등록해야 합니다.

---

**Q. 수익을 보장하나요?**

아닙니다. AI는 패턴을 분석해서 확률적으로 유리한 시점을 찾는 것이지, 수익을 보장하지 않습니다. 손실이 발생할 수 있으며, 암호화폐 선물 거래는 원금 전액 손실이 가능한 고위험 투자입니다.

---

**Q. 어떤 코인을 지원하나요?**

MVP에서는 BTC(비트코인)와 ETH(이더리움) 선물만 지원합니다. Elite 플랜은 최대 5개 코인까지 확장 가능하도록 설계되어 있습니다.

---

**Q. 자동매매를 언제든 멈출 수 있나요?**

네. 대시보드에서 즉시 중단할 수 있습니다. 또한 다음 상황에서는 시스템이 자동으로 중단합니다:
- 일일 손실이 설정한 한도에 도달했을 때
- 청산 위험 포지션이 감지됐을 때
- Binance API 연결이 끊어졌을 때

---

**Q. Binance API Key가 유출되면 어떻게 되나요?**

이 서비스는 **거래 권한만 있는 API Key**만 등록을 허용합니다. 출금 권한이 있는 Key는 등록 즉시 거부됩니다. API Key는 AES-256-GCM으로 암호화되어 저장되며, 주문 실행 직전에만 복호화됩니다. 최악의 경우에도 거래소 계정의 자금이 외부로 출금되는 것은 막혀 있습니다.

---

**Q. AI가 어떤 데이터를 보고 판단하나요?**

5가지 정보를 종합합니다:
1. **차트 지표** — RSI, MACD, 볼린저 밴드, EMA, 거래량
2. **뉴스 감성** — FinBERT 모델이 최신 뉴스를 읽고 긍정/부정 점수 계산
3. **시장 심리** — 공포/탐욕 지수 (극단적 공포=매수 기회, 극단적 탐욕=조심)
4. **파생상품 지표** — 미결제약정(OI), 펀딩비, 롱/숏 비율
5. **Claude AI 판단** — 위 4가지를 종합해 최종 LONG/SHORT/HOLD 결정

---

## 라이선스

Private — All rights reserved.
