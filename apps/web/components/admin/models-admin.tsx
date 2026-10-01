"use client"

import { useRouter } from "next/navigation"
import { useTransition } from "react"
import { toast } from "sonner"

import { chooseProfile } from "@/app/actions"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { CatalogModel, ModelsView, ProfileView } from "@/lib/api/types"
import { moment, sentence } from "@/lib/format"
import { cn } from "@/lib/utils"

const ABOUT: Record<ProfileView["name"], string> = {
  mock: "Rule-based stand-ins play every role. Free, and no provider key needed.",
  low: "The cheapest models everywhere. Pennies a day; right for checking plumbing.",
  medium: "Sonnet 5.5 on the agents, Haiku 4.5 on routing and the input check.",
  high: "Opus 5.5 on the agents, Sonnet 5.5 on routing and the input check.",
}

const ROLES: { role: string; label: string }[] = [
  { role: "dispatcher", label: "Dispatcher" },
  { role: "support", label: "Support" },
  { role: "ops", label: "Ops" },
  { role: "insights", label: "Insights" },
  { role: "guard", label: "Input check" },
  { role: "qa", label: "QA reviewer" },
  { role: "customer", label: "Simulated customers" },
]

const PROVIDERS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
}

function price(value: number): string {
  return value === 0 ? "free" : `$${value.toFixed(value < 1 ? 3 : 2)}`
}

export function ModelsAdmin({ view }: { view: ModelsView }) {
  const router = useRouter()
  const [pending, startTransition] = useTransition()
  const byKey = new Map<string, CatalogModel>(
    view.models.map((model) => [model.key, model])
  )
  const choose = (profile: ProfileView["name"]) =>
    startTransition(async () => {
      const result = await chooseProfile(profile)
      if (!result.ok) {
        toast.error(result.error)
        return
      }
      toast.success(
        `Every role now plays on the ${profile} profile, from each piece of work's next step.`
      )
      router.refresh()
    })

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            Playing on
            <Badge className="text-sm capitalize">{view.profile}</Badge>
          </CardTitle>
          <CardDescription>
            {view.chosen_by && view.chosen_at
              ? `Picked by ${view.chosen_by} ${moment(view.chosen_at)}. `
              : `The deployment's default, until you pick one. `}
            A switch reaches work at its next step; the knowledge base keeps its
            embedder and reranker whatever the profile.
            {view.switchable
              ? ""
              : " This process plays one fixed profile and cannot switch."}
          </CardDescription>
        </CardHeader>
      </Card>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {view.profiles.map((profile) => {
          const current = profile.name === view.profile
          return (
            <Card
              key={profile.name}
              className={cn(
                "flex flex-col",
                current && "ring-2 ring-[var(--map-live)]"
              )}
            >
              <CardHeader>
                <CardTitle className="capitalize">{profile.name}</CardTitle>
                <CardDescription>{ABOUT[profile.name]}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col gap-3 text-sm">
                <dl className="flex flex-col gap-1.5">
                  {ROLES.map(({ role, label }) => {
                    const model = byKey.get(profile.roles[role] ?? "")
                    return (
                      <div key={role} className="flex justify-between gap-3">
                        <dt className="text-muted-foreground">{label}</dt>
                        <dd className="text-right font-mono text-xs">
                          {model?.key ?? profile.roles[role]}
                        </dd>
                      </div>
                    )
                  })}
                </dl>
                <p className="text-xs text-muted-foreground">
                  {profile.version_models
                    ? "Runs the model an agent version names, when it names one."
                    : "Keeps these models whatever a version names."}
                </p>
                <Button
                  className="mt-auto"
                  variant={current ? "secondary" : "default"}
                  disabled={current || !profile.available || pending}
                  onClick={() => choose(profile.name)}
                >
                  {current
                    ? "Playing now"
                    : profile.available
                      ? `Switch to ${profile.name}`
                      : "Needs a provider key"}
                </Button>
              </CardContent>
            </Card>
          )
        })}
      </section>

      <Card>
        <CardHeader>
          <CardTitle>The catalog</CardTitle>
          <CardDescription>
            Prices per million tokens. A model whose calls keep failing hands
            its calls to its fallback until its breaker closes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Model</TableHead>
                <TableHead>Served by</TableHead>
                <TableHead className="text-right">Input</TableHead>
                <TableHead className="text-right">Output</TableHead>
                <TableHead className="text-right">Cache read</TableHead>
                <TableHead className="text-right">Cache write</TableHead>
                <TableHead>Reasoning</TableHead>
                <TableHead>Fallback</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.models
                .filter((model) => model.key !== "fake")
                .map((model) => (
                  <TableRow key={model.key}>
                    <TableCell className="font-mono text-xs">
                      {model.id}
                    </TableCell>
                    <TableCell>
                      {PROVIDERS[model.provider] ?? sentence(model.provider)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {price(model.input)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {price(model.output)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {price(model.cache_read)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {price(model.cache_write)}
                    </TableCell>
                    <TableCell>{model.reasoning ? "adaptive" : ""}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {model.fallback ?? ""}
                    </TableCell>
                  </TableRow>
                ))}
              <TableRow>
                <TableCell className="font-mono text-xs">
                  {view.embeddings.id}
                </TableCell>
                <TableCell>Embeddings</TableCell>
                <TableCell className="text-right tabular-nums">
                  {price(view.embeddings.price)}
                </TableCell>
                <TableCell colSpan={5} />
              </TableRow>
              <TableRow>
                <TableCell className="font-mono text-xs">
                  {view.rerank.id}
                </TableCell>
                <TableCell>Reranking</TableCell>
                <TableCell className="text-right tabular-nums">
                  {price(view.rerank.price)}
                </TableCell>
                <TableCell colSpan={5} />
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
