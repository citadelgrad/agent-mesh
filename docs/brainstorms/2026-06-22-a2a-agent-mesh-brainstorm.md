---
date: 2026-06-22
topic: a2a-agent-mesh
---

# Make the Agent Mesh Usable: Remote Specialists over A2A

## What We're Building

Turn the mesh from a single deployment with three hardcoded in-process
specialists into a real mesh of **independently-deployed specialist agents** that
join over the network. Specialists become standalone services exposed via the
**Agent2Agent (A2A) protocol**; they're catalogued in **GCP Agent Registry**; and
a **router agent stays the single front door** you talk to directly. The router
discovers what's available from the catalog and, per request, either delegates to
one best-fit specialist or fans out to several and synthesizes — no router
redeploy needed to add an agent.

This fixes the current core defect: the `ParallelDispatcher` only knows
in-process `BaseAgent` objects from a static dict built at startup
(`agent.py:38-45`), so `registry.register(...)` can advertise an agent the
dispatcher can never actually call.

## Why This Approach

Two GCP concepts were conflated in the original idea and we separated them:

- **Agent Registry** (`agentregistry.googleapis.com`) = the *catalog* — discovery
  and governance. Replaces the bookkeeping role of the SQLite `CapabilityRegistry`.
- **A2A protocol** (`RemoteA2aAgent`, `to_a2a()`) = the *transport* — the actual
  HTTP/JSON-RPC wire that lets the router call a remote agent. This is the missing
  piece; the registry alone doesn't make agents callable.

Cost analysis showed the discovery choice is price-neutral: the bill is dominated
by per-agent runtime (~$0.0864/vCPU-hr + $0.009/GB-hr) and model tokens,
identical across all options. The catalog itself is ~$0. So the choice was made on
governance value, not price — Agent Registry wins if other teams will also publish
agents we must find.

## Key Decisions

- **Agent model: independent deployed services over A2A.** Each specialist is its
  own deployment (Cloud Run / Agent Engine), wrapped with `to_a2a()`. Router calls
  them via `RemoteA2aAgent`.
- **Discovery: GCP Agent Registry**, accessed behind a thin `AgentCatalog`
  interface (one `list_agents() -> [AgentCard]` method). Mitigates Public-Preview
  API churn — when the API shifts, we patch one adapter, not the router. Catalog is
  seedable from static config as a fallback.
- **Router behavior: both modes, router chooses.** Narrow request → delegate to one
  specialist (ADK native transfer). Multi-capability request → fan-out + synthesize
  (today's pipeline, now over remote agents). Evolution of the existing router LLM,
  not a rewrite.
- **Health: reactive only.** Delete the background health monitor and the
  healthy/degraded/offline state machine. Catalog says what *exists*; a call that
  times out or errors says what's *down* — captured as
  `SpecialistResult(success=False)` and noted by the synthesizer. Lean on a short
  A2A call timeout (the `TimeoutAgentTool` pattern already does this).
- **First cut: extract one specialist (code-review) as the A2A pilot.** Keep
  web-search + summarizer in-process for now. Smallest change that exercises the
  full chain: deploy → register Agent Card → discover via catalog →
  `RemoteA2aAgent` → call → synthesize.
- **Catalog refresh: TTL cache (~5 min).** Router caches `list_agents()` and
  refreshes on expiry. New agents go live within the TTL window with no router
  redeploy; reactive health means a stale/dead entry just costs one timeout.
- **Agent Card source of truth: live card URL.** Registry stores only
  `{name, a2a_url}`; capabilities are read from the agent's own
  `/.well-known/agent-card`. One source of truth, never drifts, updates when the
  agent redeploys.

## What Gets Deleted / Changed (from today's code)

- `health_monitor.py` + the liveness state machine in `registry.py` → **gone**
  (reactive health).
- `CapabilityRegistry` (SQLite) → demoted to optional local fallback;
  authoritative catalog is GCP Agent Registry via the `AgentCatalog` adapter.
- `ParallelDispatcher.specialist_tools` static dict → built **dynamically** from
  the catalog; entries can be `RemoteA2aAgent` (remote) or local agents (during
  migration).
- Router gains a delegate-vs-fanout decision step; synthesizer largely unchanged.

## Open Questions (for planning)

- **A2A auth between router and remote agents** — service identity / IAM on
  Cloud Run vs. Agent Engine. Deferred to `/ce:plan` (it's HOW, not WHAT); likely
  router service-account ID token + `roles/run.invoker` on each agent.

## Resolved Questions

- **Catalog refresh timing** → TTL cache (~5 min). See Key Decisions.
- **Agent Card source of truth** → point at live card URL. See Key Decisions.

## Next Steps

→ `/ce:plan` for implementation details (pilot: extract code-review over A2A).
