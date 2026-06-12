"use client"

import { ArrowUpCircle, ArrowDownCircle, CheckCircle2, XCircle, Loader2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { ShadowTrade } from "@/lib/schemas"

interface Props {
  trades: ShadowTrade[]
}

function DirectionBadge({ direction }: { direction: "LONG" | "SHORT" }) {
  if (direction === "LONG") {
    return (
      <span className="inline-flex items-center gap-1 font-semibold text-blue-400">
        <ArrowUpCircle className="h-4 w-4" />
        LONG
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 font-semibold text-red-400">
      <ArrowDownCircle className="h-4 w-4" />
      SHORT
    </span>
  )
}

function StatusBadge({ status }: { status: ShadowTrade["status"] }) {
  if (status === "TP_HIT") {
    return (
      <Badge className="gap-1 bg-green-500/15 text-green-400 hover:bg-green-500/20">
        <CheckCircle2 className="h-3 w-3" />
        목표 달성
      </Badge>
    )
  }
  if (status === "SL_HIT") {
    return (
      <Badge className="gap-1 bg-red-500/15 text-red-400 hover:bg-red-500/20">
        <XCircle className="h-3 w-3" />
        손절
      </Badge>
    )
  }
  if (status === "OPEN") {
    return (
      <Badge className="gap-1 bg-yellow-500/15 text-yellow-400 hover:bg-yellow-500/20">
        <Loader2 className="h-3 w-3 animate-spin" />
        진행중
      </Badge>
    )
  }
  return <Badge variant="secondary">취소됨</Badge>
}

function PnlCell({ pnl }: { pnl: number | null | undefined }) {
  if (pnl == null) return <span className="text-muted-foreground">-</span>
  const color = pnl >= 0 ? "text-green-400" : "text-red-400"
  return (
    <span className={`font-semibold tabular-nums ${color}`}>
      {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
    </span>
  )
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds == null) return "-"
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m}분`
  const h = Math.floor(m / 60)
  const rem = m % 60
  return rem > 0 ? `${h}시간 ${rem}분` : `${h}시간`
}

function formatPrice(val: string | null | undefined) {
  if (!val) return "-"
  const n = parseFloat(val)
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
}

function formatDate(iso: string | null | undefined) {
  if (!iso) return "-"
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
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <p className="text-lg font-medium">아직 거래 기록이 없습니다</p>
        <p className="mt-1 text-sm">Shadow Trading이 활성화되면 5분마다 자동으로 거래가 생성됩니다.</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>코인</TableHead>
            <TableHead>방향</TableHead>
            <TableHead className="text-right">진입가</TableHead>
            <TableHead className="text-right">목표가</TableHead>
            <TableHead className="text-right">손절가</TableHead>
            <TableHead className="text-right">레버리지</TableHead>
            <TableHead>결과</TableHead>
            <TableHead className="text-right">손익</TableHead>
            <TableHead className="text-right">보유 시간</TableHead>
            <TableHead>시작</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((t) => (
            <TableRow key={t.id}>
              <TableCell className="font-semibold">{t.coin}</TableCell>
              <TableCell>
                <DirectionBadge direction={t.direction} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(t.entry_price)}</TableCell>
              <TableCell className="text-right tabular-nums text-green-400">{formatPrice(t.tp_price)}</TableCell>
              <TableCell className="text-right tabular-nums text-red-400">{formatPrice(t.sl_price)}</TableCell>
              <TableCell className="text-right">{t.leverage}x</TableCell>
              <TableCell>
                <StatusBadge status={t.status} />
              </TableCell>
              <TableCell className="text-right">
                <PnlCell pnl={t.pnl_usdt} />
              </TableCell>
              <TableCell className="text-right text-muted-foreground">
                {formatDuration(t.duration_seconds)}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">{formatDate(t.opened_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
