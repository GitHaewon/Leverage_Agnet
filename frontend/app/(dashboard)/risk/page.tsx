import { RiskOverview } from "@/components/risk/RiskOverview"

export default function RiskPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">리스크 개요</h1>
        <p className="text-sm text-muted-foreground">
          수익률 통계, 최대 낙폭, 손익비 분석
        </p>
      </div>

      <RiskOverview />
    </div>
  )
}
