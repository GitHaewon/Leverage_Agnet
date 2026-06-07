"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { z } from "zod"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuthStore } from "@/store/auth"
import { api } from "@/lib/api"
import { loginResponseSchema } from "@/lib/schemas"
import { Zap } from "lucide-react"

const loginSchema = z.object({
  email: z.string().email("유효한 이메일을 입력해주세요."),
  password: z.string().min(8, "비밀번호는 8자 이상이어야 합니다."),
  totp_code: z.string().optional(),
})

type LoginForm = z.infer<typeof loginSchema>
type FieldErrors = Partial<Record<keyof LoginForm, string>>

export default function LoginPage() {
  const router = useRouter()
  const setAuth = useAuthStore((s) => s.setAuth)

  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [totpCode, setTotpCode] = useState("")
  const [requires2FA, setRequires2FA] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [serverError, setServerError] = useState("")
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setServerError("")
    setFieldErrors({})

    const parsed = loginSchema.safeParse({
      email,
      password,
      totp_code: totpCode || undefined,
    })

    if (!parsed.success) {
      const errors: FieldErrors = {}
      for (const issue of parsed.error.issues) {
        const field = issue.path[0] as keyof LoginForm
        errors[field] = issue.message
      }
      setFieldErrors(errors)
      return
    }

    setIsLoading(true)
    try {
      const { data: raw } = await api.post<unknown>("/auth/login", {
        email: parsed.data.email,
        password: parsed.data.password,
        ...(parsed.data.totp_code ? { totp_code: parsed.data.totp_code } : {}),
      })
      const result = loginResponseSchema.parse(raw)
      setAuth(result.data.access_token, result.data.user)
      router.push("/dashboard")
    } catch (err: unknown) {
      if (
        err &&
        typeof err === "object" &&
        "response" in err
      ) {
        const axiosErr = err as {
          response?: { status?: number; data?: { error?: { code?: string; message?: string } } }
        }
        const code = axiosErr.response?.data?.error?.code
        const msg = axiosErr.response?.data?.error?.message ?? "로그인에 실패했습니다."
        if (axiosErr.response?.status === 422 && code === "AUTH_003") {
          setRequires2FA(true)
          setServerError("2FA 코드를 입력해주세요.")
        } else {
          setServerError(msg)
        }
      } else {
        setServerError("네트워크 오류가 발생했습니다.")
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-1 text-center">
          <div className="flex justify-center mb-2">
            <Zap className="h-8 w-8 text-primary" />
          </div>
          <CardTitle className="text-2xl font-bold">Trading Copilot</CardTitle>
          <p className="text-sm text-muted-foreground">계정에 로그인하세요</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="email">이메일</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                aria-describedby={fieldErrors.email ? "email-error" : undefined}
              />
              {fieldErrors.email && (
                <p id="email-error" className="text-xs text-destructive">
                  {fieldErrors.email}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <Label htmlFor="password">비밀번호</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-describedby={fieldErrors.password ? "password-error" : undefined}
              />
              {fieldErrors.password && (
                <p id="password-error" className="text-xs text-destructive">
                  {fieldErrors.password}
                </p>
              )}
            </div>

            {requires2FA && (
              <div className="space-y-1">
                <Label htmlFor="totp">2FA 코드</Label>
                <Input
                  id="totp"
                  type="text"
                  placeholder="6자리 코드"
                  inputMode="numeric"
                  maxLength={6}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value)}
                />
              </div>
            )}

            {serverError && (
              <p
                role="alert"
                className="text-sm text-destructive text-center"
              >
                {serverError}
              </p>
            )}

            <Button
              type="submit"
              className="w-full"
              disabled={isLoading}
            >
              {isLoading ? "로그인 중..." : "로그인"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
