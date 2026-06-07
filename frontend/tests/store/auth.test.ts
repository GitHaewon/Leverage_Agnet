/**
 * Zustand auth store tests.
 *
 * Verified:
 *   - initial state: null tokens, not authenticated
 *   - setAuth: stores token + user, sets isAuthenticated=true
 *   - setAccessToken: updates token, keeps user
 *   - logout: clears all state
 *   - isAuthenticated reflects token presence
 */

import { describe, it, expect, beforeEach } from "vitest"
import { useAuthStore } from "@/store/auth"

const TEST_USER = {
  id: "550e8400-e29b-41d4-a716-446655440000",
  email: "user@example.com",
  display_name: "김지민",
  plan: "pro" as const,
  risk_profile: "moderate",
  is_2fa_enabled: false,
  is_onboarding_completed: true,
}

function getStore() {
  return useAuthStore.getState()
}

function resetStore() {
  useAuthStore.setState({
    accessToken: null,
    user: null,
    isAuthenticated: false,
  })
}

describe("useAuthStore", () => {
  beforeEach(() => {
    resetStore()
  })

  it("initial state has null accessToken", () => {
    expect(getStore().accessToken).toBeNull()
  })

  it("initial state has null user", () => {
    expect(getStore().user).toBeNull()
  })

  it("initial isAuthenticated is false", () => {
    expect(getStore().isAuthenticated).toBe(false)
  })

  it("setAuth stores token and user", () => {
    getStore().setAuth("tok123", TEST_USER)
    expect(getStore().accessToken).toBe("tok123")
    expect(getStore().user?.email).toBe("user@example.com")
  })

  it("setAuth sets isAuthenticated to true", () => {
    getStore().setAuth("tok123", TEST_USER)
    expect(getStore().isAuthenticated).toBe(true)
  })

  it("setAccessToken updates only token", () => {
    getStore().setAuth("old_tok", TEST_USER)
    getStore().setAccessToken("new_tok")
    expect(getStore().accessToken).toBe("new_tok")
    expect(getStore().user?.email).toBe("user@example.com")
  })

  it("setAccessToken sets isAuthenticated to true", () => {
    getStore().setAccessToken("tok")
    expect(getStore().isAuthenticated).toBe(true)
  })

  it("logout clears accessToken", () => {
    getStore().setAuth("tok123", TEST_USER)
    getStore().logout()
    expect(getStore().accessToken).toBeNull()
  })

  it("logout clears user", () => {
    getStore().setAuth("tok123", TEST_USER)
    getStore().logout()
    expect(getStore().user).toBeNull()
  })

  it("logout sets isAuthenticated to false", () => {
    getStore().setAuth("tok123", TEST_USER)
    getStore().logout()
    expect(getStore().isAuthenticated).toBe(false)
  })

  it("user plan preserved through setAuth", () => {
    getStore().setAuth("tok", { ...TEST_USER, plan: "elite" })
    expect(getStore().user?.plan).toBe("elite")
  })
})
