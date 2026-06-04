# AI Trading Copilot — API Specification

> 작성일: 2026-06-04
> 버전: v1.0
> 상태: 확정
> 참조: PRD.md, DATABASE.md, ARCHITECTURE.md, TRADING_RULES.md

---

## 목차

1. [공통 규칙](#1-공통-규칙)
2. [Auth API](#2-auth-api)
3. [User API](#3-user-api)
4. [Binance API](#4-binance-api)
5. [Signal API](#5-signal-api)
6. [Position API](#6-position-api)
7. [Order API](#7-order-api)
8. [Notification API](#8-notification-api)
9. [Subscription API](#9-subscription-api)
10. [WebSocket API](#10-websocket-api)
11. [에러 코드 전체 목록](#11-에러-코드-전체-목록)

---

## 1. 공통 규칙

### 1.1 Base URL

```
Production:  https://api.trading-copilot.com/api/v1
Staging:     https://staging-api.trading-copilot.com/api/v1
Local:       http://localhost:8000/api/v1
```

### 1.2 인증

```
방식: Bearer JWT (Authorization 헤더)
Access Token 만료: 15분
Refresh Token 만료: 7일 (HttpOnly Cookie)

Authorization: Bearer <access_token>
```

공개 엔드포인트 (인증 불필요):
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/verify-email`
- `POST /auth/refresh`
- `POST /auth/forgot-password`
- `POST /auth/reset-password`
- `GET  /billing/plans`
- `POST /billing/webhook`

### 1.3 공통 응답 형식

#### 성공 응답

```json
{
  "data": { ... },
  "meta": {
    "request_id": "req_01J...",
    "timestamp": "2026-06-04T09:30:00Z"
  }
}
```

목록 응답:
```json
{
  "data": {
    "items": [ ... ],
    "total": 142,
    "limit": 20,
    "offset": 0,
    "has_next": true
  },
  "meta": {
    "request_id": "req_01J...",
    "timestamp": "2026-06-04T09:30:00Z"
  }
}
```

#### 에러 응답

```json
{
  "error": {
    "code": "AUTH_001",
    "message": "이메일 또는 비밀번호가 올바르지 않습니다",
    "detail": {}
  },
  "meta": {
    "request_id": "req_01J...",
    "timestamp": "2026-06-04T09:30:00Z"
  }
}
```

### 1.4 HTTP 상태 코드

| 코드 | 의미 |
|------|------|
| 200 | 성공 |
| 201 | 생성 성공 |
| 204 | 성공 (응답 본문 없음) |
| 400 | 잘못된 요청 (입력 검증 실패) |
| 401 | 인증 실패 (토큰 없음 / 만료) |
| 403 | 권한 없음 (플랜 제한 포함) |
| 404 | 리소스 없음 |
| 409 | 충돌 (중복 생성 등) |
| 422 | 유효성 검사 실패 |
| 429 | Rate Limit 초과 |
| 500 | 서버 내부 오류 |

### 1.5 Rate Limit

| 플랜 | 한도 | 헤더 |
|------|------|------|
| Free | 60 req/min | `X-RateLimit-Limit: 60` |
| Pro | 300 req/min | `X-RateLimit-Limit: 300` |
| Elite | 1000 req/min | `X-RateLimit-Limit: 1000` |

응답 헤더:
```
X-RateLimit-Limit: 300
X-RateLimit-Remaining: 287
X-RateLimit-Reset: 1748997060
```

Rate Limit 초과 시:
```http
HTTP/1.1 429 Too Many Requests
Retry-After: 43

{
  "error": {
    "code": "RATE_001",
    "message": "요청 한도를 초과했습니다. 잠시 후 다시 시도하세요.",
    "detail": { "retry_after_seconds": 43 }
  }
}
```

### 1.6 페이지네이션

쿼리 파라미터:
```
limit:  int (default 20, max 100)
offset: int (default 0)
```

### 1.7 공통 타입 정의

```typescript
type UUID = string                // "550e8400-e29b-41d4-a716-446655440000"
type Datetime = string            // ISO 8601 UTC "2026-06-04T09:30:00Z"
type Decimal = string             // "67450.00000000" (금융 정밀도)
type Plan = "free" | "pro" | "elite"
type RiskProfile = "conservative" | "moderate" | "aggressive"
type Direction = "LONG" | "SHORT" | "HOLD"
type SignalStatus = "active" | "expired" | "executed" | "dismissed"
type PositionStatus = "open" | "closed"
type OrderStatus = "pending" | "filled" | "cancelled" | "rejected"
type TradingMode = "full_auto" | "semi_auto" | "signal_only"
type NotificationType = "signal" | "order_filled" | "position_closed" | "liquidation_warning" | "daily_summary" | "system"
```

---

## 2. Auth API

### 2.1 `POST /auth/register` — 회원가입

**Request**

```http
POST /api/v1/auth/register
Content-Type: application/json
```

```json
{
  "email": "user@example.com",
  "password": "P@ssw0rd123!",
  "display_name": "김지민",
  "agreed_to_terms": true,
  "agreed_to_privacy": true
}
```

**Validation 규칙**
```
email:            유효한 이메일 형식, 최대 255자
password:         최소 8자, 대문자/소문자/숫자/특수문자 각 1개 이상
display_name:     2~30자 (선택)
agreed_to_terms:  반드시 true
agreed_to_privacy: 반드시 true
```

**Response 201**

```json
{
  "data": {
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "message": "인증 이메일이 발송되었습니다. 5분 내에 확인해주세요."
  }
}
```

**Error**

```json
// 409 — 이미 가입된 이메일
{
  "error": {
    "code": "AUTH_006",
    "message": "이미 가입된 이메일입니다.",
    "detail": {}
  }
}

// 422 — 비밀번호 강도 미달
{
  "error": {
    "code": "VALIDATION_001",
    "message": "비밀번호는 대소문자, 숫자, 특수문자를 각 1개 이상 포함해야 합니다.",
    "detail": { "field": "password" }
  }
}
```

---

### 2.2 `POST /auth/verify-email` — 이메일 인증

**Request**

```http
POST /api/v1/auth/verify-email
Content-Type: application/json
```

```json
{
  "email": "user@example.com",
  "code": "482910"
}
```

**Response 200**

```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 900,
    "user": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "email": "user@example.com",
      "plan": "free",
      "is_email_verified": true,
      "is_2fa_enabled": false,
      "is_onboarding_completed": false
    }
  }
}
```

Set-Cookie 헤더:
```
Set-Cookie: refresh_token=<token>; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth; Max-Age=604800
```

**Error**

```json
// 400 — 코드 만료
{
  "error": {
    "code": "AUTH_007",
    "message": "인증 코드가 만료되었습니다. 재발송을 요청하세요.",
    "detail": {}
  }
}

// 400 — 코드 불일치
{
  "error": {
    "code": "AUTH_008",
    "message": "인증 코드가 올바르지 않습니다.",
    "detail": { "attempts_remaining": 4 }
  }
}
```

---

### 2.3 `POST /auth/resend-verification` — 인증 이메일 재발송

**Request**

```http
POST /api/v1/auth/resend-verification
Content-Type: application/json
```

```json
{
  "email": "user@example.com"
}
```

**Response 200**

```json
{
  "data": {
    "message": "인증 이메일이 재발송되었습니다.",
    "expires_in": 300
  }
}
```

---

### 2.4 `POST /auth/login` — 로그인

**Request**

```http
POST /api/v1/auth/login
Content-Type: application/json
```

```json
{
  "email": "user@example.com",
  "password": "P@ssw0rd123!",
  "totp_code": "482910"
}
```

```
totp_code: 2FA 활성화 시 필수 (없으면 422 반환)
```

**Response 200**

```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 900,
    "user": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "email": "user@example.com",
      "display_name": "김지민",
      "plan": "pro",
      "risk_profile": "moderate",
      "is_2fa_enabled": true,
      "is_onboarding_completed": true,
      "last_login_at": "2026-06-03T22:15:00Z"
    }
  }
}
```

Set-Cookie 헤더: (위와 동일)

**Error**

```json
// 401 — 이메일/비밀번호 불일치
{
  "error": {
    "code": "AUTH_001",
    "message": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "detail": { "attempts_remaining": 3 }
  }
}

// 403 — 계정 잠김
{
  "error": {
    "code": "AUTH_009",
    "message": "로그인 시도 5회 초과로 계정이 잠겼습니다.",
    "detail": { "locked_until": "2026-06-04T09:45:00Z" }
  }
}

// 422 — 2FA 코드 누락
{
  "error": {
    "code": "AUTH_003",
    "message": "2FA 코드를 입력해주세요.",
    "detail": { "requires_totp": true }
  }
}

// 401 — 이메일 미인증
{
  "error": {
    "code": "AUTH_002",
    "message": "이메일 인증이 필요합니다.",
    "detail": {}
  }
}
```

---

### 2.5 `POST /auth/refresh` — 토큰 갱신

**Request**

```http
POST /api/v1/auth/refresh
Cookie: refresh_token=<token>
```

**Response 200**

```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 900
  }
}
```

**Error**

```json
// 401 — Refresh Token 만료/무효
{
  "error": {
    "code": "AUTH_004",
    "message": "세션이 만료되었습니다. 다시 로그인해주세요.",
    "detail": {}
  }
}
```

---

### 2.6 `POST /auth/logout` — 로그아웃

**Request**

```http
POST /api/v1/auth/logout
Authorization: Bearer <access_token>
Cookie: refresh_token=<token>
```

**Response 204** (No Content)

Refresh Token 즉시 무효화, Cookie 삭제.

---

### 2.7 `POST /auth/forgot-password` — 비밀번호 재설정 요청

**Request**

```http
POST /api/v1/auth/forgot-password
Content-Type: application/json
```

```json
{
  "email": "user@example.com"
}
```

**Response 200**

```json
{
  "data": {
    "message": "비밀번호 재설정 링크가 발송되었습니다.",
    "expires_in": 1800
  }
}
```

이메일 미존재 시에도 동일 응답 반환 (계정 존재 여부 노출 방지).

---

### 2.8 `POST /auth/reset-password` — 비밀번호 재설정

**Request**

```http
POST /api/v1/auth/reset-password
Content-Type: application/json
```

```json
{
  "token": "reset_token_from_email",
  "new_password": "NewP@ssw0rd456!"
}
```

**Response 200**

```json
{
  "data": {
    "message": "비밀번호가 재설정되었습니다. 다시 로그인해주세요."
  }
}
```

성공 시 모든 Refresh Token 무효화.

---

### 2.9 `POST /auth/2fa/enable` — 2FA 활성화 요청

**Request**

```http
POST /api/v1/auth/2fa/enable
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "qr_code_url": "otpauth://totp/TradingCopilot:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=TradingCopilot",
    "qr_code_image": "data:image/png;base64,iVBORw0KGgo...",
    "secret": "JBSWY3DPEHPK3PXP",
    "backup_codes": [
      "a1b2-c3d4",
      "e5f6-g7h8",
      "i9j0-k1l2",
      "m3n4-o5p6",
      "q7r8-s9t0",
      "u1v2-w3x4",
      "y5z6-a7b8"
    ]
  }
}
```

---

### 2.10 `POST /auth/2fa/verify` — 2FA 활성화 확인

**Request**

```http
POST /api/v1/auth/2fa/verify
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "totp_code": "482910"
}
```

**Response 200**

```json
{
  "data": {
    "is_2fa_enabled": true,
    "message": "2단계 인증이 활성화되었습니다."
  }
}
```

---

### 2.11 `POST /auth/2fa/disable` — 2FA 비활성화

**Request**

```http
POST /api/v1/auth/2fa/disable
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "totp_code": "482910",
  "password": "P@ssw0rd123!"
}
```

**Response 200**

```json
{
  "data": {
    "is_2fa_enabled": false,
    "message": "2단계 인증이 비활성화되었습니다."
  }
}
```

---

## 3. User API

### 3.1 `GET /users/me` — 내 프로파일 조회

**Request**

```http
GET /api/v1/users/me
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "display_name": "김지민",
    "plan": "pro",
    "risk_profile": "moderate",
    "timezone": "Asia/Seoul",
    "is_email_verified": true,
    "is_2fa_enabled": true,
    "is_onboarding_completed": true,
    "created_at": "2026-05-01T09:00:00Z",
    "last_login_at": "2026-06-04T08:00:00Z",
    "settings": {
      "mode": "full_auto",
      "coins": ["BTC", "ETH"],
      "risk_per_trade": "0.02",
      "max_leverage": 5,
      "daily_loss_limit": "500.00",
      "max_concurrent_positions": 5,
      "allowed_hours_start": "09:00",
      "allowed_hours_end": "23:00",
      "is_trading_active": true
    }
  }
}
```

---

### 3.2 `PATCH /users/me` — 프로파일 수정

**Request**

```http
PATCH /api/v1/users/me
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "display_name": "박성현",
  "timezone": "Asia/Seoul"
}
```

모든 필드 선택사항. 변경할 필드만 포함.

**Response 200**

```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "display_name": "박성현",
    "timezone": "Asia/Seoul",
    "updated_at": "2026-06-04T09:30:00Z"
  }
}
```

---

### 3.3 `POST /users/me/change-password` — 비밀번호 변경

**Request**

```http
POST /api/v1/users/me/change-password
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "current_password": "P@ssw0rd123!",
  "new_password": "NewP@ssw0rd456!",
  "totp_code": "482910"
}
```

**Response 200**

```json
{
  "data": {
    "message": "비밀번호가 변경되었습니다. 기존 세션이 모두 종료됩니다."
  }
}
```

성공 시 현재 세션 제외 모든 Refresh Token 무효화.

---

### 3.4 `GET /users/me/stats` — 수익률 통계

**Request**

```http
GET /api/v1/users/me/stats?period=30d
Authorization: Bearer <access_token>
```

Query:
```
period: 7d | 30d | 90d | all  (default: 30d)
```

**Response 200**

```json
{
  "data": {
    "period": "30d",
    "summary": {
      "total_pnl": "1234.56",
      "total_pnl_pct": "5.14",
      "win_rate": "0.67",
      "total_trades": 42,
      "winning_trades": 28,
      "losing_trades": 14,
      "avg_win_pct": "3.21",
      "avg_loss_pct": "-1.08",
      "max_drawdown": "-2.34",
      "sharpe_ratio": "1.87",
      "profit_factor": "2.32"
    },
    "daily_pnl": [
      {
        "date": "2026-05-05",
        "pnl": "234.50",
        "pnl_pct": "0.98",
        "cumulative_pnl": "234.50",
        "trades": 3
      },
      {
        "date": "2026-05-06",
        "pnl": "-87.30",
        "pnl_pct": "-0.36",
        "cumulative_pnl": "147.20",
        "trades": 2
      }
    ],
    "best_trade": {
      "coin": "BTC",
      "direction": "LONG",
      "pnl": "543.21",
      "pnl_pct": "8.76",
      "closed_at": "2026-05-15T14:30:00Z"
    },
    "worst_trade": {
      "coin": "ETH",
      "direction": "SHORT",
      "pnl": "-234.56",
      "pnl_pct": "-3.21",
      "closed_at": "2026-05-20T09:15:00Z"
    }
  }
}
```

---

### 3.5 `POST /users/me/onboarding` — 온보딩 설문 제출

**Request**

```http
POST /api/v1/users/me/onboarding
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "experience": "6m_2y",
  "target_monthly_return": "15_30",
  "acceptable_loss": "10_15"
}
```

```
experience: "beginner" | "6m_2y" | "2y_plus"
target_monthly_return: "5_10" | "15_30" | "30_plus"
acceptable_loss: "under_5" | "10_15" | "dynamic"
```

**Response 200**

```json
{
  "data": {
    "risk_profile": "moderate",
    "recommended_settings": {
      "risk_per_trade": "0.02",
      "max_leverage": 5,
      "daily_loss_limit_pct": "0.10",
      "mode": "semi_auto"
    },
    "is_onboarding_completed": true,
    "message": "중립형 프로파일로 설정되었습니다."
  }
}
```

---

### 3.6 `DELETE /users/me` — 계정 탈퇴

**Request**

```http
DELETE /api/v1/users/me
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "password": "P@ssw0rd123!",
  "reason": "서비스가 기대에 미치지 못했습니다",
  "confirm": "DELETE_MY_ACCOUNT"
}
```

**Response 200**

```json
{
  "data": {
    "message": "계정이 삭제 예약되었습니다. 7일 후 영구 삭제됩니다.",
    "scheduled_deletion_at": "2026-06-11T09:30:00Z"
  }
}
```

오픈 포지션 존재 시:
```json
{
  "error": {
    "code": "USER_001",
    "message": "오픈 포지션이 있어 탈퇴할 수 없습니다. 먼저 포지션을 청산해주세요.",
    "detail": { "open_positions": 2 }
  }
}
```

---

## 4. Binance API

### 4.1 `POST /binance/connect` — API Key 등록

**Request**

```http
POST /api/v1/binance/connect
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "api_key": "vmPUZE6mv9SD5VNHk4HlbGsG5A89...",
  "api_secret": "NhqPtmdSJYdKjVHjA7PZj4Mge3NMfn...",
  "label": "Main Account",
  "is_testnet": false
}
```

```
api_key:    Binance API Key (필수)
api_secret: Binance API Secret (필수)
label:      계좌 레이블 (선택, 최대 50자)
is_testnet: Testnet 여부 (기본 false)
```

**서버 처리 순서**
```
1. Binance GET /api/v3/account 호출 → 권한 목록 조회
2. "Withdraw" 권한 존재 시 즉시 거부 (BINANCE_002)
3. "Futures" 권한 없을 시 거부 (BINANCE_003)
4. GET /fapi/v2/balance 호출 → USDT 잔고 조회
5. AES-256-GCM 암호화 후 exchange_accounts 테이블 저장
6. 평문 Key는 응답에 절대 포함하지 않음
```

**Response 201**

```json
{
  "data": {
    "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "label": "Main Account",
    "status": "connected",
    "is_testnet": false,
    "balance_usdt": "24500.00000000",
    "unrealized_pnl": "342.15000000",
    "permissions": ["FUTURES_TRADING"],
    "connected_at": "2026-06-04T09:30:00Z"
  }
}
```

**Error**

```json
// 400 — 출금 권한 포함
{
  "error": {
    "code": "BINANCE_002",
    "message": "출금 권한이 포함된 API Key는 등록할 수 없습니다. Futures Trading 권한만 허용됩니다.",
    "detail": { "detected_permissions": ["FUTURES_TRADING", "Withdraw"] }
  }
}

// 400 — Futures 권한 없음
{
  "error": {
    "code": "BINANCE_003",
    "message": "Futures 거래 권한이 없는 API Key입니다.",
    "detail": {}
  }
}

// 400 — API Key 인증 실패
{
  "error": {
    "code": "BINANCE_001",
    "message": "API Key 연결에 실패했습니다. Key와 Secret을 확인해주세요.",
    "detail": {}
  }
}

// 409 — 이미 연결된 계좌
{
  "error": {
    "code": "BINANCE_005",
    "message": "이미 연결된 Binance 계좌가 있습니다.",
    "detail": {}
  }
}
```

---

### 4.2 `GET /binance/status` — 연결 상태 조회

**Request**

```http
GET /api/v1/binance/status
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "is_connected": true,
    "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "label": "Main Account",
    "is_testnet": false,
    "balance_usdt": "24157.85000000",
    "available_usdt": "21342.60000000",
    "unrealized_pnl": "+342.15000000",
    "margin_used": "2457.10000000",
    "last_checked_at": "2026-06-04T09:29:45Z",
    "consecutive_failures": 0,
    "status": "healthy"
  }
}
```

```
status: "healthy" | "degraded" | "disconnected"
degraded: API 오류 1~2회 연속
disconnected: API 오류 3회 연속 (자동매매 중단됨)
```

연결 없는 경우:
```json
{
  "data": {
    "is_connected": false,
    "account_id": null
  }
}
```

---

### 4.3 `GET /binance/balance` — 잔고 상세 조회

**Request**

```http
GET /api/v1/binance/balance
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "total_balance": "24500.00000000",
    "available_balance": "21342.60000000",
    "total_unrealized_pnl": "+342.15000000",
    "total_margin_used": "2815.25000000",
    "margin_ratio": "0.1149",
    "assets": [
      {
        "asset": "USDT",
        "wallet_balance": "24500.00000000",
        "unrealized_profit": "+342.15000000",
        "margin_balance": "24842.15000000",
        "available_balance": "21342.60000000"
      }
    ],
    "fetched_at": "2026-06-04T09:30:00Z"
  }
}
```

---

### 4.4 `DELETE /binance/disconnect` — API Key 삭제

**Request**

```http
DELETE /api/v1/binance/disconnect
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "confirm": true
}
```

**Response 200**

```json
{
  "data": {
    "message": "Binance API 연결이 해제되었습니다. 자동매매가 중단되었습니다.",
    "auto_trading_stopped": true
  }
}
```

오픈 포지션 존재 시:
```json
{
  "error": {
    "code": "BINANCE_006",
    "message": "오픈 포지션이 있어 API Key를 삭제할 수 없습니다. 먼저 포지션을 청산해주세요.",
    "detail": { "open_positions": 2 }
  }
}
```

---

### 4.5 `GET /binance/permissions` — API Key 권한 재조회

**Request**

```http
GET /api/v1/binance/permissions
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "permissions": ["FUTURES_TRADING"],
    "ip_whitelist": ["203.0.113.10"],
    "checked_at": "2026-06-04T09:30:00Z"
  }
}
```

---

## 5. Signal API

### 5.1 `GET /signals` — 시그널 목록 조회

**Request**

```http
GET /api/v1/signals?coin=BTC&direction=LONG&status=active&min_confidence=0.75&limit=20&offset=0
Authorization: Bearer <access_token>
```

Query:
```
coin:           BTC | ETH | all  (default: all)
direction:      LONG | SHORT | HOLD | all  (default: all)
status:         active | expired | executed | dismissed | all  (default: active)
min_confidence: 0.0 ~ 1.0  (default: 0.0)
limit:          1 ~ 100  (default: 20)
offset:         0 이상  (default: 0)
```

**Response 200**

```json
{
  "data": {
    "items": [
      {
        "id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
        "coin": "BTC",
        "direction": "LONG",
        "confidence": 0.87,
        "entry_price": "67450.00000000",
        "take_profit": "69200.00000000",
        "stop_loss": "66800.00000000",
        "leverage": 5,
        "rr_ratio": "2.71",
        "reasons": [
          "RSI(14) = 42, 과매도 구간 진입 후 상승 반전",
          "4시간봉 EMA(50) 지지 확인, 거래량 증가 동반",
          "Funding Rate -0.02% (숏 과다), OI 3% 증가"
        ],
        "status": "active",
        "is_executed": false,
        "expires_at": "2026-06-04T10:30:00Z",
        "created_at": "2026-06-04T09:30:00Z"
      }
    ],
    "total": 1,
    "limit": 20,
    "offset": 0,
    "has_next": false
  }
}
```

Free 플랜 일일 한도 초과 시:
```json
{
  "error": {
    "code": "BILLING_001",
    "message": "오늘의 무료 시그널(3개)이 소진되었습니다. Pro 업그레이드 후 무제한으로 받으세요.",
    "detail": {
      "daily_limit": 3,
      "used": 3,
      "upgrade_url": "/billing/plans"
    }
  }
}
```

---

### 5.2 `GET /signals/{signal_id}` — 시그널 상세

**Request**

```http
GET /api/v1/signals/sig_01JVBCK3XY7Z8A9BCD0EFG
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
    "coin": "BTC",
    "symbol": "BTCUSDT",
    "direction": "LONG",
    "confidence": 0.87,
    "entry_price": "67450.00000000",
    "take_profit": "69200.00000000",
    "stop_loss": "66800.00000000",
    "leverage": 5,
    "rr_ratio": "2.71",
    "reasons": [
      "RSI(14) = 42, 과매도 구간 진입 후 상승 반전",
      "4시간봉 EMA(50) 지지 확인, 거래량 증가 동반",
      "Funding Rate -0.02% (숏 과다), OI 3% 증가"
    ],
    "agent_scores": {
      "technical": 0.72,
      "sentiment": 0.65,
      "market_structure": 0.81
    },
    "market_snapshot": {
      "price_at_signal": "67450.00",
      "volume_24h": "28450000000.00",
      "open_interest": "15230000000.00",
      "funding_rate": "-0.0002",
      "long_short_ratio": "0.89",
      "fear_greed_index": 42
    },
    "status": "active",
    "is_executed": false,
    "executed_order_id": null,
    "expires_at": "2026-06-04T10:30:00Z",
    "created_at": "2026-06-04T09:30:00Z",
    "generation_time_ms": 1842
  }
}
```

---

### 5.3 `POST /signals/{signal_id}/execute` — 시그널 수동 실행

반자동 / 알림 전용 모드 사용자가 시그널을 확인 후 실행.

**Request**

```http
POST /api/v1/signals/sig_01JVBCK3XY7Z8A9BCD0EFG/execute
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "confirm": true,
  "override_leverage": 3
}
```

```
confirm:           반드시 true (의도적 실행 확인)
override_leverage: 시그널 추천 레버리지 덮어쓰기 (선택, 1~user.max_leverage)
```

**Response 201**

```json
{
  "data": {
    "order_id": "ord_01JVBCM4XY8Z9A0BCD1EFG",
    "signal_id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
    "status": "pending",
    "symbol": "BTCUSDT",
    "direction": "LONG",
    "quantity": "0.01500000",
    "entry_price": "67452.00000000",
    "take_profit": "69200.00000000",
    "stop_loss": "66800.00000000",
    "leverage": 3,
    "margin_required": "337.26000000",
    "created_at": "2026-06-04T09:30:05Z"
  }
}
```

**Error**

```json
// 400 — 시그널 만료
{
  "error": {
    "code": "SIGNAL_001",
    "message": "시그널이 만료되었습니다.",
    "detail": { "expired_at": "2026-06-04T08:30:00Z" }
  }
}

// 400 — 일일 손실 한도 도달
{
  "error": {
    "code": "ORDER_001",
    "message": "일일 손실 한도에 도달했습니다. 자동매매가 중단된 상태입니다.",
    "detail": {
      "daily_loss": "-500.00",
      "daily_loss_limit": "-500.00"
    }
  }
}

// 400 — 잔고 부족
{
  "error": {
    "code": "BINANCE_004",
    "message": "잔고가 부족합니다.",
    "detail": {
      "required": "337.26",
      "available": "200.00"
    }
  }
}
```

---

### 5.4 `POST /signals/{signal_id}/dismiss` — 시그널 무시

**Request**

```http
POST /api/v1/signals/sig_01JVBCK3XY7Z8A9BCD0EFG/dismiss
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "reason": "진입 타이밍이 좋지 않다고 판단"
}
```

**Response 200**

```json
{
  "data": {
    "signal_id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
    "status": "dismissed",
    "dismissed_at": "2026-06-04T09:31:00Z"
  }
}
```

---

### 5.5 `GET /signals/history` — 시그널 히스토리

**Request**

```http
GET /api/v1/signals/history?limit=50&offset=0&coin=BTC
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "items": [
      {
        "id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
        "coin": "BTC",
        "direction": "LONG",
        "confidence": 0.87,
        "entry_price": "67450.00000000",
        "take_profit": "69200.00000000",
        "stop_loss": "66800.00000000",
        "leverage": 5,
        "rr_ratio": "2.71",
        "status": "executed",
        "outcome": "tp_hit",
        "pnl": "+234.50",
        "created_at": "2026-06-03T14:00:00Z",
        "closed_at": "2026-06-03T18:23:00Z"
      }
    ],
    "total": 87,
    "limit": 50,
    "offset": 0,
    "has_next": true
  }
}
```

---

## 6. Position API

### 6.1 `GET /positions` — 오픈 포지션 목록

**Request**

```http
GET /api/v1/positions
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "positions": [
      {
        "id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
        "symbol": "BTCUSDT",
        "coin": "BTC",
        "direction": "LONG",
        "status": "open",
        "quantity": "0.01500000",
        "entry_price": "67452.00000000",
        "current_price": "67890.00000000",
        "take_profit": "69200.00000000",
        "stop_loss": "66800.00000000",
        "leverage": 5,
        "margin_used": "202.36000000",
        "unrealized_pnl": "+65.70000000",
        "unrealized_pnl_pct": "+3.25",
        "liquidation_price": "54250.00000000",
        "liquidation_distance_pct": "20.09",
        "tp_distance_pct": "1.93",
        "sl_distance_pct": "-1.56",
        "duration_seconds": 3625,
        "source": "auto",
        "signal_id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
        "opened_at": "2026-06-04T08:29:20Z"
      }
    ],
    "summary": {
      "total_positions": 1,
      "total_unrealized_pnl": "+65.70",
      "total_margin_used": "202.36"
    }
  }
}
```

---

### 6.2 `GET /positions/{position_id}` — 포지션 상세

**Request**

```http
GET /api/v1/positions/pos_01JVBCN5XY9Z0A1BCD2EFG
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
    "symbol": "BTCUSDT",
    "coin": "BTC",
    "direction": "LONG",
    "status": "open",
    "quantity": "0.01500000",
    "remaining_quantity": "0.01500000",
    "entry_price": "67452.00000000",
    "current_price": "67890.00000000",
    "take_profit": "69200.00000000",
    "stop_loss": "66800.00000000",
    "leverage": 5,
    "margin_used": "202.36000000",
    "unrealized_pnl": "+65.70000000",
    "unrealized_pnl_pct": "+3.25",
    "liquidation_price": "54250.00000000",
    "liquidation_distance_pct": "20.09",
    "fee_paid": "2.02",
    "source": "auto",
    "signal_id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
    "exchange_position_id": "123456789",
    "orders": [
      {
        "id": "ord_01JVBCM4XY8Z9A0BCD1EFG",
        "type": "market",
        "side": "buy",
        "quantity": "0.01500000",
        "filled_price": "67452.00000000",
        "status": "filled",
        "created_at": "2026-06-04T08:29:15Z"
      },
      {
        "id": "ord_01JVBCM5XY9Z0A1BCD2EFG",
        "type": "take_profit",
        "side": "sell",
        "quantity": "0.01500000",
        "price": "69200.00000000",
        "status": "open"
      },
      {
        "id": "ord_01JVBCM6XY0Z1A2BCD3EFG",
        "type": "stop_loss",
        "side": "sell",
        "quantity": "0.01500000",
        "price": "66800.00000000",
        "status": "open"
      }
    ],
    "opened_at": "2026-06-04T08:29:20Z",
    "last_updated_at": "2026-06-04T09:30:00Z"
  }
}
```

---

### 6.3 `POST /positions/{position_id}/close` — 포지션 청산

**Request**

```http
POST /api/v1/positions/pos_01JVBCN5XY9Z0A1BCD2EFG/close
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "type": "market",
  "quantity_ratio": 0.5,
  "reason": "수동 청산 — 리스크 감소"
}
```

```
type:           "market" | "limit"
quantity_ratio: 0.0 초과 ~ 1.0 이하 (1.0 = 전량 청산)
price:          type=limit 시 필수
reason:         청산 사유 (선택, 기록용)
```

**Response 200**

```json
{
  "data": {
    "order_id": "ord_01JVBCM7XY1Z2A3BCD4EFG",
    "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
    "type": "market",
    "quantity_closed": "0.00750000",
    "quantity_remaining": "0.00750000",
    "estimated_pnl": "+32.85",
    "status": "pending",
    "created_at": "2026-06-04T09:30:05Z"
  }
}
```

---

### 6.4 `PATCH /positions/{position_id}/tpsl` — TP/SL 수정

**Request**

```http
PATCH /api/v1/positions/pos_01JVBCN5XY9Z0A1BCD2EFG/tpsl
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "take_profit": "70000.00",
  "stop_loss": "67000.00"
}
```

둘 중 하나만 전송 가능.

**Response 200**

```json
{
  "data": {
    "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
    "take_profit": "70000.00000000",
    "stop_loss": "67000.00000000",
    "rr_ratio": "3.14",
    "updated_at": "2026-06-04T09:30:10Z"
  }
}
```

SL을 진입가보다 불리한 방향으로 이동 시 경고:
```json
{
  "data": {
    "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
    "take_profit": "70000.00000000",
    "stop_loss": "65000.00000000",
    "warning": "손절가를 진입가(67452)보다 멀게 설정했습니다. 리스크가 증가합니다.",
    "updated_at": "2026-06-04T09:30:10Z"
  }
}
```

---

### 6.5 `POST /positions/{position_id}/dca` — DCA 추가 진입

**Request**

```http
POST /api/v1/positions/pos_01JVBCN5XY9Z0A1BCD2EFG/dca
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "confirm": true
}
```

**Response 201**

```json
{
  "data": {
    "dca_order_id": "ord_01JVBCM8XY2Z3A4BCD5EFG",
    "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
    "dca_count": 1,
    "original_entry": "67452.00",
    "new_avg_entry": "67671.00",
    "new_quantity": "0.03000000",
    "new_margin_required": "202.36",
    "new_stop_loss": "66800.00",
    "new_rr_ratio": "2.31",
    "status": "pending"
  }
}
```

DCA 불가 시:
```json
{
  "error": {
    "code": "ORDER_006",
    "message": "DCA 추가 진입 조건을 충족하지 않습니다.",
    "detail": {
      "reason": "가격 이동이 ATR × 1.0 미만입니다",
      "current_movement_pct": "0.23",
      "required_movement_pct": "0.45"
    }
  }
}
```

---

### 6.6 `POST /positions/close-all` — 전체 포지션 긴급 청산

**Request**

```http
POST /api/v1/positions/close-all
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "confirm": "CLOSE_ALL"
}
```

오타 방지 이중 확인. 문자열이 정확히 `"CLOSE_ALL"` 이어야 실행.

**Response 200**

```json
{
  "data": {
    "closed_positions": 3,
    "failed_positions": 0,
    "total_realized_pnl": "-87.30",
    "details": [
      {
        "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
        "coin": "BTC",
        "status": "closed",
        "realized_pnl": "+45.20"
      },
      {
        "position_id": "pos_01JVBCO6XY0Z1A2BCD3EFG",
        "coin": "ETH",
        "status": "closed",
        "realized_pnl": "-132.50"
      }
    ],
    "completed_at": "2026-06-04T09:30:08Z"
  }
}
```

---

## 7. Order API

### 7.1 `GET /orders` — 주문 내역 조회

**Request**

```http
GET /api/v1/orders?status=filled&limit=20&offset=0&coin=BTC
Authorization: Bearer <access_token>
```

Query:
```
status:     open | filled | cancelled | rejected | all  (default: all)
coin:       BTC | ETH | all  (default: all)
start_date: ISO 8601 날짜 (선택)
end_date:   ISO 8601 날짜 (선택)
limit:      1 ~ 100  (default: 20)
offset:     0 이상
```

**Response 200**

```json
{
  "data": {
    "items": [
      {
        "id": "ord_01JVBCM4XY8Z9A0BCD1EFG",
        "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
        "signal_id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
        "symbol": "BTCUSDT",
        "coin": "BTC",
        "order_type": "market",
        "side": "buy",
        "quantity": "0.01500000",
        "filled_quantity": "0.01500000",
        "entry_price": null,
        "filled_price": "67452.00000000",
        "take_profit": "69200.00000000",
        "stop_loss": "66800.00000000",
        "leverage": 5,
        "fee": "2.02",
        "status": "filled",
        "source": "auto",
        "client_order_id": "tc_01JVBCM4XY8Z9A0BCD1EFG",
        "exchange_order_id": "987654321",
        "created_at": "2026-06-04T08:29:15Z",
        "executed_at": "2026-06-04T08:29:16Z"
      }
    ],
    "total": 87,
    "limit": 20,
    "offset": 0,
    "has_next": true
  }
}
```

---

### 7.2 `GET /orders/{order_id}` — 주문 상세

**Request**

```http
GET /api/v1/orders/ord_01JVBCM4XY8Z9A0BCD1EFG
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "id": "ord_01JVBCM4XY8Z9A0BCD1EFG",
    "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
    "signal_id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
    "symbol": "BTCUSDT",
    "order_type": "market",
    "side": "buy",
    "quantity": "0.01500000",
    "filled_quantity": "0.01500000",
    "filled_price": "67452.00000000",
    "take_profit": "69200.00000000",
    "stop_loss": "66800.00000000",
    "leverage": 5,
    "margin_used": "202.36000000",
    "fee": "2.02",
    "fee_asset": "USDT",
    "status": "filled",
    "source": "auto",
    "client_order_id": "tc_01JVBCM4XY8Z9A0BCD1EFG",
    "exchange_order_id": "987654321",
    "retry_count": 0,
    "created_at": "2026-06-04T08:29:15Z",
    "executed_at": "2026-06-04T08:29:16Z"
  }
}
```

---

### 7.3 `GET /orders/stats` — 주문 통계

**Request**

```http
GET /api/v1/orders/stats?period=30d
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "period": "30d",
    "total_orders": 87,
    "filled": 84,
    "cancelled": 2,
    "rejected": 1,
    "success_rate": "0.966",
    "avg_execution_time_ms": 143,
    "total_fees_paid": "178.54",
    "by_coin": {
      "BTC": { "count": 52, "win_rate": "0.71" },
      "ETH": { "count": 35, "win_rate": "0.60" }
    },
    "by_direction": {
      "LONG": { "count": 54, "win_rate": "0.69" },
      "SHORT": { "count": 33, "win_rate": "0.61" }
    }
  }
}
```

---

## 8. Notification API

### 8.1 `GET /notifications` — 알림 목록 조회

**Request**

```http
GET /api/v1/notifications?is_read=false&limit=20&offset=0
Authorization: Bearer <access_token>
```

Query:
```
is_read:    true | false | all  (default: all)
type:       signal | order_filled | position_closed | liquidation_warning | daily_summary | system | all
limit:      1 ~ 100  (default: 20)
offset:     0 이상
```

**Response 200**

```json
{
  "data": {
    "items": [
      {
        "id": "notif_01JVBCP7XY1Z2A3BCD4EFG",
        "type": "signal",
        "title": "BTC LONG 시그널 발생",
        "body": "신뢰도 87% | 진입 $67,450 | TP $69,200 | SL $66,800",
        "metadata": {
          "signal_id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
          "coin": "BTC",
          "direction": "LONG",
          "confidence": 0.87
        },
        "channel": "web",
        "is_read": false,
        "created_at": "2026-06-04T09:30:00Z"
      },
      {
        "id": "notif_01JVBCP8XY2Z3A4BCD5EFG",
        "type": "order_filled",
        "title": "BTC LONG 주문 체결",
        "body": "체결가 $67,452 | 수량 0.015 BTC | 레버리지 5x",
        "metadata": {
          "order_id": "ord_01JVBCM4XY8Z9A0BCD1EFG",
          "coin": "BTC",
          "filled_price": "67452.00"
        },
        "channel": "web",
        "is_read": false,
        "created_at": "2026-06-04T09:30:05Z"
      }
    ],
    "total": 24,
    "unread_count": 5,
    "limit": 20,
    "offset": 0,
    "has_next": true
  }
}
```

---

### 8.2 `POST /notifications/{notification_id}/read` — 알림 읽음 처리

**Request**

```http
POST /api/v1/notifications/notif_01JVBCP7XY1Z2A3BCD4EFG/read
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "notification_id": "notif_01JVBCP7XY1Z2A3BCD4EFG",
    "is_read": true,
    "read_at": "2026-06-04T09:31:00Z"
  }
}
```

---

### 8.3 `POST /notifications/read-all` — 전체 읽음 처리

**Request**

```http
POST /api/v1/notifications/read-all
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "marked_count": 5,
    "read_at": "2026-06-04T09:31:00Z"
  }
}
```

---

### 8.4 `GET /notifications/settings` — 알림 설정 조회

**Request**

```http
GET /api/v1/notifications/settings
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "channels": {
      "web": true,
      "telegram": true,
      "email": false
    },
    "types": {
      "signal": true,
      "order_filled": true,
      "position_closed": true,
      "liquidation_warning": true,
      "daily_summary": true,
      "system": true
    },
    "quiet_hours": {
      "enabled": true,
      "start": "00:00",
      "end": "07:00",
      "timezone": "Asia/Seoul"
    },
    "telegram": {
      "is_connected": true,
      "chat_id": "123456789",
      "username": "@tradingcopilot_bot",
      "connected_at": "2026-05-15T09:00:00Z"
    }
  }
}
```

---

### 8.5 `PUT /notifications/settings` — 알림 설정 변경

**Request**

```http
PUT /api/v1/notifications/settings
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "channels": {
    "web": true,
    "telegram": true,
    "email": false
  },
  "types": {
    "signal": true,
    "order_filled": true,
    "position_closed": true,
    "liquidation_warning": true,
    "daily_summary": false,
    "system": true
  },
  "quiet_hours": {
    "enabled": true,
    "start": "01:00",
    "end": "08:00",
    "timezone": "Asia/Seoul"
  }
}
```

모든 필드 선택사항. 변경할 필드만 포함.

**Response 200**

```json
{
  "data": {
    "channels": { "web": true, "telegram": true, "email": false },
    "types": {
      "signal": true,
      "order_filled": true,
      "position_closed": true,
      "liquidation_warning": true,
      "daily_summary": false,
      "system": true
    },
    "quiet_hours": { "enabled": true, "start": "01:00", "end": "08:00", "timezone": "Asia/Seoul" },
    "updated_at": "2026-06-04T09:32:00Z"
  }
}
```

---

### 8.6 `POST /notifications/telegram/connect` — 텔레그램 연결

**Request**

```http
POST /api/v1/notifications/telegram/connect
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "connect_url": "https://t.me/tradingcopilot_bot?start=link_abc123xyz",
    "link_token": "link_abc123xyz",
    "expires_in": 600,
    "instructions": "위 링크를 클릭하여 텔레그램 봇에서 /start 명령을 실행하세요. 10분 내에 완료해주세요."
  }
}
```

---

### 8.7 `DELETE /notifications/telegram/disconnect` — 텔레그램 연결 해제

**Request**

```http
DELETE /api/v1/notifications/telegram/disconnect
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "message": "텔레그램 연결이 해제되었습니다."
  }
}
```

---

### 8.8 `POST /notifications/test` — 테스트 알림 발송

**Request**

```http
POST /api/v1/notifications/test
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "channel": "telegram",
  "type": "signal"
}
```

**Response 200**

```json
{
  "data": {
    "message": "테스트 알림이 발송되었습니다.",
    "channel": "telegram",
    "sent_at": "2026-06-04T09:33:00Z"
  }
}
```

---

## 9. Subscription API

### 9.1 `GET /billing/plans` — 플랜 목록 (공개 API)

**Request**

```http
GET /api/v1/billing/plans
```

인증 불필요.

**Response 200**

```json
{
  "data": {
    "plans": [
      {
        "id": "free",
        "name": "Free",
        "price_monthly": "0",
        "price_yearly": "0",
        "currency": "USD",
        "stripe_price_id_monthly": null,
        "stripe_price_id_yearly": null,
        "features": {
          "signals_per_day": 3,
          "auto_trading": false,
          "max_positions": 1,
          "journal_days": 30,
          "backtesting": false,
          "custom_strategy": false,
          "api_access": false,
          "telegram_notifications": "basic_3",
          "support": "community",
          "coins": ["BTC", "ETH"]
        }
      },
      {
        "id": "pro",
        "name": "Pro",
        "price_monthly": "29",
        "price_yearly": "278",
        "yearly_discount_pct": 20,
        "currency": "USD",
        "stripe_price_id_monthly": "price_1ABC...",
        "stripe_price_id_yearly": "price_1DEF...",
        "features": {
          "signals_per_day": -1,
          "auto_trading": true,
          "max_positions": 5,
          "journal_days": -1,
          "backtesting_days": 90,
          "custom_strategy": false,
          "api_access": false,
          "telegram_notifications": "all",
          "support": "email",
          "coins": ["BTC", "ETH", "top_10"]
        }
      },
      {
        "id": "elite",
        "name": "Elite",
        "price_monthly": "99",
        "price_yearly": "950",
        "yearly_discount_pct": 20,
        "currency": "USD",
        "stripe_price_id_monthly": "price_1GHI...",
        "stripe_price_id_yearly": "price_1JKL...",
        "features": {
          "signals_per_day": -1,
          "auto_trading": true,
          "max_positions": 20,
          "journal_days": -1,
          "backtesting_days": -1,
          "custom_strategy": true,
          "api_access": true,
          "telegram_notifications": "all_custom",
          "support": "dedicated",
          "coins": "all"
        }
      }
    ]
  }
}
```

---

### 9.2 `GET /billing/subscription` — 현재 구독 상태

**Request**

```http
GET /api/v1/billing/subscription
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "plan": "pro",
    "status": "active",
    "billing_period": "monthly",
    "current_period_start": "2026-06-01T00:00:00Z",
    "current_period_end": "2026-07-01T00:00:00Z",
    "cancel_at_period_end": false,
    "cancelled_at": null,
    "trial_end_at": null,
    "stripe_subscription_id": "sub_1ABC...",
    "next_billing_date": "2026-07-01T00:00:00Z",
    "next_billing_amount": "29.00",
    "currency": "USD"
  }
}
```

무료 플랜:
```json
{
  "data": {
    "plan": "free",
    "status": "active",
    "billing_period": null,
    "current_period_end": null,
    "cancel_at_period_end": false,
    "stripe_subscription_id": null
  }
}
```

---

### 9.3 `POST /billing/checkout` — Stripe Checkout 세션 생성

**Request**

```http
POST /api/v1/billing/checkout
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "plan": "pro",
  "billing_period": "monthly",
  "success_url": "https://app.trading-copilot.com/billing/success",
  "cancel_url": "https://app.trading-copilot.com/billing/plans"
}
```

**Response 200**

```json
{
  "data": {
    "checkout_url": "https://checkout.stripe.com/pay/cs_live_...",
    "session_id": "cs_live_...",
    "expires_at": "2026-06-04T10:30:00Z"
  }
}
```

**Error**

```json
// 400 — 이미 동일 또는 상위 플랜 구독 중
{
  "error": {
    "code": "BILLING_004",
    "message": "이미 Pro 플랜을 구독 중입니다.",
    "detail": {}
  }
}
```

---

### 9.4 `POST /billing/upgrade` — 즉시 업그레이드 (차액 정산)

**Request**

```http
POST /api/v1/billing/upgrade
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "plan": "elite",
  "billing_period": "monthly"
}
```

**Response 200**

```json
{
  "data": {
    "plan": "elite",
    "effective_at": "2026-06-04T09:33:00Z",
    "proration_amount": "46.45",
    "next_billing_amount": "99.00",
    "next_billing_date": "2026-07-01T00:00:00Z",
    "checkout_url": null
  }
}
```

---

### 9.5 `DELETE /billing/subscription` — 구독 취소

**Request**

```http
DELETE /api/v1/billing/subscription
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "reason": "비용이 부담됩니다",
  "feedback": "가격을 낮춰주시면 다시 구독할 의향이 있습니다"
}
```

**Response 200**

```json
{
  "data": {
    "plan": "pro",
    "cancel_at_period_end": true,
    "access_until": "2026-07-01T00:00:00Z",
    "message": "구독이 취소되었습니다. 2026-07-01까지 Pro 기능을 계속 이용할 수 있습니다."
  }
}
```

---

### 9.6 `POST /billing/reactivate` — 구독 재활성화 (취소 철회)

**Request**

```http
POST /api/v1/billing/reactivate
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "plan": "pro",
    "cancel_at_period_end": false,
    "next_billing_date": "2026-07-01T00:00:00Z",
    "message": "구독 취소가 철회되었습니다."
  }
}
```

---

### 9.7 `GET /billing/invoices` — 인보이스 목록

**Request**

```http
GET /api/v1/billing/invoices?limit=20&offset=0
Authorization: Bearer <access_token>
```

**Response 200**

```json
{
  "data": {
    "items": [
      {
        "id": "in_1ABC...",
        "amount": "29.00",
        "currency": "USD",
        "status": "paid",
        "description": "AI Trading Copilot Pro — June 2026",
        "pdf_url": "https://pay.stripe.com/invoice/pdf/...",
        "hosted_invoice_url": "https://invoice.stripe.com/...",
        "paid_at": "2026-06-01T00:05:00Z",
        "created_at": "2026-06-01T00:00:00Z"
      },
      {
        "id": "in_1DEF...",
        "amount": "29.00",
        "currency": "USD",
        "status": "paid",
        "description": "AI Trading Copilot Pro — May 2026",
        "pdf_url": "https://pay.stripe.com/invoice/pdf/...",
        "hosted_invoice_url": "https://invoice.stripe.com/...",
        "paid_at": "2026-05-01T00:04:00Z",
        "created_at": "2026-05-01T00:00:00Z"
      }
    ],
    "total": 2,
    "limit": 20,
    "offset": 0,
    "has_next": false
  }
}
```

---

### 9.8 `POST /billing/webhook` — Stripe Webhook 수신

**Request**

```http
POST /api/v1/billing/webhook
Stripe-Signature: t=1748997060,v1=abc123...
Content-Type: application/json
```

서버는 `Stripe-Signature` 헤더로 HMAC-SHA256 서명 검증 후 처리.

처리 이벤트:

| Stripe 이벤트 | 서버 처리 |
|---------------|-----------|
| `customer.subscription.created` | 구독 레코드 생성, 플랜 활성화 |
| `customer.subscription.updated` | 플랜 변경 동기화 |
| `customer.subscription.deleted` | 플랜 Free 다운그레이드 |
| `invoice.payment_succeeded` | 인보이스 기록, 이메일 발송 |
| `invoice.payment_failed` | 결제 실패 알림 (이메일 + 텔레그램), 유예기간 시작 |
| `invoice.payment_action_required` | 추가 인증 필요 알림 |

**Response 200**

```json
{
  "received": true
}
```

서명 검증 실패 시 `400` 반환.

---

## 10. WebSocket API

### 10.1 연결

```
Base URL: wss://api.trading-copilot.com/ws/v1
인증:      쿼리 파라미터 토큰 또는 초기 메시지 인증
```

연결 방식:
```javascript
const ws = new WebSocket(
  `wss://api.trading-copilot.com/ws/v1/signals?token=${accessToken}`
)
```

---

### 10.2 공통 메시지 형식

**클라이언트 → 서버**
```json
{
  "type": "ping",
  "id": "msg_01"
}
```

**서버 → 클라이언트**
```json
{
  "type": "pong",
  "id": "msg_01",
  "timestamp": "2026-06-04T09:30:00Z"
}
```

```json
{
  "type": "event_type",
  "data": { ... },
  "timestamp": "2026-06-04T09:30:00Z"
}
```

---

### 10.3 `WS /ws/v1/signals` — 실시간 시그널 스트림

**이벤트 목록**

#### `signal.new` — 새 시그널 생성

```json
{
  "type": "signal.new",
  "data": {
    "id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
    "coin": "BTC",
    "direction": "LONG",
    "confidence": 0.87,
    "entry_price": "67450.00000000",
    "take_profit": "69200.00000000",
    "stop_loss": "66800.00000000",
    "leverage": 5,
    "rr_ratio": "2.71",
    "reasons": [
      "RSI(14) = 42, 과매도 구간 진입 후 상승 반전",
      "4시간봉 EMA(50) 지지 확인, 거래량 증가 동반",
      "Funding Rate -0.02% (숏 과다), OI 3% 증가"
    ],
    "expires_at": "2026-06-04T10:30:00Z"
  },
  "timestamp": "2026-06-04T09:30:00Z"
}
```

#### `signal.expired` — 시그널 만료

```json
{
  "type": "signal.expired",
  "data": {
    "signal_id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
    "coin": "BTC",
    "direction": "LONG"
  },
  "timestamp": "2026-06-04T10:30:00Z"
}
```

#### `signal.executed` — 시그널 실행됨 (자동매매)

```json
{
  "type": "signal.executed",
  "data": {
    "signal_id": "sig_01JVBCK3XY7Z8A9BCD0EFG",
    "order_id": "ord_01JVBCM4XY8Z9A0BCD1EFG",
    "coin": "BTC",
    "filled_price": "67452.00000000",
    "quantity": "0.01500000"
  },
  "timestamp": "2026-06-04T09:30:05Z"
}
```

---

### 10.4 `WS /ws/v1/positions` — 실시간 포지션 업데이트

#### `position.updated` — PnL / 가격 업데이트 (1초 간격)

```json
{
  "type": "position.updated",
  "data": {
    "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
    "coin": "BTC",
    "current_price": "67890.00000000",
    "unrealized_pnl": "+65.70000000",
    "unrealized_pnl_pct": "+3.25",
    "liquidation_price": "54250.00000000",
    "liquidation_distance_pct": "20.09",
    "tp_distance_pct": "1.93",
    "sl_distance_pct": "-1.56"
  },
  "timestamp": "2026-06-04T09:30:01Z"
}
```

#### `position.warning` — 청산가 근접 경보

```json
{
  "type": "position.warning",
  "data": {
    "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
    "coin": "BTC",
    "direction": "LONG",
    "warning_level": "critical",
    "liquidation_distance_pct": "4.87",
    "current_price": "64580.00000000",
    "liquidation_price": "61450.00000000",
    "message": "청산가까지 4.87% 남았습니다. 즉시 확인하세요."
  },
  "timestamp": "2026-06-04T10:15:00Z"
}
```

```
warning_level: "caution" (10% 이내) | "warning" (5% 이내) | "critical" (3% 이내)
```

#### `position.closed` — 포지션 종료

```json
{
  "type": "position.closed",
  "data": {
    "position_id": "pos_01JVBCN5XY9Z0A1BCD2EFG",
    "coin": "BTC",
    "direction": "LONG",
    "close_reason": "tp_hit",
    "realized_pnl": "+234.50000000",
    "realized_pnl_pct": "+3.82",
    "entry_price": "67452.00000000",
    "exit_price": "69212.00000000",
    "duration_seconds": 15780
  },
  "timestamp": "2026-06-04T12:53:00Z"
}
```

```
close_reason: "tp_hit" | "sl_hit" | "manual" | "liquidated" | "emergency"
```

---

### 10.5 `WS /ws/v1/dashboard` — 대시보드 종합 스트림

계좌 잔고, 포지션, 시그널 이벤트를 단일 WebSocket으로 수신.

#### `account.updated` — 계좌 잔고 업데이트 (5초 간격)

```json
{
  "type": "account.updated",
  "data": {
    "balance_usdt": "24157.85000000",
    "available_usdt": "21342.60000000",
    "total_unrealized_pnl": "+65.70000000",
    "today_pnl": "+432.10000000",
    "today_pnl_pct": "+1.82"
  },
  "timestamp": "2026-06-04T09:30:00Z"
}
```

#### `trading.halted` — 자동매매 중단 이벤트

```json
{
  "type": "trading.halted",
  "data": {
    "reason": "daily_loss_limit",
    "message": "일일 손실 한도(-$500)에 도달하여 자동매매가 중단되었습니다.",
    "auto_resume_at": null,
    "manual_action_required": true
  },
  "timestamp": "2026-06-04T15:30:00Z"
}
```

---

### 10.6 재연결 정책

```javascript
// 클라이언트 구현 참조
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000] // ms, 지수 백오프

let attemptCount = 0

function reconnect() {
  const delay = RECONNECT_DELAYS[Math.min(attemptCount, RECONNECT_DELAYS.length - 1)]
  setTimeout(() => {
    attemptCount++
    connect()
  }, delay)
}

// Heartbeat — 30초마다 ping 전송, 10초 내 pong 없으면 재연결
```

---

## 11. 에러 코드 전체 목록

### 인증 (AUTH)

| 코드 | HTTP | 설명 |
|------|------|------|
| AUTH_001 | 401 | 이메일 또는 비밀번호가 올바르지 않습니다 |
| AUTH_002 | 401 | 이메일 인증이 필요합니다 |
| AUTH_003 | 422 | 2FA 코드가 올바르지 않습니다 |
| AUTH_004 | 401 | 토큰이 만료되었습니다 |
| AUTH_005 | 403 | 접근 권한이 없습니다 |
| AUTH_006 | 409 | 이미 가입된 이메일입니다 |
| AUTH_007 | 400 | 인증 코드가 만료되었습니다 |
| AUTH_008 | 400 | 인증 코드가 올바르지 않습니다 |
| AUTH_009 | 403 | 로그인 시도 초과로 계정이 잠겼습니다 |
| AUTH_010 | 400 | 비밀번호 재설정 링크가 만료되었습니다 |

### Binance (BINANCE)

| 코드 | HTTP | 설명 |
|------|------|------|
| BINANCE_001 | 400 | API Key 연결에 실패했습니다 |
| BINANCE_002 | 400 | 출금 권한이 포함된 API Key는 등록할 수 없습니다 |
| BINANCE_003 | 400 | Futures 거래 권한이 없습니다 |
| BINANCE_004 | 400 | 잔고가 부족합니다 |
| BINANCE_005 | 409 | 이미 연결된 Binance 계좌가 있습니다 |
| BINANCE_006 | 400 | 오픈 포지션이 있어 작업을 완료할 수 없습니다 |
| BINANCE_007 | 503 | Binance API 연결이 일시적으로 불안정합니다 |

### 주문/포지션 (ORDER)

| 코드 | HTTP | 설명 |
|------|------|------|
| ORDER_001 | 400 | 일일 손실 한도에 도달했습니다 |
| ORDER_002 | 400 | 최대 포지션 수에 도달했습니다 |
| ORDER_003 | 400 | 손절가가 설정되지 않았습니다 |
| ORDER_004 | 400 | R:R 비율이 2.0 미만입니다 |
| ORDER_005 | 500 | 주문 실행에 실패했습니다 |
| ORDER_006 | 400 | DCA 추가 진입 조건을 충족하지 않습니다 |
| ORDER_007 | 400 | 주간 손실 한도에 도달했습니다 |
| ORDER_008 | 400 | 연속 손실 쿨다운 중입니다 |
| ORDER_009 | 400 | 레버리지 한도를 초과했습니다 |

### 시그널 (SIGNAL)

| 코드 | HTTP | 설명 |
|------|------|------|
| SIGNAL_001 | 400 | 시그널이 만료되었습니다 |
| SIGNAL_002 | 400 | 이미 실행된 시그널입니다 |
| SIGNAL_003 | 400 | 이미 무시한 시그널입니다 |
| SIGNAL_004 | 503 | AI 시그널 생성 서비스가 일시적으로 불안정합니다 |

### 구독/결제 (BILLING)

| 코드 | HTTP | 설명 |
|------|------|------|
| BILLING_001 | 403 | 이 기능은 Pro 이상 플랜에서 사용 가능합니다 |
| BILLING_002 | 400 | 결제에 실패했습니다 |
| BILLING_003 | 403 | 구독이 만료되었습니다 |
| BILLING_004 | 400 | 이미 해당 플랜을 구독 중입니다 |
| BILLING_005 | 400 | 다운그레이드는 다음 갱신일에 적용됩니다 |

### 사용자 (USER)

| 코드 | HTTP | 설명 |
|------|------|------|
| USER_001 | 400 | 오픈 포지션이 있어 작업을 완료할 수 없습니다 |
| USER_002 | 400 | 현재 비밀번호가 올바르지 않습니다 |

### 공통 (COMMON)

| 코드 | HTTP | 설명 |
|------|------|------|
| VALIDATION_001 | 422 | 입력 값이 올바르지 않습니다 |
| RATE_001 | 429 | 요청 한도를 초과했습니다 |
| NOT_FOUND_001 | 404 | 요청한 리소스를 찾을 수 없습니다 |
| SERVER_001 | 500 | 서버 내부 오류가 발생했습니다 |
| SERVER_002 | 503 | 서비스가 일시적으로 사용 불가합니다 |

---

## 부록 A. 공통 스키마 정의

### Signal

```typescript
interface Signal {
  id: string
  coin: "BTC" | "ETH" | string
  symbol: string                            // "BTCUSDT"
  direction: "LONG" | "SHORT" | "HOLD"
  confidence: number                        // 0.0 ~ 1.0
  entry_price: string                       // Decimal
  take_profit: string                       // Decimal
  stop_loss: string                         // Decimal
  leverage: number                          // 1 ~ 20
  rr_ratio: string                          // Decimal, 최소 "2.00"
  reasons: string[]                         // 3개 이상
  agent_scores?: {
    technical: number
    sentiment: number
    market_structure: number
  }
  status: "active" | "expired" | "executed" | "dismissed"
  is_executed: boolean
  executed_order_id?: string | null
  expires_at: string                        // ISO 8601
  created_at: string                        // ISO 8601
}
```

### Position

```typescript
interface Position {
  id: string
  symbol: string
  coin: string
  direction: "LONG" | "SHORT"
  status: "open" | "closed"
  quantity: string                          // Decimal
  remaining_quantity: string                // Decimal
  entry_price: string                       // Decimal
  current_price?: string                    // Decimal (open 상태 시)
  take_profit: string                       // Decimal (NOT NULL)
  stop_loss: string                         // Decimal (NOT NULL)
  leverage: number
  margin_used: string                       // Decimal
  unrealized_pnl?: string                   // Decimal
  unrealized_pnl_pct?: string
  realized_pnl?: string                     // Decimal (closed 상태 시)
  liquidation_price: string                 // Decimal
  liquidation_distance_pct?: string
  fee_paid: string                          // Decimal
  source: "auto" | "manual"
  signal_id?: string | null
  exchange_position_id: string
  opened_at: string                         // ISO 8601
  closed_at?: string | null                 // ISO 8601
}
```

### Order

```typescript
interface Order {
  id: string
  position_id?: string | null
  signal_id?: string | null
  symbol: string
  order_type: "market" | "limit" | "take_profit" | "stop_loss"
  side: "buy" | "sell"
  quantity: string                          // Decimal
  filled_quantity: string                   // Decimal
  entry_price?: string | null               // Decimal (limit 주문)
  filled_price?: string | null              // Decimal
  take_profit?: string | null               // Decimal
  stop_loss?: string | null                 // Decimal
  leverage?: number
  fee: string                               // Decimal
  status: "pending" | "filled" | "cancelled" | "rejected"
  source: "auto" | "manual"
  client_order_id: string
  exchange_order_id?: string | null
  created_at: string                        // ISO 8601
  executed_at?: string | null               // ISO 8601
}
```

---

## 부록 B. Pydantic 스키마 예시 (FastAPI)

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from decimal import Decimal
from uuid import UUID
from datetime import datetime

class SignalExecuteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    confirm: Literal[True]
    override_leverage: int | None = Field(None, ge=1, le=20)


class PositionCloseRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    type: Literal["market", "limit"]
    quantity_ratio: Decimal = Field(default=Decimal("1.0"), gt=0, le=1)
    price: Decimal | None = Field(None, gt=0)
    reason: str | None = Field(None, max_length=255)

    @model_validator(mode="after")
    def validate_price_for_limit(self) -> "PositionCloseRequest":
        if self.type == "limit" and self.price is None:
            raise ValueError("limit 주문은 price 필수")
        return self


class CloseAllRequest(BaseModel):
    confirm: Literal["CLOSE_ALL"]


class BinanceConnectRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    api_key: str = Field(min_length=10, max_length=100)
    api_secret: str = Field(min_length=10, max_length=100)
    label: str | None = Field(None, max_length=50)
    is_testnet: bool = False
```

---

## 부록 C. Zod 스키마 예시 (Next.js)

```typescript
import { z } from "zod"

export const signalSchema = z.object({
  id: z.string(),
  coin: z.string(),
  direction: z.enum(["LONG", "SHORT", "HOLD"]),
  confidence: z.number().min(0).max(1),
  entry_price: z.string(),
  take_profit: z.string(),
  stop_loss: z.string(),
  leverage: z.number().int().min(1).max(20),
  rr_ratio: z.string(),
  reasons: z.array(z.string()).min(3),
  status: z.enum(["active", "expired", "executed", "dismissed"]),
  expires_at: z.string().datetime(),
  created_at: z.string().datetime(),
})

export const positionSchema = z.object({
  id: z.string(),
  symbol: z.string(),
  coin: z.string(),
  direction: z.enum(["LONG", "SHORT"]),
  status: z.enum(["open", "closed"]),
  quantity: z.string(),
  entry_price: z.string(),
  take_profit: z.string(),
  stop_loss: z.string(),
  leverage: z.number(),
  margin_used: z.string(),
  unrealized_pnl: z.string().optional(),
  liquidation_price: z.string(),
  opened_at: z.string().datetime(),
})

export const apiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    detail: z.record(z.unknown()).optional(),
  }),
  meta: z.object({
    request_id: z.string(),
    timestamp: z.string().datetime(),
  }),
})

export type Signal = z.infer<typeof signalSchema>
export type Position = z.infer<typeof positionSchema>
export type ApiError = z.infer<typeof apiErrorSchema>
```
