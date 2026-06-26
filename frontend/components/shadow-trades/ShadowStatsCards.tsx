"use client"

import { Clock, DollarSign, Target, TrendingDown, TrendingUp, Trophy } from "lucide-react"
import type { ShadowTradeStats } from "@/lib/schemas"
import { cn } from "@/lib/utils"

interface Props {
  stats: ShadowTradeStats
  openPositionCount?: number
}

function StatCard({
  title,
  value,
  sub,
  icon: Icon,
  valueColor,
  iconColor,
  iconBg,
}: {
  title: string
  value: string
  sub?: string
  icon: React.ElementType
  valueColor?: string
  iconColor?: string
  iconBg?: string
}) {
  return (
    <div className="group relative overflow-hidden rounded-xl border border-white/[0.06] bg-white/[0.025] p-4 backdrop-blur-sm transition-all duration-200 hover:border-white/[0.1] hover:bg-white/[0.04] hover:shadow-[0_4px_24px_rgba(0,0,0,0.35)] hover:-translate-y-px">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">
            {title}
          </p>
          <p
            className={cn(
              "mt-2 text-2xl font-bold tracking-tight tabular-nums leading-none",
              valueColor ?? "text-foreground"
            )}
          >
            {value}
          </p>
          {sub && (
            <p className="mt-1.5 text-[11px] text-muted-foreground/50 truncate">{sub}</p>
          )}
        </div>
        <div
          className={cn(
            "flex-shrink-0 flex h-9 w-9 items-center justify-center rounded-lg border",
            iconBg ?? "bg-white/[0.06] border-white/[0.08]"
          )}
        >
          <Icon className={cn("h-4 w-4", iconColor ?? "text-muted-foreground")} />
        </div>
      </div>
    </div>
  )
}

export function ShadowStatsCards({ stats, openPositionCount }: Props) {
  const pnlPositive = stats.total_pnl_usdt >= 0
  const winGood = stats.win_rate >= 50
  const openSub =
    openPositionCount == null
      ? `진행중 체결 ${stats.open_trades}건`
      : `${openPositionCount}포지션 / 체결 ${stats.open_trades}건`

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <StatCard
        title="총 거래"
        value={`${stats.total_trades}회`}
        sub={openSub}
        icon={Target}
        iconColor="text-blue-400"
        iconBg="bg-blue-500/10 border-blue-500/20"
      />
      <StatCard
        title="승률"
        value={`${stats.win_rate}%`}
        sub={`${stats.tp_hit}승 ${stats.sl_hit}패`}
        icon={Trophy}
        valueColor={winGood ? "text-emerald-400" : "text-rose-400"}
        iconColor={winGood ? "text-emerald-400" : "text-rose-400"}
        iconBg={
          winGood
            ? "bg-emerald-500/10 border-emerald-500/20"
            : "bg-rose-500/10 border-rose-500/20"
        }
      />
      <StatCard
        title="총 손익"
        value={`${pnlPositive ? "+" : ""}$${stats.total_pnl_usdt.toFixed(2)}`}
        sub={`평균 ${stats.avg_pnl_usdt >= 0 ? "+" : ""}$${stats.avg_pnl_usdt.toFixed(2)}/회`}
        icon={DollarSign}
        valueColor={pnlPositive ? "text-emerald-400" : "text-rose-400"}
        iconColor={pnlPositive ? "text-emerald-400" : "text-rose-400"}
        iconBg={
          pnlPositive
            ? "bg-emerald-500/10 border-emerald-500/20"
            : "bg-rose-500/10 border-rose-500/20"
        }
      />
      <StatCard
        title="최고 수익"
        value={stats.best_pnl_usdt != null ? `+$${stats.best_pnl_usdt.toFixed(2)}` : "—"}
        icon={TrendingUp}
        valueColor="text-emerald-400"
        iconColor="text-emerald-400"
        iconBg="bg-emerald-500/10 border-emerald-500/20"
      />
      <StatCard
        title="최대 손실"
        value={stats.worst_pnl_usdt != null ? `$${stats.worst_pnl_usdt.toFixed(2)}` : "—"}
        icon={TrendingDown}
        valueColor="text-rose-400"
        iconColor="text-rose-400"
        iconBg="bg-rose-500/10 border-rose-500/20"
      />
      <StatCard
        title="평균 보유"
        value={
          stats.avg_duration_minutes != null
            ? `${Math.round(stats.avg_duration_minutes)}분`
            : "—"
        }
        icon={Clock}
        iconColor="text-sky-400"
        iconBg="bg-sky-500/10 border-sky-500/20"
      />
    </div>
  )
}
