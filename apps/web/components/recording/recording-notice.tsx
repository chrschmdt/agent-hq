"use client"

import { useSource } from "@/components/recording/recording-provider"
import { Card, CardContent } from "@/components/ui/card"

export function RecordingNotice() {
  const source = useSource()
  const text = source.loading
    ? "Loading the recorded day."
    : source.failed
      ? "The recorded day could not be loaded. Reload the page to try again."
      : "No recorded day is published yet. Once the admin publishes one, every page plays it back."
  return (
    <Card>
      <CardContent className="py-10 text-center text-sm text-muted-foreground">
        {text}
      </CardContent>
    </Card>
  )
}
