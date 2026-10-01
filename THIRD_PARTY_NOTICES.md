# Third-party notices

## τ³-bench (tau2-bench) v1.0.1

- Source: <https://github.com/sierra-research/tau2-bench>, tag `v1.0.1`
- Copyright (c) 2025 Sierra Research
- License: MIT, reproduced in [`data/tau3/v1.0.1/LICENSE`](data/tau3/v1.0.1/LICENSE)

AHQ uses the benchmark's retail domain:

- **Data, vendored unchanged** in `data/tau3/v1.0.1/`: the store database (`db.json`), the tasks and their split,
  and the store policy. [`SOURCE.md`](data/tau3/v1.0.1/SOURCE.md) lists the upstream paths and checksums.
- **Code, ported:** the retail tools' rules and error messages are ported to `apps/api/ahq/retail/`, with one
  fix: `modify_pending_order_items` prices each swapped item by its own new variant, where upstream applies the last
  variant's price to all of them.
- **Code, run as a reference:** `scripts/record_tau3_reference.py` runs upstream's own tools to record the replays
  the port is tested against.
- **Text, copied unchanged into the api package**, which is deployed without the repository's `data/` folder: the
  store policy as `apps/api/ahq/agents/support/tau3_policy.md` (Support's prompt includes it, and a test keeps it
  identical to the vendored copy), and the user simulator's guidelines as `apps/api/ahq/sim/customer_guidelines.md`
  (from `data/tau2/user_simulator/simulation_guidelines.md`).
- **Code, ported:** the user simulator's scenario layout and stop tokens (`apps/api/ahq/sim/customer.py`), the
  natural-language assertion judge's instructions (`apps/api/ahq/grading/judge.py`), and the agent's greeting.
