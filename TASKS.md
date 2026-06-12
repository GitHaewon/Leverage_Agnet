# AI Trading Copilot — MVP Task Breakdown

> 작성일: 2026-06-04
> 버전: v1.0
> 대상: MVP (8주, Week 1~8)
> 참조: PRD.md §6, ARCHITECTURE.md, DATABASE.md, AGENTS.md, TRADING_RULES.md, API_SPEC.md

---

## 범례

```
우선순위
  P0 — 블로커 (없으면 MVP 불가)
  P1 — 중요 (MVP 품질에 영향)
  P2 — 있으면 좋음 (런칭 후 가능)

소요시간: 단독 개발자 기준 예측치 (AI 보조 포함)

선행 작업: 반드시 완료되어야 시작 가능한 Task ID
```

---

## 목차

- [E-01: 인프라 & 개발 환경](#e-01-인프라--개발-환경) — Week 1
- [E-02: 인증 & 사용자 관리](#e-02-인증--사용자-관리) — Week 1~2
- [E-03: Binance 연동](#e-03-binance-연동) — Week 2
- [E-04: AI 에이전트 엔진](#e-04-ai-에이전트-엔진) — Week 3~4
- [E-05: 자동매매 실행 엔진](#e-05-자동매매-실행-엔진) — Week 5~6
- [E-06: 포지션 모니터링](#e-06-포지션-모니터링) — Week 5~6
- [E-07: 프론트엔드](#e-07-프론트엔드) — Week 7
- [E-08: 텔레그램 봇](#e-08-텔레그램-봇) — Week 7
- [E-09: 구독 & 결제](#e-09-구독--결제) — Week 2, 7
- [E-10: 테스트 & QA & 런칭](#e-10-테스트--qa--런칭) — Week 8
- [전체 공수 요약](#전체-공수-요약)

---

## E-01: 인프라 & 개발 환경

> **목표:** 모든 서비스가 로컬에서 `docker compose up` 하나로 실행되는 개발 환경 구축
> **타겟 주차:** Week 1
> **총 예상:** 22h

---

### E-01-F-01: Docker Compose & 프로젝트 스캐폴딩

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-01-01 | Docker Compose 작성 (FastAPI, Next.js, PostgreSQL 16+TimescaleDB, Redis, Celery, Nginx) | 3h | P0 | — |
| T-01-02 | FastAPI 프로젝트 구조 생성 (`api/`, `services/`, `repositories/`, `models/`, `schemas/`, `agents/`, `workers/`, `utils/`) | 2h | P0 | T-01-01 |
| T-01-03 | Next.js 14 App Router 프로젝트 생성 + Tailwind CSS + shadcn/ui 초기 셋업 | 2h | P0 | T-01-01 |
| T-01-04 | `pydantic-settings` 기반 환경변수 관리 (`Settings` 클래스) + `.env.example` 전체 키 목록 작성 | 1h | P0 | T-01-02 |

---

### E-01-F-02: 데이터베이스 초기화

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-01-05 | SQLAlchemy 2.0 async 엔진 설정 + Alembic 마이그레이션 디렉토리 초기화 | 1h | P0 | T-01-02 |
| T-01-06 | TimescaleDB extension 설치 스크립트 + `ohlcv` 하이퍼테이블 마이그레이션 | 1h | P0 | T-01-05 |
| T-01-07 | 1차 마이그레이션: `users`, `subscriptions`, `user_settings`, `exchange_accounts` 테이블 | 2h | P0 | T-01-05 |
| T-01-08 | 2차 마이그레이션: `signals`, `positions`, `orders`, `trade_logs`, `agent_decisions`, `notifications` 테이블 | 2h | P0 | T-01-07 |
| T-01-09 | 3차 마이그레이션: `refresh_tokens`, `audit_logs`, 보조 테이블, DB 트리거 함수 (로그인 잠금, 구독 동기화) | 2h | P0 | T-01-07 |

---

### E-01-F-03: 비동기 인프라

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-01-10 | Redis 연결 클라이언트 (`aioredis`) + 헬스체크 엔드포인트 (`GET /health`) | 1h | P0 | T-01-02 |
| T-01-11 | Celery + Redis Broker 기본 구조 + `celery.py` 앱 생성 | 2h | P0 | T-01-10 |
| T-01-12 | Redis Streams 기본 Consumer Group 설정 (`stream:signals`, `stream:orders`, `stream:notifications`) | 1h | P0 | T-01-10 |

---

### E-01-F-04: CI & 모니터링 기반

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-01-13 | GitHub Actions CI 파이프라인 (lint, type-check, test, Docker build) | 2h | P1 | T-01-01 |
| T-01-14 | Prometheus + Grafana Docker Compose 서비스 추가 + FastAPI metrics 엔드포인트 | 2h | P2 | T-01-01 |

---

## E-02: 인증 & 사용자 관리

> **목표:** 이메일 회원가입 → 인증 → 로그인 → 2FA → 온보딩 전체 플로우 완성
> **타겟 주차:** Week 1~2
> **총 예상:** 30h

---

### E-02-F-01: 회원가입 & 이메일 인증

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-02-01 | `User`, `RefreshToken` SQLAlchemy ORM 모델 작성 | 1h | P0 | T-01-07 |
| T-02-02 | `UserRepository` (CRUD: create, get_by_email, get_by_id, update, soft_delete) | 2h | P0 | T-02-01 |
| T-02-03 | 이메일 발송 서비스 (SMTP + 인증 코드 6자리 Redis 저장, TTL 5분) | 2h | P0 | T-01-10 |
| T-02-04 | `POST /auth/register` 엔드포인트 (비밀번호 강도 검증, 중복 이메일 처리) | 1h | P0 | T-02-02, T-02-03 |
| T-02-05 | `POST /auth/verify-email` 엔드포인트 (코드 검증 → 최초 Access/Refresh Token 발급) | 1h | P0 | T-02-04 |
| T-02-06 | `POST /auth/resend-verification` 엔드포인트 (Rate Limit: 1분 1회) | 1h | P1 | T-02-03 |

---

### E-02-F-02: JWT 로그인 & 세션 관리

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-02-07 | `AuthService` — JWT 생성/검증 (`python-jose`), bcrypt 해싱 (`passlib`) | 2h | P0 | T-02-02 |
| T-02-08 | `POST /auth/login` 엔드포인트 (TOTP 조건부 요구, Refresh Token HttpOnly Cookie 설정) | 2h | P0 | T-02-07 |
| T-02-09 | 로그인 실패 횟수 추적 + 5회 초과 시 계정 잠금 (`locked_until`) 로직 | 1h | P0 | T-02-08 |
| T-02-10 | `POST /auth/refresh` 엔드포인트 (Refresh Token DB 조회 + 새 Access Token 발급) | 1h | P0 | T-02-08 |
| T-02-11 | `POST /auth/logout` 엔드포인트 (RefreshToken 무효화 + Cookie 삭제) | 1h | P0 | T-02-10 |
| T-02-12 | FastAPI `get_current_user` 의존성 주입 미들웨어 (JWT 검증 → User 반환) | 1h | P0 | T-02-07 |
| T-02-13 | `POST /auth/forgot-password`, `POST /auth/reset-password` (토큰 기반, 성공 시 전 세션 만료) | 2h | P1 | T-02-03, T-02-07 |

---

### E-02-F-03: TOTP 2FA

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-02-14 | `TwoFactorService` — TOTP 시크릿 생성, QR URL 생성, 코드 검증, 백업 코드 7개 생성 (`pyotp`) | 3h | P0 | T-02-12 |
| T-02-15 | `POST /auth/2fa/enable` — 시크릿 생성 후 AES-256-GCM 암호화 저장 + QR 반환 | 1h | P0 | T-02-14 |
| T-02-16 | `POST /auth/2fa/verify` — TOTP 코드 확인 → `is_2fa_enabled = true` 처리 | 1h | P0 | T-02-15 |
| T-02-17 | `POST /auth/2fa/disable` — 비밀번호 + TOTP 이중 확인 후 비활성화 | 1h | P0 | T-02-16 |

---

### E-02-F-04: 사용자 프로파일 & 온보딩

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-02-18 | `UserSettings` ORM 모델 + Repository (모드, 코인, 리스크 파라미터) | 1h | P0 | T-01-07 |
| T-02-19 | `GET /users/me`, `PATCH /users/me` 엔드포인트 | 1h | P0 | T-02-12 |
| T-02-20 | `POST /users/me/onboarding` — 설문 응답 → 리스크 프로파일 자동 분류 → UserSettings 기본값 설정 | 2h | P0 | T-02-18, T-02-19 |
| T-02-21 | `GET /users/me/stats` — 기간별 수익률 통계 쿼리 (`trade_logs` 집계, 승률, MDD, Sharpe 계산) | 3h | P1 | T-01-08 |

---

## E-03: Binance 연동

> **목표:** API Key 등록 → 권한 검증 → 암호화 저장 → 잔고 조회 → OHLCV 수집 파이프라인 완성
> **타겟 주차:** Week 2
> **총 예상:** 22h

---

### E-03-F-01: API Key 관리

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-03-01 | `ExchangeAccount` ORM 모델 + Repository | 1h | P0 | T-01-07 |
| T-03-02 | AES-256-GCM 암호화/복호화 유틸리티 (`cryptography` 라이브러리, `BINANCE_ENCRYPT_KEY` 환경변수) | 2h | P0 | T-01-04 |
| T-03-03 | Binance REST API 클라이언트 래퍼 (Testnet/Mainnet 전환, 서명 생성) | 3h | P0 | T-01-04 |
| T-03-04 | API Key 권한 검증 서비스: Withdraw 권한 차단 + Futures 권한 확인 + USDT 잔고 테스트 조회 | 2h | P0 | T-03-03 |
| T-03-05 | `POST /binance/connect` 엔드포인트 (검증 → AES 암호화 → 저장, 응답에 Key 절대 미포함) | 2h | P0 | T-03-02, T-03-04 |
| T-03-06 | `GET /binance/status`, `GET /binance/balance`, `GET /binance/permissions` 엔드포인트 | 2h | P0 | T-03-05 |
| T-03-07 | `DELETE /binance/disconnect` 엔드포인트 (오픈 포지션 존재 시 차단) | 1h | P0 | T-03-06 |

---

### E-03-F-02: 실시간 데이터 수집

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-03-08 | Binance WebSocket 클라이언트 — OHLCV Kline 스트림 수신 (BTC, ETH, 6 타임프레임) | 3h | P0 | T-03-03 |
| T-03-09 | OHLCV → TimescaleDB 저장 Repository (`ohlcv` 하이퍼테이블, upsert) | 2h | P0 | T-03-08, T-01-06 |
| T-03-10 | Celery Beat OHLCV 히스토리 백필 태스크 (초기 실행 시 최근 1000봉 수집) | 2h | P1 | T-03-09, T-01-11 |

---

### E-03-F-03: API 연결 안정성

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-03-11 | API 연결 헬스체크 Celery 태스크 (30초 간격, 3회 연속 실패 시 `auto_trading` 중단 + 알림) | 2h | P0 | T-03-06, T-01-11 |

---

## E-04: AI 에이전트 엔진

> **목표:** 5분마다 BTC/ETH 분석 → LangGraph 5-에이전트 파이프라인 → 시그널 생성 → Redis Streams 발행
> **타겟 주차:** Week 3~4
> **총 예상:** 48h

---

### E-04-F-01: Technical Analysis Agent

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-04-01 | `Signal`, `AgentDecision` ORM 모델 + Repository | 2h | P0 | T-01-08 |
| T-04-02 | OHLCV Redis 캐시 조회 유틸리티 (최신 200봉 → DataFrame 변환) | 2h | P0 | T-03-09 |
| T-04-03 | `pandas-ta` 기반 지표 계산 함수: RSI(14), MACD(12/26/9), Bollinger Bands, EMA(9/21/50/200), ATR, Volume Profile | 4h | P0 | T-04-02 |
| T-04-04 | Technical Analysis Agent 구현 (6 타임프레임 병렬 분석 → 방향성 점수 -1.0~+1.0) | 4h | P0 | T-04-03 |

---

### E-04-F-02: Sentiment Agent

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-04-05 | Fear & Greed Index API 클라이언트 (alternative.me, Redis 캐시 TTL 1h) | 1h | P0 | T-01-10 |
| T-04-06 | CryptoCompare News API 클라이언트 (최신 50개 뉴스, Redis 캐시 TTL 15m) | 1h | P0 | T-01-10 |
| T-04-07 | FinBERT 감성 분석 파이프라인 (Hugging Face `ProsusAI/finbert`, 배치 추론, 뉴스 최신성 가중치) | 4h | P0 | T-04-06 |
| T-04-08 | Sentiment Agent 구현 (FinBERT + Fear & Greed 통합 → 감성 점수 -1.0~+1.0) | 3h | P0 | T-04-07, T-04-05 |

---

### E-04-F-03: Market Structure Agent

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-04-09 | Binance Futures 시장 구조 데이터 수집: OI, Funding Rate, Long/Short 비율, 청산 데이터 | 2h | P0 | T-03-03 |
| T-04-10 | Market Structure Agent 구현 (OI 변화율 + Funding Rate 반추세 로직 → 구조 점수 -1.0~+1.0) | 3h | P0 | T-04-09 |

---

### E-04-F-04: DecisionEngine + Reviewer Agent (GPT-5)

> **리팩토링 완료:** T-04-11~14의 원래 계획(Claude Sonnet 기반 Synthesis Agent)은 결정적 파이프라인으로 대체되었다.
> 현행 구현: `agents/decision/` (결정적 TradeCandidate 생성) + `agents/synthesis/` (GPT-5 APPROVE/REJECT 검토).
> 참조: [docs/DECISION_FLOW.md](docs/DECISION_FLOW.md)

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-04-11 | OpenAI SDK 설정 (`settings.OPENAI_MODEL` 환경변수, temperature=0.0) | 1h | P0 | T-01-04 |
| T-04-12 | DecisionEngine 6-stage 체인 구현 (market_regime → chart_score → sentiment → derivatives → strategy → TradeCandidate) | 4h | P0 | T-04-11 |
| T-04-13 | ReviewerAgent SYSTEM_PROMPT 작성 (TradeCandidate 검토, APPROVE/REJECT JSON 출력) | 2h | P0 | T-04-12 |
| T-04-14 | ReviewerAgent 구현 (OpenAI API 호출 → decision/confidence/rationale 파싱, 모든 실패 → 안전 REJECT) | 3h | P0 | T-04-13 |

---

### E-04-F-05: Risk Manager Agent

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-04-15 | `risk_constants.py` 작성 (TRADING_RULES.md의 모든 상수 → 코드 파일) | 1h | P0 | — |
| T-04-16 | Risk Agent 검증 1~4단계: 신뢰도 60%+ / R:R 2.0+ / SL 존재 / 레버리지 4중 상한 | 3h | P0 | T-04-15, T-04-14 |
| T-04-17 | Risk Agent 검증 5~8단계: 일일 손실 한도 / 주간 손실 한도 / 연속 손실 쿨다운 / 포지션 수 상한 | 3h | P0 | T-04-16 |
| T-04-18 | Risk Agent 검증 9~11단계: 포트폴리오 리스크 10% / 포지션 사이징 계산 / 잔고 충분 여부 | 3h | P0 | T-04-17 |
| T-04-19 | `ValidationResult` 반환 (approved/rejected + 거부 사유 코드, 실행 파라미터 포함) | 1h | P0 | T-04-18 |

---

### E-04-F-06: LangGraph 파이프라인 & 시그널 발행

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-04-20 | `AgentState` TypedDict 정의 + LangGraph 그래프 구조 설계 (병렬 실행 노드) | 2h | P0 | T-04-14, T-04-19 |
| T-04-21 | 10-step 파이프라인 빌드: TA + MS 병렬 → DecisionEngine → ReviewerAgent → RiskEngine → FinalDecision | 4h | P0 | T-04-20 |
| T-04-22 | 승인된 시그널 → `signals` 테이블 저장 + `agent_decisions` 스냅샷 저장 | 2h | P0 | T-04-01, T-04-21 |
| T-04-23 | 시그널 → Redis Streams 발행 (`stream:signals`) | 1h | P0 | T-04-22, T-01-12 |
| T-04-24 | Celery Beat 5분 주기 분석 태스크 (BTC, ETH 병렬 실행) | 2h | P0 | T-04-23, T-01-11 |
| T-04-25 | 시그널 만료 처리 Celery 태스크 (만료 시 `status = expired`, WebSocket 이벤트 발행) | 1h | P1 | T-04-24 |
| T-04-26 | `GET /signals`, `GET /signals/{id}`, `GET /signals/history` API 엔드포인트 | 2h | P0 | T-04-22 |

---

## E-05: 자동매매 실행 엔진

> **목표:** 시그널 수신 → Pre-check → 포지션 사이징 → Binance 주문 → OCO TP/SL → 실패 복구
> **타겟 주차:** Week 5~6
> **총 예상:** 44h

---

### E-05-F-01: Pre-execution 체크

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-05-01 | `PreExecutionChecker` 서비스: 6단계 순차 검증 (잔고, 일일 손실, 포지션 수, 중복 코인, 허용 시간, API 상태) | 3h | P0 | T-04-15, T-03-06 |
| T-05-02 | 일일 손실 한도 도달 시 `is_trading_active = false` 자동 설정 + 알림 발행 로직 | 2h | P0 | T-05-01 |
| T-05-03 | 포지션 사이징 계산 서비스: `size = balance × risk_pct / |entry - sl|`, `quantity = size × leverage / price`, 거래소 최소 수량 로트 반올림 | 2h | P0 | T-04-15 |

---

### E-05-F-02: 주문 실행 & OCO 설정

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-05-04 | `Position`, `Order` ORM 모델 + Repository | 2h | P0 | T-01-08 |
| T-05-05 | Binance 시장가 주문 실행 서비스 (지수 백오프 재시도 3회: 1s/2s/4s, `client_order_id` 멱등성) | 4h | P0 | T-03-03, T-05-03, T-05-04 |
| T-05-06 | OCO TP/SL 주문 설정 서비스 (`TAKE_PROFIT_MARKET` + `STOP_MARKET` Binance API) | 3h | P0 | T-05-05 |
| T-05-07 | TP/SL 주문 실패 시 즉시 포지션 전량 시장가 청산 + 긴급 알림 발행 | 2h | P0 | T-05-06 |
| T-05-08 | Redis 분산 락 (`SETNX`, TTL 10s): 동일 심볼 동시 주문 방지 | 2h | P0 | T-01-10 |

---

### E-05-F-03: Order Executor Worker

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-05-09 | `OrderExecutorWorker` — Redis Streams `stream:orders` 소비자 그룹 구현 | 3h | P0 | T-05-05, T-05-08, T-01-12 |
| T-05-10 | 자동매매 모드 (`full_auto`) 시 시그널 스트림 자동 소비 → 주문 실행 파이프라인 | 3h | P0 | T-05-09, T-04-23 |

---

### E-05-F-04: 포지션 & 주문 관리 API

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-05-11 | `GET /positions`, `GET /positions/{id}` 엔드포인트 | 1h | P0 | T-05-04 |
| T-05-12 | `POST /signals/{id}/execute` 엔드포인트 (반자동 모드 수동 실행) | 2h | P0 | T-05-09, T-04-26 |
| T-05-13 | `POST /signals/{id}/dismiss` 엔드포인트 | 1h | P0 | T-04-26 |
| T-05-14 | `POST /positions/{id}/close` 엔드포인트 (부분/전체 청산, 시장가/지정가) | 2h | P0 | T-05-05, T-05-04 |
| T-05-15 | `PATCH /positions/{id}/tpsl` 엔드포인트 (불리한 방향 이동 경고 응답 포함) | 2h | P0 | T-05-06 |
| T-05-16 | `POST /positions/close-all` 엔드포인트 (confirm="CLOSE_ALL" 이중 확인, 10초 완료 목표) | 2h | P0 | T-05-14 |
| T-05-17 | `POST /positions/{id}/dca` 엔드포인트 (ATR × 1.0 이상 이동, 최대 2회, 리스크 재계산) | 3h | P1 | T-05-05, T-04-15 |
| T-05-18 | `GET /orders`, `GET /orders/{id}`, `GET /orders/stats` 엔드포인트 | 2h | P0 | T-05-04 |

---

### E-05-F-05: 자동매매 설정 API

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-05-19 | `GET /trading/settings`, `PUT /trading/settings` 엔드포인트 | 1h | P0 | T-02-18 |
| T-05-20 | `POST /trading/start`, `POST /trading/stop` 엔드포인트 (`is_trading_active` 플래그 전환) | 1h | P0 | T-05-19 |

---

## E-06: 포지션 모니터링

> **목표:** Binance WebSocket 실시간 포지션 동기화 → 청산가 경보 → FastAPI WebSocket 클라이언트 전달
> **타겟 주차:** Week 5~6
> **총 예상:** 20h

---

### E-06-F-01: 실시간 포지션 동기화

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-06-01 | Binance User Data Stream WebSocket 연결 + Listen Key 갱신 (30분 keepalive) | 3h | P0 | T-03-08 |
| T-06-02 | `ORDER_TRADE_UPDATE` 이벤트 파싱 → `positions`, `orders` 테이블 동기화 서비스 | 3h | P0 | T-06-01, T-05-04 |
| T-06-03 | 미실현 PnL 실시간 계산 + Redis 캐시 갱신 (1초 간격) | 2h | P0 | T-06-02 |
| T-06-04 | 청산가 근접 경보 로직 (10% 주의 / 5% 경고 / 3% 위험) + 알림 큐 발행 | 2h | P0 | T-06-03 |
| T-06-05 | 긴급 자동 부분 청산 서비스 (청산가 3% → 50% 자동 청산, 2% → 100% 강제 청산) | 2h | P0 | T-06-04, T-05-05 |

---

### E-06-F-02: WebSocket 서버

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-06-06 | FastAPI WebSocket 엔드포인트 `WS /ws/v1/positions` (JWT 쿼리 파라미터 인증, ConnectionManager) | 3h | P0 | T-06-03, T-02-12 |
| T-06-07 | FastAPI WebSocket 엔드포인트 `WS /ws/v1/signals` (새 시그널, 만료, 실행 이벤트) | 2h | P0 | T-04-23, T-02-12 |
| T-06-08 | FastAPI WebSocket 엔드포인트 `WS /ws/v1/dashboard` (계좌 업데이트, 거래 중단 이벤트) | 2h | P0 | T-06-06, T-06-07 |
| T-06-09 | WebSocket 끊김 시 30초 내 REST 폴백 처리 로직 (서버 측) + Ping/Pong Heartbeat (30초) | 1h | P1 | T-06-06 |

---

## E-07: 프론트엔드

> **목표:** 인증 → 온보딩 → 대시보드 → 시그널 → 포지션 → 설정 전체 UI 완성
> **타겟 주차:** Week 7
> **총 예상:** 56h

---

### E-07-F-01: 공통 기반

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-07-01 | Axios 인스턴스 설정 (Base URL, Authorization 헤더 자동 주입, 401 시 자동 토큰 갱신 인터셉터) | 2h | P0 | T-02-10 |
| T-07-02 | Zod 응답 검증 스키마 (Signal, Position, Order, User, ApiError 전체) | 2h | P0 | T-07-01 |
| T-07-03 | Zustand 스토어 (auth, user, trading) | 2h | P0 | T-07-01 |
| T-07-04 | TanStack Query 훅 (`useMe`, `useSignals`, `usePositions`, `useStats`, `useOrders`) | 3h | P0 | T-07-02 |
| T-07-05 | WebSocket 클라이언트 훅 (`useWebSocket`, 지수 백오프 재연결, Heartbeat 30초) | 3h | P0 | T-07-03 |
| T-07-06 | 인증 가드 미들웨어 (`middleware.ts`, 비인증 → /auth/login 리다이렉트) | 1h | P0 | T-07-03 |
| T-07-07 | 공통 레이아웃 컴포넌트 (Sidebar, Header, 모바일 하단 탭 네비게이션) | 3h | P0 | T-07-06 |

---

### E-07-F-02: 인증 페이지

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-07-08 | `/auth/signup` — 회원가입 폼 (비밀번호 강도 표시, 약관 동의 체크박스) | 2h | P0 | T-07-01 |
| T-07-09 | `/auth/verify-email` — 6자리 코드 입력 (자동 포커스 이동, 재발송 타이머) | 1h | P0 | T-07-08 |
| T-07-10 | `/auth/login` — 로그인 폼 (2FA 조건부 추가 입력 필드, 계정 잠금 안내) | 2h | P0 | T-07-01 |
| T-07-11 | `/auth/forgot-password`, `/auth/reset-password` 페이지 | 2h | P1 | T-07-10 |

---

### E-07-F-03: 온보딩 플로우

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-07-12 | `/onboarding/survey` — 3단계 설문 (진행률 표시, 각 단계 15초 목표) | 2h | P0 | T-07-10 |
| T-07-13 | `/onboarding/risk-profile` — AI 분류 결과 표시 (프로파일 카드 + 기본값 미리보기) | 1h | P0 | T-07-12 |
| T-07-14 | `/onboarding/connect-binance` — 4단계 API 연결 가이드 (스크린샷 포함, 연결 테스트 버튼) | 3h | P0 | T-07-13 |
| T-07-15 | `/onboarding/select-plan` — Free vs Pro 비교 카드 (Stripe Checkout 리다이렉트) | 1h | P0 | T-07-14 |

---

### E-07-F-04: 메인 대시보드

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-07-16 | 계좌 요약 카드 컴포넌트 4종 (총잔고, 오늘 수익, 승률, MDD) — WebSocket 실시간 | 2h | P0 | T-07-05, T-07-04 |
| T-07-17 | 오픈 포지션 테이블 컴포넌트 (미실현 PnL 실시간 색상 변화, 청산가 진행 바) | 3h | P0 | T-07-05, T-07-16 |
| T-07-18 | TradingView Lightweight Charts — 수익 곡선 (기간 선택: 1D/1W/1M/ALL) | 3h | P0 | T-07-04 |
| T-07-19 | AI 시그널 피드 컴포넌트 (신뢰도 순 카드, 실시간 스트림) | 2h | P0 | T-07-05 |
| T-07-20 | 최근 거래 내역 테이블 컴포넌트 (최근 10건) | 1h | P0 | T-07-04 |
| T-07-21 | `/dashboard` 페이지 조립 + 자동매매 ON/OFF 토글 (헤더) | 2h | P0 | T-07-16~T-07-20, T-07-07 |

---

### E-07-F-05: 시그널 UI

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-07-22 | 시그널 카드 컴포넌트 (신뢰도 프로그레스 바, TP/SL 거리, 근거 3줄, 만료 카운트다운, R:R) | 4h | P0 | T-07-05 |
| T-07-23 | 시그널 실행 확인 모달 (레버리지 덮어쓰기, 예상 수익/손실 계산기, 증거금 표시) | 2h | P0 | T-07-22 |
| T-07-24 | `/signals` 페이지 (필터 바: 코인, 방향, 신뢰도, 상태) | 2h | P0 | T-07-22, T-07-07 |
| T-07-25 | Free 플랜 일일 한도 도달 시 업그레이드 유도 배너 | 1h | P0 | T-07-24 |

---

### E-07-F-06: 포지션 UI

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-07-26 | 포지션 청산 모달 (부분/전체, 비율 슬라이더 25%/50%/75%/100%) | 2h | P0 | T-07-17 |
| T-07-27 | TP/SL 수정 모달 (불리한 방향 이동 경고 UI) | 1h | P0 | T-07-17 |
| T-07-28 | 전체 긴급 청산 버튼 + "CLOSE_ALL" 텍스트 입력 이중 확인 다이얼로그 | 1h | P0 | T-07-26 |
| T-07-29 | `/positions` 페이지 + 청산가 근접 경보 Toast 알림 (warning_level별 색상) | 2h | P0 | T-07-17, T-07-26, T-07-07 |

---

### E-07-F-07: 설정 페이지

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-07-30 | `/settings/trading` — 모드 선택 + 리스크 파라미터 슬라이더 + 허용 시간 + 면책 동의 체크박스 | 3h | P0 | T-07-04 |
| T-07-31 | `/settings/binance-api` — 연결 상태 표시, API Key 등록/삭제 폼 (Key 마스킹: `****...XXXX`) | 2h | P0 | T-07-04 |
| T-07-32 | `/settings/notifications` — 텔레그램 연결 버튼 + 알림 종류별 토글 + 조용한 시간 설정 | 2h | P1 | T-07-04 |
| T-07-33 | `/settings/security` — 2FA 활성화/비활성화 UI (QR 코드 표시, 백업 코드 다운로드) | 2h | P0 | T-07-04 |
| T-07-34 | `/settings/profile` — 프로파일 편집, 비밀번호 변경, 계정 탈퇴 섹션 | 1h | P1 | T-07-04 |

---

## E-08: 텔레그램 봇

> **목표:** 5종 알림 자동 발송 + 7개 명령어 응답
> **타겟 주차:** Week 7
> **총 예상:** 18h

---

### E-08-F-01: 봇 초기화 & 연결 플로우

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-08-01 | `python-telegram-bot` 셋업 + Webhook 등록 (`TELEGRAM_BOT_TOKEN` 환경변수) | 1h | P0 | T-01-04 |
| T-08-02 | 연결 플로우: 링크 토큰 생성 → Bot 딥링크 URL 반환 → `/start` 명령 시 `chat_id` 저장 | 2h | P0 | T-08-01, T-02-12 |
| T-08-03 | `POST /notifications/telegram/connect`, `DELETE /notifications/telegram/disconnect` API | 1h | P0 | T-08-02 |

---

### E-08-F-02: 알림 Worker & 5종 메시지

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-08-04 | Notification Worker — Redis Streams `stream:notifications` 소비자, 재시도 3회, DLQ | 2h | P0 | T-01-12, T-08-01 |
| T-08-05 | 알림 #1 시그널 발생 메시지 포맷 (코인, 방향, 신뢰도, TP/SL, R:R, 근거 첫 줄) | 1h | P0 | T-08-04, T-04-23 |
| T-08-06 | 알림 #2 주문 체결 메시지 포맷 (체결가, 수량, 레버리지, 증거금) | 1h | P0 | T-08-04, T-05-09 |
| T-08-07 | 알림 #3 포지션 종료 메시지 포맷 (수익/손실, 진입→청산가, 보유 시간) | 1h | P0 | T-08-04, T-06-02 |
| T-08-08 | 알림 #4 청산 위험 경보 메시지 포맷 + 즉시 청산 버튼 (InlineKeyboard) | 1h | P0 | T-08-04, T-06-04 |
| T-08-09 | 알림 #5 일일 성과 요약 Celery Beat (22:00 KST, 수익/거래 수/승률) | 2h | P0 | T-08-04, T-01-11 |
| T-08-10 | 조용한 시간 필터링 로직 (타임존 기반, 경보 제외) | 1h | P1 | T-08-04 |

---

### E-08-F-03: 7개 명령어

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-08-11 | `/status`, `/positions`, `/pnl`, `/signal` 명령어 (DB 조회 → 포맷 → 응답) | 2h | P0 | T-08-02, T-05-04, T-04-01 |
| T-08-12 | `/stop` 명령어 (`is_trading_active = false`, 확인 메시지) | 1h | P0 | T-08-11, T-05-20 |
| T-08-13 | `/closeall` 명령어 ("CONFIRM" 재입력 이중 확인 → 전체 청산 실행) | 2h | P0 | T-08-12, T-05-16 |
| T-08-14 | `/settings` 명령어 (현재 설정 표시 + 주요 파라미터 인라인 수정 버튼) | 1h | P1 | T-08-11 |

---

## E-09: 구독 & 결제

> **목표:** Stripe Checkout → Webhook 이벤트 처리 → 플랜 자동 동기화
> **타겟 주차:** Week 2 (모델/API), Week 7 (프론트엔드)
> **총 예상:** 20h

---

### E-09-F-01: Stripe 백엔드

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-09-01 | `Subscription` ORM 모델 + Repository | 1h | P0 | T-01-07 |
| T-09-02 | Stripe SDK 초기화 (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` 환경변수) | 1h | P0 | T-01-04 |
| T-09-03 | `GET /billing/plans` 엔드포인트 (공개 API, 인증 불필요) | 1h | P0 | T-09-01 |
| T-09-04 | `POST /billing/checkout` — Stripe Checkout 세션 생성 (plan, billing_period) | 2h | P0 | T-09-02 |
| T-09-05 | `POST /billing/webhook` — HMAC-SHA256 서명 검증 + 5종 이벤트 처리 (플랜 동기화) | 4h | P0 | T-09-04 |
| T-09-06 | 플랜 기능 제한 FastAPI 의존성 (`require_plan("pro")`) — 403 BILLING_001 반환 | 2h | P0 | T-09-05 |
| T-09-07 | `GET /billing/subscription`, `DELETE /billing/subscription`, `POST /billing/reactivate` | 2h | P0 | T-09-05 |
| T-09-08 | `GET /billing/invoices` 엔드포인트 (Stripe API 조회) | 1h | P1 | T-09-05 |
| T-09-09 | 결제 실패 알림 발행 (이메일 + 텔레그램) | 1h | P0 | T-09-05, T-08-04 |

---

### E-09-F-02: 결제 프론트엔드

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-09-10 | `/billing/plans` — Free / Pro 비교 테이블 (월간/연간 전환 토글, 20% 할인 표시) | 2h | P0 | T-07-07, T-09-03 |
| T-09-11 | `/billing/success` — 결제 완료 페이지 (플랜 활성화 확인, 웰컴 메시지) | 1h | P0 | T-09-10 |
| T-09-12 | `/settings/subscription` — 현재 구독 상태, 인보이스 목록, 취소/재활성화 버튼 | 2h | P1 | T-09-07, T-07-07 |

---

## E-10: 테스트 & QA & 런칭

> **목표:** 커버리지 80%+ (주문 실행 95%+), Testnet 48h 안정성, 부하 테스트 100명
> **타겟 주차:** Week 8
> **총 예상:** 56h

---

### E-10-F-01: 테스트 인프라

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-10-01 | pytest 설정 (`conftest.py`, 테스트 DB 픽스처, 비동기 지원 `pytest-asyncio`) | 2h | P0 | T-01-06 |
| T-10-02 | Factory Boy 픽스처 (User, Signal, Position, Order 팩토리) | 2h | P0 | T-10-01 |
| T-10-03 | Vitest + Testing Library 설정 (Next.js 컴포넌트 테스트) | 1h | P1 | T-01-03 |

---

### E-10-F-02: 핵심 경로 단위 테스트

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-10-04 | Risk Manager Agent 단위 테스트 (11개 검증 경로 전부, 목표 100% 브랜치 커버리지) | 4h | P0 | T-04-19, T-10-02 |
| T-10-05 | Order Executor 단위 테스트 (주문 성공/실패/재시도/멱등성, 목표 95%+ 커버리지) | 4h | P0 | T-05-09, T-10-02 |
| T-10-06 | Pre-execution 체크 단위 테스트 (6단계 전 분기 커버리지) | 2h | P0 | T-05-01, T-10-02 |
| T-10-07 | 포지션 사이징 단위 테스트 (엣지 케이스: 소수점 반올림, 최소 수량, 레버리지 상한) | 2h | P0 | T-05-03, T-10-02 |
| T-10-08 | AES-256-GCM 암호화/복호화 단위 테스트 (Key 응답 포함 여부 검증 포함) | 1h | P0 | T-03-02, T-10-01 |
| T-10-09 | JWT 인증 단위 테스트 (만료, 변조, Refresh Token 재사용 방지) | 2h | P0 | T-02-07, T-10-01 |
| T-10-10 | 일일 손실 한도 자동 중단 단위 테스트 | 1h | P0 | T-05-02, T-10-01 |
| T-10-11 | API Key 출금 권한 차단 단위 테스트 | 1h | P0 | T-03-04, T-10-01 |

---

### E-10-F-03: 통합 & E2E 테스트

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-10-12 | Binance Testnet 통합 테스트 (`BINANCE_TESTNET=true`, 시장가 주문 → TP/SL 설정 → 청산) | 6h | P0 | T-05-06, T-10-02 |
| T-10-13 | AI 파이프라인 통합 테스트 (OpenAI API Mock — ReviewerAgent, TradeCandidate 검토 → DB 저장 → Redis 발행) | 4h | P0 | T-04-22, T-10-02 |
| T-10-14 | Stripe Webhook E2E 테스트 (`stripe-cli` 이벤트 주입 → 플랜 동기화 확인) | 2h | P0 | T-09-05, T-10-01 |
| T-10-15 | 전체 자동매매 시나리오 E2E: 회원가입 → Binance 연결 → 시그널 생성 → 주문 → TP 달성 → 알림 | 8h | P0 | T-10-12, T-10-13 |

---

### E-10-F-04: 안정성 & 부하 & 보안

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-10-16 | Testnet 48시간 무중단 자동매매 안정성 테스트 (로그 모니터링, 오류 수집) | 48h | P0 | T-10-15 |
| T-10-17 | Locust 부하 테스트 스크립트 작성 (동시 100명, 주요 API 시나리오) | 3h | P0 | T-10-15 |
| T-10-18 | 보안 점검: API 응답 내 Key 노출 여부 전수 검사, SQL Injection 시도, XSS 페이로드 테스트 | 4h | P0 | T-10-15 |

---

### E-10-F-05: 런칭 준비

| ID | Task | 소요시간 | 우선순위 | 선행 작업 |
|----|------|:--------:|:--------:|----------|
| T-10-19 | Docker Compose Production 설정 분리 (`docker-compose.prod.yml`, 환경변수 분리) | 2h | P0 | T-01-01 |
| T-10-20 | Nginx Production 설정 (SSL, Rate Limit, 보안 헤더: HSTS, CSP, X-Frame-Options) | 2h | P0 | T-10-19 |
| T-10-21 | Grafana 알림 규칙 설정 (주문 실패율 > 1%, API 지연 > 200ms, 에러율 > 5%) | 2h | P1 | T-01-14 |
| T-10-22 | 베타 사용자 10명 온보딩 체크리스트 검증 (Testnet → 실계좌 전환 포함) | 8h | P0 | T-10-16 |

---

## 전체 공수 요약

| Epic | 설명 | 주차 | 예상 공수 | P0 비중 |
|------|------|:----:|:--------:|:-------:|
| E-01 | 인프라 & 개발 환경 | 1 | 22h | 86% |
| E-02 | 인증 & 사용자 관리 | 1~2 | 30h | 90% |
| E-03 | Binance 연동 | 2 | 22h | 100% |
| E-04 | AI 에이전트 엔진 | 3~4 | 48h | 95% |
| E-05 | 자동매매 실행 엔진 | 5~6 | 44h | 90% |
| E-06 | 포지션 모니터링 | 5~6 | 20h | 90% |
| E-07 | 프론트엔드 | 7 | 56h | 85% |
| E-08 | 텔레그램 봇 | 7 | 18h | 85% |
| E-09 | 구독 & 결제 | 2, 7 | 20h | 80% |
| E-10 | 테스트 & QA & 런칭 | 8 | 56h | 90% |
| **합계** | | **8주** | **336h** | |

```
주간 기준 (1인 기준):
  Week 1:   E-01 (22h) + E-02 시작 (15h) = 37h
  Week 2:   E-02 마무리 (15h) + E-03 (22h) = 37h
  Week 3~4: E-04 (48h) = 24h/주
  Week 5~6: E-05 (44h) + E-06 (20h) = 32h/주
  Week 7:   E-07 (56h) + E-08 일부 (18h) = 37h (주말 포함)
  Week 8:   E-09 FE (5h) + E-10 (56h) = 이상적으로 2명 동시 작업 권장

1인 체제 시: 주 40~45h 투입 기준 8~9주 소요
2인 체제 시: 역할 분리 (백엔드/프론트엔드) 시 8주 내 완료 가능
```

---

## 의존성 Critical Path

```
T-01-01 → T-01-05 → T-01-07 → T-01-08
                              ↓
T-03-03 → T-03-09 → T-04-02 → T-04-03 → T-04-04
                                         ↓
T-04-11 → T-04-14 → T-04-20 → T-04-21 → T-04-22 → T-04-23 → T-04-24
                                                     ↓
T-04-15 → T-04-16 → T-04-17 → T-04-18 → T-04-19
           ↓
T-05-01 → T-05-05 → T-05-06 → T-05-09 → T-10-15 → T-10-16
                    ↓
T-06-01 → T-06-02 → T-06-03 → T-06-06
```

**절대 블로커 순서:**
1. Docker Compose (T-01-01)
2. PostgreSQL 스키마 (T-01-07, T-01-08)
3. Binance REST 클라이언트 + OHLCV (T-03-03, T-03-09)
4. LangGraph 파이프라인 (T-04-21)
5. Risk Manager Agent (T-04-19)
6. Order Executor (T-05-09)
7. Testnet 통합 테스트 (T-10-12, T-10-15)

---

## 안전 규칙 체크리스트 (주문 실행 Task 착수 전 필독)

```
E-05 작업 시작 전 반드시 확인:

□ T-04-15 (risk_constants.py) 완료 후 착수
□ Stop Loss 없는 주문 실행 코드 경로가 존재하지 않는가?
□ 출금 권한 API Key 등록 차단 로직이 T-03-04에 구현되어 있는가?
□ 모든 Binance 통합 테스트가 BINANCE_TESTNET=true 환경에서만 실행되는가?
□ 주문 실행 서비스 테스트 커버리지 ≥ 95% (T-10-05) 없이 PR merge 금지
□ gpt-5 외 AI 모델 사용 금지 (settings.OPENAI_MODEL 환경변수 확인)
```
