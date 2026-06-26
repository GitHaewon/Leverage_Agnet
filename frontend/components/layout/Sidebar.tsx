"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  LayoutDashboard,
  TrendingUp,
  History,
  ShieldAlert,
  LogOut,
  Zap,
  FlaskConical,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth"
import { api } from "@/lib/api"

const NAV_ITEMS = [
  { href: "/dashboard", label: "대시보드", icon: LayoutDashboard },
  { href: "/shadow-trades", label: "Shadow Trading", icon: FlaskConical },
  { href: "/positions", label: "포지션", icon: TrendingUp },
  { href: "/trades", label: "거래 내역", icon: History },
  { href: "/risk", label: "리스크", icon: ShieldAlert },
]

export function Sidebar() {
  const pathname = usePathname()
  const logout = useAuthStore((s) => s.logout)

  const handleLogout = async () => {
    try {
      await api.post("/auth/logout")
    } finally {
      logout()
      window.location.href = "/login"
    }
  }

  return (
    <aside className="flex h-full w-60 flex-col border-r border-white/[0.06] bg-card/60 backdrop-blur-sm">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-white/[0.06]">
        <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-primary/15 border border-primary/20">
          <Zap className="h-3.5 w-3.5 text-primary" />
        </div>
        <span className="font-semibold text-sm text-foreground tracking-tight">
          Trading Copilot
        </span>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 px-3 py-4">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href || pathname.startsWith(`${href}/`)
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200 relative",
                isActive
                  ? "bg-primary/10 text-primary before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:h-4 before:w-0.5 before:rounded-r-full before:bg-primary"
                  : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4 flex-shrink-0" />
              {label}
            </Link>
          )
        })}
      </nav>

      {/* Logout */}
      <div className="border-t border-white/[0.06] px-3 py-4">
        <button
          onClick={handleLogout}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground/70 transition-all duration-200 hover:bg-rose-500/10 hover:text-rose-400"
        >
          <LogOut className="h-4 w-4 flex-shrink-0" />
          로그아웃
        </button>
      </div>
    </aside>
  )
}
