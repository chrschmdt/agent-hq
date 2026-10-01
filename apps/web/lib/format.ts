export const STORE_TIME_ZONE = "America/New_York"

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    timeZone: STORE_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}

export function moment(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    timeZone: STORE_TIME_ZONE,
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}

export function usd(amount: number): string {
  if (amount === 0) {
    return "$0"
  }
  if (amount < 0.01) {
    return `$${amount.toFixed(4)}`
  }
  return `$${amount.toFixed(2)}`
}

export function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export function words(value: string): string {
  return value.replaceAll("_", " ")
}

export function sentence(value: string): string {
  const text = words(value)
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function version(id: string): string {
  return id.replace(/^([a-z_]+)@(\d+)$/, "$1 v$2")
}

export function versionsIn(text: string): string {
  return text.replace(/\b([a-z_]+)@(\d+)\b/g, "$1 v$2")
}

export function lasted(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000))
  if (seconds < 60) {
    return `${seconds} s`
  }
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) {
    return `${minutes} min`
  }
  const hours = Math.floor(minutes / 60)
  return minutes % 60 === 0 ? `${hours} h` : `${hours} h ${minutes % 60} min`
}

export function ago(iso: string, now = Date.now()): string {
  const seconds = Math.max(
    0,
    Math.round((now - new Date(iso).getTime()) / 1000)
  )
  if (seconds < 60) {
    return `${seconds}s ago`
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ago`
  }
  if (seconds < 86400) {
    return `${Math.floor(seconds / 3600)}h ago`
  }
  return `${Math.floor(seconds / 86400)}d ago`
}
