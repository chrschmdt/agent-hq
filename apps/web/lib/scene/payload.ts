type Payload = Readonly<Record<string, unknown>> | undefined

export function text(payload: Payload, key: string): string | null {
  const value = payload?.[key]
  return typeof value === "string" ? value : null
}

export function num(payload: Payload, key: string): number | null {
  const value = payload?.[key]
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

export function flag(payload: Payload, key: string): boolean | null {
  const value = payload?.[key]
  return typeof value === "boolean" ? value : null
}

export function record(
  payload: Payload,
  key: string
): Record<string, unknown> | null {
  const value = payload?.[key]
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

export function list(payload: Payload, key: string): unknown[] {
  const value = payload?.[key]
  return Array.isArray(value) ? value : []
}
