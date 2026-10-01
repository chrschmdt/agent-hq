export type FieldKind = "text" | "number" | "list" | "json"

export type Field = {
  name: string
  label: string
  kind: FieldKind
  description: string
  required: boolean
}

type Schema = {
  type?: string
  items?: Schema
  description?: string
  title?: string
  anyOf?: Schema[]
}

function kindOf(schema: Schema): FieldKind {
  const options = schema.anyOf ?? [schema]
  const concrete = options.find((option) => option.type !== "null") ?? schema
  if (concrete.type === "string") {
    return "text"
  }
  if (concrete.type === "number" || concrete.type === "integer") {
    return "number"
  }
  if (concrete.type === "array" && concrete.items?.type === "string") {
    return "list"
  }
  return "json"
}

export function fieldsOf(parameters: Record<string, unknown>): Field[] {
  const properties = (parameters.properties ?? {}) as Record<string, Schema>
  const required = new Set((parameters.required ?? []) as string[])
  return Object.entries(properties).map(([name, schema]) => ({
    name,
    label: schema.title ?? name.replaceAll("_", " "),
    kind: kindOf(schema),
    description: schema.description ?? "",
    required: required.has(name),
  }))
}

export function toValues(
  fields: Field[],
  args: Record<string, unknown>
): Record<string, string> {
  const values: Record<string, string> = {}
  for (const field of fields) {
    const value = args[field.name]
    if (value === undefined || value === null) {
      values[field.name] = ""
    } else if (field.kind === "list" && Array.isArray(value)) {
      values[field.name] = value.join("\n")
    } else if (field.kind === "json") {
      values[field.name] = JSON.stringify(value, null, 2)
    } else {
      values[field.name] = String(value)
    }
  }
  return values
}

export function toArguments(
  fields: Field[],
  values: Record<string, string>
): { ok: true; args: Record<string, unknown> } | { ok: false; error: string } {
  const args: Record<string, unknown> = {}
  for (const field of fields) {
    const raw = (values[field.name] ?? "").trim()
    if (raw === "") {
      if (field.required) {
        return { ok: false, error: `${field.label} is required.` }
      }
      continue
    }
    switch (field.kind) {
      case "text":
        args[field.name] = raw
        break
      case "number": {
        const number = Number(raw)
        if (Number.isNaN(number)) {
          return { ok: false, error: `${field.label} must be a number.` }
        }
        args[field.name] = number
        break
      }
      case "list":
        args[field.name] = raw
          .split(/[\n,]/)
          .map((item) => item.trim())
          .filter(Boolean)
        break
      case "json":
        try {
          args[field.name] = JSON.parse(raw)
        } catch {
          return { ok: false, error: `${field.label} is not valid JSON.` }
        }
    }
  }
  return { ok: true, args }
}

export function changed(
  before: Record<string, unknown>,
  after: Record<string, unknown>
): boolean {
  const canonical = (value: Record<string, unknown>) =>
    JSON.stringify(
      Object.keys(value)
        .sort()
        .map((key) => [key, value[key]])
    )
  return canonical(before) !== canonical(after)
}
