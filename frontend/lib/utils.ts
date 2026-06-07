import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

export function formatPrice(value: string | number | undefined | null): string {
  if (value === undefined || value === null) return "—"
  const num = typeof value === "string" ? parseFloat(value) : value
  if (isNaN(num)) return "—"
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num)
}

export function formatPct(value: string | number | undefined | null): string {
  if (value === undefined || value === null) return "—"
  const num = typeof value === "string" ? parseFloat(value) : value
  if (isNaN(num)) return "—"
  const sign = num > 0 ? "+" : ""
  return `${sign}${num.toFixed(2)}%`
}

export function formatDuration(seconds: number | undefined | null): string {
  if (seconds === undefined || seconds === null) return "—"
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  return `${Math.floor(seconds / 86400)}d`
}

export function isPnlPositive(value: string | undefined | null): boolean {
  if (!value) return false
  return parseFloat(value) >= 0
}
