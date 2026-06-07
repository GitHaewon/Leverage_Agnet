import { PositionsTable } from "@/components/positions/PositionsTable"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function PositionsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">포지션</h1>
        <p className="text-sm text-muted-foreground">
          오픈 포지션 실시간 모니터링 및 청산
        </p>
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
