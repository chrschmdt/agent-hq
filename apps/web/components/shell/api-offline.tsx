import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function ApiOffline() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>The api is not reachable</CardTitle>
        <CardDescription>
          Start it with <code className="font-mono">make api</code>, or{" "}
          <code className="font-mono">make api-offline</code> to run without
          services, then reload this page.
        </CardDescription>
      </CardHeader>
    </Card>
  )
}
