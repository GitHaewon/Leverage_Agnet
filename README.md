# AI Trading Copilot

**Crypto Futures Trading Decision-Support Pipeline**

암호화폐 선물 시장 데이터를 수집하고, 결정적 규칙으로 거래 후보를 생성한 뒤,
AI가 검토하고 리스크 엔진이 최종 안전 게이트를 수행하는 의사결정 지원 시스템이다.

---

## 안전 공지 (Safety Notice)

> **이 프로젝트는 금융 조언이 아닙니다.**
> 암호화폐 선물 거래는 원금 전액 손실이 가능한 고위험 투자입니다.

- **실거래 주문 실행은 기본 비활성화**(`LIVE_TRADING_ENABLED=false`)되어 있다. 플래그를 `true`로 변경하기 전에 반드시 shadow 기간을 충분히 거쳐야 한다.
- AI(`ReviewerAgent`)는 후보를 `APPROVE` 또는 `REJECT`만 할 수 있다. 진입가·손절가·목표가·레버리지를 만들거나 수정하는 권한이 없다.
- `HIGH_VOLATILITY` 또는 `NEWS_EVENT` 국면에서는 모든 신규 진입이 차단된다. `UNKNOWN` 국면도 보수적으로 `REJECT`된다.
- 다양한 코인을 지원하도록 설계되어 있으나, 코인마다 유동성·변동성·스프레드·펀딩비가 다르므로 동일한 임계값을 그대로 사용하면 안 된다.
- 사용자는 실제 API Key나 자금을 연결하기 전에 반드시 충분한 shadow 테스트와 backtesting을 수행해야 한다.

---

## 프로젝트 개요

### 목적

이 프로젝트는 **실거래 자동 실행 봇이 아니다.** 현재 주된 운영 목적은 다음과 같다:

1. **Shadow Trading / Paper Decision Evaluation** — 실제 시장 데이터로 가상 거래 결정을 평가한다.
2. **Decision-Support Pipeline** — 시장 데이터 → 기술적 분석 → 전략 → 결정 → AI 리뷰 → 리스크 검증 → 최종 결정 → 로그까지 이어지는 파이프라인을 제공한다.
3. **AI는 Reviewer 역할만 수행** — 결정적 코드(`DecisionEngine`)가 거래 후보를 생성하고, GPT 기반 `ReviewerAgent`가 검토하며, `RiskEngine`이 최종 안전 게이트를 담당한다. AI가 직접 주문을 결정하지 않는다.

### 멀티 심볼 지원

파이프라인은 `coin` 파라미터(예: `"BTC"`, `"ETH"`)를 입력받아 `{coin}USDT` 심볼로 작동한다.

- **현재 구조**: 파이프라인 1회 실행 = 코인 1개 처리. 여러 코인을 처리하려면 파이프라인을 코인별로 반복 실행한다.
- **BTC는 기본 예시 심볼**이다. `scripts/` 하위 스모크 테스트와 `verify_openai.py`에서 `BTCUSDT` 픽스처 데이터를 사용하지만, 프로젝트가 BTC 전용은 아니다.
- 다른 코인으로 전환하려면 `PipelineInput(coin="ETH", ...)` 또는 실행 스크립트의 `--symbol` 인자를 변경한다.

---

## Pipeline 구조

```
Step 1.  market_data       CRITICAL   실패 → FAILED (파이프라인 중단)
Step 2.  technical         DEGRADED   실패 → 중립값(tech_score=0.0)으로 계속
Step 3.  strategy          DEGRADED   실패 → 중립값으로 계속
Step 4.  decision          결정적      국면/점수/전략선택/후보 생성. 예외·HOLD → 종료
Step 5.  ai_review         검토 전용   APPROVE/REJECT만. 파싱 실패 → 안전 REJECT → HOLD
Step 6.  risk              GATE        validate_candidate. 예외/거부 → HOLD (실행 없음)
Step 7.  final_decision    결정적      candidate+review+risk 조립. HOLD → 실행 없음
Step 8.  portfolio         GATE        실패/거부 → REJECTED
Step 9.  position_manager  실패 → FAILED
Step 10. execution         실패 → FAILED (retry=3) | TP/SL 실패 → 긴급 청산
```

| 컴포넌트 | 클래스 | 역할 |
|---|---|---|
| `decision` | `DecisionEngine` | 결정적 `TradeCandidate` 생성 (AI 호출 없음) |
| `ai_review` | `ReviewerAgent` (GPT) | `APPROVE` / `REJECT`만 — 숫자 권한 없음 |
| `risk` | `RiskEngine.validate_candidate` | 최종 안전 게이트 (R:R, SL, 손실 한도 등) |
| `final_decision` | `decide_final_action` | 세 레이어를 조합, HOLD 아니면 실행 경로 |
| `execution` | `ExecutionEngine` / `ShadowExecutionEngine` | 실거래 또는 Shadow 기록 |

**안전 원칙**: FinalDecision이 `LONG` 또는 `SHORT`일 때만 실행 경로에 도달한다. 분류/점수/후보생성/AI리뷰/리스크/최종결정 중 어떤 예외도 `HOLD`/`REJECT`로 귀결된다.

---

## Market Regime & Strategy Playbook

`DecisionEngine`과 `ReviewerAgent`는 모두 `REGIME_ALLOWED_STRATEGIES` 플레이북을 참조한다.

### MarketRegime 분류

| Regime | 설명 |
|---|---|
| `TREND_UP` | 상승 추세 |
| `TREND_DOWN` | 하락 추세 |
| `RANGE` | 횡보 |
| `HIGH_VOLATILITY` | 고변동성 — **모든 신규 진입 차단** |
| `NEWS_EVENT` | 뉴스 이벤트 — **모든 신규 진입 차단** |
| `UNKNOWN` | 불명확 — **보수적 REJECT** |

### REGIME_ALLOWED_STRATEGIES

```python
REGIME_ALLOWED_STRATEGIES = {
    "TREND_UP":       ("TREND_FOLLOWING", "TREND_PULLBACK", "BREAKOUT", "BREAKOUT_RETEST", "INTRADAY"),
    "TREND_DOWN":     ("TREND_FOLLOWING", "TREND_PULLBACK", "BREAKOUT", "BREAKOUT_RETEST", "INTRADAY"),
    "RANGE":          ("MEAN_REVERSION", "RSI_REVERSAL", "SCALPING", "INTRADAY"),
    "HIGH_VOLATILITY": (),    # No Trade
    "NEWS_EVENT":     (),     # No Trade
    "UNKNOWN":        (),     # Conservative reject
}
```

### 전략별 최소 R:R (STRATEGY_MIN_RR)

모든 전략의 최소 R:R은 `2.0`이다. `RiskEngine`은 이 값을 최종 강제한다.

```python
STRATEGY_MIN_RR = {
    "SCALPING":        2.0,
    "INTRADAY":        2.0,
    "TREND_FOLLOWING": 2.0,
    "TREND_PULLBACK":  2.0,
    "BREAKOUT":        2.0,
    "BREAKOUT_RETEST": 2.0,
    "MEAN_REVERSION":  2.0,
    "RSI_REVERSAL":    2.0,
    "UNKNOWN":         999.0,  # 사실상 전략 없음
}
```

### 전략 선택 우선순위 (`select_strategy_type`)

```
1. TREND_FOLLOWING   (TREND_UP/DOWN + 강한 방향성)
2. BREAKOUT          (거래량 급증 + 이른 진입 기회)
3. INTRADAY          (보통 추세·횡보 + 적정 방향성)
4. SCALPING          (저변동 + 타이트 스프레드 + 소폭 엣지)
5. UNKNOWN           (조건 미충족 → 상위 레이어 HOLD 처리)
```

### ReviewerAgent 플레이북 가드

`ReviewerAgent`는 GPT 호출 전에 결정적으로 플레이북을 적용한다:
- `HIGH_VOLATILITY` / `NEWS_EVENT` / `UNKNOWN` 국면 → 즉시 `REJECT`
- 현재 국면에서 허용되지 않는 전략 → 즉시 `REJECT`
- 전략별 최소 R:R 미충족 → 즉시 `REJECT`

플레이북 통과 후에만 GPT API가 호출된다.

---

## 디렉토리 구조

```
Leverage_Agent/
├── agents/
│   ├── alert/              # Telegram alert dispatcher
│   ├── analyst/            # (deprecated — 마이그레이션 보류 중)
│   ├── backtest/           # 백테스팅 엔진
│   ├── decision/           # 핵심 의사결정 레이어
│   │   ├── candidate_generator.py   # TradeCandidate 생성
│   │   ├── chart_signals.py         # 차트 시그널 점수화
│   │   ├── constants.py             # 임계값 상수 (REGIME_ALLOWED_STRATEGIES 등)
│   │   ├── derivatives_market.py    # 파생 시장 점수화
│   │   ├── engine.py                # DecisionEngine (결정적)
│   │   ├── final_decision.py        # decide_final_action
│   │   ├── models.py                # TradeCandidate, AIReviewResult, FinalAction 등
│   │   ├── news_sentiment.py        # 뉴스 감성 점수화
│   │   ├── regime.py                # classify_market_regime
│   │   └── strategy_selector.py     # select_strategy_type
│   ├── execution/          # ExecutionEngine, ExecutionGateway
│   ├── market_data/        # 시장 데이터 수집·정규화
│   ├── market_structure/   # OI, 펀딩비, 롱숏 비율
│   ├── monitoring/         # Prometheus 메트릭
│   ├── orchestrator/       # OrchestratorPipeline (10단계 조율)
│   ├── paper_trading/      # Paper trading 엔진 (독립 모듈)
│   ├── portfolio/          # 포트폴리오 관리
│   ├── position_manager/   # 포지션 라이프사이클 (TP/SL, 긴급 청산, DCA)
│   ├── risk/               # RiskEngine, KillSwitch, 포지션 사이징
│   ├── sentiment/          # 뉴스 수집, Fear & Greed 지수
│   ├── shadow/             # ShadowExecutionEngine, performance_analysis
│   ├── strategy/           # 전략 구현 (breakout, ema_trend, rsi_reversal)
│   ├── synthesis/          # ReviewerAgent (GPT 기반 AI 리뷰어)
│   └── technical_analysis/ # 기술 지표 계산 (RSI, MACD, BB, EMA 등)
│
├── backend/                # FastAPI 웹 서비스 레이어
│   ├── app/                # API routes, services, repositories, models, schemas
│   ├── alembic/            # DB 마이그레이션
│   ├── scripts/            # 백엔드 전용 스크립트
│   ├── tests/              # 백엔드 단위·통합 테스트
│   ├── pyproject.toml      # Python 3.12+, pytest, ruff, mypy 설정
│   ├── requirements.txt    # 운영 의존성
│   └── requirements-dev.txt
│
├── docs/
│   ├── DECISION_FLOW.md    # 파이프라인 전체 흐름 상세 설명
│   ├── RISK_ENGINE.md      # 안전 규칙·포지션 사이징 공식
│   ├── SHADOW_TRADING.md   # Shadow 모드 설정·결과 해석
│   ├── LIVE_TRADING_CHECKLIST.md  # 실거래 전환 체크리스트
│   └── KNOWN_ISSUES.md     # 알려진 이슈·설계 트레이드오프
│
├── logs/
│   ├── shadow_smoke_decisions.jsonl   # 스모크 테스트 의사결정 로그
│   └── shadow_smoke_summary.json      # 스모크 테스트 요약
│
├── scripts/
│   ├── run_shadow_smoke.py            # Shadow 스모크 테스트 실행
│   ├── analyze_shadow_performance.py  # Decision 로그 성과 분석
│   └── verify_openai.py               # OpenAI 연결 검증
│
├── tests/
│   ├── unit/agents/        # 에이전트 레이어 단위 테스트
│   ├── unit/backend/       # 백엔드 단위 테스트
│   └── integration/        # Binance Testnet 통합 테스트
│
├── .env.example
├── docker-compose.yml
├── CLAUDE.md               # 개발 절대 규칙 (CTO 권한)
└── ARCHITECTURE.md         # 전체 시스템 아키텍처
```

---

## 설치 방법

**Python 3.12 이상이 필요하다.** (macOS 기준)

```bash
# 1. 프로젝트 루트에서 가상환경 생성
cd Leverage_Agent
python3.12 -m venv .venv
source .venv/bin/activate

# 2. 백엔드 의존성 설치 (에이전트 레이어 테스트 포함)
pip install -r backend/requirements.txt
pip install -r backend/requirements-dev.txt

# 3. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 필요한 항목을 채운다 (아래 환경변수 설명 참조)
```

> `.env` 파일은 절대 git에 커밋하지 않는다. `.gitignore`에 이미 등록되어 있다.

---

## 주요 환경변수

`.env.example`을 복사해 `.env`를 작성한다.

| 변수 | 설명 | 기본값 |
|---|---|---|
| `OPENAI_API_KEY` | ReviewerAgent GPT 호출에 필요 | (필수 입력) |
| `OPENAI_MODEL` | 사용할 GPT 모델 (소스 하드코딩 금지) | `gpt-5` |
| `BINANCE_TESTNET` | `true`: Testnet 사용 / `false`: 실거래 | `true` |
| `BINANCE_ENCRYPT_KEY` | Binance API Key 암호화용 32자 hex | (필수 입력) |
| `LIVE_TRADING_ENABLED` | 실거래 전환 플래그 | `false` |
| `SHADOW_TRADING_ENABLED` | Shadow 가상 기록 활성화 | `false` |
| `SHADOW_INITIAL_BALANCE_USDT` | Shadow 초기 가상 잔고 | `10000` |
| `SHADOW_MIN_LONG_SCORE` | Shadow 전용 long_score 하한 완화 | (기본 75.0) |
| `SHADOW_MIN_SHORT_SCORE` | Shadow 전용 short_score 하한 완화 | (기본 75.0) |
| `SHADOW_MAX_RISK_SCORE` | Shadow 전용 risk_score 상한 완화 | (기본 55.0) |
| `SHADOW_AI_REVIEW_REQUIRED` | Shadow에서 AI 리뷰 우회 여부 | `true` |
| `JWT_SECRET` | 최소 32자 랜덤 문자열 | (필수 입력) |
| `JWT_REFRESH_SECRET` | 최소 32자 랜덤 문자열 (다른 값) | (필수 입력) |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 알림 발송용 | (선택) |
| `STRIPE_SECRET_KEY` | 구독 결제 처리용 | (선택) |

**시크릿 생성 예시:**

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 실행 방법

### Shadow 스모크 테스트

실제 주문을 내지 않는 Shadow 모드로 파이프라인을 1회 실행한다.
`OPENAI_API_KEY`가 없어도 실행 가능하다 (AI 리뷰어가 fake stub으로 대체됨).

```bash
# BTC 기본 픽스처 데이터로 실행
python scripts/run_shadow_smoke.py

# 결과 로그는 logs/shadow_smoke_decisions.jsonl 에 누적된다
```

### Shadow 성과 분석

Decision 로그 JSONL을 분석해 요약 통계를 출력한다.

```bash
# 기본 (shadow_smoke_decisions.jsonl 분석)
python scripts/analyze_shadow_performance.py logs/shadow_smoke_decisions.jsonl

# 결과를 별도 파일로 저장
python scripts/analyze_shadow_performance.py logs/shadow_smoke_decisions.jsonl -o results.json
```

분석 결과는 다음을 포함한다:
- 전체 decision 수 / 실행된 가상 거래 수 / HOLD 비율
- AI reject rate, 리스크 거절 코드 분포
- 거절 단계별 분포 (decision / ai_review / risk / portfolio)
- 시장 국면별·전략별·방향별 성과
- 승률, Profit factor, Max drawdown, 수수료/슬리피지 반영 순손익
- 경고: Net PnL ≤ 0, Profit factor < 1.2 등

### OpenAI 연결 검증

```bash
python scripts/verify_openai.py
# OPENAI_API_KEY, OPENAI_MODEL 환경변수를 읽어 LONG/SHORT/HOLD 시나리오를 테스트한다
```

### 전체 시스템 실행 (Docker)

```bash
cp .env.example .env  # 필요한 키 입력 후

docker compose up -d
# Web 대시보드: http://localhost:3000
# API 문서:     http://localhost:8000/docs
# 모니터링:     http://localhost:3001  (admin / admin)

docker compose down
```

---

## 테스트 방법

### 에이전트 레이어 단위 테스트 (전체)

```bash
# 루트에서 실행
python -m pytest tests/unit/agents/ --tb=short -v
```

### Decision 관련 테스트

```bash
# DecisionEngine + StrategySelector + CandidateGenerator
python -m pytest tests/unit/agents/test_decision_engine_strategy_candidates.py \
                 tests/unit/agents/test_strategy_selector.py \
                 tests/unit/agents/test_trade_candidate_generator.py -v

# MarketRegime 분류
python -m pytest tests/unit/agents/test_regime_classifier.py -v

# FinalDecision
python -m pytest tests/unit/agents/test_final_decision.py -v
```

### AI Reviewer 테스트

```bash
# ReviewerAgent (APPROVE/REJECT 로직, 플레이북 가드)
python -m pytest tests/unit/agents/test_synthesis_reviewer.py -v
```

### RiskEngine 테스트

```bash
python -m pytest tests/unit/agents/test_risk_engine.py \
                 tests/unit/agents/test_kill_switch.py \
                 tests/unit/agents/test_position_sizing.py \
                 tests/unit/agents/test_sizing_engine.py -v
```

### 전략 테스트

```bash
python -m pytest tests/unit/agents/test_strategy_engine.py \
                 tests/unit/agents/test_strategy_breakout.py \
                 tests/unit/agents/test_strategy_ema_trend.py \
                 tests/unit/agents/test_strategy_rsi_reversal.py -v
```

### Orchestrator 파이프라인 테스트

```bash
python -m pytest tests/unit/agents/test_orchestrator_pipeline.py -v
```

### Shadow 테스트

```bash
python -m pytest tests/unit/agents/test_shadow_performance_analysis.py \
                 tests/unit/agents/test_shadow_smoke_script.py -v
```

### 백엔드 단위 테스트 (backend/)

```bash
cd backend
python -m pytest tests/unit/ --tb=short -v
```

### Binance Testnet 통합 테스트

```bash
# TESTNET_API_KEY / TESTNET_API_SECRET 환경변수 필요
python -m pytest tests/integration/ -m testnet -v
```

---

## 로그 및 산출물

### Shadow Decision JSONL (`logs/shadow_smoke_decisions.jsonl`)

파이프라인 1회 실행마다 1개의 JSON 오브젝트가 누적된다. 주요 필드:

```
timestamp, coin, symbol, market_price
market_regime, chart_score, news_score, derivatives_score
strategy_type, actual_rr, min_required_rr
ai_review (review_action, confidence, critical_contradiction)
risk_result (approved, failed_checks, rejection_reason)
candidate_action, final_action, decision_outcome
rejection_stage, rejection_reason
leverage, stop_loss, take_profit, notional_size
expected_net_profit, expected_net_loss
```

### Shadow Summary JSON (`logs/shadow_smoke_summary.json`)

`run_shadow_smoke.py` 실행 후 생성되는 요약 파일 (있을 경우).

### Performance Summary (`shadow_performance_summary.json`)

`analyze_shadow_performance.py` 실행 시 지정한 경로에 생성되는 machine-readable JSON.

---

## 주요 안전 규칙

다음 규칙은 코드에서 우회할 수 없다 (`agents/decision/constants.py`, `agents/risk/`):

```python
REQUIRE_STOP_LOSS       = True    # SL 없는 주문 금지
REQUIRE_TAKE_PROFIT     = True    # TP 없는 주문 금지
ISOLATED_MARGIN_ONLY    = True    # Cross 마진 사용 금지
CLOSE_IF_SL_TP_FAIL     = True    # TP/SL 설정 실패 시 긴급 청산
ALLOW_MARTINGALE        = False   # 마틴게일 전략 금지
ALLOW_AVERAGING_DOWN    = False   # 물타기 금지

GLOBAL_MIN_RISK_REWARD_RATIO = 2.0   # 최소 R:R 2.0 (Decision 레이어 사전 필터)
# RiskEngine(agents/risk/)의 MIN_RR_RATIO = 2.0 이 최종 강제 게이트

DECISION_MAX_LEVERAGE         = 10   # 의사결정 레이어 레버리지 상한
DECISION_MAX_DAILY_LOSS_PCT   = 0.03 # 일일 손실 한도 3%
DECISION_MAX_WEEKLY_LOSS_PCT  = 0.08 # 주간 손실 한도 8%
DECISION_MAX_CONSECUTIVE_LOSSES = 3  # 연속 손실 쿨다운
DECISION_MAX_OPEN_POSITIONS   = 1    # 동시 오픈 포지션 상한

HIGH_VOLATILITY_BLOCK = True   # 고변동성 국면 진입 차단
NEWS_EVENT_BLOCK      = True   # 뉴스 이벤트 국면 진입 차단
```

**출금 권한 API Key는 등록을 차단한다.** 해킹 시에도 거래소 자금 출금이 불가능하다.

---

## 개발 원칙

1. **최소 변경 원칙** — 기존 pipeline behavior와 인터페이스를 보존한다.
2. **결정적 규칙 우선** — AI reviewer는 보조적 역할. 결정적 `RiskEngine`과 `DecisionEngine`이 우선이다.
3. **불확실성 = HOLD** — 어떤 예외도 HOLD/REJECT로 귀결된다. APPROVE로 새어나가지 않는다.
4. **테스트 커버리지** — 주문 실행 경로 95% 이상, AI 에이전트 85% 이상.
5. **Binance 통합 테스트는 Testnet에서만** — 메인넷 연결 금지.
6. **코인별 독립 검토** — 여러 코인을 지원하더라도, 각 코인의 시장 국면과 리스크를 독립적으로 검토한다.

---

## 문서 인덱스

| 파일 | 내용 |
|---|---|
| [`docs/DECISION_FLOW.md`](docs/DECISION_FLOW.md) | 10단계 파이프라인 상세, DecisionEngine, AI reviewer, FinalDecision |
| [`docs/RISK_ENGINE.md`](docs/RISK_ENGINE.md) | 안전 규칙, 포지션 사이징 공식, KillSwitch, 긴급 청산 |
| [`docs/SHADOW_TRADING.md`](docs/SHADOW_TRADING.md) | Shadow 모드 설정, 성과 분석 결과 해석 방법 |
| [`docs/LIVE_TRADING_CHECKLIST.md`](docs/LIVE_TRADING_CHECKLIST.md) | 실거래 전환 전 필수 확인 항목 |
| [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) | 환경 이슈, 설계 트레이드오프 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 전체 시스템 아키텍처 (frontend, backend, DB, queue) |
| [`AGENTS.md`](AGENTS.md) | 에이전트 설계 상세 |
| [`TRADING_RULES.md`](TRADING_RULES.md) | 리스크 규칙 레퍼런스 (RiskEngine 코드와 1:1 대응) |
| [`CLAUDE.md`](CLAUDE.md) | 개발 절대 규칙 (CTO 권한) |

---

Private — All rights reserved.
