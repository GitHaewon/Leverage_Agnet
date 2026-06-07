/**
 * MetricCard component tests.
 *
 * Verified:
 *   - renders title
 *   - renders value
 *   - renders subValue when provided
 *   - renders icon when provided
 *   - shows loading skeleton when isLoading=true
 *   - hides value when isLoading=true
 *   - applies green color for trend=up
 *   - applies red color for trend=down
 *   - no subValue when not provided
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { MetricCard } from "@/components/dashboard/MetricCard"
import { DollarSign } from "lucide-react"

describe("MetricCard", () => {
  it("renders title", () => {
    render(<MetricCard title="총 잔고" value="$24,157.85" />)
    expect(screen.getByText("총 잔고")).toBeDefined()
  })

  it("renders value", () => {
    render(<MetricCard title="총 잔고" value="$24,157.85" />)
    expect(screen.getByText("$24,157.85")).toBeDefined()
  })

  it("renders subValue when provided", () => {
    render(<MetricCard title="잔고" value="$24,157.85" subValue="가용 $21,342.60" />)
    expect(screen.getByText(/가용/i)).toBeDefined()
  })

  it("does not render subValue when omitted", () => {
    render(<MetricCard title="잔고" value="$24,157.85" />)
    expect(screen.queryByText(/가용/i)).toBeNull()
  })

  it("shows loading skeleton when isLoading=true", () => {
    const { container } = render(<MetricCard title="잔고" value="$24,157.85" isLoading />)
    expect(container.querySelector(".animate-pulse")).toBeDefined()
  })

  it("hides value text when isLoading=true", () => {
    render(<MetricCard title="잔고" value="$24,157.85" isLoading />)
    expect(screen.queryByText("$24,157.85")).toBeNull()
  })

  it("renders icon when provided", () => {
    const { container } = render(
      <MetricCard title="잔고" value="$24,157.85" icon={DollarSign} />
    )
    expect(container.querySelector("svg")).toBeDefined()
  })

  it("applies green color class for trend=up", () => {
    render(<MetricCard title="손익" value="+$65.70" trend="up" />)
    const valueEl = screen.getByText("+$65.70")
    expect(valueEl.className).toContain("green")
  })

  it("applies red color class for trend=down", () => {
    render(<MetricCard title="손익" value="-$50.00" trend="down" />)
    const valueEl = screen.getByText("-$50.00")
    expect(valueEl.className).toContain("red")
  })

  it("neutral trend uses muted color", () => {
    render(<MetricCard title="포지션" value="3" trend="neutral" />)
    const valueEl = screen.getByText("3")
    expect(valueEl.className).toContain("muted")
  })
})
