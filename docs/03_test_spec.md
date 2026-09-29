# Test Specification

## Test Strategy
- Coverage target: 100% of TC/PB items below; every real `FunctionNode`
  (`PreProcessNode`, `MainNode`, `PostProcessNode`) covers success +
  error/edge path; `KPIScoringNode` (step-helper,
  not a framework node) is unit-tested directly since it carries the
  Subcontract Act compliance determination logic
- Test types: Unit (per-node/per-step, mocked LLM) / Proof-of-Boundary
  (framework contract) — no Integration suite in this iteration (see
  docs/02_design.md Composition Pattern: standalone pipeline, no subgraph
  to integration-test beyond the unit-tested nodes/step)
- LLM is injected via `MainNode(llm, ...)` constructor — all unit tests use
  a `FakeLLM` stub, no real Anthropic API calls

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Type check pass, no Pydantic/dataclass | Pass |
| TC-02 | SecurityViolationError fires on invalid input | Error raised | Pass |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations (S-5 enforcement moved to CI) | Pass |
| TC-04 | InvocationContext via configurable only | Direct access raises error | N/A — this agent does not call `ctx.secrets.require()` in any node (LLM instance is injected at graph construction, not resolved via secrets inside `execute()`); `ANTHROPIC_API_KEY` is resolved once by `AnthropicClient` outside the node boundary |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from `execute()` body | 0 duplicates |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-08 | `required_trust_level` enforced | Insufficient trust → refused | Pass — manifest declares `VERIFIED_EXTERNAL` at agent level (config/agent.yaml); all 3 domain `FunctionNode`s declare `required_trust_level` explicitly. `KPIScoringNode` has no trust level of its own — it is a step-helper called from inside `MainNode.execute()`, gated entirely by `MainNode`'s S-1 |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial when domain checks needed | Domain-specific input checks execute correctly (e.g. PII scan on additional fields, consent validation, business rules) | Hook body non-trivial — `PreProcessNode` enforces the 5,000-record payload size cap, JSON shape validation, and evaluation-period date validation |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial when domain checks needed | Domain-specific output checks execute correctly (e.g. nested credential scan, PII re-check, content filtering, preservation verification) | Hook body non-trivial — `MainNode` rejects malformed per-supplier narratives; `PostProcessNode` blocks output whose Markdown report contains PII-shaped patterns |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | Domain event emitted on every invocation path | ≥1 per node — `suppliers_normalized` (pre_process), `kpi_scored` + `llm_call` (main), `scorecard_assembled` (post_process — this event is the Subcontract Act compliance evidence audit log) |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures | Pass |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | Pass — all fields are `str`/`float`/`bool`/`list`/`dict` (docs/02_design.md State Definition); runtime-verified by a msgpack round-trip on `formatted_output` |
| PB-3 | Level 2 → External service | Real external service connection | Data retrieved | N/A — this template has no external DB/ERP dependency at the node level (CSV/JSON payload is caller-supplied); its only external service is the LLM, exercised via `FakeLLM` in unit tests (real connectivity is an STG-stage manual check, not a unit PB) |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | Pass |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | Pass |
| PB-6 | Invoke execution order + S-1 trust gate | `__call__()`: S-1 trust gate → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete`; ANONYMOUS caller rejected on every node with `required_trust_level > ANONYMOUS` | Order verified; unauthorized caller rejected | Pass — order in `test_pb_invoke_order.py`; ANONYMOUS-caller rejection explicitly exercised via `__call__()` in `test_pb04_s1_trust_gate.py` (Turn-1 review FINDING-03: `test_pb_invoke_order.py` always passed the node's own `required_trust_level` as `caller_trust_level`, so the rejection path was never tried). File-name suffix `04` is a domain test filename, not a re-numbering of the PB-4 Import Isolation item above. `KPIScoringNode` (step-helper, not a `BaseNode` subclass) is excluded from discovery — verified by an explicit test in the same file |

## Compliance Gate Tests (Domain-Specific, Mandatory)

These cover the proposal's highest-severity risks and
the Subcontract Act determination logic, in addition to the framework
TC/PB items above.

| CG-ID | Risk Ref | Test | Input | Expected Result |
|-------|----------|------|-------|----------------|
| CG-01 | Risk #1 (LLM corrective recommendation inaccuracy) | `MainNode` passes already-finalized `kpi_scores`/`subcontract_act_flags` into the LLM prompt and never lets the LLM response overwrite them | `FakeLLM` returns a narrative contradicting the KPI numbers | `kpi_scores`/`subcontract_act_flags` in the returned state are byte-identical to `KPIScoringNode`'s deterministic output regardless of LLM response content |
| CG-02 | Subcontract Act Article 4: unjustified return rate | `KPIScoringNode._check_unjustified_return_rate()` flags when `returned_qty / received_qty * 100` exceeds `return_rate_limit_pct` | `defect_return_logs` with return rate > configured limit | `unjustified_return_rate_flag = True`; `determination_rationale` names the exceeded rate and limit |
| CG-03 | Subcontract Act Article 4: payment delay (>60 days) | `KPIScoringNode._check_payment_delay()` flags when any invoice's `payment_delay_days` exceeds `payment_delay_limit_days` | `invoice_records` with a delay of 70 days against a 60-day limit | `payment_delay_flag = True`; `determination_rationale` names the exceeded delay and limit |
| CG-04 | Risk #4 (missing KPI fields) | `KPIScoringNode` returns `None` for a KPI dimension with no input records and records it in `missing_scores`, rather than failing the whole supplier | Supplier record missing `invoice_records` | `kpi_scores["invoice_error_rate"] is None`; `"invoice_error_rate" in kpi_scores["missing_scores"]`; other 3 KPIs still scored |
| CG-05 | Risk #3 (ERP/WMS supplier ID format inconsistency) | `resolve_supplier_id()` strips known ERP/WMS prefixes to a canonical ID | Raw IDs `"SAP-ABC123"` and `"ABC123"` for the same supplier | Both resolve to `"ABC123"`; `normalize_suppliers()` merges them into one supplier record instead of two |
| CG-06 | Proposal §4 Step 5 | Subcontract Act compliance evidence recorded via S-4 | `PostProcessNode.execute()` on a payload with at least one flagged supplier | `emit_trace_event("scorecard_assembled", ...)` payload includes `subcontract_act_flags` with the flag and rationale for JFTC evidence purposes |
| CG-07 | PostProcessNode S-3 | Output blocked when the rendered Markdown report contains PII-shaped content | Markdown report text containing an email address or JP phone-number pattern | `RuntimeError` raised by `_extra_security_gate_output()`; `__call__()` returns `status = error` |
| CG-08 | Turn-1 review FINDING-02 (max_retry never wired) | `MainNode` returns `status = retry` when every supplier in the batch falls back to the deterministic narrative (LLM unavailable/broken, not a one-off) | 2-supplier batch, LLM returns unparseable JSON for both | `status = AgentStatus.RETRY.value`; `error_log` names the batch size; `kpi_scores`/`subcontract_act_flags` untouched by the retry decision |
| CG-09 | Turn-1 review FINDING-02 (fail-soft for partial failure) | `MainNode` does NOT retry when only some suppliers in the batch fall back | 2-supplier batch, LLM fails for 1 of 2 suppliers | `status = AgentStatus.SUCCESS.value`; the failing supplier's narrative uses `fallback_narrative()`, the other supplier's narrative is LLM-generated |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | `parse_payload()` rejects malformed JSON | Non-JSON string | `SupplierPayloadError` raised | Pass |
| BL-02 | `normalize_evaluation_period()` rejects `end_date` before `start_date` | `{"start_date": "2026-04-01", "end_date": "2026-01-01"}` | `ValueError` raised | Pass |
| BL-03 | `PreProcessNode` rejects empty payload | `user_input = "[]"` | `status = error`; `error_log` non-empty | Pass |
| BL-04 | `KPIScoringNode` on-time delivery rate calculation | 2 delivery records, 1 on-time (`actual_date <= contracted_date`), 1 late | `on_time_delivery_rate == 50.0` | Pass |
| BL-05 | `KPIScoringNode` defect PPM calculation | `received_qty=1000`, `defect_qty=10` | `defect_ppm == 10000.0` | Pass |
| BL-06 | `MainNode` success path with `FakeLLM` | Valid suppliers + evaluation_period | `status = success`; `scorecard_narrative` length equals supplier count | Pass |
| BL-07 | `MainNode` falls back to deterministic narrative when LLM response is unparseable | `FakeLLM` returns non-JSON string | `status = success`; `scorecard_narrative` uses `fallback_narrative()` shape, not an error | Pass |
| BL-08 | `PostProcessNode` assembles valid JSON + Markdown | Valid `kpi_scores`/`subcontract_act_flags`/`scorecard_narrative` | `formatted_output` contains both `json_scorecard` and `markdown_report` | Pass |
| BL-09 | `PostProcessNode` rejects orphaned supplier references | `scorecard_narrative` entry referencing a `supplier_id` absent from `kpi_scores`/`subcontract_act_flags` | `status = error`; `error_log` names the orphaned `supplier_id` (explicit consistency check before assembly — not an uncaught `KeyError`) | Pass |

## Test Execution Summary
- Execution date: 2026-07-06
- Total tests: 11 TC + 6 PB + 9 CG + 9 BL = 35 (doc-level item count); 45
  pytest cases executed (some items covered by more than one test function
  — e.g. success + error variants, and PB-1/PB-2/PB-3 domain tests are
  additional to the 6 framework PB items)
- Pass: 45 / Fail: 0 / Skip: 0 (TC-04, PB-3 marked N/A with rationale, not skipped)
- Coverage: All 3 `FunctionNode`s (`PreProcessNode`, `MainNode`,
  `PostProcessNode`) have ≥1 success-path and ≥1 error-path unit test;
  `KPIScoringNode` step-helper is directly unit-tested for all 4 KPI tools
  and both Subcontract Act Article 4 checks
- Fix during test-writing: `PostProcessNode.execute()` originally let an
  orphaned `supplier_id` in `scorecard_narrative` raise an uncaught
  `KeyError` inside `assemble_json_scorecard()`; added an explicit
  consistency check before assembly so this surfaces as `status = error`
  with a clear message instead (see BL-09)
- Turn-1 review fixes: FINDING-01 (base_type rationale — documented in
  config/agent.yaml, no code change; verified against the manifest schema that no formal base_type field or ToolCallingAgent/
  DocGenerationAgent class exists in the framework), FINDING-02
  (max_retry never wired — MainNode now returns status=RETRY when every
  supplier in the batch falls back to the deterministic narrative, so the
  graph-level max_retry actually has an effect; a single supplier's
  fallback still degrades gracefully without a retry, see CG-08/CG-09),
  and FINDING-03 (S-1 rejection path never tested with an ANONYMOUS caller
  — added tests/proof_of_boundary/test_pb04_s1_trust_gate.py, same pattern
  as a sibling template; verified it fails loudly on a deliberate regression to
  ANONYMOUS before confirming it passes at the current state; KPIScoringNode
  is excluded from discovery by the existing issubclass(BaseNode) filter,
  with an explicit test asserting so)
