import { blocks, spans } from "@/lib/markdown"

function Inline({ text }: { text: string }) {
  return (
    <>
      {spans(text).map((span, index) =>
        span.code ? (
          <code key={index} className="rounded bg-muted px-1 font-mono text-xs">
            {span.text}
          </code>
        ) : span.bold ? (
          <strong key={index}>{span.text}</strong>
        ) : (
          <span key={index}>{span.text}</span>
        )
      )}
    </>
  )
}

export function Article({ markdown }: { markdown: string }) {
  return (
    <article className="flex flex-col gap-3 text-sm leading-relaxed">
      {blocks(markdown).map((block, index) => {
        switch (block.kind) {
          case "heading":
            return block.level === 1 ? (
              <h2 key={index} className="text-lg font-semibold">
                <Inline text={block.text} />
              </h2>
            ) : (
              <h3 key={index} className="pt-2 font-semibold">
                <Inline text={block.text} />
              </h3>
            )
          case "paragraph":
            return (
              <p key={index}>
                <Inline text={block.text} />
              </p>
            )
          case "list": {
            const List = block.ordered ? "ol" : "ul"
            return (
              <List
                key={index}
                className={
                  block.ordered ? "list-decimal pl-5" : "list-disc pl-5"
                }
              >
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>
                    <Inline text={item} />
                  </li>
                ))}
              </List>
            )
          }
        }
      })}
    </article>
  )
}
