# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: RetailSupplierQualitySLAScorecardAgent
- **L1 Base**: AgentBaseGraph
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

> **Node mapping note:** The proposal describes four logical blocks
> (PreProcess → KPIScoring[4 tools + Subcontract Act flags] →
> DocGeneration[LLM narrative] → Output[JSON/MD assembly + S-4]), but
> `AgentBaseGraph` exposes exactly 3 fixed domain slots
> (`pre_process`/`main`/`post_process`) — there is no framework mechanism to
> register a 4th slot. KPIScoring and DocGeneration are grouped into the
> same `main` `FunctionNode`: KPIScoring's tool-computed scores and
> Subcontract Act flags are finalized first (deterministic, no LLM), then
> DocGeneration's LLM call runs against that already-finalized data within
> the same `execute()`. This keeps the LLM narrative layer strictly
> downstream of, and unable to alter, the deterministic KPI/compliance
> results (proposal §11 Risk #1 mitigation — LLM affects narrative only,
> never the numbers). Output/S-4 assembly remains a separate concern in
> `post_process`.

## Architecture Overview

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | Sets `schema_version`, `session_id`, `trust_level` | `input_context` | `session_id`, `correlation_id`, `caller_trust_level` | InitializeNode (default) |
| pre_process | S-2 input validation (schema/payload); supplier ID resolution; evaluation-period date normalization; missing-KPI-field detection | `user_input` (supplier performance payload), `input_context` (evaluation period, supplier ID map) | `suppliers`, `evaluation_period`, `missing_field_flags`, `status` | `FunctionNode` |
| main | KPIScoringNode: 4-dimension KPI scoring (on-time delivery, defect PPM, invoice error rate, responsiveness SLA) + Subcontract Act Article 4 flag check, then DocGenerationNode: LLM-generated scorecard narrative against the finalized scores/flags | `suppliers`, `evaluation_period`, `missing_field_flags` | `kpi_scores`, `subcontract_act_flags`, `scorecard_narrative`, `status` | `FunctionNode` (DocGenerationAgent pattern + ToolCallingAgent sub-pattern for KPI tools) |
| post_process | S-3 output sanitization; JSON scorecard assembly; Markdown report assembly; S-4 Subcontract Act compliance evidence audit log | `kpi_scores`, `subcontract_act_flags`, `scorecard_narrative` | `formatted_output`, `status` | `FunctionNode` |
| finalize | Builds `response_metadata`, `total_time_ms` | `formatted_output` | (response envelope) | FinalizeNode (default) |

### Data Flow

```
START → initialize → pre_process → main → {route} → post_process → finalize → END
                                            ↓ (retry, max_retry per config.yaml)
                                          pre_process
```

- `main` returns `status=retry` only on a soft failure (e.g. transient LLM
  error during DocGeneration) — routes back to `pre_process` up to
  `max_retry`. KPI/Subcontract Act results already computed in that attempt
  are discarded and recomputed on retry (main is stateless per node-contract.md).
- `main` returns `status=error` on a hard failure (e.g. zero suppliers with
  usable data after `pre_process`) — routes to `finalize` directly.

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `evaluation_period` | `dict` (`{"start_date": str, "end_date": str}`) | Caller-supplied evaluation window, normalized by `pre_process` | Yes |
| `suppliers` | `list[dict]` | Normalized per-supplier records, each `{"supplier_id": str, "delivery_records": list[dict], "defect_return_logs": list[dict], "invoice_records": list[dict], "responsiveness_log": list[dict]}` — supplier IDs resolved to the canonical form via `pre_process` | Set by `pre_process` |
| `missing_field_flags` | `list[dict]` | Per-supplier record of which KPI input fields were absent, each `{"supplier_id": str, "missing_fields": list[str]}` | Set by `pre_process` |
| `kpi_scores` | `list[dict]` | Per-supplier KPI results, each `{"supplier_id": str, "on_time_delivery_rate": float, "defect_ppm": float, "invoice_error_rate": float, "responsiveness_sla_score": float, "missing_scores": list[str]}` | Set by `main` (KPIScoringNode) |
| `subcontract_act_flags` | `list[dict]` | Per-supplier Subcontract Act Article 4 determination, each `{"supplier_id": str, "unjustified_return_rate_flag": bool, "payment_delay_flag": bool, "determination_rationale": str}` | Set by `main` (KPIScoringNode) |
| `scorecard_narrative` | `list[dict]` | Per-supplier LLM-generated narrative sections, each `{"supplier_id": str, "kpi_trend_narrative": str, "corrective_recommendations": list[str], "gx_scope3_notes": str}` | Set by `main` (DocGenerationNode) |
| `formatted_output` | `dict` | Final assembled payload: `{"json_scorecard": dict, "markdown_report": str}` | Set by `post_process` |

All list/dict fields above are plain (not `Annotated[..., operator.add]`) —
each node fully replaces its own output fields; there is no accumulator
pattern needed since `pre_process` → `main` → `post_process` is a strict
linear handoff, not a fan-in across multiple upstream nodes.

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)
- Supplier transaction data is confidential business data, not personal
  information under APPI (proposal §10 Angle 5) — no PII-specific handling
  required, but if supplier contact *names* appear in raw payloads,
  `pre_process` should mask them (proposal §10 note); tracked as a design
  follow-up, not a v1 blocker

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id; caller-supplied
      `evaluation_period` read from `input_context` in `pre_process`)
- [ ] ConnectionPolicy (retry/timeout strategy) — not needed; LLM call in
      `main` uses framework-default single-pass retry via `status=retry` routing
- [x] SecurityViolationError — raised if `pre_process` receives a caller
      below `required_trust_level`
- [x] S-2: `_extra_security_gate_input()` on `pre_process` —
      payload schema validation (required top-level fields present) and
      confidential-business-data guard; rejects by setting
      `state["status"] = AgentStatus.ERROR.value`, does not raise
- [x] S-3: `_extra_security_gate_output()` on `post_process` —
      re-scan `formatted_output` for credential-shaped and PII-shaped
      patterns before it leaves the node (belt-and-suspenders; supplier
      transaction data is not expected to contain either)
- [x] S-4: `emit_trace_event()` — at least one domain-specific event inside
      each `execute()`:
      - `pre_process`: `suppliers_normalized` `{supplier_count, missing_field_count}`
      - `main`: `kpi_scored` `{supplier_count, subcontract_act_flag_count}` and
        `llm_call` `{model, tokens}`
      - `post_process`: `scorecard_assembled` `{supplier_count}` — this event
        **is** the Subcontract Act compliance evidence audit log required by
        the proposal (§4 Step 5); its payload includes
        `subcontract_act_flags` and `determination_rationale` per supplier

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

All three domain nodes in this template are plain `FunctionNode` subclasses —
no `GraphNode`/`RemoteAgentNode` composition is used, so no no-op gate
override applies.

### Composition Pattern

- **Pattern**: Standalone (all three domain nodes are direct `FunctionNode`
  instances registered in `register_nodes()`; no subgraph, no remote agent
  composition)
- **Composition target**: N/A — this template is a leaf endpoint, callable
  directly by procurement systems or batch jobs; it is not itself composed
  from another agent, though the proposal notes it forms one half of a
  future "Supply Chain Quality Bundle" alongside a sibling template
  (separate templates, not a runtime composition)
- **Error propagation strategy**: propagate — `main`'s hard failures
  (`status=error`, e.g. no suppliers with usable KPI input after
  `pre_process`) route straight to `finalize` and surface in `error_log`;
  soft failures (`status=retry`, e.g. transient LLM error during
  DocGeneration) route back to `pre_process` up to `max_retry`

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Fixed pipeline (data receipt → scoring → compliance flags → report), no self-directed think→act loop; termination is pipeline-determined (proposal §1 Cat 2, confirmed in docs/01_proposal.md) |
| KPIScoring + DocGeneration placement | Split across `main` (KPIScoring only) and `post_process` (DocGeneration + Output) | Both in `main`; `post_process` is Output-only | **Both in `main`** | Keeps the deterministic/LLM boundary at the intra-node level: KPI scores and Subcontract Act flags are finalized by tool logic *before* the LLM call runs in the same `execute()`, so the LLM structurally cannot influence the numbers (proposal §11 Risk #1). `post_process` stays a pure formatting/audit concern, matching its role in the framework's fixed 3-slot pipeline |
| Subcontract Act rule source | Hardcode thresholds in node code | External `config/subcontract_rules.yaml` | **External YAML config** | Proposal §11 Risk #2 (rule config going stale on law revision) requires the rules to be updatable without redeployment; proposal explicitly designs `config/subcontract_rules.yaml` with revision-date metadata for this reason |
| KPI threshold source | Hardcode per-KPI thresholds in node code | External `config/kpi_thresholds.yaml` | **External YAML config** | Proposal §4 note: thresholds must be configurable per evaluation cycle without redeployment; matches the Subcontract Act rule config precedent above |
| Missing KPI field handling | Fail the whole supplier record | Null score + explicit missing flag, degrade gracefully | **Null score + missing flag** | Proposal §11 Risk #4 (low severity): missing invoice error rate data, etc. should not block scoring for the supplier's other dimensions; `pre_process` flags the gap and the scorecard explicitly states "data not available" rather than silently omitting the supplier |
| LLM narrative failure handling | Always fall back silently, never retry | Fall back per-supplier; retry (`status=RETRY`) only when every supplier in the batch fell back | **Fall back per-supplier + full-batch retry** | `max_retry` (config/agent.yaml) is graph-level — the router re-enters `pre_process` only when a node returns `status=RETRY`. A single supplier's malformed LLM response is a one-off glitch — fail-soft via `fallback_narrative()` is preferable to retrying the whole batch over one bad response. But every supplier falling back in the same pass indicates the LLM itself is unavailable/broken, not a one-off — in that case `MainNode` returns `status=RETRY` so `max_retry` actually has an effect, instead of always silently degrading to fallback narratives regardless of failure scope |
