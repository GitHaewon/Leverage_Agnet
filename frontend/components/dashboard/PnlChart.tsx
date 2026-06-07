"use client"

import { useEffect, useRef, useState } from "react"
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type AreaData,
  ColorType,
  LineStyle,
} from "lightweight-charts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useStats, type StatsPeriod } from "@/hooks/useAccount"
import { cn } from "@/lib/utils"
import type { DailyPnl } from "@/lib/schemas"

const PERIODS: { label: string; value: StatsPeriod }[] = [
  { label: "7일", value: "7d" },
  { label: "30일", value: "30d" },
  { label: "90일", value: "90d" },
  { label: "전체", value: "all" },
]

function toChartData(dailyPnl: DailyPnl[]): AreaData[] {
  return dailyPnl.map((d) => ({
    time: d.date as `${number}-${number}-${number}`,
    value: parseFloat(d.cumulative_pnl),
  }))
}

export function PnlChart() {
  const [period, setPeriod] = useState<StatsPeriod>("30d")
  const { data, isLoading } = useStats(period)

  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null)

  // initialize chart
  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "#1e293b", style: LineStyle.Dotted },
        horzLines: { color: "#1e293b", style: LineStyle.Dotted },
      },
      crosshair: { horzLine: { visible: true }, vertLine: { visible: true } },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155", timeVisible: true },
      handleScroll: false,
      handleScale: false,
    })

    const series = chart.addAreaSeries({
      lineColor: "#3b82f6",
      topColor: "rgba(59,130,246,0.3)",
      bottomColor: "rgba(59,130,246,0.0)",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    })

    chartRef.current = chart
    seriesRef.current = series

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        chart.applyOptions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        })
      }
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
    }
  }, [])

  // update data
  useEffect(() => {
    if (!seriesRef.current || !data) return
    const chartData = toChartData(data.daily_pnl)
    if (chartData.length > 0) {
      seriesRef.current.setData(chartData)
      chartRef.current?.timeScale().fitContent()
    }
  }, [data])

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold">누적 손익</CardTitle>
          <div className="flex gap-1">
            {PERIODS.map(({ label, value }) => (
              <button
                key={value}
                onClick={() => setPeriod(value)}
                className={cn(
                  "rounded px-2 py-1 text-xs font-medium transition-colors",
                  period === value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {data && (
          <div className="flex gap-4 text-sm">
            <span className="text-muted-foreground">
              총 손익:{" "}
              <span
                className={
                  parseFloat(data.summary.total_pnl) >= 0
                    ? "text-green-400"
                    : "text-red-400"
                }
              >
                ${data.summary.total_pnl}
              </span>
            </span>
            <span className="text-muted-foreground">
              승률:{" "}
              <span className="text-foreground">
                {(parseFloat(data.summary.win_rate) * 100).toFixed(1)}%
              </span>
            </span>
          </div>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
            로딩 중...
          </div>
        ) : (
          <div ref={containerRef} className="h-48 w-full" />
        )}
      </CardContent>
    </Card>
  )
}
