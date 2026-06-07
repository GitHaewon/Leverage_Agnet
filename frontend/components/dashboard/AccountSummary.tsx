"use client"

import { DollarSign, TrendingUp, TrendingDown, Activity } from "lucide-react"
import { MetricCard } from "./MetricCard"
import { usePositionsStore } from "@/store/positions"
import { useBalance } from "@/hooks/useAccount"
import { formatPrice, formatPct } from "@/lib/utils"

export function AccountSummary() {
  const liveAccount = usePositionsStore((s) => s.liveAccount)
  const openPositions = usePositionsStore((s) => s.getOpenPositions())
  const { data: balance, isLoading } = useBalance()

  const displayBalance = liveAccount?.balance_usdt ?? balance?.total_balance
  const displayPnl =
    liveAccount?.total_unrealized_pnl ?? balance?.total_unrealized_pnl
  const todayPnl = liveAccount?.today_pnl ?? balance?.today_pnl
  const todayPnlPct = liveAccount?.today_pnl_pct ?? balance?.today_pnl_pct

  const unrealizedNum = displayPnl ? parseFloat(displayPnl) : null
  const todayNum = todayPnl ? parseFloat(todayPnl) : null

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <MetricCard
        title="총 잔고"
        value={displayBalance ? formatPrice(displayBalance) : "—"}
        subValue={
          balance?.available_balance
            ? `가용 ${formatPrice(balance.available_balance)}`
            : undefined
        }
        icon={DollarSign}
        isLoading={isLoading && !displayBalance}
      />

      <MetricCard
        title="미실현 손익"
        value={displayPnl ? formatPrice(displayPnl) : "—"}
        subValue={openPositions.length > 0 ? `${openPositions.length}개 포지션` : undefined}
        icon={Activity}
        trend={
          unrealizedNum === null
            ? "neutral"
            : unrealizedNum >= 0
              ? "up"
              : "down"
        }
        isLoading={isLoading && !displayPnl}
      />

      <MetricCard
        title="오늘 손익"
        value={todayPnl ? formatPrice(todayPnl) : "—"}
        subValue={todayPnlPct ? formatPct(todayPnlPct) : undefined}
        icon={todayNum !== null && todayNum >= 0 ? TrendingUp : TrendingDown}
        trend={
          todayNum === null ? "neutral" : todayNum >= 0 ? "up" : "down"
        }
        isLoading={isLoading && !todayPnl}
      />

      <MetricCard
        title="오픈 포지션"
        value={String(openPositions.length)}
        subValue={
          openPositions.length > 0
            ? openPositions.map((p) => p.coin).join(", ")
            : "포지션 없음"
        }
        icon={Activity}
        isLoading={false}
      />
    </div>
  )
}
