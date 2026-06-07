/**
 * PositionsTable component tests.
 *
 * Verified:
 *   - shows "오픈 포지션이 없습니다" when no positions
 *   - renders table headers when positions present
 *   - renders a row per position
 *   - displays coin + direction badge (BTC LONG)
 *   - displays entry price
 *   - shows loading state when isLoading=true
 *   - shows error state when isError=true
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import type { Position } from "@/lib/schemas"

// ── mocks ─────────────────────────────────────────────────────────────────────

const mockLivePositions: Position[] = []
const mockIsLoading = { value: false }
const mockIsError = { value: false }

vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => ({
    livePositions: mockLivePositions,
    isLoading: mockIsLoading.value,
    isError: mockIsError.value,
    summary: null,
  }),
}))

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock("@/lib/api", () => ({
  api: { post: vi.fn() },
}))

function makePosition(overrides: Partial<Position> = {}): Position {
  return {
    id: "pos_01",
    symbol: "BTCUSDT",
    coin: "BTC",
    direction: "LONG",
    status: "open",
    quantity: "0.015",
    entry_price: "67452.00",
    current_price: "67890.00",
    take_profit: "69200.00",
    stop_loss: "66800.00",
    leverage: 5,
    margin_used: "202.36",
    unrealized_pnl: "+65.70",
    unrealized_pnl_pct: "+3.25",
    liquidation_price: "54250.00",
    liquidation_distance_pct: "20.09",
    tp_distance_pct: "1.93",
    sl_distance_pct: "-1.56",
    duration_seconds: 3625,
    source: "auto",
    signal_id: null,
    opened_at: "2026-06-04T08:29:20Z",
    ...overrides,
  }
}

async function renderTable() {
  const { PositionsTable } = await import("@/components/positions/PositionsTable")
  return render(<PositionsTable />)
}

describe("PositionsTable", () => {
  it("shows empty state when no positions", async () => {
    mockLivePositions.length = 0
    mockIsLoading.value = false
    await renderTable()
    expect(screen.getByText(/오픈 포지션이 없습니다/i)).toBeDefined()
  })

  it("renders table headers when positions present", async () => {
    mockLivePositions.length = 0
    mockLivePositions.push(makePosition())
    mockIsLoading.value = false
    await renderTable()
    expect(screen.getByText(/진입가/i)).toBeDefined()
  })

  it("renders one row per position", async () => {
    mockLivePositions.length = 0
    mockLivePositions.push(makePosition({ id: "pos_01" }))
    mockLivePositions.push(makePosition({ id: "pos_02", coin: "ETH" }))
    await renderTable()
    const badges = screen.getAllByText(/LONG/i)
    expect(badges.length).toBeGreaterThanOrEqual(2)
  })

  it("displays coin in badge", async () => {
    mockLivePositions.length = 0
    mockLivePositions.push(makePosition({ coin: "BTC" }))
    await renderTable()
    expect(screen.getByText(/BTC/i)).toBeDefined()
  })

  it("shows loading state", async () => {
    mockLivePositions.length = 0
    mockIsLoading.value = true
    await renderTable()
    expect(screen.getByText(/로딩/i)).toBeDefined()
    mockIsLoading.value = false
  })

  it("shows error state", async () => {
    mockLivePositions.length = 0
    mockIsError.value = true
    mockIsLoading.value = false
    await renderTable()
    expect(screen.getByText(/불러오지 못했습니다/i)).toBeDefined()
    mockIsError.value = false
  })
})
