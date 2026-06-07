import { TradeHistoryTable } from "@/components/trades/TradeHistoryTable"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function TradesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">거래 내역</h1>
        <p className="text-sm text-muted-foreground">주문 체결 내역 및 수수료 현황</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold">거래 내역</CardTitle>
        </CardHeader>
        <CardContent>
          <TradeHistoryTable />
        </CardContent>
      </Card>
    </div>
  )
}
