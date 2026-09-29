"""AgentCore Platform v1.0"""

# Service layer: LLM prompt construction and response parsing for the
# DocGenerationNode step (see docs/02_design.md). Pure domain logic — no
# framework imports — called by src/nodes/main_node.py.

from __future__ import annotations

import json
from typing import Any


def build_narrative_prompt(
    supplier_id: str,
    kpi_score: dict[str, Any],
    subcontract_act_flag: dict[str, Any],
    evaluation_period: dict[str, Any],
) -> str:
    """Build the LLM prompt for one supplier's scorecard narrative.

    KPI numbers and Subcontract Act flags are passed in as already-finalized
    facts — the prompt explicitly instructs the model not to alter them
    (docs/02_design.md Design Decision Record: LLM affects narrative only,
    never the numbers — proposal §11 Risk #1 mitigation).
    """
    return (
        f"You are generating a supplier SLA scorecard narrative section for "
        f"supplier {supplier_id}, evaluation period "
        f"{evaluation_period['start_date']} to {evaluation_period['end_date']}.\n\n"
        f"These KPI scores and Subcontract Act flags are FINAL — do not "
        f"recompute, contradict, or alter any number or flag below. Your "
        f"task is narrative interpretation only.\n\n"
        f"KPI scores: {json.dumps(kpi_score, ensure_ascii=False)}\n"
        f"Subcontract Act Article 4 flags: "
        f"{json.dumps(subcontract_act_flag, ensure_ascii=False)}\n\n"
        f"Generate:\n"
        f"1. kpi_trend_narrative — a short paragraph interpreting the KPI scores\n"
        f"2. corrective_recommendations — a list of specific improvement actions "
        f"(empty list if all KPIs are healthy and no Subcontract Act flag is set)\n"
        f"3. gx_scope3_notes — a short note on this supplier's emission data "
        f"quality for GX Scope 3 reporting purposes (based on data completeness, "
        f"not a real emissions calculation)\n\n"
        f"Respond as a JSON object with exactly these three fields."
    )


def parse_narrative_response(raw_response: str) -> dict[str, Any] | None:
    """Parse the LLM's JSON object response. Returns None on malformed
    output rather than raising — the caller (MainNode) decides retry vs
    a fallback narrative."""
    try:
        parsed = json.loads(raw_response)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(parsed, dict):
        return None

    required_fields = {"kpi_trend_narrative", "corrective_recommendations", "gx_scope3_notes"}
    if not required_fields.issubset(parsed.keys()):
        return None

    return parsed


def fallback_narrative(kpi_score: dict[str, Any], subcontract_act_flag: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback narrative used when the LLM response is
    unparseable — ensures the pipeline degrades gracefully rather than
    failing the whole supplier record over a narrative-generation glitch."""
    recommendations = []
    if subcontract_act_flag.get("unjustified_return_rate_flag"):
        recommendations.append("Review return-rate root causes with supplier immediately")
    if subcontract_act_flag.get("payment_delay_flag"):
        recommendations.append("Escalate payment delay to procurement/accounting")
    if kpi_score.get("missing_scores"):
        recommendations.append(f"Request missing data for: {', '.join(kpi_score['missing_scores'])}")

    return {
        "kpi_trend_narrative": "Narrative unavailable — LLM response could not be parsed; scores above are authoritative.",
        "corrective_recommendations": recommendations,
        "gx_scope3_notes": "Data quality note unavailable — see missing_scores for known gaps.",
    }
