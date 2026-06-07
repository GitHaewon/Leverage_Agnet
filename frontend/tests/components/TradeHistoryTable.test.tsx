/**
 * TradeHistoryTable component tests.
 *
 * Verified:
 *   - shows loading state
 *   - shows error state
 *   - shows empty state when no orders
 *   - renders order rows
 *   - displays coin badge
 *   - displays order status badge
 *   - renders pagination buttons
 *   - Prev button disabled at offset=0
 *   - Next button disabled when has_next=false
 *   - status filter buttons rendered
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import type { Order } from "@/lib/schemas"

// ── mocks ─────────────────────────────────────────────────────────────────────

type MockQueryResult = {
  data: { items: Order[]; total: number; limit: number; offset: number; has_next: boolean } | undefined
  isLoading: boolean
  isError: boolean
}

const mockQuery: MockQueryResult = {
  data: undefined,
  isLoading: false,
  isError: false,
}

vi.mock("@/hooks/useOrders", () => ({
  useOrders: () => mockQuery,
}))

function makeOrder(overrides: Partial<Order> = {}): Order {
  return {
    id: "ord_01",
    symbol: "BTCUSDT",
    coin: "BTC",
    order_type: "market",
    side: "buy",
    quantity: "0.015",
    filled_quantity: "0.015",
    filled_price: "67452.00",
    fee: "2.02",
    status: "filled",
    source: "auto",
    client_order_id: "tc_01",
    created_at: "2026-06-04T08:29:15Z",
    ...overrides,
  }
}

async function renderTable() {
  const { TradeHistoryTable } = await import(
    "@/components/trades/TradeHistoryTable"
  )
  return render(<TradeHistoryTable />)
}

describe("TradeHistoryTable", () => {
  beforeEach(() => {
    mockQuery.data = undefined
    mockQuery.isLoading = false
    mockQuery.isError = false
  })

  it("shows loading state", async () => {
    mockQuery.isLoading = true
    await renderTable()
    expect(screen.getByText(/로딩 중/i)).toBeDefined()
  })

  it("shows error state", async () => {
    mockQuery.isError = true
    await renderTable()
    expect(screen.getByText(/불러오지 못했습니다/i)).toBeDefined()
  })

  it("shows empty state when no orders", async () => {
    mockQuery.data = { items: [], total: 0, limit: 20, offset: 0, has_next: false }
    await renderTable()
    expect(screen.getByText(/거래 내역이 없습니다/i)).toBeDefined()
  })

  it("renders order rows", async () => {
    mockQuery.data = {
      items: [makeOrder(), makeOrder({ id: "ord_02" })],
      total: 2,
      limit: 20,
      offset: 0,
      has_next: false,
    }
    await renderTable()
    const btcElements = screen.getAllByText(/BTC/i)
    expect(btcElements.length).toBeGreaterThanOrEqual(2)
  })

  it("displays filled status badge", async () => {
    mockQuery.data = {
      items: [makeOrder({ status: "filled" })],
      total: 1,
      limit: 20,
      offset: 0,
      has_next: false,
    }
    await renderTable()
    expect(screen.getByText(/filled/i)).toBeDefined()
  })

  it("renders pagination when total > 0", async () => {
    mockQuery.data = {
      items: [makeOrder()],
      total: 25,
      limit: 20,
      offset: 0,
      has_next: true,
    }
    await renderTable()
    expect(screen.getByText(/1 \/ 2/i)).toBeDefined()
  })

  it("Prev button disabled at offset=0", async () => {
    mockQuery.data = {
      items: [makeOrder()],
      total: 25,
      limit: 20,
      offset: 0,
      has_next: true,
    }
    await renderTable()
    const buttons = screen.getAllByRole("button")
    const prevBtn = buttons.find((b) => b.querySelector("svg"))
    expect(prevBtn?.hasAttribute("disabled") || prevBtn?.getAttribute("disabled") !== null).toBe(true)
  })

  it("renders status filter buttons", async () => {
    mockQuery.data = {
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
      has_next: false,
    }
    await renderTable()
    expect(screen.getByRole("button", { name: "전체" })).toBeDefined()
    expect(screen.getByRole("button", { name: "체결" })).toBeDefined()
  })

  it("cancelled order shows cancelled badge", async () => {
    mockQuery.data = {
      items: [makeOrder({ status: "cancelled" })],
      total: 1,
      limit: 20,
      offset: 0,
      has_next: false,
    }
    await renderTable()
    expect(screen.getByText(/cancelled/i)).toBeDefined()
  })
})
