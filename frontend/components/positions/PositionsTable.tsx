"use client"

"use client"

import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { PositionRow } from "./PositionRow"
import { usePositions } from "@/hooks/usePositions"

export function PositionsTable() {
  const { livePositions, isLoading, isError } = usePositions()

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
        포지션 로딩 중...
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-red-400">
        포지션을 불러오지 못했습니다.
      </div>
    )
  }

  if (livePositions.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
        오픈 포지션이 없습니다.
      </div>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>방향 / 레버리지</TableHead>
          <TableHead>진입가</TableHead>
          <TableHead>현재가</TableHead>
          <TableHead>미실현 손익</TableHead>
          <TableHead>익절</TableHead>
          <TableHead>손절</TableHead>
          <TableHead>청산 여유</TableHead>
          <TableHead>보유 시간</TableHead>
          <TableHead></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {livePositions.map((position) => (
          <PositionRow key={position.id} position={position} />
        ))}
      </TableBody>
    </Table>
  )
}
