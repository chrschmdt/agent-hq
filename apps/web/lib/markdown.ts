export type Block =
  | { kind: "heading"; level: 1 | 2 | 3; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }

export type Span = { text: string; bold?: boolean; code?: boolean }

export function blocks(markdown: string): Block[] {
  const result: Block[] = []
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length > 0) {
      result.push({ kind: "paragraph", text: paragraph.join(" ") })
      paragraph = []
    }
  }
  for (const raw of markdown.split("\n")) {
    const line = raw.trim()
    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    const bullet = /^[-*]\s+(.*)$/.exec(line)
    const numbered = /^\d+\.\s+(.*)$/.exec(line)
    if (line === "") {
      flush()
    } else if (heading) {
      flush()
      result.push({
        kind: "heading",
        level: heading[1].length as 1 | 2 | 3,
        text: heading[2],
      })
    } else if (bullet || numbered) {
      flush()
      const ordered = Boolean(numbered)
      const item = (bullet ?? numbered)![1]
      const last = result.at(-1)
      if (last?.kind === "list" && last.ordered === ordered) {
        last.items.push(item)
      } else {
        result.push({ kind: "list", ordered, items: [item] })
      }
    } else {
      paragraph.push(line)
    }
  }
  flush()
  return result
}

export function spans(text: string): Span[] {
  const result: Span[] = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let last = 0
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) {
      result.push({ text: text.slice(last, match.index) })
    }
    const token = match[0]
    result.push(
      token.startsWith("**")
        ? { text: token.slice(2, -2), bold: true }
        : { text: token.slice(1, -1), code: true }
    )
    last = match.index + token.length
  }
  if (last < text.length) {
    result.push({ text: text.slice(last) })
  }
  return result
}
