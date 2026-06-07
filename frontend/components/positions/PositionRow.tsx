"use client"

import { useState } from "react"
import { TableCell, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatPrice, formatPct, formatDuration, isPnlPositive } from "@/lib/utils"
import type { Position } from "@/lib/schemas"
import { api } from "@/lib/api"
import { useQueryClient } from "@tanstack/react-query"

interface PositionRowProps {
  position: Position
}

const WARNING_THRESHOLDS = { caution: 10, warning: 5, critical: 3 }

function getLiqWarningLevel(pct: string | null | undefined) {
  if (!pct) return null
  const n = parseFloat(pct)
  if (n <= WARNING_THRESHOLDS.critical) return "critical"
  if (n <= WARNING_THRESHOLDS.warning) return "warning"
  if (n <= WARNING_THRESHOLDS.caution) return "caution"
  return null
}

export function PositionRow({ position: pos }: PositionRowProps) {
  const [closing, setClosing] = useState(false)
  const queryClient = useQueryClient()

  const pnlPositive = isPnlPositive(pos.unrealized_pnl)
  const liqWarning = getLiqWarningLevel(pos.liquidation_distance_pct)

  const handleClose = async () => {
    if (!confirm(`${pos.coin} ${pos.direction} 포지션을 전량 청산하시겠습니까?`)) return
    setClosing(true)
    try {
      await api.post(`/positions/${pos.id}/close`, {
        type: "market",
        quantity_ratio: 1.0,
        reason: "수동 청산",
      })
      await queryClient.invalidateQueries({ queryKey: ["positions"] })
    } finally {
      setClosing(false)
    }
  }

  return (
    <TableRow>
      <TableCell>
        <div className="flex items-center gap-2">
          <Badge variant={pos.direction === "LONG" ? "long" : "short"}>
            {pos.coin} {pos.direction}
          </Badge>
          <span className="text-xs text-muted-foreground">
            ×{pos.leverage}
          </span>
        </div>
      </TableCell>
      <TableCell className="font-mono">{formatPrice(pos.entry_price)}</TableCell>
      <TableCell className="font-mono">{formatPrice(pos.current_price)}</TableCell>
      <TableCell className={`font-mono font-medium ${pnlPositive ? "text-green-400" : "text-red-400"}`}>
        <div>{formatPrice(pos.unrealized_pnl)}</div>
        <div className="text-xs">{formatPct(pos.unrealized_pnl_pct)}</div>
      </TableCell>
      <TableCell className="font-mono text-xs">
        <div>{formatPrice(pos.take_profit)}</div>
        <div className="text-muted-foreground">{pos.tp_distance_pct ? `${pos.tp_distance_pct}%` : "—"}</div>
      </TableCell>
      <TableCell className="font-mono text-xs">
        <div>{formatPrice(pos.stop_loss)}</div>
        <div className="text-muted-foreground">{pos.sl_distance_pct ? `${pos.sl_distance_pct}%` : "—"}</div>
      </TableCell>
      <TableCell>
        {liqWarning ? (
          <Badge variant={liqWarning}>
            {pos.liquidation_distance_pct}% 남음
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground font-mono">
            {pos.liquidation_distance_pct ? `${pos.liquidation_distance_pct}%` : "—"}
          </span>
        )}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {formatDuration(pos.duration_seconds)}
      </TableCell>
      <TableCell>
        <Button
          variant="outline"
          size="sm"
          onClick={handleClose}
          disabled={closing}
          className="text-xs"
        >
          {closing ? "청산 중..." : "청산"}
        </Button>
      </TableCell>
    </TableRow>
  )
}
