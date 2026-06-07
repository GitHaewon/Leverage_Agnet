import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { ordersResponseSchema } from "@/lib/schemas"

export interface UseOrdersParams {
  status?: "open" | "filled" | "cancelled" | "rejected" | "all"
  coin?: "BTC" | "ETH" | "all"
  limit?: number
  offset?: number
}

export function useOrders({
  status = "all",
  coin = "all",
  limit = 20,
  offset = 0,
}: UseOrdersParams = {}) {
  return useQuery({
    queryKey: ["orders", { status, coin, limit, offset }],
    queryFn: async () => {
      const { data: raw } = await api.get<unknown>("/orders", {
        params: { status, coin, limit, offset },
      })
      return ordersResponseSchema.parse(raw).data
    },
  })
}
