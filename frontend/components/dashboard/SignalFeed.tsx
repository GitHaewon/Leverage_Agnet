"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useAuthStore } from "@/store/auth"
import { wsSignalNewSchema, type WsSignalNew } from "@/lib/schemas"

const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/v1"

type Signal = WsSignalNew["data"]

const MAX_SIGNALS = 10

export function SignalFeed() {
  const [signals, setSignals] = useState<Signal[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const accessToken = useAuthStore((s) => s.accessToken)

  const addSignal = useCallback((signal: Signal) => {
    setSignals((prev) => [signal, ...prev].slice(0, MAX_SIGNALS))
  }, [])

  useEffect(() => {
    if (!accessToken) return
    const url = `${WS_BASE_URL}/signals?token=${encodeURIComponent(accessToken)}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onmessage = (event: MessageEvent<string>) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(event.data) as unknown
      } catch {
        return
      }
      const result = wsSignalNewSchema.safeParse(parsed)
      if (result.success) addSignal(result.data.data)
    }

    return () => ws.close()
  }, [accessToken, addSignal])

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-semibold">실시간 시그널</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 p-4 pt-0">
        {signals.length === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-4">
            새 시그널을 기다리는 중...
          </p>
        ) : (
          signals.map((signal) => (
            <SignalItem key={signal.id} signal={signal} />
          ))
        )}
      </CardContent>
    </Card>
  )
}

function SignalItem({ signal }: { signal: Signal }) {
  const isLong = signal.direction === "LONG"
  const confidencePct = (signal.confidence * 100).toFixed(0)

  return (
    <div className="flex items-center justify-between rounded-md border border-border p-3 text-sm">
      <div className="flex items-center gap-2">
        <Badge variant={isLong ? "long" : "short"}>
          {signal.coin} {signal.direction}
        </Badge>
        <span className="text-muted-foreground">×{signal.leverage}</span>
      </div>
      <div className="flex items-center gap-3 text-right">
        <div className="text-xs text-muted-foreground">
          진입 ${parseFloat(signal.entry_price).toLocaleString("en-US")}
        </div>
        <div className="text-xs text-muted-foreground">
          R:R {signal.rr_ratio}
        </div>
        <div className="text-xs font-medium">{confidencePct}%</div>
      </div>
    </div>
  )
}
