export const MAX_AGENT_TICKETS = 200

export function agentTicketsError(value: string): string | null {
  const text = value.trim()
  if (!/^\d+$/.test(text)) {
    return "Enter a whole number of tickets."
  }
  if (Number(text) > MAX_AGENT_TICKETS) {
    return `The agents can take at most ${MAX_AGENT_TICKETS} tickets.`
  }
  return null
}
