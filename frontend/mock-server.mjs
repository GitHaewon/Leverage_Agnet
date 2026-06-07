/**
 * Mock API Server — 포트 8000
 * 실제 FastAPI 백엔드 없이 프론트엔드 전체 플로우를 데모할 수 있는 stub 서버.
 *
 * 실행: node mock-server.mjs
 *
 * 데모 계정:
 *   이메일:    demo@trading.com
 *   비밀번호:  아무거나 (Demo1234! 권장)
 */

import http from "node:http"
import { createHash } from "node:crypto"

// ── CORS ──────────────────────────────────────────────────────────────────────

const CORS = {
  "Access-Control-Allow-Origin": "http://localhost:3000",
  "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Allow-Credentials": "true",
}

function reply(res, status, data) {
  res.writeHead(status, { ...CORS, "Content-Type": "application/json" })
  res.end(JSON.stringify(data))
}

function ok(res, data) { reply(res, 200, { data }) }
function created(res, data) { reply(res, 201, { data }) }
function notFound(res) { reply(res, 404, { error: { code: "NOT_FOUND", message: "Not found" } }) }
function unauthorized(res) { reply(res, 401, { error: { code: "AUTH_001", message: "인증이 필요합니다." } }) }

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_TOKEN = "mock.eyJhbGciOiJIUzI1NiJ9.demo_user_token"

const MOCK_USER = {
  id: "550e8400-e29b-41d4-a716-446655440000",
  email: "demo@trading.com",
  display_name: "데모 트레이더",
  plan: "pro",
  risk_profile: "moderate",
  is_2fa_enabled: false,
  is_onboarding_completed: true,
  last_login_at: new Date().toISOString(),
}

const MOCK_POSITIONS = [
  {
    id: "pos_BTC_001",
    symbol: "BTCUSDT",
    coin: "BTC",
    direction: "LONG",
    status: "open",
    quantity: "0.01500000",
    entry_price: "67452.00000000",
    current_price: "68120.00000000",
    take_profit: "69200.00000000",
    stop_loss: "66800.00000000",
    leverage: 5,
    margin_used: "202.36000000",
    unrealized_pnl: "+100.20000000",
    unrealized_pnl_pct: "+3.12",
    liquidation_price: "54250.00000000",
    liquidation_distance_pct: "20.36",
    tp_distance_pct: "1.58",
    sl_distance_pct: "-1.94",
    duration_seconds: 7200,
    source: "auto",
    signal_id: "sig_001",
    opened_at: new Date(Date.now() - 7200_000).toISOString(),
  },
  {
    id: "pos_ETH_001",
    symbol: "ETHUSDT",
    coin: "ETH",
    direction: "SHORT",
    status: "open",
    quantity: "0.50000000",
    entry_price: "3521.00000000",
    current_price: "3498.00000000",
    take_profit: "3420.00000000",
    stop_loss: "3580.00000000",
    leverage: 3,
    margin_used: "586.83000000",
    unrealized_pnl: "+11.50000000",
    unrealized_pnl_pct: "+0.65",
    liquidation_price: "4100.00000000",
    liquidation_distance_pct: "17.21",
    tp_distance_pct: "2.24",
    sl_distance_pct: "-2.34",
    duration_seconds: 3600,
    source: "auto",
    signal_id: "sig_002",
    opened_at: new Date(Date.now() - 3600_000).toISOString(),
  },
]

const MOCK_ORDERS = [
  {
    id: "ord_001", position_id: "pos_BTC_001", signal_id: "sig_001",
    symbol: "BTCUSDT", coin: "BTC", order_type: "market", side: "buy",
    quantity: "0.01500000", filled_quantity: "0.01500000",
    filled_price: "67452.00000000", take_profit: "69200.00000000",
    stop_loss: "66800.00000000", leverage: 5, fee: "2.02",
    status: "filled", source: "auto", client_order_id: "tc_001",
    exchange_order_id: "987654321",
    created_at: new Date(Date.now() - 7200_000).toISOString(),
    executed_at: new Date(Date.now() - 7199_000).toISOString(),
  },
  {
    id: "ord_002", position_id: "pos_ETH_001", signal_id: "sig_002",
    symbol: "ETHUSDT", coin: "ETH", order_type: "market", side: "sell",
    quantity: "0.50000000", filled_quantity: "0.50000000",
    filled_price: "3521.00000000", take_profit: "3420.00000000",
    stop_loss: "3580.00000000", leverage: 3, fee: "1.76",
    status: "filled", source: "auto", client_order_id: "tc_002",
    exchange_order_id: "987654322",
    created_at: new Date(Date.now() - 3600_000).toISOString(),
    executed_at: new Date(Date.now() - 3599_000).toISOString(),
  },
  {
    id: "ord_003", position_id: "pos_prev_001", signal_id: null,
    symbol: "BTCUSDT", coin: "BTC", order_type: "market", side: "buy",
    quantity: "0.01000000", filled_quantity: "0.01000000",
    filled_price: "65200.00000000", take_profit: "67000.00000000",
    stop_loss: "64500.00000000", leverage: 5, fee: "1.63",
    status: "filled", source: "manual", client_order_id: "tc_003",
    exchange_order_id: "987654323",
    created_at: new Date(Date.now() - 86400_000).toISOString(),
    executed_at: new Date(Date.now() - 86399_000).toISOString(),
  },
  {
    id: "ord_004", position_id: null, signal_id: null,
    symbol: "ETHUSDT", coin: "ETH", order_type: "limit", side: "buy",
    quantity: "0.30000000", filled_quantity: "0.00000000",
    entry_price: "3300.00000000", filled_price: null,
    take_profit: null, stop_loss: null, leverage: null, fee: "0.00",
    status: "cancelled", source: "manual", client_order_id: "tc_004",
    exchange_order_id: null,
    created_at: new Date(Date.now() - 43200_000).toISOString(),
    executed_at: null,
  },
  {
    id: "ord_005", position_id: "pos_prev_002", signal_id: "sig_prev_001",
    symbol: "BTCUSDT", coin: "BTC", order_type: "market", side: "sell",
    quantity: "0.01000000", filled_quantity: "0.01000000",
    filled_price: "67120.00000000", take_profit: null, stop_loss: null,
    leverage: 5, fee: "1.68",
    status: "filled", source: "auto", client_order_id: "tc_005",
    exchange_order_id: "987654325",
    created_at: new Date(Date.now() - 172800_000).toISOString(),
    executed_at: new Date(Date.now() - 172799_000).toISOString(),
  },
]

function buildDailyPnl() {
  const days = []
  let cumulative = 0
  for (let i = 29; i >= 0; i--) {
    const date = new Date(Date.now() - i * 86400_000)
    const dateStr = date.toISOString().split("T")[0]
    const pnl = (Math.random() * 400 - 100).toFixed(2)
    cumulative += parseFloat(pnl)
    days.push({
      date: dateStr,
      pnl: pnl,
      pnl_pct: (parseFloat(pnl) / 24000 * 100).toFixed(2),
      cumulative_pnl: cumulative.toFixed(2),
      trades: Math.floor(Math.random() * 5),
    })
  }
  return days
}

const DAILY_PNL = buildDailyPnl()
const TOTAL_PNL = DAILY_PNL[DAILY_PNL.length - 1]?.cumulative_pnl ?? "0"

const MOCK_STATS = {
  period: "30d",
  summary: {
    total_pnl: TOTAL_PNL,
    total_pnl_pct: (parseFloat(TOTAL_PNL) / 24000 * 100).toFixed(2),
    win_rate: "0.67",
    total_trades: 42,
    winning_trades: 28,
    losing_trades: 14,
    avg_win_pct: "3.21",
    avg_loss_pct: "-1.08",
    max_drawdown: "-4.23",
    sharpe_ratio: "1.87",
    profit_factor: "2.32",
  },
  daily_pnl: DAILY_PNL,
  best_trade: {
    coin: "BTC", direction: "LONG",
    pnl: "543.21", pnl_pct: "8.76",
    closed_at: new Date(Date.now() - 10 * 86400_000).toISOString(),
  },
  worst_trade: {
    coin: "ETH", direction: "SHORT",
    pnl: "-234.56", pnl_pct: "-3.21",
    closed_at: new Date(Date.now() - 15 * 86400_000).toISOString(),
  },
}

const MOCK_BALANCE = {
  total_balance: "24157.85000000",
  available_balance: "23368.66000000",
  total_unrealized_pnl: "+111.70000000",
  today_pnl: "+432.10000000",
  today_pnl_pct: "+1.82",
}

// ── Request handling ──────────────────────────────────────────────────────────

function parseBody(req) {
  return new Promise((resolve) => {
    let body = ""
    req.on("data", (chunk) => (body += chunk))
    req.on("end", () => {
      try { resolve(JSON.parse(body)) } catch { resolve({}) }
    })
  })
}

function isAuthorized(req) {
  const auth = req.headers["authorization"] ?? ""
  return auth.startsWith("Bearer ")
}

const server = http.createServer(async (req, res) => {
  const urlObj = new URL(req.url, "http://localhost:8000")
  const path = urlObj.pathname
  const method = req.method

  // Preflight
  if (method === "OPTIONS") {
    res.writeHead(204, CORS)
    res.end()
    return
  }

  // ── Auth endpoints ──────────────────────────────────────────────────────────

  if (method === "POST" && path === "/api/v1/auth/login") {
    const body = await parseBody(req)
    if (!body.email || !body.password) {
      return reply(res, 422, { error: { code: "VALIDATION_001", message: "이메일과 비밀번호를 입력해주세요." } })
    }
    return ok(res, {
      access_token: MOCK_TOKEN,
      token_type: "bearer",
      expires_in: 900,
      user: { ...MOCK_USER, email: body.email },
    })
  }

  if (method === "POST" && path === "/api/v1/auth/refresh") {
    return ok(res, { access_token: MOCK_TOKEN, token_type: "bearer", expires_in: 900 })
  }

  if (method === "POST" && path === "/api/v1/auth/logout") {
    return ok(res, { message: "로그아웃 되었습니다." })
  }

  // ── Protected routes — require Authorization header ─────────────────────────

  if (!isAuthorized(req)) return unauthorized(res)

  // ── Positions ───────────────────────────────────────────────────────────────

  if (method === "GET" && path === "/api/v1/positions") {
    return ok(res, {
      positions: MOCK_POSITIONS,
      summary: {
        total_positions: MOCK_POSITIONS.length,
        total_unrealized_pnl: "+111.70",
        total_margin_used: "789.19",
      },
    })
  }

  if (method === "POST" && path.match(/^\/api\/v1\/positions\/[^/]+\/close$/)) {
    const posId = path.split("/")[4]
    const idx = MOCK_POSITIONS.findIndex((p) => p.id === posId)
    if (idx !== -1) MOCK_POSITIONS.splice(idx, 1)
    return ok(res, { message: "포지션이 청산되었습니다.", position_id: posId })
  }

  // ── Orders ──────────────────────────────────────────────────────────────────

  if (method === "GET" && path === "/api/v1/orders") {
    const status = urlObj.searchParams.get("status") ?? "all"
    const coin = urlObj.searchParams.get("coin") ?? "all"
    const limit = parseInt(urlObj.searchParams.get("limit") ?? "20")
    const offset = parseInt(urlObj.searchParams.get("offset") ?? "0")

    let items = MOCK_ORDERS
    if (status !== "all") items = items.filter((o) => o.status === status)
    if (coin !== "all") items = items.filter((o) => o.coin === coin)

    const total = items.length
    const page = items.slice(offset, offset + limit)
    return ok(res, {
      items: page,
      total,
      limit,
      offset,
      has_next: offset + limit < total,
    })
  }

  // ── Users / stats ───────────────────────────────────────────────────────────

  if (method === "GET" && path === "/api/v1/users/me") {
    return ok(res, MOCK_USER)
  }

  if (method === "GET" && path === "/api/v1/users/me/stats") {
    return ok(res, MOCK_STATS)
  }

  // ── Binance balance ─────────────────────────────────────────────────────────

  if (method === "GET" && path === "/api/v1/binance/balance") {
    return ok(res, MOCK_BALANCE)
  }

  // ── Health ──────────────────────────────────────────────────────────────────

  if (method === "GET" && (path === "/api/v1/health" || path === "/health")) {
    return ok(res, { status: "ok", service: "mock-api" })
  }

  notFound(res)
})

server.listen(8000, "localhost", () => {
  console.log("")
  console.log("  ⚡ Mock API Server  →  http://localhost:8000")
  console.log("")
  console.log("  데모 계정:")
  console.log("    이메일:   demo@trading.com")
  console.log("    비밀번호: Demo1234!")
  console.log("")
  console.log("  엔드포인트:")
  console.log("    POST  /api/v1/auth/login")
  console.log("    POST  /api/v1/auth/refresh")
  console.log("    GET   /api/v1/positions")
  console.log("    GET   /api/v1/orders")
  console.log("    GET   /api/v1/users/me/stats")
  console.log("    GET   /api/v1/binance/balance")
  console.log("")
})
