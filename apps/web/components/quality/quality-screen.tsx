"use client"

import { CalibrationView } from "@/components/quality/calibration-view"
import { GuardrailsView } from "@/components/quality/guardrails-view"
import { ReviewsTable } from "@/components/quality/reviews-table"
import { RecordingNotice } from "@/components/recording/recording-notice"
import { useRecorded } from "@/components/recording/recording-provider"
import { Card, CardContent } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type {
  CriterionCalibration,
  GuardrailSummary,
  ReviewRecord,
} from "@/lib/api/types"
import { guardrailsAt, reviewsAt } from "@/lib/recording/derive"

export function QualityScreen({
  live,
  calibration,
}: {
  live: { reviews: ReviewRecord[]; guardrails: GuardrailSummary } | null
  calibration: CriterionCalibration[]
}) {
  const recorded = useRecorded((prepared, cursor) => ({
    reviews: reviewsAt(prepared, cursor),
    guardrails: guardrailsAt(prepared, cursor),
  }))
  const shown = recorded.recording ? recorded.data : live
  if (!shown) {
    return <RecordingNotice />
  }
  return (
    <Tabs defaultValue="reviews">
      <TabsList>
        <TabsTrigger value="reviews">Reviews</TabsTrigger>
        <TabsTrigger value="calibration">Calibration</TabsTrigger>
        <TabsTrigger value="guardrails">Guardrails</TabsTrigger>
      </TabsList>
      <TabsContent value="reviews">
        <Card>
          <CardContent>
            <ReviewsTable reviews={shown.reviews} />
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="calibration">
        <Card>
          <CardContent>
            <CalibrationView report={calibration} />
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="guardrails">
        <Card>
          <CardContent>
            <GuardrailsView summary={shown.guardrails} />
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  )
}
