"use client"

import { TrendingUp, TrendingDown, Target, Trophy, Clock, DollarSign } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ShadowTradeStats } from "@/lib/schemas"

interface Props {
  stats: ShadowTradeStats
}

function StatCard({
  title,
  value,
  sub,
  icon: Icon,
  valueColor,
}: {
  title: string
  value: string
  sub?: string
  icon: React.ElementType
  valueColor?: string
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${valueColor ?? "text-foreground"}`}>{value}</div>
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  )
}

export function ShadowStatsCards({ stats }: Props) {
  const pnlColor = stats.total_pnl_usdt >= 0 ? "text-green-400" : "text-red-400"
  const winColor = stats.win_rate >= 50 ? "text-green-400" : "text-red-400"

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
      <StatCard
        title="총 거래"
        value={`${stats.total_trades}회`}
        sub={`진행중 ${stats.open_trades}건`}
        icon={Target}
      />
      <StatCard
        title="승률"
        value={`${stats.win_rate}%`}
        sub={`${stats.tp_hit}승 ${stats.sl_hit}패`}
        icon={Trophy}
        valueColor={winColor}
      />
      <StatCard
        title="총 손익"
        value={`${stats.total_pnl_usdt >= 0 ? "+" : ""}$${stats.total_pnl_usdt.toFixed(2)}`}
        sub={`평균 ${stats.avg_pnl_usdt >= 0 ? "+" : ""}$${stats.avg_pnl_usdt.toFixed(2)}/회`}
        icon={DollarSign}
        valueColor={pnlColor}
      />
      <StatCard
        title="최고 수익"
        value={stats.best_pnl_usdt != null ? `+$${stats.best_pnl_usdt.toFixed(2)}` : "-"}
        icon={TrendingUp}
        valueColor="text-green-400"
      />
      <StatCard
        title="최대 손실"
        value={stats.worst_pnl_usdt != null ? `$${stats.worst_pnl_usdt.toFixed(2)}` : "-"}
        icon={TrendingDown}
        valueColor="text-red-400"
      />
      <StatCard
        title="평균 보유"
        value={stats.avg_duration_minutes != null ? `${Math.round(stats.avg_duration_minutes)}분` : "-"}
        icon={Clock}
      />
    </div>
  )
}
