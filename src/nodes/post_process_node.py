"""AgentCore Platform v1.0"""

import re
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.output_assembly_service import (
    assemble_json_scorecard,
    render_markdown_report,
    validate_output_schema,
)

# S-3 domain check: supplier transaction data is confidential business data,
# not personal information (proposal §10 Angle 5), but if supplier contact
# names/emails leak into narrative text this is a real data leak — block
# rather than redact.
#
# The framework's detect_pii() covers person-name detection (capitalized
# word-pair heuristic), but that same heuristic false-positives on ordinary
# Markdown headings and prose in this template's output (e.g. "Supplier
# Quality" or "Scorecard\nAll" get flagged as names) — unusable here without
# suppressing every report. These two patterns instead target the specific,
# unambiguous PII shapes (JP phone numbers, email addresses) the framework
# detector does not cover for this residual case; quantifiers are bounded
# per the PII regex bounding rule.
_PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{4}-\d{4}\b"),  # JP phone number shape
    re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,4}"),  # email address
]


class PostProcessNode(FunctionNode):
    """Assemble the final JSON scorecard + Markdown report, and record the
    Subcontract Act compliance evidence audit log."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        formatted_output = result.get("formatted_output")
        if not formatted_output:
            return result

        markdown_report = formatted_output.get("markdown_report", "")
        if any(p.search(markdown_report) for p in _PII_PATTERNS):
            raise RuntimeError(
                "PostProcessNode: S-3 blocked output — possible PII " "detected in generated Markdown report"
            )
        return result

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        kpi_scores = state.get("kpi_scores", [])
        subcontract_act_flags = state.get("subcontract_act_flags", [])
        scorecard_narrative = state.get("scorecard_narrative", [])
        evaluation_period = state.get("evaluation_period", {})

        if not scorecard_narrative:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PostProcessNode: no scorecard narrative to assemble"],
            }

        score_ids = {s["supplier_id"] for s in kpi_scores}
        flag_ids = {f["supplier_id"] for f in subcontract_act_flags}
        narrative_ids = {n["supplier_id"] for n in scorecard_narrative}
        orphaned_ids = narrative_ids - (score_ids & flag_ids)
        if orphaned_ids:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    f"PostProcessNode: scorecard_narrative references supplier_id(s) "
                    f"{sorted(orphaned_ids)} missing from kpi_scores/subcontract_act_flags"
                ],
            }

        json_scorecard = assemble_json_scorecard(
            kpi_scores, subcontract_act_flags, scorecard_narrative, evaluation_period
        )

        schema_errors = validate_output_schema(json_scorecard)
        if schema_errors:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": schema_errors,
            }

        markdown_report = render_markdown_report(json_scorecard)

        # S-4: this event IS the Subcontract Act compliance evidence audit
        # log — payload carries the flags and rationale per supplier so it
        # can be submitted as JFTC investigation evidence (docs/02_design.md
        # Framework Utilization).
        emit_trace_event(
            "scorecard_assembled",
            {
                "supplier_count": len(json_scorecard["suppliers"]),
                "subcontract_act_flags": subcontract_act_flags,
            },
            state,
        )

        return {
            "formatted_output": {
                "json_scorecard": json_scorecard,
                "markdown_report": markdown_report,
            },
            "status": AgentStatus.SUCCESS.value,
        }
