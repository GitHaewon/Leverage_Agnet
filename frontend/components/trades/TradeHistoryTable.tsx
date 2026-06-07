"use client"

import { useState } from "react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useOrders, type UseOrdersParams } from "@/hooks/useOrders"
import { formatPrice } from "@/lib/utils"
import { ChevronLeft, ChevronRight } from "lucide-react"

const PAGE_SIZE = 20

const ORDER_STATUS_VARIANT = {
  filled: "success",
  pending: "warning",
  cancelled: "outline",
  rejected: "destructive",
} as const

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function TradeHistoryTable() {
  const [offset, setOffset] = useState(0)
  const [statusFilter, setStatusFilter] = useState<UseOrdersParams["status"]>("all")
  const [coinFilter, setCoinFilter] = useState<UseOrdersParams["coin"]>("all")

  const { data, isLoading, isError } = useOrders({
    status: statusFilter,
    coin: coinFilter,
    limit: PAGE_SIZE,
    offset,
  })

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  const handlePrev = () => setOffset((o) => Math.max(0, o - PAGE_SIZE))
  const handleNext = () => {
    if (data?.has_next) setOffset((o) => o + PAGE_SIZE)
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {(["all", "filled", "cancelled", "rejected"] as const).map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setOffset(0) }}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              statusFilter === s
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground"
            }`}
          >
            {s === "all" ? "전체" : s === "filled" ? "체결" : s === "cancelled" ? "취소" : "거절"}
          </button>
        ))}
        <div className="ml-2 h-px w-px" />
        {(["all", "BTC", "ETH"] as const).map((c) => (
          <button
            key={c}
            onClick={() => { setCoinFilter(c); setOffset(0) }}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              coinFilter === c
                ? "bg-secondary text-secondary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground"
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
          로딩 중...
        </div>
      ) : isError ? (
        <div className="flex h-32 items-center justify-center text-sm text-red-400">
          거래 내역을 불러오지 못했습니다.
        </div>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>종목 / 방향</TableHead>
                <TableHead>유형</TableHead>
                <TableHead>체결가</TableHead>
                <TableHead>수량</TableHead>
                <TableHead>레버리지</TableHead>
                <TableHead>수수료</TableHead>
                <TableHead>상태</TableHead>
                <TableHead>출처</TableHead>
                <TableHead>시간</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.items.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={9}
                    className="h-24 text-center text-muted-foreground"
                  >
                    거래 내역이 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                data?.items.map((order) => (
                  <TableRow key={order.id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Badge variant={order.side === "buy" ? "long" : "short"}>
                          {order.coin ?? order.symbol.replace("USDT", "")} {order.side === "buy" ? "매수" : "매도"}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground capitalize">
                      {order.order_type.replace("_", " ")}
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {formatPrice(order.filled_price ?? order.entry_price)}
                    </TableCell>
                    <TableCell className="font-mono text-sm text-muted-foreground">
                      {order.filled_quantity}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {order.leverage ? `×${order.leverage}` : "—"}
                    </TableCell>
                    <TableCell className="font-mono text-sm text-muted-foreground">
                      {formatPrice(order.fee)}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          ORDER_STATUS_VARIANT[order.status] ?? "outline"
                        }
                      >
                        {order.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {order.source === "auto" ? "자동" : "수동"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(order.executed_at ?? order.created_at)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          {data && data.total > 0 && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                총 {data.total}건 중 {offset + 1}–
                {Math.min(offset + PAGE_SIZE, data.total)}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handlePrev}
                  disabled={offset === 0}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span>
                  {currentPage} / {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleNext}
                  disabled={!data.has_next}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
