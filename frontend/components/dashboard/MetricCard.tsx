import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { LucideIcon } from "lucide-react"

export interface MetricCardProps {
  title: string
  value: string
  subValue?: string
  icon?: LucideIcon
  trend?: "up" | "down" | "neutral"
  className?: string
  isLoading?: boolean
}

export function MetricCard({
  title,
  value,
  subValue,
  icon: Icon,
  trend,
  className,
  isLoading = false,
}: MetricCardProps) {
  const trendColor =
    trend === "up"
      ? "text-green-400"
      : trend === "down"
        ? "text-red-400"
        : "text-muted-foreground"

  return (
    <Card className={cn("relative overflow-hidden", className)}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="h-7 w-28 animate-pulse rounded bg-muted" />
        ) : (
          <div className={cn("text-2xl font-bold", trendColor)}>{value}</div>
        )}
        {subValue && !isLoading && (
          <p className="mt-1 text-xs text-muted-foreground">{subValue}</p>
        )}
      </CardContent>
    </Card>
  )
}
