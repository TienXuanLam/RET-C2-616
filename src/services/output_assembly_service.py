"""AgentCore Platform v1.0"""

# Service layer: final JSON/Markdown scorecard assembly + schema validation
# for the OutputNode step (see docs/02_design.md). Pure domain logic —
# no framework imports — called by src/nodes/post_process_node.py.

from __future__ import annotations

from typing import Any

_REQUIRED_SUPPLIER_FIELDS = {
    "supplier_id",
    "kpi_scores",
    "subcontract_act_flags",
    "kpi_trend_narrative",
    "corrective_recommendations",
    "gx_scope3_notes",
}


def assemble_json_scorecard(
    kpi_scores: list[dict[str, Any]],
    subcontract_act_flags: list[dict[str, Any]],
    scorecard_narrative: list[dict[str, Any]],
    evaluation_period: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the final structured JSON scorecard payload
    (proposal §4 Step 5)."""
    scores_by_id = {s["supplier_id"]: s for s in kpi_scores}
    flags_by_id = {f["supplier_id"]: f for f in subcontract_act_flags}

    suppliers = []
    for narrative in scorecard_narrative:
        supplier_id = narrative["supplier_id"]
        suppliers.append(
            {
                "supplier_id": supplier_id,
                "kpi_scores": scores_by_id[supplier_id],
                "subcontract_act_flags": flags_by_id[supplier_id],
                "kpi_trend_narrative": narrative["kpi_trend_narrative"],
                "corrective_recommendations": narrative["corrective_recommendations"],
                "gx_scope3_notes": narrative["gx_scope3_notes"],
            }
        )

    return {
        "evaluation_period": evaluation_period,
        "suppliers": suppliers,
    }


def render_markdown_report(json_scorecard: dict[str, Any]) -> str:
    """Render the JSON scorecard into a Markdown report
    (proposal §4 Step 5: "PDF rendering compatible")."""
    period = json_scorecard["evaluation_period"]
    lines = [
        "# Supplier Quality SLA Scorecard",
        f"**Evaluation Period:** {period['start_date']} to {period['end_date']}",
        "",
    ]

    for supplier in json_scorecard["suppliers"]:
        scores = supplier["kpi_scores"]
        flags = supplier["subcontract_act_flags"]

        lines.append(f"## Supplier: {supplier['supplier_id']}")
        lines.append("")
        lines.append("| KPI | Value |")
        lines.append("|---|---|")
        lines.append(f"| On-time delivery rate | {scores['on_time_delivery_rate']}% |")
        lines.append(f"| Defect PPM | {scores['defect_ppm']} |")
        lines.append(f"| Invoice error rate | {scores['invoice_error_rate']}% |")
        lines.append(f"| Responsiveness SLA score | {scores['responsiveness_sla_score']}% |")
        lines.append("")

        lines.append("**Subcontract Act (下請法) Article 4 Compliance:**")
        lines.append(
            f"- Unjustified return rate flag: " f"{'⚠️ FLAGGED' if flags['unjustified_return_rate_flag'] else '✅ OK'}"
        )
        lines.append(f"- Payment delay flag: " f"{'⚠️ FLAGGED' if flags['payment_delay_flag'] else '✅ OK'}")
        lines.append(f"- Rationale: {flags['determination_rationale']}")
        lines.append("")

        lines.append("**KPI Trend Narrative:**")
        lines.append(supplier["kpi_trend_narrative"])
        lines.append("")

        lines.append("**Corrective Recommendations:**")
        if supplier["corrective_recommendations"]:
            for rec in supplier["corrective_recommendations"]:
                lines.append(f"- {rec}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("**GX Scope 3 Data Quality Notes:**")
        lines.append(supplier["gx_scope3_notes"])
        lines.append("")

    return "\n".join(lines)


def validate_output_schema(json_scorecard: dict[str, Any]) -> list[str]:
    """Validate required fields are present. Returns a list of error
    messages; empty list means the payload is valid."""
    errors: list[str] = []

    if "evaluation_period" not in json_scorecard:
        errors.append("OutputNode: missing required field 'evaluation_period'")
    if "suppliers" not in json_scorecard:
        errors.append("OutputNode: missing required field 'suppliers'")
        return errors

    for supplier in json_scorecard["suppliers"]:
        missing = _REQUIRED_SUPPLIER_FIELDS - supplier.keys()
        if missing:
            errors.append(f"OutputNode: supplier_id={supplier.get('supplier_id')} " f"missing fields {sorted(missing)}")

    return errors
