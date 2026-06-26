"use client"

import { TrendingUp, TrendingDown, CheckCircle2, XCircle, Loader2 } from "lucide-react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { ShadowTrade } from "@/lib/schemas"
import { cn } from "@/lib/utils"

interface Props {
  trades: ShadowTrade[]
}

function DirectionBadge({ direction }: { direction: "LONG" | "SHORT" }) {
  if (direction === "LONG") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-blue-500/20 bg-blue-500/10 px-2 py-0.5 text-xs font-bold text-blue-400">
        <TrendingUp className="h-3 w-3" />
        LONG
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-rose-500/20 bg-rose-500/10 px-2 py-0.5 text-xs font-bold text-rose-400">
      <TrendingDown className="h-3 w-3" />
      SHORT
    </span>
  )
}

function StatusBadge({ status }: { status: ShadowTrade["status"] }) {
  if (status === "TP_HIT") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-400">
        <CheckCircle2 className="h-3 w-3" />
        목표 달성
      </span>
    )
  }
  if (status === "SL_HIT") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-rose-500/20 bg-rose-500/10 px-2 py-0.5 text-xs font-semibold text-rose-400">
        <XCircle className="h-3 w-3" />
        손절
      </span>
    )
  }
  if (status === "OPEN") {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-400">
        <Loader2 className="h-3 w-3 animate-spin" />
        진행중
      </span>
    )
  }
  return (
    <span className="inline-flex items-center rounded-md border border-white/[0.08] bg-white/[0.05] px-2 py-0.5 text-xs font-medium text-muted-foreground">
      취소됨
    </span>
  )
}

function PnlCell({ pnl }: { pnl: number | null | undefined }) {
  if (pnl == null) return <span className="text-muted-foreground/30">—</span>
  const isPositive = pnl >= 0
  return (
    <span
      className={cn(
        "font-semibold tabular-nums",
        isPositive ? "text-emerald-400" : "text-rose-400"
      )}
    >
      {isPositive ? "+" : ""}${pnl.toFixed(2)}
    </span>
  )
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds == null) return "—"
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m}분`
  const h = Math.floor(m / 60)
  const rem = m % 60
  return rem > 0 ? `${h}시간 ${rem}분` : `${h}시간`
}

function formatPrice(val: string | null | undefined) {
  if (!val) return "—"
  const n = parseFloat(val)
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return "—"
  return new Date(iso).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function ShadowTradesTable({ trades }: Props) {
  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-white/[0.06] bg-white/[0.03]">
          <Loader2 className="h-5 w-5 text-muted-foreground/30" />
        </div>
        <p className="text-sm font-medium text-foreground/40">아직 거래 기록이 없습니다</p>
        <p className="mt-1.5 text-xs text-muted-foreground/30">
          Shadow Trading이 활성화되면 5분마다 자동으로 거래가 생성됩니다.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow className="border-white/[0.06] hover:bg-transparent">
            <TableHead className="pl-5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50">
              코인
            </TableHead>
            <TableHead className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50">
              방향
            </TableHead>
            <TableHead className="text-right text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50">
              진입가
            </TableHead>
            <TableHead className="text-right text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50">
              목표가
            </TableHead>
            <TableHead className="text-right text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50">
              손절가
            </TableHead>
            <TableHead className="text-right text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50">
              레버리지
            </TableHead>
            <TableHead className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50">
              결과
            </TableHead>
            <TableHead className="text-right text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50">
              손익
            </TableHead>
            <TableHead className="hidden text-right text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50 md:table-cell">
              보유
            </TableHead>
            <TableHead className="hidden text-[11px] font-medium uppercase tracking-wider text-muted-foreground/50 lg:table-cell">
              시작
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((t) => (
            <TableRow
              key={t.id}
              className="border-white/[0.04] transition-colors duration-150 hover:bg-white/[0.025]"
            >
              <TableCell className="pl-5 font-bold text-foreground">{t.coin}</TableCell>
              <TableCell>
                <DirectionBadge direction={t.direction} />
              </TableCell>
              <TableCell className="text-right tabular-nums text-sm text-foreground/70">
                {formatPrice(t.entry_price)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-sm text-emerald-400/70">
                {formatPrice(t.tp_price)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-sm text-rose-400/70">
                {formatPrice(t.sl_price)}
              </TableCell>
              <TableCell className="text-right">
                <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-xs font-bold text-foreground/60">
                  {t.leverage}x
                </span>
              </TableCell>
              <TableCell>
                <StatusBadge status={t.status} />
              </TableCell>
              <TableCell className="text-right">
                <PnlCell pnl={t.pnl_usdt} />
              </TableCell>
              <TableCell className="hidden text-right tabular-nums text-xs text-muted-foreground/50 md:table-cell">
                {formatDuration(t.duration_seconds)}
              </TableCell>
              <TableCell className="hidden tabular-nums text-xs text-muted-foreground/40 lg:table-cell">
                {formatDate(t.opened_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
