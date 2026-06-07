import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { statsResponseSchema, accountBalanceSchema } from "@/lib/schemas"

export type StatsPeriod = "7d" | "30d" | "90d" | "all"

export function useStats(period: StatsPeriod = "30d") {
  return useQuery({
    queryKey: ["stats", period],
    queryFn: async () => {
      const { data: raw } = await api.get<unknown>("/users/me/stats", {
        params: { period },
      })
      return statsResponseSchema.parse(raw).data
    },
  })
}

export function useBalance() {
  return useQuery({
    queryKey: ["balance"],
    queryFn: async () => {
      const { data: raw } = await api.get<unknown>("/binance/balance")
      return accountBalanceSchema.parse(raw).data
    },
    refetchInterval: 5_000,
  })
}
