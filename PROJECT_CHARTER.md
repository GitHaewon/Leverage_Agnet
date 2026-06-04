# AI Trading Copilot — Project Charter

> 작성일: 2026-06-04
> 작성자: CTO
> 버전: v1.0
> 상태: 확정 (Approved)

---

## 목차

1. [프로젝트 비전](#1-프로젝트-비전)
2. [핵심 가치](#2-핵심-가치)
3. [성공 지표 (KPI)](#3-성공-지표-kpi)
4. [기술 원칙](#4-기술-원칙)
5. [개발 원칙](#5-개발-원칙)
6. [보안 원칙](#6-보안-원칙)

---

## 1. 프로젝트 비전

### 한 줄 비전

> **"모든 트레이더에게 기관 수준의 AI 트레이딩 인텔리전스를"**

### 배경

암호화폐 선물 시장에서 개인 트레이더의 80%는 1년 내 손실로 이탈한다.
실패의 원인은 능력 부족이 아니라 정보 비대칭과 감정 개입이다.

기관 트레이더는 퀀트 팀, 리스크 시스템, 실시간 데이터 파이프라인을 갖춘다.
개인 트레이더는 그렇지 않다.

**AI Trading Copilot은 이 격차를 제거한다.**

### 제품 정의

AI Trading Copilot은 Binance Futures 특화 AI 트레이딩 SaaS다.

멀티 에이전트 AI가 시장 분석 → 시그널 생성 → 리스크 검증 → 자동 실행 → 사후 회고까지
트레이딩의 전체 사이클을 자동화한다. 트레이더는 전략의 방향만 결정한다.

### 타겟 시장

| 세그먼트 | 정의 | 규모 |
|---------|------|------|
| Primary | Binance Futures 활성 사용자 (월 거래대금 $1K+) | ~3M명 |
| Secondary | 자동매매 도구 사용 경험자 | ~800K명 |
| Beachhead | 한국·동남아 기반 암호화폐 투자 직장인 | ~200K명 |

### 수익 모델

```
Free   $0/월  — AI 시그널 3개/일, 수동 거래만
Pro    $29/월 — 무제한 시그널, 자동매매, 포지션 5개
Elite  $99/월 — 포지션 20개, 커스텀 전략, API 접근
```

---

## 2. 핵심 가치

핵심 가치는 제품 결정의 우선순위 기준이다.
충돌이 발생하면 위에 있는 가치가 이긴다.

### 2.1 Safety First — 안전이 수익보다 먼저다

트레이더의 자본을 보호하는 것이 수익을 극대화하는 것보다 중요하다.
AI가 어떤 시그널을 생성하더라도 리스크 관리 레이어를 통과하지 못하면 실행되지 않는다.

```
원칙:
- 손절 없는 주문은 시스템이 거부한다
- 일일 최대 손실 한도 도달 시 자동매매가 즉시 중단된다
- 레버리지는 AI가 추천하고 사용자가 설정한 상한 중 낮은 값을 사용한다
- 출금 권한이 있는 Binance API Key는 등록을 차단한다
```

### 2.2 Reliability Over Features — 안정성이 기능보다 먼저다

트레이딩 시스템의 다운타임은 직접적인 금전 손실이다.
불안정한 기능을 추가하는 것보다 기존 기능을 완벽하게 운영하는 것이 우선이다.

```
원칙:
- 새 기능의 릴리즈 기준은 기존 기능의 99.9% 가용성 유지다
- 주문 실행 경로에는 기능 플래그(feature flag)를 사용하지 않는다
- 롤백 가능한 배포 전략(Blue-Green, Canary)을 기본으로 한다
```

### 2.3 Transparency — AI의 판단은 설명 가능해야 한다

사용자는 AI가 왜 그 결정을 내렸는지 이해할 수 있어야 한다.
블랙박스 시그널은 신뢰를 만들지 못한다.

```
원칙:
- 모든 시그널은 3줄 이상의 근거를 포함한다
- 신뢰도(Confidence %)와 그 산출 근거를 표시한다
- 과거 시그널의 성과 기록을 사용자가 열람할 수 있다
```

### 2.4 User Sovereignty — 사용자가 항상 통제권을 가진다

AI는 부조종사(Copilot)다. 최종 결정은 사용자에게 있다.

```
원칙:
- 사용자는 언제든 자동매매를 즉시 중단할 수 있다
- 텔레그램 한 명령어로 전체 포지션 긴급 청산이 가능하다
- AI 추천을 무시하고 수동 거래를 하는 것을 시스템이 방해하지 않는다
```

### 2.5 Compound Learning — 시스템은 거래할수록 똑똑해진다

사용자의 거래 데이터가 시스템의 학습 자산이 된다.
개인화된 인사이트가 시스템의 가장 강력한 해자(Moat)다.

```
원칙:
- 모든 거래 결과는 자동으로 기록되고 분석된다
- AI는 개인별 거래 패턴에서 반복 실수를 감지하고 알린다
- 시스템 전체 시그널 성과는 지속적으로 추적되고 개선된다
```

---

## 3. 성공 지표 (KPI)

### 3.1 비즈니스 KPI

| 지표 | 8주 (MVP) | 3개월 | 6개월 | 12개월 |
|------|-----------|-------|-------|--------|
| 누적 가입자 | 50명 | 200명 | 800명 | 3,000명 |
| 유료 전환율 | 20% | 25% | 30% | 35% |
| MRR | $290 | $1,450 | $8,700 | $52,000 |
| 월 Churn Rate | — | < 8% | < 6% | < 5% |
| NPS | — | > 40 | > 50 | > 60 |
| CAC | — | — | < $30 | < $25 |
| LTV/CAC | — | — | > 3x | > 5x |

### 3.2 제품 KPI

| 지표 | 목표 | 측정 방법 |
|------|------|---------|
| 자동매매 실행 성공률 | > 99.5% | 주문 성공 / 시도 횟수 |
| 시그널 생성 지연 | < 3초 | p95 응답시간 |
| 주문 실행 지연 | < 200ms | p99 주문 왕복시간 |
| 포지션 데이터 갱신 | < 1초 | WebSocket 갱신 주기 |
| 텔레그램 알림 지연 | < 5초 | 이벤트 → 메시지 전송 |
| 대시보드 로딩 | < 2초 | LCP (Largest Contentful Paint) |

### 3.3 시스템 KPI

| 지표 | 목표 |
|------|------|
| 서비스 가용성 | > 99.9% (월 다운타임 44분 이하) |
| API 응답시간 | p95 < 500ms |
| 에러율 | < 0.1% |
| 주문 실행 경로 가용성 | > 99.99% (별도 SLO) |

### 3.4 AI 품질 KPI

| 지표 | 목표 | 측정 기간 |
|------|------|---------|
| 시그널 승률 | > 55% | 최근 90일 |
| 평균 R:R 달성률 | > 60% | 최근 90일 |
| 오버레버리지 방지율 | 100% | 전체 기간 |
| 강제청산 발생률 | < 0.5% | 전체 포지션 대비 |

---

## 4. 기술 원칙

### 4.1 확정 기술 스택

이 스택은 CTO 승인 없이 변경할 수 없다.

```yaml
Frontend:
  framework:    Next.js 14 (App Router)
  language:     TypeScript (strict mode)
  styling:      Tailwind CSS + shadcn/ui
  charts:       TradingView Lightweight Charts
  state:        Zustand + TanStack Query
  realtime:     WebSocket (native)

Backend:
  framework:    FastAPI (Python 3.12+)
  task_queue:   Celery + Redis
  broker:       Redis Streams
  orm:          SQLAlchemy 2.0 (async)
  migration:    Alembic

AI:
  llm:          claude-sonnet (Anthropic API)
  orchestration: LangGraph
  ta_library:   pandas-ta
  sentiment:    FinBERT (transformers)

Database:
  primary:      PostgreSQL 16
  timeseries:   TimescaleDB (PostgreSQL extension)
  cache:        Redis 7.2
  storage:      Cloudflare R2

Infrastructure:
  container:    Docker + Docker Compose
  ci_cd:        GitHub Actions
  monitoring:   Grafana + Prometheus
  logging:      Loki

Payment:
  billing:      Stripe
```

### 4.2 AI 모델 정책

```
승인 모델:
  claude-sonnet  (모든 AI 기능의 기본값)

금지 모델:
  claude-opus    (비용 정당화 불가 시 금지)
  claude-haiku   (품질 기준 미달 시 금지)
  gpt-*          (벤더 다양화 시 별도 승인 필요)
  gemini-*       (벤더 다양화 시 별도 승인 필요)
  local LLM      (레이턴시 SLO 충족 불가)

모델 교체 프로세스:
  1. CTO 승인
  2. A/B 테스트로 품질 검증
  3. 시그널 승률 비교 (최소 30일)
  4. 점진적 트래픽 이전 (10% → 50% → 100%)
```

### 4.3 아키텍처 원칙

**서비스 경계 (Service Boundary)**

```
auth-service      — 인증/인가 (JWT, 2FA, 세션)
user-service      — 사용자 프로파일, 구독 상태
trading-service   — 주문 실행, 포지션 관리
ai-engine         — 시그널 생성, AI 분석 파이프라인
notification      — 텔레그램, 이메일, 웹 푸시
journal-service   — 거래일지 생성, 통계 분석
```

**설계 규칙**

```
- 서비스 간 통신: Redis Streams (비동기) 또는 REST (동기)
- 서비스 간 데이터베이스 직접 접근 금지 (각 서비스가 자신의 스키마를 소유)
- 주문 실행 경로는 동기 (latency < 200ms) / 분석 경로는 비동기
- 모든 외부 API 호출에는 Circuit Breaker와 재시도 로직 적용
- 상태는 Redis (단기) 또는 PostgreSQL (영구)에만 저장 — 서버 메모리에 상태 금지
```

**데이터 정합성**

```
- 주문 상태는 PostgreSQL이 Source of Truth
- Redis는 조회 캐시 전용 — 쓰기는 항상 PostgreSQL 먼저
- Binance WebSocket 연결 끊김 시 REST API로 포지션 동기화 (최대 30초 내)
- 이벤트 유실 방지: Redis Streams Consumer Group + Dead Letter Queue
```

### 4.4 성능 설계 기준

```yaml
주문 실행 경로:
  목표: p99 < 200ms
  설계: PostgreSQL → Redis 캐시 우선 조회, 비동기 I/O 전용

AI 분석 파이프라인:
  목표: 시그널 생성 < 3초 (Claude API 호출 포함)
  설계: 지표 계산 병렬화, Claude 응답 스트리밍

WebSocket:
  목표: 포지션 데이터 갱신 < 1초
  설계: Binance WebSocket → Redis Pub/Sub → 클라이언트

확장 기준:
  CPU > 70% 또는 p95 latency > 300ms 시 수평 확장 트리거
```

---

## 5. 개발 원칙

### 5.1 코드 품질 기준

**타입 안전성**

```
- Python: 모든 함수에 타입 힌트 필수 (mypy strict 통과)
- TypeScript: strict mode 필수, any 타입 사용 금지
- API 스키마: Pydantic v2 (Python) / Zod (TypeScript) 검증 필수
```

**아키텍처 레이어**

```
API Route (엔드포인트)
  └── Service (비즈니스 로직)
       └── Repository (데이터 접근)
            └── Model (데이터 구조)

규칙:
- 비즈니스 로직은 Service 레이어에만 위치한다
- API Route는 요청 파싱과 응답 직렬화만 담당한다
- Repository는 SQL/ORM 쿼리만 담당한다
- 레이어 건너뛰기(Route → Repository 직접 호출) 금지
```

**함수 설계**

```
- 함수 하나의 역할은 하나다 (Single Responsibility)
- 함수 길이 50줄 초과 시 분리를 검토한다
- 매직 넘버, 하드코딩 문자열 금지 — 모두 상수 또는 환경변수로
- 주석은 WHY만 작성한다. WHAT은 코드가 설명한다
```

### 5.2 테스트 기준

```yaml
커버리지 목표:
  전체: 80% 이상
  주문 실행 경로: 95% 이상 (예외 없음)
  AI 에이전트: 85% 이상

테스트 종류:
  Unit Test:
    - 모든 Service, Repository, Agent 함수
    - 외부 의존성은 Mock 처리
  Integration Test:
    - API 엔드포인트 전체 (실제 DB 사용, 테스트 컨테이너)
    - Binance API 통합 (Testnet 사용)
    - Stripe Webhook 통합
  E2E Test:
    - 핵심 사용자 플로우 (회원가입 → API 연결 → 첫 자동매매)
    - 긴급 청산 플로우

CI 규칙:
  - PR merge 전 모든 테스트 통과 필수
  - 커버리지 감소 시 merge 차단
  - Binance Testnet 통합 테스트는 staging 브랜치 push 시 실행
```

### 5.3 브랜치 전략

```
main          — 프로덕션 배포본 (직접 push 금지)
staging       — QA 환경, main merge 전 최종 검증
develop       — 개발 통합 브랜치
feature/*     — 기능 개발 (develop에서 분기)
hotfix/*      — 프로덕션 긴급 수정 (main에서 분기)

PR 규칙:
- main, staging, develop 직접 push 금지
- PR 승인자 최소 1명 필요
- CI 통과 필수
- Squash merge 사용 (커밋 히스토리 정리)
```

### 5.4 배포 기준

```yaml
환경:
  local:    Docker Compose (개발)
  staging:  단일 서버 (Testnet, 검증)
  prod:     Docker + GitHub Actions (메인넷)

배포 원칙:
  - main 브랜치 push = 자동 프로덕션 배포
  - 배포 전 DB 마이그레이션 자동 실행 (Alembic)
  - 배포 후 헬스체크 통과 전까지 트래픽 전환 금지
  - 실패 시 이전 버전 자동 롤백

기능 출시 기준:
  - Testnet에서 48시간 이상 안정 동작 확인
  - 커버리지 기준 충족
  - 성능 테스트 (Locust) 통과
```

### 5.5 문서화 기준

모든 기능 구현 시 아래 문서를 함께 작성한다.

```
1. 목적 (Purpose) — 무엇을 해결하는가
2. 아키텍처 (Architecture) — 어떻게 설계했는가
3. API 명세 (API Spec) — 요청/응답 스키마
4. 환경변수 (Env) — 필요한 설정값
5. 사용 예시 (Example) — 실제 호출 예제
```

---

## 6. 보안 원칙

### 6.1 API Key 보안 (최우선)

Binance API Key는 이 시스템에서 가장 민감한 자산이다.
유출 시 사용자의 전체 자산이 위험에 처한다.

```
저장:
  - AES-256-GCM 암호화 후 PostgreSQL 저장
  - 암호화 키는 환경변수로 관리 (소스코드에 절대 금지)
  - 복호화는 주문 실행 직전에만 수행 (메모리 최소 노출)

검증:
  - API Key 등록 시 출금(Withdrawal) 권한 보유 여부 확인
  - 출금 권한 감지 시 등록 거부 + 사용자 경고
  - 허용 권한: Futures Trading Only

로깅:
  - API Key, Secret은 로그에 절대 출력 금지
  - 주문 요청/응답 로그에서 인증 정보 마스킹 필수

전송:
  - 모든 통신 TLS 1.3 이상
  - 내부 서비스 간 통신도 암호화
```

### 6.2 인증·인가

```yaml
인증:
  방식: JWT Access Token (15분) + Refresh Token (7일)
  저장: Access Token → 메모리, Refresh Token → HttpOnly Cookie
  2FA: TOTP (Google Authenticator 호환), Pro 이상 권장, Elite 필수

인가:
  방식: RBAC (Role-Based Access Control)
  역할: free | pro | elite | admin
  구현: 미들웨어 레벨에서 구독 플랜 검증 (엔드포인트 진입 전)

세션:
  - Refresh Token은 DB 저장 (Redis) — 탈취 시 서버에서 즉시 무효화 가능
  - 동일 계정 동시 세션 최대 3개
  - 의심 로그인(신규 IP, 신규 디바이스) 시 이메일 알림
```

### 6.3 입력 검증 및 주입 방지

```
SQL Injection:
  - SQLAlchemy ORM 파라미터 바인딩 사용 (Raw SQL 금지)
  - Raw SQL 불가피 시 sqlalchemy.text() + bindparams 필수

XSS:
  - 모든 사용자 입력 서버 사이드에서 sanitize
  - Next.js는 기본적으로 자동 이스케이프 — dangerouslySetInnerHTML 사용 금지

Command Injection:
  - subprocess, shell=True 사용 금지
  - 외부 명령 실행이 필요한 경우 CTO 검토 필수

입력 검증:
  - 모든 API 입력은 Pydantic 스키마로 검증
  - 최대 길이, 허용 문자, 형식 등 명시적 정의
```

### 6.4 비밀값 관리

```
필수 환경변수 (예시, 실제 값 코드 금지):
  ANTHROPIC_API_KEY        — Claude API 인증
  BINANCE_ENCRYPT_KEY      — AES-256 암호화 키
  DATABASE_URL             — PostgreSQL 연결
  REDIS_URL                — Redis 연결
  JWT_SECRET               — JWT 서명 키
  STRIPE_SECRET_KEY        — Stripe API 키
  TELEGRAM_BOT_TOKEN       — 텔레그램 봇 토큰

규칙:
  - .env 파일은 .gitignore에 등록 (절대 커밋 금지)
  - .env.example 파일은 키 이름만 포함 (값 없음)
  - 프로덕션 환경변수는 CI/CD 플랫폼의 Secret Store 사용
  - 로컬 .env는 팀 내부 채널로만 공유 (이메일, Slack DM 금지)
```

### 6.5 보안 모니터링

```yaml
실시간 감지:
  - 분당 API 요청 100회 초과 → Rate Limit + 알림
  - 로그인 실패 5회 연속 → 계정 잠금 (15분) + 이메일 알림
  - 비정상 주문 패턴 (금액 급증, 잦은 시간 외 거래) → 자동 플래그

감사 로그 (Audit Log):
  - API Key 등록/삭제: 영구 보관
  - 자동매매 ON/OFF: 영구 보관
  - 수동 청산 명령: 영구 보관
  - 구독 변경: 영구 보관
  - 관리자 접근: 영구 보관

정기 점검:
  - 월 1회: 의존성 취약점 스캔 (pip audit, npm audit)
  - 분기 1회: 침투 테스트
  - 연 1회: 전체 보안 아키텍처 리뷰
```

### 6.6 규정 준수

```
법적 고지:
  - 서비스 내 투자 손실 가능 문구 상시 노출
  - "본 서비스는 투자 조언을 제공하지 않습니다" 명시
  - AI 시그널은 참고용이며 투자 결정의 최종 책임은 사용자에게 있음을 고지

데이터:
  - 개인정보보호법 (한국), GDPR (EU) 준수
  - 사용자 데이터 삭제 요청 처리 (30일 이내)
  - 데이터 수집 항목과 보존 기간 명시

Binance 정책:
  - Binance API 이용약관 준수
  - 자동화 거래 관련 거래소 정책 변경 모니터링
```

---

## 부록: 의사결정 프레임워크

기능 추가 또는 기술 결정 시 아래 기준을 순서대로 적용한다.

```
1. 안전한가?        — 사용자 자본이나 시스템에 위험을 초래하는가
2. 신뢰할 수 있는가? — 99.9% 가용성 기준을 지킬 수 있는가
3. 이해 가능한가?   — 사용자가 AI의 판단을 이해할 수 있는가
4. MVP 범위인가?    — 현재 스프린트 목표에 해당하는가
5. 측정 가능한가?   — KPI로 성과를 검증할 수 있는가

5가지 모두 YES → 진행
하나라도 NO → 재검토 또는 보류
```

---

> 이 차터는 살아있는 문서다.
> 시장, 기술, 사용자 피드백에 따라 분기 단위로 검토하고 개정한다.
> 단, 핵심 가치 2.1 (Safety First)은 어떤 상황에서도 변경하지 않는다.
