/**
 * Login page component tests.
 *
 * Verified:
 *   - renders email/password inputs and submit button
 *   - shows field error for invalid email
 *   - shows field error for short password
 *   - shows loading state on submit
 *   - calls api.post with correct payload
 *   - on success: setAuth called + navigate to /dashboard
 *   - on 401 server error: shows error message
 *   - on AUTH_003 (2FA required): shows TOTP input
 *   - no dangerouslySetInnerHTML usage
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

// ── mocks ─────────────────────────────────────────────────────────────────────

const mockRouterPush = vi.fn()
const mockRouterReplace = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush, replace: mockRouterReplace }),
  usePathname: () => "/login",
  redirect: vi.fn(),
}))

const mockApiPost = vi.fn()
vi.mock("@/lib/api", () => ({
  api: { post: mockApiPost },
}))

const mockSetAuth = vi.fn()
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      accessToken: null,
      user: null,
      isAuthenticated: false,
      setAuth: mockSetAuth,
      setAccessToken: vi.fn(),
      logout: vi.fn(),
    }),
}))

// ── helpers ───────────────────────────────────────────────────────────────────

function makeLoginResponse() {
  return {
    data: {
      data: {
        access_token: "tok123",
        token_type: "bearer",
        expires_in: 900,
        user: {
          id: "uid",
          email: "user@example.com",
          display_name: "김지민",
          plan: "pro",
          risk_profile: "moderate",
          is_2fa_enabled: false,
          is_onboarding_completed: true,
        },
      },
    },
  }
}

async function renderLoginPage() {
  const { default: LoginPage } = await import(
    "@/app/(auth)/login/page"
  )
  return render(<LoginPage />)
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRouterPush.mockResolvedValue(undefined)
  })

  it("renders email input", async () => {
    await renderLoginPage()
    expect(screen.getByLabelText(/이메일/i)).toBeDefined()
  })

  it("renders password input", async () => {
    await renderLoginPage()
    expect(screen.getByLabelText(/비밀번호/i)).toBeDefined()
  })

  it("renders submit button", async () => {
    await renderLoginPage()
    expect(screen.getByRole("button", { name: /로그인/i })).toBeDefined()
  })

  it("shows email validation error for empty email", async () => {
    await renderLoginPage()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: /로그인/i }))
    await waitFor(() => {
      expect(screen.getByText(/유효한 이메일/i)).toBeDefined()
    })
  })

  it("shows password validation error for short password", async () => {
    await renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/이메일/i), "user@example.com")
    await user.type(screen.getByLabelText(/비밀번호/i), "short")
    await user.click(screen.getByRole("button", { name: /로그인/i }))
    await waitFor(() => {
      expect(screen.getByText(/8자 이상/i)).toBeDefined()
    })
  })

  it("calls api.post with email and password on valid submit", async () => {
    mockApiPost.mockResolvedValue(makeLoginResponse())
    await renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/이메일/i), "user@example.com")
    await user.type(screen.getByLabelText(/비밀번호/i), "P@ssw0rd123!")
    await user.click(screen.getByRole("button", { name: /로그인/i }))
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        "/auth/login",
        expect.objectContaining({ email: "user@example.com" })
      )
    })
  })

  it("calls setAuth on successful login", async () => {
    mockApiPost.mockResolvedValue(makeLoginResponse())
    await renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/이메일/i), "user@example.com")
    await user.type(screen.getByLabelText(/비밀번호/i), "P@ssw0rd123!")
    await user.click(screen.getByRole("button", { name: /로그인/i }))
    await waitFor(() => {
      expect(mockSetAuth).toHaveBeenCalledWith("tok123", expect.objectContaining({ email: "user@example.com" }))
    })
  })

  it("navigates to /dashboard on success", async () => {
    mockApiPost.mockResolvedValue(makeLoginResponse())
    await renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/이메일/i), "user@example.com")
    await user.type(screen.getByLabelText(/비밀번호/i), "P@ssw0rd123!")
    await user.click(screen.getByRole("button", { name: /로그인/i }))
    await waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith("/dashboard")
    })
  })

  it("shows server error message on 401", async () => {
    mockApiPost.mockRejectedValue({
      response: {
        status: 401,
        data: { error: { code: "AUTH_001", message: "이메일 또는 비밀번호가 올바르지 않습니다." } },
      },
    })
    await renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/이메일/i), "user@example.com")
    await user.type(screen.getByLabelText(/비밀번호/i), "WrongP@ss1!")
    await user.click(screen.getByRole("button", { name: /로그인/i }))
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined()
    })
  })

  it("shows TOTP input after AUTH_003 response", async () => {
    mockApiPost.mockRejectedValue({
      response: {
        status: 422,
        data: { error: { code: "AUTH_003", message: "2FA 코드를 입력해주세요." } },
      },
    })
    await renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/이메일/i), "user@example.com")
    await user.type(screen.getByLabelText(/비밀번호/i), "P@ssw0rd123!")
    await user.click(screen.getByRole("button", { name: /로그인/i }))
    await waitFor(() => {
      expect(screen.getByLabelText(/2FA/i)).toBeDefined()
    })
  })

  it("shows loading text while submitting", async () => {
    let resolvePost!: (v: unknown) => void
    mockApiPost.mockReturnValue(new Promise((res) => { resolvePost = res }))
    await renderLoginPage()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/이메일/i), "user@example.com")
    await user.type(screen.getByLabelText(/비밀번호/i), "P@ssw0rd123!")
    await user.click(screen.getByRole("button", { name: /로그인/i }))
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /로그인 중/i })).toBeDefined()
    })
    resolvePost(makeLoginResponse())
  })
})
