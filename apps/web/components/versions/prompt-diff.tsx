import { diffLines } from "@/lib/management"
import { cn } from "@/lib/utils"

const TONE = {
  add: "bg-emerald-500/10 text-emerald-800 dark:text-emerald-200",
  remove: "bg-destructive/10 text-destructive",
  hunk: "text-sky-700 dark:text-sky-300",
  file: "text-muted-foreground",
  same: "text-muted-foreground",
}

export function PromptDiff({ lines }: { lines: string[] }) {
  if (lines.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        The prompts are identical.
      </p>
    )
  }
  return (
    <pre className="max-h-[36rem] overflow-auto rounded-lg border font-mono text-xs">
      {diffLines(lines).map((line, index) => (
        <div
          key={index}
          className={cn("px-3 whitespace-pre-wrap", TONE[line.kind])}
        >
          {line.text || " "}
        </div>
      ))}
    </pre>
  )
}
