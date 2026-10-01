"use client"

import { RecordingNotice } from "@/components/recording/recording-notice"
import { useDay, useRecorded } from "@/components/recording/recording-provider"
import { DrawerLink } from "@/components/shell/drawer-context"
import { Severity } from "@/components/team/severity"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { Incident } from "@/lib/api/types"
import { moment } from "@/lib/format"
import { incidentsAt } from "@/lib/recording/derive"

export function IncidentsList({ live }: { live: Incident[] | null }) {
  const day = useDay()
  const recorded = useRecorded(incidentsAt)
  const incidents = recorded.recording ? recorded.data : live
  if (!incidents) {
    return <RecordingNotice />
  }
  return (
    <>
      {incidents.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No incidents</CardTitle>
            <CardDescription>
              {recorded.recording
                ? "None filed yet at this point of the recorded day."
                : "Play the carrier-delay day with alerts going to the agents to see one filed."}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {incidents.map((incident) => (
            <DrawerLink
              key={incident.incident_id}
              target={{ kind: "incident", id: incident.incident_id }}
              className="block"
            >
              <Card className="transition-colors hover:bg-muted/40">
                <CardContent className="flex flex-col gap-1.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{incident.report.title}</span>
                    <div className="flex items-center gap-2">
                      <Severity level={incident.report.severity} />
                      <span className="text-xs text-muted-foreground">
                        detected {moment(day(incident.detected_at))}
                      </span>
                    </div>
                  </div>
                  <p className="line-clamp-2 text-sm text-muted-foreground">
                    {incident.report.summary}
                  </p>
                </CardContent>
              </Card>
            </DrawerLink>
          ))}
        </div>
      )}
    </>
  )
}
