import { expect, type Page, test } from "@playwright/test"

test.beforeEach(async ({ context }) => {
  await context.addCookies([
    { name: "sidebar_state", value: "true", url: "http://localhost:3000" },
  ])
})

test("the sidebar starts folded to its icons and opens from its foot", async ({
  page,
  context,
}) => {
  await context.clearCookies()
  await page.goto("/overview")
  const sidebar = page.locator('[data-slot="sidebar"]').first()
  await expect(sidebar).toHaveAttribute("data-state", "collapsed")
  await page.getByRole("button", { name: "Expand sidebar" }).click()
  await expect(sidebar).toHaveAttribute("data-state", "expanded")
  await page.reload()
  await expect(sidebar).toHaveAttribute("data-state", "expanded")
})

test("a visitor opens an order from an approval, then its customer, and goes back", async ({
  page,
}) => {
  const [day] = (await (await page.request.get("/api/recordings")).json()) as {
    id: string
  }[]
  const recording = (await (
    await page.request.get(`/api/recordings/${day.id}`)
  ).json()) as { approvals: { record: { id: string } }[] }
  await page.goto(`/approvals/${recording.approvals[0].record.id}`)
  await expect(page.getByRole("button", { name: "1440x" })).toBeVisible()

  await page.getByText("For order").getByRole("button").click()
  const drawer = page.locator('[data-slot="sheet-content"]')
  await expect(drawer.getByText("During the day")).toBeVisible()
  await expect(drawer.getByText(/Waited for a person to approve/)).toBeVisible()

  await drawer
    .getByText("for", { exact: true })
    .locator("..")
    .getByRole("button")
    .click()
  await expect(drawer.getByText("Payment methods")).toBeVisible()
  await drawer.getByRole("button", { name: "Back" }).click()
  await expect(drawer.getByRole("heading", { name: "Items" })).toBeVisible()
})

async function count(page: Page, path: string): Promise<number> {
  const response = await page.request.get(path)
  return ((await response.json()) as unknown[]).length
}

test("visitors watch the recorded day and see nothing of the admin's", async ({
  page,
}) => {
  await page.goto("/overview")
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Play simulated day" })
  ).toBeVisible()
  await expect(page.getByText("Late deliveries")).toBeVisible()
  await expect(page.getByText("Spend and limits")).toHaveCount(0)

  for (const path of [
    "/admin/models",
    "/admin/simulator",
    "/admin/spend",
    "/admin/data",
  ]) {
    const response = await page.goto(path)
    expect(response?.status()).toBe(404)
  }
  expect((await page.request.get("/api/limits")).status()).toBe(401)
  const cleared = await page.request.post("/api/activity/clear", { data: {} })
  expect(cleared.status()).toBe(401)
  const refused = await page.request.post("/api/sim/start", {
    data: { scenario: "normal-day" },
  })
  expect(refused.status()).toBe(401)
})

test("every page follows the recorded day as it plays", async ({ page }) => {
  await page.goto("/overview")
  await page.getByRole("button", { name: "Play simulated day" }).click()
  await page.getByRole("button", { name: "Pause" }).click()
  await page.getByRole("button", { name: /^Incident/ }).click()
  await page.getByRole("button", { name: "Pause" }).click()
  await expect(page.getByText(/model calls ·/).first()).toBeVisible()

  await page.getByRole("link", { name: "Incidents", exact: true }).click()
  await expect(
    page.getByText(/Where-is-my-order tickets spiked/).first()
  ).toBeVisible()
  await page.getByLabel("Position in the day").fill("0")
  await expect(
    page.getByText("None filed yet at this point of the recorded day.")
  ).toBeVisible()

  const [recording] = (await (
    await page.request.get("/api/recordings")
  ).json()) as { id: string }[]
  const day = (await (
    await page.request.get(`/api/recordings/${recording.id}`)
  ).json()) as { runs: Record<string, { item: { kind: string } }> }
  const [alert] = Object.entries(day.runs).find(
    ([, run]) => run.item.kind === "alert"
  ) ?? [""]
  await page.goto(`/runs/${alert}`)
  await expect(page.getByText("The agent loop")).toBeVisible()
  await expect(page.getByText("Ops, pass 1", { exact: true })).toBeVisible()
  await expect(page.getByText(/Rule: /).first()).toBeVisible()
  await page.getByLabel("Position in the day").fill("0")
  await expect(page.getByText(/has not started yet/)).toBeVisible()
  await page.getByRole("button", { name: "1440x" }).click()
  await page.getByRole("button", { name: "Play" }).click()
  await expect(page.getByText("The agent loop")).toBeVisible({
    timeout: 90_000,
  })
})

test("the admin plays a carrier delay and publishes the notice Insights drafts", async ({
  page,
}) => {
  const incidentsBefore = await count(page, "/api/incidents")
  await page.goto("/overview")
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible()

  await page.goto("/admin/simulator")
  await page.getByRole("combobox").first().click()
  await page.getByRole("option", { name: "carrier-delay" }).click()
  await page.getByLabel("Tickets for the agents (0 to 200)").fill("2")
  await page.getByRole("button", { name: /Start/ }).click()
  await expect(page.getByText("The day has started.")).toBeVisible()

  await expect
    .poll(() => count(page, "/api/incidents"), {
      timeout: 150_000,
      intervals: [2000],
    })
    .toBeGreaterThan(incidentsBefore)

  await page.goto("/incidents")
  await page
    .getByText(
      "Where-is-my-order tickets spiked for Northstar in the Northeast"
    )
    .first()
    .click()
  await expect(
    page.getByText("Suspected cause:", { exact: true })
  ).toBeVisible()
  await expect(page.getByText("How it unfolded")).toBeVisible()
  await expect(page.getByText(/Ops filed the incident/)).toBeVisible()
  await page
    .getByRole("link", { name: /Publish a delivery delay notice/ })
    .click()

  await expect(page.getByText("Draft article")).toBeVisible()
  await page.getByRole("button", { name: "Approve and publish" }).click()
  await expect(
    page.getByText("Approved, and the article is published.")
  ).toBeVisible()
  await expect(page.getByText(/approved by/)).toBeVisible()

  await page.goto("/work")
  await page.getByRole("tab", { name: "Alerts" }).click()
  await page
    .getByText(/Alert: northstar, northeast/)
    .first()
    .click()
  await expect(page.getByRole("heading", { name: "Run" })).toBeVisible()
  await expect(page.getByText("Timeline")).toBeVisible()
  await expect(page.getByText("Ops, pass 1", { exact: true })).toBeVisible()
})

async function signIn(page: Page) {
  await page.goto("/overview")
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible()
}

type Version = { status_reason: string | null }

test("a bad change ships as a canary and is rolled back on its own", async ({
  page,
}) => {
  await signIn(page)
  await page.goto("/admin/simulator")
  await page.getByRole("combobox").first().click()
  await page.getByRole("option", { name: "bad-deploy" }).click()
  await expect(
    page.getByLabel("Tickets for the agents (0 to 200)")
  ).toHaveValue("20")
  await page.getByRole("combobox").nth(1).click()
  await page.getByRole("option", { name: /under 3 minutes/ }).click()
  await page.getByRole("button", { name: /Start/ }).click()
  await expect(page.getByText("The day has started.")).toBeVisible()

  const rolledBack = async () => {
    const response = await page.request.get("/api/versions?agent=support")
    const versions = (await response.json()) as Version[]
    return versions.some((v) => v.status_reason?.startsWith("rolled back"))
  }
  await expect
    .poll(rolledBack, { timeout: 150_000, intervals: [2000] })
    .toBe(true)

  await page.goto("/agents/support")
  await expect(
    page.getByText(/rolled back: escalation rate/).first()
  ).toBeVisible()
  await expect(page.getByText("Scorecard", { exact: true })).toBeVisible()
})

test("the admin drafts a version and passes it through the eval gate", async ({
  page,
}) => {
  await signIn(page)
  await page.goto("/agents/dispatcher")
  await page.getByRole("button", { name: "New version" }).click()
  await page.getByLabel("Dollars per work item").fill("0.03")
  await page
    .getByLabel("What changed and why")
    .fill("A little more room per decision.")
  await page.getByRole("button", { name: "Save as a draft" }).click()
  await expect(
    page.getByRole("heading", { name: /dispatcher v\d/ })
  ).toBeVisible()
  await expect(page.getByText("max usd")).toBeVisible()

  await page.goto("/agents/dispatcher")
  await page.getByRole("button", { name: "Run eval gate" }).first().click()
  await page.getByRole("button", { name: "Run the gate" }).click()
  await expect(page.getByText("The eval gate is running.")).toBeVisible()

  const status = async () => {
    const response = await page.request.get("/api/evals")
    const runs = (await response.json()) as { status: string; agent: string }[]
    return runs.find((run) => run.agent === "dispatcher")?.status
  }
  await expect
    .poll(status, { timeout: 60_000, intervals: [1000] })
    .toBe("passed")

  await page.goto("/evals")
  await page
    .getByRole("link", { name: /dispatcher v\d/ })
    .first()
    .click()
  await expect(
    page.getByText(/Passed: dispatcher v\d may go on to a canary/)
  ).toBeVisible()
})

test("attacks on the assistant are held for a person and counted", async ({
  page,
}) => {
  await signIn(page)
  await page.goto("/admin/simulator")
  await page.getByRole("combobox").first().click()
  await page.getByRole("option", { name: "prompt-injection" }).click()
  await expect(
    page.getByText("Its 6 extra customers go to the agents in any case.")
  ).toBeVisible()
  await page.getByRole("combobox").nth(1).click()
  await page.getByRole("option", { name: /under 3 minutes/ }).click()
  await page.getByRole("button", { name: /Start/ }).click()
  await expect(page.getByText("The day has started.")).toBeVisible()

  const blocked = async () => {
    const response = await page.request.get("/api/guardrails")
    return ((await response.json()) as { inputs_blocked: number })
      .inputs_blocked
  }
  await expect
    .poll(blocked, { timeout: 150_000, intervals: [2000] })
    .toBeGreaterThan(0)

  await page.goto("/quality")
  await page.getByRole("tab", { name: "Guardrails" }).click()
  await expect(
    page.getByText("messages held for a person by the input check")
  ).toBeVisible()
  await expect(page.getByText(/input, injection/).first()).toBeVisible()

  await page.goto("/overview")
  await expect(page.getByText("Cost per resolved ticket")).toBeVisible()
})

test("the admin switches profiles, and records a day visitors can then watch", async ({
  page,
}) => {
  await signIn(page)
  await page.goto("/admin/models")
  await expect(page.getByText("Playing on")).toBeVisible()
  await expect(page.getByRole("button", { name: "Playing now" })).toBeVisible()
  await expect(
    page.getByText(
      "Opus 5.5 on the agents, Sonnet 5.5 on routing and the input check."
    )
  ).toBeVisible()

  const before = await count(page, "/api/recordings")
  await page.goto("/admin/simulator")
  await page.getByRole("combobox").first().click()
  await page.getByRole("option", { name: "normal-day" }).click()
  await page.getByRole("button", { name: /Start/ }).click()
  await expect(page.getByText("The day has started.")).toBeVisible()
  await page.getByRole("button", { name: "Stop" }).click()
  await expect(page.getByText("Stopped.")).toBeVisible()

  await page.goto("/admin/recordings")
  await page.getByRole("button", { name: "Record and publish" }).first().click()
  await expect(
    page.getByText("Recorded and published. Visitors see it now.")
  ).toBeVisible()
  expect(await count(page, "/api/recordings")).toBe(before + 1)

  await page.getByRole("button", { name: "Recording", exact: true }).click()
  await page.goto("/overview")
  await expect(
    page.getByRole("button", { name: "Play simulated day" })
  ).toBeVisible()
})

test("the admin clears the activity, and the recorded day stays", async ({
  page,
}) => {
  const recordings = await count(page, "/api/recordings")
  await signIn(page)
  await page.goto("/admin/data")
  const clear = page.getByRole("button", { name: "Clear the activity" })
  await expect(clear).toBeEnabled({ timeout: 90_000 })
  await clear.click()
  await page.getByRole("button", { name: "Clear it all" }).click()
  await expect(page.getByText(/^Cleared [\d,]+ records\./)).toBeVisible()
  expect(await count(page, "/api/work")).toBe(0)
  expect(await count(page, "/api/recordings")).toBe(recordings)

  await page.goto("/overview")
  await expect(page.getByText("Nothing running live")).toBeVisible()
  await page.getByRole("button", { name: "Recording", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Play simulated day" })
  ).toBeVisible()
})
