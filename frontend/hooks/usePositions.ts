import { useQuery } from "@tanstack/react-query"
import { useEffect } from "react"
import { api } from "@/lib/api"
import { positionsResponseSchema } from "@/lib/schemas"
import { usePositionsStore } from "@/store/positions"

export function usePositions() {
  const setPositions = usePositionsStore((s) => s.setPositions)
  const livePositions = usePositionsStore((s) => s.getOpenPositions())

  const query = useQuery({
    queryKey: ["positions"],
    queryFn: async () => {
      const { data: raw } = await api.get<unknown>("/positions")
      return positionsResponseSchema.parse(raw).data
    },
    refetchInterval: 10_000,
  })

  useEffect(() => {
    if (query.data) {
      setPositions(query.data.positions)
    }
  }, [query.data, setPositions])

  return {
    ...query,
    livePositions,
    summary: query.data?.summary,
  }
}
