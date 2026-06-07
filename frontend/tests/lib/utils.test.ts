/**
 * Utility function tests.
 *
 * Verified:
 *   - formatPrice: positive / negative / zero / null / undefined
 *   - formatPct: sign prepended for positive, not for negative
 *   - formatDuration: seconds / minutes / hours / days
 *   - isPnlPositive: positive / zero / negative / null
 *   - cn: class merging
 */

import { describe, it, expect } from "vitest"
import { formatPrice, formatPct, formatDuration, isPnlPositive, cn } from "@/lib/utils"

// ── formatPrice ───────────────────────────────────────────────────────────────

describe("formatPrice", () => {
  it("formats positive number", () => {
    expect(formatPrice("67452.00")).toBe("$67,452.00")
  })

  it("formats negative number", () => {
    expect(formatPrice("-234.56")).toBe("-$234.56")
  })

  it("formats zero", () => {
    expect(formatPrice("0")).toBe("$0.00")
  })

  it("returns — for null", () => {
    expect(formatPrice(null)).toBe("—")
  })

  it("returns — for undefined", () => {
    expect(formatPrice(undefined)).toBe("—")
  })

  it("formats numeric input directly", () => {
    expect(formatPrice(1234.5)).toBe("$1,234.50")
  })
})

// ── formatPct ─────────────────────────────────────────────────────────────────

describe("formatPct", () => {
  it("adds + prefix for positive", () => {
    expect(formatPct("3.25")).toBe("+3.25%")
  })

  it("negative sign not doubled", () => {
    const result = formatPct("-1.56")
    expect(result.startsWith("-")).toBe(true)
    expect(result).toContain("%")
  })

  it("formats zero without + prefix", () => {
    expect(formatPct("0")).toBe("0.00%")
  })

  it("returns — for null", () => {
    expect(formatPct(null)).toBe("—")
  })

  it("rounds to 2 decimal places", () => {
    expect(formatPct("3.14159")).toBe("+3.14%")
  })
})

// ── formatDuration ────────────────────────────────────────────────────────────

describe("formatDuration", () => {
  it("shows seconds for < 60s", () => {
    expect(formatDuration(45)).toBe("45s")
  })

  it("shows minutes for < 1h", () => {
    expect(formatDuration(150)).toBe("2m")
  })

  it("shows hours + minutes for < 1d", () => {
    expect(formatDuration(3661)).toBe("1h 1m")
  })

  it("shows days for >= 1d", () => {
    expect(formatDuration(86400)).toBe("1d")
  })

  it("returns — for null", () => {
    expect(formatDuration(null)).toBe("—")
  })

  it("returns — for undefined", () => {
    expect(formatDuration(undefined)).toBe("—")
  })
})

// ── isPnlPositive ─────────────────────────────────────────────────────────────

describe("isPnlPositive", () => {
  it("returns true for positive string", () => {
    expect(isPnlPositive("+65.70")).toBe(true)
  })

  it("returns true for zero", () => {
    expect(isPnlPositive("0")).toBe(true)
  })

  it("returns false for negative", () => {
    expect(isPnlPositive("-50.00")).toBe(false)
  })

  it("returns false for null", () => {
    expect(isPnlPositive(null)).toBe(false)
  })

  it("returns false for undefined", () => {
    expect(isPnlPositive(undefined)).toBe(false)
  })
})

// ── cn ────────────────────────────────────────────────────────────────────────

describe("cn", () => {
  it("merges class strings", () => {
    expect(cn("a", "b")).toBe("a b")
  })

  it("resolves tailwind conflicts — last one wins", () => {
    const result = cn("p-4", "p-6")
    expect(result).toBe("p-6")
  })

  it("handles conditional classes", () => {
    const result = cn("base", false && "hidden", "visible")
    expect(result).toContain("base")
    expect(result).toContain("visible")
    expect(result).not.toContain("hidden")
  })

  it("handles undefined values", () => {
    expect(cn("a", undefined, "b")).toBe("a b")
  })
})
