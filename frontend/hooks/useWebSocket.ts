"use client"

import { useEffect, useRef, useCallback } from "react"
import { useAuthStore } from "@/store/auth"
import { usePositionsStore } from "@/store/positions"
import {
  wsAccountUpdatedSchema,
  wsPositionUpdatedSchema,
} from "@/lib/schemas"

const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/v1"
const RECONNECT_DELAY_MS = 3_000
const MAX_RECONNECT_ATTEMPTS = 5
const PING_INTERVAL_MS = 30_000

export interface WebSocketStatus {
  connected: boolean
  reconnectAttempts: number
}

export function useDashboardWebSocket(): WebSocketStatus {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectCountRef = useRef(0)
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const connectedRef = useRef(false)

  const accessToken = useAuthStore((s) => s.accessToken)
  const applyPositionUpdate = usePositionsStore((s) => s.applyPositionUpdate)
  const setLiveAccount = usePositionsStore((s) => s.setLiveAccount)

  const handleMessage = useCallback(
    (event: MessageEvent<string>) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(event.data) as unknown
      } catch {
        return
      }
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        !("type" in parsed)
      ) {
        return
      }
      const msgType = (parsed as { type: unknown }).type

      if (msgType === "account.updated") {
        const result = wsAccountUpdatedSchema.safeParse(parsed)
        if (result.success) setLiveAccount(result.data.data)
      } else if (msgType === "position.updated") {
        const result = wsPositionUpdatedSchema.safeParse(parsed)
        if (result.success) applyPositionUpdate(result.data.data)
      }
    },
    [applyPositionUpdate, setLiveAccount]
  )

  const connect = useCallback(() => {
    if (!accessToken) return
    const url = `${WS_BASE_URL}/dashboard?token=${encodeURIComponent(accessToken)}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      connectedRef.current = true
      reconnectCountRef.current = 0
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({ type: "ping", id: crypto.randomUUID() })
          )
        }
      }, PING_INTERVAL_MS)
    }

    ws.onmessage = handleMessage

    ws.onclose = () => {
      connectedRef.current = false
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current)
      if (reconnectCountRef.current < MAX_RECONNECT_ATTEMPTS) {
        reconnectCountRef.current += 1
        reconnectTimeoutRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }

    ws.onerror = () => ws.close()
  }, [accessToken, handleMessage])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return {
    connected: connectedRef.current,
    reconnectAttempts: reconnectCountRef.current,
  }
}
