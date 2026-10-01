"use client"

import { useSource } from "@/components/recording/recording-provider"
import { cn } from "@/lib/utils"

export function ModeSwitch() {
  const source = useSource()
  if (!source.admin) {
    return null
  }
  const options = [
    { mode: "live", label: "Live", disabled: false },
    {
      mode: "recording",
      label: "Recording",
      disabled: source.recordings.length === 0,
    },
  ] as const
  return (
    <div
      role="group"
      aria-label="What the control room shows"
      className="grid grid-cols-2 gap-1 rounded-lg border p-1 text-xs group-data-[collapsible=icon]:hidden"
    >
      {options.map((option) => (
        <button
          key={option.mode}
          type="button"
          disabled={option.disabled}
          aria-pressed={source.mode === option.mode}
          onClick={() => source.setMode(option.mode)}
          className={cn(
            "rounded-md px-2 py-1 transition-colors disabled:opacity-40",
            source.mode === option.mode
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-muted"
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
