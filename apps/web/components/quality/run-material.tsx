import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import type { LabelTask } from "@/lib/api/types"
import { cn } from "@/lib/utils"

const SPEAKERS: [string, string][] = [
  ["customer:", "text-sky-700 dark:text-sky-300"],
  ["work:", "text-sky-700 dark:text-sky-300"],
  ["agent calls", "text-muted-foreground"],
  ["tool ", "text-muted-foreground"],
  ["automatic check:", "text-amber-700 dark:text-amber-300"],
  ["agent:", "text-foreground"],
]

function tone(line: string): string {
  return (
    SPEAKERS.find(([start]) => line.startsWith(start))?.[1] ??
    "text-muted-foreground"
  )
}

export function RunMaterial({ material }: { material: LabelTask["material"] }) {
  return (
    <div className="flex flex-col gap-3 text-sm">
      <div>
        <p className="mb-1 text-xs text-muted-foreground uppercase">The work</p>
        <p className="whitespace-pre-wrap">{material.brief}</p>
      </div>
      <div>
        <p className="mb-1 text-xs text-muted-foreground uppercase">The run</p>
        <div className="max-h-[28rem] overflow-auto rounded-lg border p-3 font-mono text-xs">
          {material.transcript.split("\n").map((line, index) => (
            <p key={index} className={cn("whitespace-pre-wrap", tone(line))}>
              {line}
            </p>
          ))}
        </div>
      </div>
      <Collapsible className="rounded-lg border">
        <CollapsibleTrigger className="w-full px-3 py-2 text-left text-xs font-medium">
          Final answer
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t px-3 py-2">
          <pre className="font-mono text-xs whitespace-pre-wrap">
            {JSON.stringify(material.answer, null, 2)}
          </pre>
        </CollapsibleContent>
      </Collapsible>
      {material.passages && material.passages.length > 0 ? (
        <Collapsible className="rounded-lg border">
          <CollapsibleTrigger className="w-full px-3 py-2 text-left text-xs font-medium">
            {material.passages.length} passages retrieved
          </CollapsibleTrigger>
          <CollapsibleContent className="flex flex-col gap-2 border-t px-3 py-2 text-xs">
            {material.passages.map((passage) => (
              <p key={passage} className="whitespace-pre-wrap">
                {passage}
              </p>
            ))}
          </CollapsibleContent>
        </Collapsible>
      ) : null}
    </div>
  )
}
