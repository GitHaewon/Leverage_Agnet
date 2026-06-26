"use client"

import { useAuthStore } from "@/store/auth"
import { usePositionsStore } from "@/store/positions"
import { cn } from "@/lib/utils"

interface HeaderProps {
  wsConnected?: boolean
}

const PLAN_LABELS: Record<string, string> = {
  free: "Free",
  pro: "Pro",
  elite: "Elite",
}

const PLAN_STYLES: Record<string, string> = {
  free: "bg-white/[0.06] text-muted-foreground border-white/[0.08]",
  pro: "bg-blue-500/10 text-blue-400 border-blue-500/25",
  elite: "bg-amber-500/10 text-amber-400 border-amber-500/25",
}

export function Header({ wsConnected = false }: HeaderProps) {
  const user = useAuthStore((s) => s.user)
  const liveAccount = usePositionsStore((s) => s.liveAccount)

  const todayPnl = liveAccount?.today_pnl
  const todayPnlPct = liveAccount?.today_pnl_pct
  const isPositive = todayPnl ? parseFloat(todayPnl) >= 0 : null

  return (
    <header className="flex h-14 items-center justify-between border-b border-white/[0.06] bg-card/50 backdrop-blur-sm px-6">
      <div className="flex items-center gap-4">
        {liveAccount && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-xs text-muted-foreground/60">잔고</span>
            <span className="font-semibold tabular-nums text-foreground">
              ${parseFloat(liveAccount.balance_usdt).toLocaleString("en-US", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </span>
            {todayPnl !== undefined && isPositive !== null && (
              <span
                className={cn(
                  "text-xs font-medium tabular-nums",
                  isPositive ? "text-emerald-400" : "text-rose-400"
                )}
              >
                {isPositive ? "+" : ""}
                {todayPnlPct}% 오늘
              </span>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center gap-4">
        {/* WebSocket live indicator */}
        <div className="flex items-center gap-1.5 text-xs">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full flex-shrink-0",
              wsConnected
                ? "bg-emerald-400 animate-pulse-dot"
                : "bg-muted-foreground/30"
            )}
          />
          <span className={wsConnected ? "text-emerald-400" : "text-muted-foreground/50"}>
            {wsConnected ? "실시간" : "연결 중..."}
          </span>
        </div>

        {user && (
          <>
            <span
              className={cn(
                "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide",
                PLAN_STYLES[user.plan] ?? PLAN_STYLES.free
              )}
            >
              {PLAN_LABELS[user.plan] ?? user.plan}
            </span>
            <span className="text-sm text-muted-foreground/70">
              {user.display_name ?? user.email}
            </span>
          </>
        )}
      </div>
    </header>
  )
}
