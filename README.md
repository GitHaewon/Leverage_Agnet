# AI Trading Copilot

> Binance Futures 특화 AI 자동매매 SaaS

멀티 에이전트 AI가 시장 분석 → 시그널 생성 → 리스크 검증 → 자동 실행 → 거래일지까지
트레이딩 전체 사이클을 자동화하는 상업용 SaaS 플랫폼.

**구독 플랜:** Free($0) / Pro($29/월) / Elite($99/월)

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, shadcn/ui, TradingView Charts |
| Backend | FastAPI (Python 3.12+), SQLAlchemy 2.0 (async), Alembic |
| AI | Claude Sonnet API, LangGraph, pandas-ta, FinBERT |
| Database | PostgreSQL 16, TimescaleDB, Redis 7.2 |
| Queue | Celery, Redis Streams |
| Payment | Stripe |
| Infra | Docker Compose, GitHub Actions, Grafana, Prometheus |

---

## AI 에이전트 파이프라인

```
Technical Analysis Agent   (RSI, MACD, Bollinger Bands, EMA, Volume)
          ↓ 병렬 실행
Sentiment Agent            (FinBERT, Fear & Greed Index)
          ↓
Market Structure Agent     (Open Interest, Funding Rate, Long/Short 비율)
          ↓
Synthesis Agent            (Claude Sonnet — 종합 판단, 신뢰도, 근거 생성)
          ↓
Risk Manager Agent         (포지션 사이징, 레버리지 검증, 손실 한도 체크)
          ↓
     FINAL SIGNAL
```

---

## MVP 범위 (8주)

- Binance Futures API 연결 (BTC, ETH, Testnet 지원)
- AI 시그널 생성 (LONG / SHORT / HOLD + 신뢰도 + 근거 3줄)
- 자동매매 실행 (시장가 주문, TP/SL 자동 설정)
- 실시간 포지션 모니터링 (WebSocket)
- 기본 수익률 대시보드
- 텔레그램 알림 (5종) + 명령어 (7개)
- 이메일 인증 + TOTP 2FA
- Stripe 구독 결제 (Free / Pro)

---

## 프로젝트 문서

| 문서 | 설명 |
|------|------|
| [CLAUDE.md](CLAUDE.md) | AI 코딩 규칙 — Claude가 CTO로 따르는 모든 원칙 |
| [PROJECT_CHARTER.md](PROJECT_CHARTER.md) | 프로젝트 비전, 핵심 가치, KPI, 기술/개발/보안 원칙 |
| [PRD.md](PRD.md) | 상세 제품 요구사항 — 페르소나, 기능, 유저 플로우, 페이지 구조 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 시스템 아키텍처 — 10개 섹션, Mermaid 다이어그램 |
| [DATABASE.md](DATABASE.md) | PostgreSQL 스키마 — 9개 테이블 DDL, ERD, 인덱스, 제약조건 |
| [AGENTS.md](AGENTS.md) | AI 에이전트 명세 — 9개 에이전트 역할/입출력/실패처리/JSON 예시 |
| [TRADING_RULES.md](TRADING_RULES.md) | 리스크 규칙 — Risk Agent가 직접 사용하는 상수 및 검증 로직 |
| [API_SPEC.md](API_SPEC.md) | API 명세 — 8개 도메인, Request/Response/Error 예시 전체 |
| [TASKS.md](TASKS.md) | MVP 태스크 분해 — Epic/Feature/Task, 소요시간/우선순위/의존성 |

---

## 폴더 구조 (구현 예정)

```
ai-trading-copilot/
├── backend/
│   ├── api/            # FastAPI 라우터
│   ├── services/       # 비즈니스 로직
│   ├── repositories/   # DB 쿼리 (SQLAlchemy)
│   ├── models/         # ORM 모델
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

## 트레이딩 안전 원칙

```
1. Stop Loss 없는 자동 주문 실행 절대 금지
2. R:R 2.0 미만 시그널 거부
3. 최대 레버리지 20x 상한 (플랜/사용자 설정으로 추가 제한)
4. 일일 손실 한도 도달 시 자동매매 즉시 중단
5. 출금 권한 Binance API Key 등록 차단
6. Risk Manager Agent 없이 시그널 실행 불가
```

---

## 환경변수

`.env.example` 참조. 실제 값은 절대 커밋하지 않는다.

```bash
ANTHROPIC_API_KEY=
BINANCE_ENCRYPT_KEY=
DATABASE_URL=
REDIS_URL=
JWT_SECRET=
JWT_REFRESH_SECRET=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
TELEGRAM_BOT_TOKEN=
CLAUDE_MODEL=claude-sonnet-4-6
BINANCE_TESTNET=true
```

---

## 개발 일정

| 주차 | 작업 |
|------|------|
| Week 1 | 인프라 & Docker Compose & 인증 |
| Week 2 | Binance 연동 & 구독 결제 기반 |
| Week 3~4 | AI 에이전트 엔진 & LangGraph 파이프라인 |
| Week 5~6 | 자동매매 실행 & 포지션 모니터링 |
| Week 7 | 프론트엔드 & 텔레그램 봇 |
| Week 8 | 테스트 & QA & 베타 런칭 |

자세한 태스크 목록은 [TASKS.md](TASKS.md) 참조.

---

## 라이선스

Private — All rights reserved.
