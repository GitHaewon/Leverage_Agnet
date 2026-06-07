import { AccountSummary } from "@/components/dashboard/AccountSummary"
import { PnlChart } from "@/components/dashboard/PnlChart"
import { SignalFeed } from "@/components/dashboard/SignalFeed"
import { PositionsTable } from "@/components/positions/PositionsTable"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">대시보드</h1>
        <p className="text-sm text-muted-foreground">
          실시간 계좌 현황 및 포지션 모니터링
        </p>
      </div>

      <AccountSummary />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <PnlChart />
        </div>
        <div>
          <SignalFeed />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold">오픈 포지션</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <PositionsTable />
        </CardContent>
      </Card>
    </div>
  )
}
