"use client"

import { useAuthStore } from "@/store/auth"
import { Badge } from "@/components/ui/badge"
import { usePositionsStore } from "@/store/positions"
import { Wifi, WifiOff } from "lucide-react"

interface HeaderProps {
  wsConnected?: boolean
}

const PLAN_LABELS: Record<string, string> = {
  free: "Free",
  pro: "Pro",
  elite: "Elite",
}

export function Header({ wsConnected = false }: HeaderProps) {
  const user = useAuthStore((s) => s.user)
  const liveAccount = usePositionsStore((s) => s.liveAccount)

  const todayPnl = liveAccount?.today_pnl
  const todayPnlPct = liveAccount?.today_pnl_pct
  const isPositive = todayPnl ? parseFloat(todayPnl) >= 0 : null

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-card px-6">
      <div className="flex items-center gap-4">
        {liveAccount && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">잔고</span>
            <span className="font-semibold text-foreground">
              ${parseFloat(liveAccount.balance_usdt).toLocaleString("en-US", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </span>
            {todayPnl !== undefined && isPositive !== null && (
              <span
                className={
                  isPositive ? "text-green-400 text-xs" : "text-red-400 text-xs"
                }
              >
                {isPositive ? "+" : ""}
                {todayPnlPct}% 오늘
              </span>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center gap-3">
        <div
          className={`flex items-center gap-1 text-xs ${
            wsConnected ? "text-green-400" : "text-muted-foreground"
          }`}
        >
          {wsConnected ? (
            <Wifi className="h-3 w-3" />
          ) : (
            <WifiOff className="h-3 w-3" />
          )}
          {wsConnected ? "실시간" : "연결 중..."}
        </div>

        {user && (
          <>
            <Badge variant={user.plan === "elite" ? "default" : "secondary"}>
              {PLAN_LABELS[user.plan] ?? user.plan}
            </Badge>
            <span className="text-sm text-muted-foreground">
              {user.display_name ?? user.email}
            </span>
          </>
        )}
      </div>
    </header>
  )
}
