+++
doc_id = "runbook-carrier-delay"
title = "Responding to a carrier delay"
namespace = "runbooks"
audience = "internal"
version = 1
effective_date = 2026-01-01
+++

# Responding to a carrier delay

Use this runbook when late deliveries rise for one carrier.

## Detect

Compare each carrier's late delivery rate by region with its recent baseline. A jump concentrated in one carrier and
one region is a carrier incident; a rise across all carriers suggests weather or volume.

## Respond

1. File an incident naming the carrier, the region, the time the rise started, and the affected order IDs.
2. Draft a help center notice about the delay for affected customers.
3. Tell support agents which carrier and region are affected, so they can answer "where is my order" quickly.

## Close

Close the incident when the carrier's late rate in that region returns to its baseline for a full day.
