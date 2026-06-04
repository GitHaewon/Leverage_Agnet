# AI Trading Copilot — Product Requirements Document (PRD)

> 작성일: 2026-06-04
> 버전: v1.0
> 상태: 확정
> 참조: PROJECT_CHARTER.md, LEVERAGE_AGENT_PRD.md

---

## 목차

1. [사용자 유형](#1-사용자-유형)
2. [핵심 기능](#2-핵심-기능)
3. [유저 플로우](#3-유저-플로우)
4. [페이지 구조](#4-페이지-구조)
5. [API 요구사항](#5-api-요구사항)
6. [MVP 정의](#6-mvp-정의)
7. [확장 로드맵](#7-확장-로드맵)

---

## 1. 사용자 유형

### 1.1 페르소나 정의

---

#### Persona A — 입문 투자자 "김지민"

```
나이 / 직업:  26세, IT 회사 직장인
월 수입:      350만원
투자 경험:    6개월, 현물 위주
현재 고통:
  - 차트 분석 방법을 모른다
  - 강제청산을 한 번 경험했다
  - 퇴근 후 밤에 차트를 보며 불안하다
  - 어떤 코인을 살지 매번 고민된다
목표:
  - 월 5~10% 수익
  - 손실 없이 안전하게 시작하고 싶다
  - AI가 알아서 해줬으면 좋겠다
허용 리스크:  계좌의 3~5% / 거래
선호 기능:    AI 풀오토, 텔레그램 알림, 단순 대시보드
지불 의향:    Free → 수익 확인 후 Pro ($29/월)
```

---

#### Persona B — 중급 트레이더 "박성현"

```
나이 / 직업:  34세, 프리랜서 디자이너
월 수입:      600만원
투자 경험:    3년, 선물 거래 1년
현재 고통:
  - 24시간 차트를 보는 게 지쳐간다
  - 감정적 매매로 손실이 반복된다
  - 전략은 있지만 실행이 느리다
  - 수익/손실 패턴을 분석할 시간이 없다
목표:
  - 월 15~30% 수익
  - 자신의 감을 AI에 위임하고 싶다
  - 거래 패턴을 객관적으로 보고 싶다
허용 리스크:  계좌의 10~15% / 거래
선호 기능:    반자동 (AI 시그널 + 본인 확인), 거래일지, 통계
지불 의향:    Pro ($29/월) 즉시 가입
```

---

#### Persona C — 전문 트레이더 "이현우"

```
나이 / 직업:  42세, 전업 트레이더
월 거래규모:  $100K~$500K
투자 경험:    10년, 퀀트 전략 운영 중
현재 고통:
  - 멀티 심볼 동시 모니터링이 힘들다
  - 전략 실행 자동화 도구가 부족하다
  - 포트폴리오 리스크를 한눈에 보기 어렵다
  - 세금 신고용 거래 기록 정리가 번거롭다
목표:
  - 월 40%+ 알파
  - 전략을 코드 없이 자동화
  - 포트폴리오 수준의 리스크 관리
허용 리스크:  동적 포지션 사이징 (Kelly Criterion)
선호 기능:    커스텀 전략, API 접근, 고급 통계, 백테스팅
지불 의향:    Elite ($99/월), 연간 결제 선호
```

---

### 1.2 사용자 구분과 권한

| 기능 | Free | Pro | Elite |
|------|:----:|:---:|:-----:|
| AI 시그널 | 3개/일 | 무제한 | 무제한 |
| 자동매매 | ✗ | ✓ | ✓ |
| 동시 포지션 | 1 | 5 | 20 |
| 거래일지 | 최근 30일 | 무제한 | 무제한 |
| 백테스팅 | ✗ | 최근 90일 | 무제한 |
| 커스텀 전략 | ✗ | ✗ | ✓ |
| API 접근 | ✗ | ✗ | ✓ |
| 텔레그램 알림 | 기본 3종 | 전체 | 전체 + 커스텀 |
| 전담 지원 | ✗ | ✗ | ✓ |
| 분석 대상 코인 | BTC, ETH | BTC, ETH + Top 10 | 전체 |

---

## 2. 핵심 기능

### F-01. Binance API 연결 `[P0 — MVP]`

**목적:** 사용자의 Binance Futures 계좌를 안전하게 연동한다.

**요구사항:**
```
기능:
  - API Key / Secret 입력 및 AES-256-GCM 암호화 저장
  - 연결 시 권한 자동 검증 (Futures Trading 확인, 출금 권한 차단)
  - USDT-M Futures 잔고 실시간 조회
  - 연결 상태 헬스체크 (30초 간격)
  - API 오류 발생 시 즉시 텔레그램 + 웹 알림
  - Testnet / Mainnet 전환 지원

수용 기준:
  - 출금(Withdrawal) 권한 포함 Key 등록 시 오류 반환
  - 연결 성공 후 30초 내 잔고 표시
  - API 오류 3회 연속 시 자동매매 일시 중단 + 알림
  - 암호화된 Key는 어떤 응답에도 노출되지 않음
```

---

### F-02. AI 분석 엔진 `[P0 — MVP]`

**목적:** 멀티 에이전트가 시장을 분석하고 트레이딩 시그널을 생성한다.

**에이전트 파이프라인:**
```
[1] Technical Analyst Agent
    입력: OHLCV (1m, 5m, 15m, 1h, 4h, 1d)
    분석: RSI, MACD, Bollinger Bands, EMA(9/21/50/200),
          Volume Profile, ATR, 지지/저항선
    출력: 기술적 방향성 점수 (-1.0 ~ +1.0)

[2] Sentiment Agent
    입력: CryptoCompare 뉴스, Fear & Greed Index
    분석: FinBERT 감성 분석, 트렌드 강도
    출력: 감성 점수 (-1.0 ~ +1.0)

[3] Market Structure Agent
    입력: Binance 선물 데이터
    분석: Open Interest 변화율, Funding Rate, Long/Short 비율,
          청산 데이터, 고래 포지션 변화
    출력: 시장 구조 점수 (-1.0 ~ +1.0)

[4] Synthesis Agent (Claude Sonnet)
    입력: 1~3 에이전트 점수 + 원본 데이터
    분석: 종합 판단, 신뢰도 계산, 3줄 근거 생성
    출력: 방향 (LONG/SHORT/HOLD) + 신뢰도 (0~100%)

[5] Risk Manager Agent
    입력: 시그널 + 사용자 계좌 상태
    검증: 포지션 사이징, 레버리지 상한, 포트폴리오 리스크
    출력: 최종 시그널 (승인/거부) + 실행 파라미터
```

**최종 시그널 스키마:**
```json
{
  "id": "sig_01J...",
  "coin": "BTC",
  "direction": "LONG",
  "confidence": 0.87,
  "entry_price": 67450.0,
  "take_profit": 69200.0,
  "stop_loss": 66800.0,
  "leverage": 5,
  "rr_ratio": 2.71,
  "reasons": [
    "RSI(14) = 42, 과매도 구간 진입 후 상승 반전",
    "4시간봉 EMA(50) 지지 확인, 거래량 증가 동반",
    "Funding Rate -0.02% (숏 과다), OI 3% 증가"
  ],
  "created_at": "2026-06-04T09:30:00Z",
  "expires_at": "2026-06-04T10:30:00Z"
}
```

**수용 기준:**
```
- 시그널 생성 시간: < 3초 (Claude API 포함)
- 분석 주기: 5분 (BTC, ETH)
- 최소 R:R 비율: 2.0 (미달 시 HOLD 처리)
- 신뢰도 < 60% 시 시그널 발행 안 함
- 모든 시그널은 근거 3줄 이상 필수
```

---

### F-03. LONG / SHORT 추천 카드 `[P0 — MVP]`

**목적:** 사용자가 시그널을 직관적으로 이해하고 빠르게 결정한다.

**요구사항:**
```
카드 표시 정보:
  - 코인 심볼 + 방향 (LONG/SHORT) 뱃지
  - 신뢰도 프로그레스 바 (%)
  - 진입가 / 목표가 / 손절가
  - 레버리지 추천
  - R:R 비율
  - 근거 요약 (3줄)
  - 예상 수익/손실 금액 계산기 (투자금 입력 시 실시간 계산)
  - 유효 시간 카운트다운

행동:
  - [지금 실행] — 자동매매 ON 사용자: 즉시 주문
  - [확인 후 실행] — 반자동 사용자: 확인 모달 → 실행
  - [무시] — 기록 후 종료

수용 기준:
  - 최대 동시 활성 시그널 5개 (코인별 1개)
  - 시그널 유효시간 기본 1시간
  - Free: 일 3개 제한, 초과 시 업그레이드 유도 UI
```

---

### F-04. 자동매매 실행 엔진 `[P0 — MVP]`

**목적:** AI 시그널을 실제 Binance 주문으로 자동 변환·실행한다.

**실행 전 체크리스트 (순서대로, 하나라도 실패 시 주문 중단):**
```
1. 계좌 잔고 충분한가? (필요 증거금 이상)
2. 일일 손실 한도 초과인가?
3. 동시 포지션 한도 초과인가?
4. 동일 코인 기존 포지션 존재인가? (DCA 또는 반전 처리)
5. 사용자 설정 거래 허용 시간인가?
6. API 연결 상태 정상인가?
```

**주문 흐름:**
```
포지션 사이징 계산
  size = balance × risk_pct / |entry - stop_loss|
  leverage = min(signal.leverage, user.max_leverage)
  quantity = size × leverage / entry_price
        ↓
시장가 주문 전송 (POST /fapi/v1/order)
        ↓
성공 → OCO 주문 (TP + SL 동시 설정)
실패 → 지수 백오프 재시도 (최대 3회, 1s / 2s / 4s)
       → 실패 시 알림 + 로그
        ↓
포지션 레지스트리 업데이트 (PostgreSQL + Redis)
        ↓
WebSocket 모니터링 시작
```

**수용 기준:**
```
- 주문 실행 지연: p99 < 200ms
- 주문 성공률: > 99.5%
- 동시 오픈 포지션: Free(1), Pro(5), Elite(20)
- 일일 최대 손실 도달 시 자동매매 즉시 중단
- TP/SL 주문 실패 시 포지션 즉시 수동 청산 + 긴급 알림
```

---

### F-05. 실시간 포지션 모니터링 `[P0 — MVP]`

**목적:** 오픈 포지션의 실시간 상태를 추적하고 위험 시 즉시 대응한다.

**요구사항:**
```
실시간 표시 (1초 갱신):
  - 미실현 PnL (금액 + %)
  - 현재가 vs 진입가
  - 강제청산 예상가
  - TP/SL 거리 (%)
  - 포지션 유지 시간

경보 시스템:
  - 청산가까지 10% 이내 → 웹 + 텔레그램 경보
  - 청산가까지 5% 이내 → 긴급 알림 (반복)
  - 청산가까지 2% 이내 → 자동 부분 청산 (50%) 옵션

조작:
  - [즉시 청산] — 시장가 전량 청산
  - [부분 청산] — 비율 선택 (25%, 50%, 75%)
  - [TP 수정] — 새 목표가 입력
  - [SL 수정] — 새 손절가 입력 (기존보다 불리한 방향 이동 경고)
  - [DCA 추가] — 동일 방향 추가 매수 (리스크 재계산)

수용 기준:
  - 포지션 데이터 갱신: < 1초 (Binance WebSocket)
  - WebSocket 끊김 시 30초 내 REST API 폴백
  - 청산가 90% 도달 경보: 지연 < 3초
```

---

### F-06. 실시간 대시보드 `[P0 — MVP]`

**목적:** 계좌 전체 상황을 한눈에 파악한다.

**요구사항:**
```
계좌 요약 카드:
  - 총 잔고 (USDT)
  - 미실현 PnL (금액 + %)
  - 오늘 수익률 / 이번 달 수익률 / 누적 수익률
  - 승률 (최근 30일)
  - 최대 낙폭 (MDD)
  - 샤프 지수

오픈 포지션 테이블:
  - 코인, 방향, 레버리지, 진입가, 현재가, 청산가
  - 미실현 PnL, 진행 시간
  - 액션 버튼 (청산, TP/SL 수정)

수익 곡선 차트:
  - TradingView Lightweight Charts
  - 기간 선택: 1D / 1W / 1M / 3M / ALL
  - AI 봇 수익 vs 수동 거래 수익 오버레이

AI 시그널 피드:
  - 최신 시그널 카드 (신뢰도 순)
  - 실행/대기/만료 상태 표시

최근 거래 내역:
  - 최근 10건 테이블
  - 코인, 방향, PnL, 실행 모드 (자동/수동)

수용 기준:
  - 초기 로딩: < 2초
  - 데이터 갱신: WebSocket 실시간
  - 모바일 반응형 (모든 카드)
```

---

### F-07. 거래일지 자동 생성 `[P1 — Post-MVP]`

**목적:** 거래 종료 시 AI가 자동으로 일지를 생성하고 패턴을 분석한다.

**요구사항:**
```
자동 생성 내용:
  - 진입 근거 (AI 시그널 스냅샷)
  - 포지션 유지 중 가격 흐름 요약
  - 결과 (수익/손실, 목표가 달성 여부)
  - AI 평가 ("TP까지 42% 도달 후 반전, SL 적중")
  - 개선 제안 ("진입 타이밍이 RSI 고점이었음, 다음에는...")

내보내기:
  - PDF 월간 리포트
  - CSV (세금 신고용, 거래소별 양식)

수용 기준:
  - 거래 종료 후 5분 내 일지 자동 생성
  - 거래 당시 차트 스냅샷 이미지 포함
```

---

### F-08. 텔레그램 알림 `[P0 — MVP]`

**목적:** 중요 이벤트를 실시간으로 사용자에게 전달한다.

**알림 종류 (MVP 5종):**
```
1. 시그널 발생
   "🚀 BTC LONG 시그널
   신뢰도: 87% | 진입: $67,450
   TP: $69,200 (+2.6%) | SL: $66,800 (-1.0%)
   R:R = 1:2.7
   근거: RSI 반등 + OI 증가..."

2. 주문 체결
   "✅ BTC LONG 주문 체결
   체결가: $67,452 | 수량: 0.015 BTC
   레버리지: 5x | 증거금: $202"

3. 포지션 종료
   "📊 BTC LONG 종료 (TP 달성)
   수익: +$234.5 (+3.8%)
   진입: $67,452 → 청산: $69,210
   보유시간: 4시간 23분"

4. 청산 위험 경보
   "⚠️ BTC LONG 청산 위험
   청산가까지 남은 거리: 8.2%
   현재가: $67,100 | 청산가: $61,450
   [즉시 청산] 버튼 포함"

5. 일일 성과 요약 (매일 22:00 KST)
   "📈 오늘의 성과
   수익: +$432.1 (+1.8%)
   거래: 3건 (승 2 / 패 1) 승률 67%
   이번 달 누적: +$1,234.5 (+5.1%)"
```

**텔레그램 명령어:**
```
/status     — 현재 포지션 요약
/positions  — 오픈 포지션 상세
/pnl        — 오늘/이번달 수익
/signal     — 최신 AI 시그널
/stop       — 자동매매 즉시 중단
/closeall   — 전체 포지션 긴급 청산 (이중 확인)
/settings   — 알림 설정 변경
```

**수용 기준:**
```
- 알림 지연: < 5초
- /closeall 실행 후 전체 청산 완료: < 10초
- 알림 종류별 개별 ON/OFF 설정
- 조용한 시간 설정 (예: 00:00~07:00 알림 차단)
```

---

### F-09. 구독 및 결제 `[P0 — MVP]`

**목적:** Stripe 기반 구독 과금과 플랜 관리를 처리한다.

**요구사항:**
```
결제:
  - Stripe Checkout (카드, 애플페이, 구글페이)
  - 월간 / 연간 선택 (연간 20% 할인)
  - 결제 실패 시 3일 유예기간 → 자동매매 일시 중단

플랜 관리:
  - 즉시 업그레이드 (차액 정산)
  - 다운그레이드 (다음 갱신일부터 적용)
  - 취소 (남은 기간 서비스 유지)
  - 인보이스 자동 발행

수용 기준:
  - Stripe Webhook으로 플랜 상태 실시간 동기화
  - 결제 실패 알림 (이메일 + 텔레그램)
  - PCI DSS: 카드 정보는 Stripe에서만 처리 (서버 비저장)
```

---

## 3. 유저 플로우

### 3.1 신규 사용자 온보딩

```
[랜딩 페이지]
      │  클릭: 무료 시작
      ▼
[회원가입]
  이메일 + 비밀번호 입력
  구글 소셜 로그인 (선택)
      │
      ▼
[이메일 인증]
  인증 코드 발송 → 5분 내 입력
      │
      ▼
[온보딩 설문] (3단계, 각 단계 15초)
  Step 1: 투자 경험?
    ○ 처음 해봐요  ○ 6개월~2년  ○ 2년 이상
  Step 2: 목표 월 수익률?
    ○ 5~10%       ○ 15~30%      ○ 30%+
  Step 3: 감당 가능한 손실?
    ○ 5% 이하     ○ 10~15%      ○ 동적 관리
      │
      ▼
[AI 리스크 프로파일 생성]
  → 안정형 / 중립형 / 공격형 자동 분류
  → 기본 레버리지 / 리스크% 자동 설정
      │
      ▼
[Binance API 연결 가이드]
  Step 1: Binance 로그인 → API 관리
  Step 2: API Key 생성 (Futures Trading Only 선택)
  Step 3: IP 화이트리스트 설정 안내 (선택)
  Step 4: Key / Secret 입력 → 연결 테스트 → ✅ 확인
      │
      ▼
[플랜 선택]
  [Free 시작] 또는 [Pro 구독 $29/월]
      │
      ▼
[메인 대시보드] ← 온보딩 완료
  → 첫 시그널 발생 시 튜토리얼 오버레이 표시
```

---

### 3.2 자동매매 설정 플로우

```
[대시보드] → [설정] 메뉴
      │
      ▼
[자동매매 모드 선택]
  ○ 풀오토    — AI가 자동 실행 (초보 추천)
  ○ 반자동    — AI 시그널 수신 후 본인 확인 (중급 추천)
  ○ 알림만    — 시그널 알림만, 직접 거래 (고급)
      │
      ▼
[거래 설정]
  코인 선택: □ BTC  □ ETH  (Pro: + Top 10)
  거래당 리스크: [___] % (기본: 프로파일 기반 자동 설정)
  최대 레버리지: [___] x (기본: 5x, 최대: 20x)
  일일 최대 손실: [___] USDT (초과 시 자동매매 중단)
  최대 동시 포지션: [___] 개
      │
      ▼
[알림 설정]
  텔레그램 봇 연결: [Connect] → Bot 링크 → /start
  알림 종류 선택 (개별 토글)
  조용한 시간: [00:00] ~ [07:00]
      │
      ▼
[30일 백테스트 프리뷰]
  → 설정값 기준 최근 30일 가상 성과 표시
  → 예상 승률, 평균 수익, 최대 낙폭
      │
      ▼
[자동매매 활성화]
  → 초록 불 ON
  → "설정 완료. AI가 BTC/ETH를 모니터링합니다" 토스트
```

---

### 3.3 시그널 → 주문 실행 플로우

```
[AI 시그널 생성] (5분 주기)
  "BTC LONG 87%, 진입 $67,450"
          │
          ▼
     [모드 분기]
   풀오토 ─────────────────────────────┐
   반자동 → [웹 + 텔레그램 알림]       │
              │                        │
              ▼                        │
        [확인 모달]                    │
         ├── ✅ 실행                  │
         └── ❌ 무시 → 기록 후 종료   │
              │                        │
              └────────────────────────┘
                        │
                        ▼
              [Pre-execution 체크 6종]
              모두 통과 → 주문 생성
              실패 → 스킵 + 알림
                        │
                        ▼
              [포지션 사이징 계산]
                        │
                        ▼
              [Binance 주문 전송]
               ├── 성공 → TP/SL OCO 설정
               └── 실패 → 재시도 3회 → 알림
                        │
                        ▼
              [포지션 모니터링 시작]
               ├── TP 도달 → 익절 청산 → 일지 생성 → 알림
               ├── SL 도달 → 손절 청산 → 일지 생성 → 알림
               └── 청산 위험 → 경보 → 사용자 조작 대기
```

---

### 3.4 구독 업그레이드 플로우

```
[기능 제한 도달]
  예: "일일 시그널 3개 소진"
          │
          ▼
[업그레이드 유도 배너]
  "오늘의 시그널이 소진되었습니다.
   Pro로 업그레이드하면 무제한으로 받을 수 있어요."
   [Pro 시작하기 — $29/월]
          │
          ▼
[플랜 비교 페이지]
  Free vs Pro vs Elite 기능 비교 테이블
  [Pro 월간 $29] [Pro 연간 $278 (20% 절약)]
          │
          ▼
[Stripe Checkout]
  카드 정보 입력 (Stripe 호스팅)
          │
          ▼
[결제 완료]
  → 즉시 Pro 기능 활성화
  → "Pro 업그레이드 완료! 무제한 시그널을 받아보세요." 웰컴 팝업
  → 인보이스 이메일 발송
```

---

## 4. 페이지 구조

### 4.1 사이트맵

```
/                          — 랜딩 페이지
/auth
  /signup                  — 회원가입
  /login                   — 로그인
  /verify-email            — 이메일 인증
  /forgot-password         — 비밀번호 찾기
  /reset-password          — 비밀번호 재설정

/onboarding
  /survey                  — 투자 성향 설문
  /risk-profile            — AI 리스크 프로파일 결과
  /connect-binance         — Binance API 연결
  /select-plan             — 플랜 선택

/dashboard                 — 메인 대시보드 (인증 필요)

/signals                   — AI 시그널 피드
  /[signal-id]             — 시그널 상세

/positions                 — 포지션 관리
  /[position-id]           — 포지션 상세

/journal                   — 거래일지 목록
  /[trade-id]              — 거래일지 상세

/analytics                 — 통계 분석
  /performance             — 수익률 분석
  /habits                  — 거래 습관 분석
  /comparison              — AI vs 수동 비교

/settings
  /profile                 — 프로파일
  /binance-api             — API Key 관리
  /trading                 — 자동매매 설정
  /notifications           — 알림 설정
  /subscription            — 구독 관리
  /security                — 보안 (2FA, 비밀번호)

/billing
  /plans                   — 플랜 비교
  /checkout                — 결제 (Stripe Checkout 리다이렉트)
  /success                 — 결제 완료
  /invoices                — 인보이스 내역

/admin (관리자 전용)
  /users                   — 사용자 관리
  /signals                 — 시그널 모니터링
  /system                  — 시스템 상태
```

---

### 4.2 페이지 상세 명세

#### `/dashboard` — 메인 대시보드

```
레이아웃: 좌측 사이드바 + 메인 콘텐츠
모바일: 하단 탭 네비게이션

컴포넌트 구성:
┌─────────────────────────────────────────────────┐
│ Header: 로고 | 계좌잔고 | 자동매매 ON/OFF 토글   │
├──────────┬──────────────────────────────────────┤
│          │  [계좌 요약 카드 4개]                  │
│ Sidebar  │  총잔고 | 오늘수익 | 승률 | MDD       │
│          │                                       │
│ - 대시보드│  [오픈 포지션 테이블]                 │
│ - 시그널  │  코인|방향|PnL|청산가|액션            │
│ - 포지션  │                                       │
│ - 일지   │  [2컬럼 그리드]                        │
│ - 분석   │  수익 곡선 차트 | AI 시그널 피드        │
│ - 설정   │                                       │
│          │  [최근 거래 테이블]                    │
└──────────┴──────────────────────────────────────┘

상태:
  - 자동매매 ON: 초록 배지 + 실시간 업데이트
  - 자동매매 OFF: 회색 배지 + 정적 데이터
  - API 연결 끊김: 상단 경고 배너
```

#### `/signals` — AI 시그널 피드

```
레이아웃: 카드 그리드 (3열 데스크톱, 1열 모바일)

필터 바:
  - 코인 선택 (멀티셀렉트)
  - 방향: ALL / LONG / SHORT
  - 신뢰도: 60%+ / 75%+ / 90%+
  - 상태: 활성 / 만료 / 실행됨

시그널 카드:
┌─────────────────────────────┐
│ BTC  🔴 SHORT   신뢰도 87%  │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░ 87%     │
│                              │
│ 진입가   $67,450             │
│ 목표가   $65,200  (-3.3%)   │
│ 손절가   $68,200  (+1.1%)   │
│ 레버리지  5x   R:R  1:3.0   │
│                              │
│ 근거:                        │
│ • RSI(4h) 과매수 영역 진입   │
│ • OI 급증 후 Funding +0.05% │
│ • 일봉 저항선 터치 후 거절   │
│                              │
│ 유효: 45분 후 만료           │
│                              │
│  [즉시 실행]  [계산기]       │
└─────────────────────────────┘
```

#### `/settings/trading` — 자동매매 설정

```
섹션 1: 모드 선택
  라디오 버튼 3종 (설명 포함)

섹션 2: 거래 파라미터
  - 코인 선택 토글
  - 슬라이더: 거래당 리스크 % (0.5 ~ 5.0)
  - 슬라이더: 최대 레버리지 (1 ~ 20)
  - 입력: 일일 손실 한도 (USDT)
  - 입력: 최대 동시 포지션 수

섹션 3: 텔레그램 연결
  - 연결 상태 표시
  - [연결] / [재연결] / [해제] 버튼

섹션 4: 알림 설정
  - 알림 종류별 토글
  - 조용한 시간 범위 선택

섹션 5: 위험 안내
  - 현재 설정 기준 "최대 손실 시나리오" 시뮬레이션
  - 면책 동의 체크박스 (설정 변경 시마다)
```

---

## 5. API 요구사항

### 5.1 API 설계 원칙

```
Base URL:     /api/v1
인증:          Bearer JWT (Authorization 헤더)
응답 형식:     JSON
에러 형식:     { "error": "code", "message": "...", "detail": {} }
버전 관리:     URL 경로 버전 (/v1, /v2)
Rate Limit:   Free 60req/min, Pro 300req/min, Elite 1000req/min
```

---

### 5.2 인증 API

```yaml
POST /api/v1/auth/register
  설명: 신규 회원가입
  Body:
    email: string (required)
    password: string (required, min 8자, 대소문자+숫자+특수문자)
    agreed_to_terms: boolean (required, true)
  Response 201:
    user_id: uuid
    message: "인증 이메일이 발송되었습니다"

POST /api/v1/auth/verify-email
  설명: 이메일 인증 코드 확인
  Body:
    email: string
    code: string (6자리)
  Response 200:
    access_token: string
    refresh_token: string (HttpOnly Cookie)

POST /api/v1/auth/login
  설명: 로그인
  Body:
    email: string
    password: string
    totp_code: string (2FA 활성화 시 필수)
  Response 200:
    access_token: string (만료: 15분)
    user: { id, email, plan, is_2fa_enabled }

POST /api/v1/auth/refresh
  설명: Access Token 갱신
  Cookie: refresh_token (HttpOnly)
  Response 200:
    access_token: string

POST /api/v1/auth/logout
  설명: 로그아웃 (Refresh Token 무효화)
  Response 200: {}

POST /api/v1/auth/2fa/enable
  설명: TOTP 2FA 활성화
  Response 200:
    qr_code_url: string
    backup_codes: string[]

POST /api/v1/auth/2fa/verify
  설명: 2FA 설정 완료 확인
  Body:
    totp_code: string
  Response 200:
    is_2fa_enabled: true
```

---

### 5.3 사용자 API

```yaml
GET /api/v1/users/me
  설명: 내 프로파일 조회
  Response 200:
    id, email, plan, risk_profile, created_at
    settings: { max_leverage, risk_per_trade, daily_loss_limit }

PATCH /api/v1/users/me
  설명: 프로파일 수정
  Body: { display_name?, timezone? }

GET /api/v1/users/me/stats
  설명: 수익률 통계
  Query: period=7d|30d|90d|all
  Response 200:
    total_pnl, win_rate, total_trades
    sharpe_ratio, max_drawdown
    daily_pnl: [{ date, pnl, cumulative_pnl }]
```

---

### 5.4 Binance API 관리

```yaml
POST /api/v1/binance/connect
  설명: Binance API Key 등록 및 검증
  Body:
    api_key: string
    api_secret: string
    is_testnet: boolean (default: false)
  Process:
    1. 권한 조회 (GET /api/v3/account)
    2. 출금 권한 감지 시 즉시 거부
    3. Futures 잔고 조회 테스트
    4. AES-256-GCM 암호화 후 저장
  Response 201:
    status: "connected"
    balance_usdt: float
    permissions: ["FUTURES_TRADING"]

GET /api/v1/binance/status
  설명: 연결 상태 및 잔고 조회
  Response 200:
    is_connected: boolean
    balance_usdt: float
    unrealized_pnl: float
    last_checked_at: datetime

DELETE /api/v1/binance/disconnect
  설명: API Key 삭제 (자동매매 중단 후)
  Response 200: {}
```

---

### 5.5 시그널 API

```yaml
GET /api/v1/signals
  설명: 시그널 목록 조회
  Query:
    coin: BTC|ETH|all
    direction: LONG|SHORT|HOLD|all
    status: active|expired|executed
    min_confidence: float (0.0~1.0)
    limit: int (default 20, max 100)
    offset: int
  Response 200:
    signals: [Signal]
    total: int

GET /api/v1/signals/{signal_id}
  설명: 시그널 상세 조회
  Response 200: Signal (전체 필드)

POST /api/v1/signals/{signal_id}/execute
  설명: 시그널 수동 실행 (반자동 모드)
  Body:
    confirm: true
  Response 201:
    order_id: string
    status: "pending" | "filled"

POST /api/v1/signals/{signal_id}/dismiss
  설명: 시그널 무시 처리
  Response 200: {}

# WebSocket: 실시간 시그널 스트림
WS /ws/v1/signals
  Events:
    signal.new     — 새 시그널 생성
    signal.expired — 시그널 만료
    signal.updated — 신뢰도 업데이트
```

---

### 5.6 주문 및 포지션 API

```yaml
GET /api/v1/positions
  설명: 오픈 포지션 목록
  Response 200:
    positions: [Position]
    total_unrealized_pnl: float

GET /api/v1/positions/{position_id}
  설명: 포지션 상세
  Response 200: Position (전체 필드)

POST /api/v1/positions/{position_id}/close
  설명: 포지션 청산
  Body:
    type: "market" | "limit"
    quantity_ratio: float (0.0~1.0, 기본 1.0 전체 청산)
    price?: float (type=limit 시 필수)
  Response 200:
    order_id: string
    status: string

PATCH /api/v1/positions/{position_id}/tpsl
  설명: TP/SL 수정
  Body:
    take_profit?: float
    stop_loss?: float
  Validation:
    SL을 진입가보다 불리한 방향으로 이동 시 경고 응답
  Response 200: Position

POST /api/v1/positions/close-all
  설명: 전체 포지션 긴급 청산
  Body:
    confirm: "CLOSE_ALL"  # 오타 방지 이중 확인
  Response 200:
    closed_count: int
    total_realized_pnl: float

GET /api/v1/orders
  설명: 주문 내역 조회
  Query: status=open|filled|cancelled, limit, offset
  Response 200:
    orders: [Order]

# WebSocket: 실시간 포지션 업데이트
WS /ws/v1/positions
  Events:
    position.updated  — PnL, 가격 업데이트
    position.closed   — 청산 완료
    position.warning  — 청산가 근접 경보
```

---

### 5.7 자동매매 설정 API

```yaml
GET /api/v1/trading/settings
  설명: 자동매매 설정 조회
  Response 200: TradingSettings

PUT /api/v1/trading/settings
  설명: 자동매매 설정 전체 업데이트
  Body: TradingSettings
  Response 200: TradingSettings

POST /api/v1/trading/start
  설명: 자동매매 시작
  Response 200:
    status: "active"
    started_at: datetime

POST /api/v1/trading/stop
  설명: 자동매매 중단
  Response 200:
    status: "inactive"
    stopped_at: datetime

# TradingSettings 스키마
TradingSettings:
  mode: "full_auto" | "semi_auto" | "signal_only"
  coins: string[]
  risk_per_trade: float (0.005 ~ 0.05)
  max_leverage: int (1 ~ 20)
  daily_loss_limit: float
  max_concurrent_positions: int
  allowed_hours: { start: "HH:MM", end: "HH:MM" }
```

---

### 5.8 구독 및 결제 API

```yaml
GET /api/v1/billing/plans
  설명: 플랜 목록 조회 (공개 API, 인증 불필요)
  Response 200:
    plans: [{ id, name, price_monthly, price_yearly, features }]

POST /api/v1/billing/checkout
  설명: Stripe Checkout 세션 생성
  Body:
    plan: "pro" | "elite"
    billing_period: "monthly" | "yearly"
  Response 200:
    checkout_url: string (Stripe 호스팅 URL)

GET /api/v1/billing/subscription
  설명: 현재 구독 상태
  Response 200:
    plan: string
    status: "active" | "past_due" | "cancelled"
    current_period_end: datetime
    cancel_at_period_end: boolean

DELETE /api/v1/billing/subscription
  설명: 구독 취소 (기간 말까지 유지)
  Response 200:
    cancel_at_period_end: true
    access_until: datetime

GET /api/v1/billing/invoices
  설명: 인보이스 목록
  Response 200:
    invoices: [{ id, amount, status, pdf_url, created_at }]

POST /api/v1/billing/webhook  (Stripe Webhook)
  설명: Stripe 이벤트 처리 (서명 검증 필수)
  Events:
    customer.subscription.updated
    customer.subscription.deleted
    invoice.payment_failed
    invoice.payment_succeeded
```

---

### 5.9 에러 코드 정의

```yaml
인증:
  AUTH_001: 이메일 또는 비밀번호가 올바르지 않습니다
  AUTH_002: 이메일 인증이 필요합니다
  AUTH_003: 2FA 코드가 올바르지 않습니다
  AUTH_004: 토큰이 만료되었습니다
  AUTH_005: 접근 권한이 없습니다

Binance:
  BINANCE_001: API Key 연결에 실패했습니다
  BINANCE_002: 출금 권한이 포함된 API Key는 등록할 수 없습니다
  BINANCE_003: Futures 거래 권한이 없습니다
  BINANCE_004: 잔고가 부족합니다

주문:
  ORDER_001: 일일 손실 한도에 도달했습니다
  ORDER_002: 최대 포지션 수에 도달했습니다
  ORDER_003: 손절가가 설정되지 않았습니다
  ORDER_004: R:R 비율이 2.0 미만입니다
  ORDER_005: 주문 실행에 실패했습니다

구독:
  BILLING_001: 이 기능은 Pro 이상 플랜에서 사용 가능합니다
  BILLING_002: 결제에 실패했습니다
  BILLING_003: 구독이 만료되었습니다
```

---

## 6. MVP 정의

### 6.1 MVP 범위 (8주)

```
✅ MVP 포함
─────────────────────────────────────────────
F-01  Binance API 연결 (BTC, ETH, Testnet 지원)
F-02  AI 분석 엔진 (5분 주기, Claude Sonnet)
F-03  LONG/SHORT 시그널 카드 (신뢰도 + 근거)
F-04  자동매매 실행 (시장가, TP/SL 자동)
F-05  실시간 포지션 모니터링 (WebSocket)
F-06  메인 대시보드 (기본 통계 + 차트)
F-07  텔레그램 알림 (5종 + 명령어 7개)
      사용자 인증 (이메일 + 2FA TOTP)
      구독 결제 (Stripe, Free/Pro)
      .env 기반 설정 관리
      Docker Compose 개발 환경

❌ MVP 제외 (Post-MVP)
─────────────────────────────────────────────
      거래일지 자동 생성 (F-07)
      투자 습관 분석 리포트
      백테스팅 UI
      커스텀 전략 빌더
      모바일 앱 (React Native)
      Elite 플랜
      알트코인 확장 (Top 10)
      소셜 로그인 (Google/Apple)
      레퍼럴 프로그램
      공개 API
```

---

### 6.2 MVP 개발 일정

```
Week 1~2: 인프라 & 인증
  ├── Docker Compose 환경 (FastAPI + Next.js + PostgreSQL + Redis)
  ├── PostgreSQL 스키마 + Alembic 마이그레이션 셋업
  ├── FastAPI JWT 인증 + 이메일 인증
  ├── TOTP 2FA 구현
  ├── Next.js 프로젝트 + shadcn/ui 셋업
  └── Binance API 연결 + 잔고 조회 + Key 암호화

Week 3~4: AI 엔진 & 시그널
  ├── pandas-ta 기술 지표 파이프라인 (BTC/ETH)
  ├── LangGraph 5-에이전트 구조 구축
  ├── Claude Sonnet API 통합 (Synthesis + Risk Manager)
  ├── FinBERT 감성 분석 통합
  ├── 시그널 생성 → Redis Streams 발행
  └── Celery 5분 주기 분석 태스크

Week 5~6: 주문 실행 & 포지션
  ├── Order Executor 서비스 (Pre-check + 포지션 사이징)
  ├── Binance Futures 시장가 주문 API
  ├── OCO TP/SL 자동 설정
  ├── Binance WebSocket 포지션 실시간 동기화
  ├── 긴급 전체 청산 기능
  └── Testnet 전체 시나리오 테스트

Week 7: 대시보드 & 알림
  ├── Next.js 대시보드 UI (모든 컴포넌트)
  ├── TradingView Lightweight Charts 통합
  ├── WebSocket 클라이언트 실시간 연동
  ├── Telegram Bot (python-telegram-bot)
  └── 알림 5종 + 명령어 7개 구현

Week 8: QA & 런칭
  ├── Testnet 48시간 안정성 테스트
  ├── 부하 테스트 (Locust, 동시 100명)
  ├── 보안 점검 (API Key 암호화, SQL Injection, XSS)
  ├── Stripe 결제 End-to-End 테스트
  ├── 베타 사용자 10명 초대 온보딩
  └── 모니터링 대시보드 (Grafana) 셋업
```

---

### 6.3 MVP 성공 기준 (KPI)

```yaml
8주 완료 기준:
  기능:
    - Binance Testnet 자동매매 24시간 무중단 동작
    - 시그널 생성 지연 < 3초 (100% 달성)
    - 주문 실행 지연 < 200ms (p99)
    - 전체 테스트 커버리지 80%+
    - 주문 실행 경로 커버리지 95%+

  비즈니스 (베타 런칭 후 2주):
    - 베타 사용자 10명 온보딩
    - NPS > 30
    - 자동매매 실행 성공률 > 99%
    - 치명적 버그 0건

12주 목표:
  - 누적 가입자 200명
  - Pro 전환율 25%
  - MRR $1,450
  - 시스템 가용성 99.9%
```

---

## 7. 확장 로드맵

### Phase 1: MVP (Month 1~2)

```
목표: 작동하는 자동매매 + 유료 고객 10명
──────────────────────────────────────────
✓ BTC/ETH 자동매매
✓ Free / Pro 플랜
✓ 텔레그램 봇
✓ 기본 대시보드
✓ Stripe 결제
```

---

### Phase 2: Growth (Month 3~5)

```
목표: MRR $10K, 가입자 300명
──────────────────────────────────────────
[ ] 알트코인 확장 (OI 기준 Top 20)
[ ] 거래일지 자동 생성 (Claude API, PDF/CSV 내보내기)
[ ] 투자 습관 분석 리포트 (주간, 개인화 인사이트)
[ ] 백테스팅 UI (최근 90일, 전략 파라미터 조정)
[ ] Elite 플랜 출시 ($99/월, 커스텀 전략, API)
[ ] 소셜 로그인 (Google, Apple)
[ ] React Native 모바일 앱 (iOS/Android, Expo)
[ ] 레퍼럴 프로그램 (추천인 1개월 무료)
[ ] AI 봇 vs 수동 거래 상세 비교 분석

신규 기능 상세:
  거래일지:
    - 거래 종료 5분 내 자동 생성
    - 진입 근거 스냅샷, AI 평가, 개선 제안
    - 세금 신고용 CSV (국내/해외 양식)

  습관 분석:
    - "당신은 화요일 오전 11시 승률이 42% 낮습니다"
    - 감정매매 감지 (연속 손실 후 과다 레버리지 패턴)
    - 주간 리포트 이메일 발송
```

---

### Phase 3: Expansion (Month 6~9)

```
목표: MRR $50K, 가입자 1,500명
──────────────────────────────────────────
[ ] 커스텀 전략 빌더 (No-code)
    - 조건 블록 드래그앤드롭 UI
    - 기술 지표 조합 커스터마이징
    - 전략 백테스팅 + 최적화

[ ] 카피트레이딩 마켓플레이스
    - 검증된 트레이더 전략 구독 ($5~$50/월)
    - 전략 제공자 수익 공유 (20%)
    - 성과 기반 순위 시스템

[ ] Bybit 거래소 추가
    - 통합 멀티 거래소 포트폴리오 뷰
    - 거래소 간 헤징 전략

[ ] 공개 API (Elite)
    - REST API + WebSocket 제공
    - API Key 관리 UI
    - 사용량 모니터링 대시보드

[ ] 웹훅 알림 (Discord, Slack)
[ ] 포트폴리오 리밸런싱 자동화
[ ] 세금 리포트 자동 생성 (국가별)
```

---

### Phase 4: Enterprise (Month 10~18)

```
목표: MRR $200K, ARR $2.4M
──────────────────────────────────────────
[ ] B2B Enterprise 플랜
    - 헤지펀드 / 패밀리오피스 대상
    - 화이트라벨 솔루션 ($50K 초기 + $5K/월)
    - 전담 AI 모델 파인튜닝
    - 전담 지원 + SLA 99.99%

[ ] 온체인 DeFi 통합
    - dYdX, GMX, Hyperliquid 연결
    - CEX/DEX 차익거래 전략

[ ] AI 전략 마켓플레이스
    - 전략 성과 기반 수수료 (순이익의 5~10%)
    - 전략 검증 시스템 (6개월 실거래 기록)

[ ] 규제 대응
    - 한국: 금융위 가이드라인 준수
    - EU: MiCA 대응
    - 글로벌: 투자 자문 면제 구조

[ ] 모바일 위젯 (iOS Live Activity)
[ ] AI 음성 브리핑 (매일 아침 시황 요약)
[ ] OKX 거래소 추가
```

---

### 수익 모델 확장 계획

```
Phase 1 (MVP):
  구독료만
  Free($0) / Pro($29/월) / Elite($99/월)

Phase 3 추가:
  카피트레이딩 수수료: 수익의 10%
  전략 마켓플레이스: 전략당 $5~$50/월
  API 사용료 (초과분): $0.01/요청

Phase 4 추가:
  Enterprise 라이선스: $5,000~$20,000/월
  화이트라벨: $50,000 초기 + $5,000/월
  성과 보수 (Carry): 순이익의 5~10%

ARR 목표:
  Year 1: $300K
  Year 2: $1.5M
  Year 3: $5M
```

---

### 기술 부채 관리

```yaml
매월:
  - pip audit / npm audit (의존성 취약점)
  - 커버리지 리포트 검토
  - 슬로우 쿼리 분석 (PostgreSQL)

분기:
  - 아키텍처 리뷰 (서비스 경계 재검토)
  - 성능 프로파일링 (Locust 부하 테스트)
  - 침투 테스트 (API 보안)
  - AI 모델 성능 재평가 (시그널 승률 추이)

연간:
  - Claude 최신 모델 업그레이드 평가
  - 데이터베이스 스키마 최적화
  - 레거시 코드 리팩토링 스프린트
  - 전체 보안 아키텍처 리뷰
```

---

> **핵심 원칙:** MVP는 "작동하는 자동매매 + 실시간 대시보드 + 텔레그램 알림"
> 이 세 가지를 8주 안에 완벽하게 만드는 것이다.
> 나머지는 실제 사용자 피드백 이후에 우선순위를 결정한다.
