"""AgentCore Platform v1.0"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.kpi_scoring_node import KPIScoringNode
from src.services.scorecard_narrative_service import (
    build_narrative_prompt,
    fallback_narrative,
    parse_narrative_response,
)


class MainNode(FunctionNode):
    """KPIScoringNode step + DocGenerationNode step, run sequentially.

    docs/02_design.md "Node mapping note": KPI scores and Subcontract Act
    flags are finalized by KPIScoringNode (deterministic, no LLM) before
    DocGenerationNode's LLM call runs against that already-finalized data,
    within this same execute(). This keeps the LLM narrative layer
    structurally unable to alter the numbers (proposal §11 Risk #1).
    """

    # S-1: enforced per-node inside BaseNode.__call__(), not inherited from
    # config/agent.yaml's manifest-level declaration. Set to
    # VERIFIED_EXTERNAL to match the manifest and prevent an ANONYMOUS
    # caller from invoking this LLM-backed generation step directly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self,
        llm: Any = None,
        kpi_thresholds: dict[str, Any] | None = None,
        subcontract_rules: dict[str, Any] | None = None,
    ) -> None:
        # Defaults so framework tooling that dynamically instantiates node
        # classes with no args (e.g. PB-6 invoke-order verification) can
        # construct this node — execute() returns before touching self._llm
        # whenever "suppliers" is absent from state.
        self._llm = llm
        self._kpi_scoring = KPIScoringNode(kpi_thresholds or {}, subcontract_rules or {})

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        # S-3: defence-in-depth — drop any per-supplier
        # narrative that failed to parse into the fallback-safe shape.
        # (fallback_narrative() already guarantees valid shape, so this is
        # a structural safety net, not expected to trigger in practice.)
        narratives = result.get("scorecard_narrative")
        if not narratives:
            return result

        required_fields = {"kpi_trend_narrative", "corrective_recommendations", "gx_scope3_notes"}
        for narrative in narratives:
            if not required_fields.issubset(narrative.keys()):
                raise RuntimeError(
                    f"MainNode: S-3 blocked output — malformed narrative for "
                    f"supplier_id={narrative.get('supplier_id')}"
                )
        return result

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        suppliers = state.get("suppliers", [])
        evaluation_period = state.get("evaluation_period", {})

        if not suppliers:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["MainNode: no suppliers available from pre_process"],
            }

        # KPIScoringNode step — deterministic, no LLM.
        kpi_scores, subcontract_act_flags = self._kpi_scoring.execute(suppliers)

        flagged_count = sum(
            1 for f in subcontract_act_flags if f["unjustified_return_rate_flag"] or f["payment_delay_flag"]
        )
        emit_trace_event(
            "kpi_scored",
            {
                "supplier_count": len(suppliers),
                "subcontract_act_flag_count": flagged_count,
            },
            state,
        )

        # DocGenerationNode step — LLM narrative against finalized data.
        scores_by_id = {s["supplier_id"]: s for s in kpi_scores}
        flags_by_id = {f["supplier_id"]: f for f in subcontract_act_flags}

        scorecard_narrative = []
        fallback_count = 0
        total_tokens = 0
        for supplier in suppliers:
            supplier_id = supplier["supplier_id"]
            kpi_score = scores_by_id[supplier_id]
            subcontract_act_flag = flags_by_id[supplier_id]

            prompt = build_narrative_prompt(supplier_id, kpi_score, subcontract_act_flag, evaluation_period)
            raw_response = ""
            if self._llm is not None:
                response = self._llm.complete([{"role": "user", "content": prompt}])
                raw_response = response.get("content", "") if isinstance(response, dict) else str(response)
            total_tokens += len(prompt) // 4 + len(raw_response) // 4

            parsed = parse_narrative_response(raw_response)
            if parsed is None:
                fallback_count += 1
                narrative = fallback_narrative(kpi_score, subcontract_act_flag)
            else:
                narrative = parsed
            narrative["supplier_id"] = supplier_id
            scorecard_narrative.append(narrative)

        emit_trace_event(
            "llm_call",
            {
                "model": getattr(self._llm, "model_name", "unknown"),
                "tokens": total_tokens,
                "supplier_count": len(suppliers),
                "fallback_count": fallback_count,
            },
            state,
        )

        # max_retry (config/agent.yaml, graph-level) only takes effect when a node returns status=RETRY;
        # the router then re-enters pre_process, up to max_retry attempts.
        # A single supplier falling back to the deterministic narrative is
        # not retried (docs/02_design.md: fail-soft is preferable to
        # fail-hard for one supplier in a larger batch). But every supplier
        # falling back in the same pass indicates the LLM is unavailable or
        # broken for the whole batch, not a one-off malformed response — for
        # that case, request a retry rather than silently degrading the
        # entire scorecard to fallback narratives.
        if suppliers and fallback_count == len(suppliers):
            # retry_count is a plain overwrite channel (no operator.add
            # reducer on AgentState) — the router only compares it against
            # max_retry, it never increments it itself. A RETRY status with
            # no incremented retry_count in the returned dict would loop
            # pre_process -> main -> route forever (confirmed: hits
            # LangGraph's recursion ceiling long before any framework-level
            # retry limit), since the same retry_count=0 keeps being read
            # back on every pass.
            return {
                "status": AgentStatus.RETRY.value,
                "retry_count": state.get("retry_count", 0) + 1,
                "error_log": [
                    f"MainNode: LLM narrative generation failed for all "
                    f"{len(suppliers)} suppliers in this batch — retrying "
                    f"(kpi_scores and subcontract_act_flags are unaffected)"
                ],
            }

        return {
            "kpi_scores": kpi_scores,
            "subcontract_act_flags": subcontract_act_flags,
            "scorecard_narrative": scorecard_narrative,
            "status": AgentStatus.SUCCESS.value,
        }
