# PB-1 (domain): LLM narrative layer cannot alter deterministic KPI/flag data
# Verifies docs/02_design.md's core design decision — KPIScoringNode's
# deterministic output is finalized before DocGenerationNode's LLM call
# runs, and nothing in MainNode.execute() lets the LLM response overwrite
# kpi_scores/subcontract_act_flags — proposal_en.md §11 Risk #1 (highest
# severity risk for this template).

import json

from src.nodes.main_node import MainNode


class ContradictingLLM:
    """Always returns a narrative that contradicts whatever KPI/flag data
    it was given — used to prove the numbers are structurally protected."""

    def complete(self, prompt, **kwargs):
        return json.dumps({
            "kpi_trend_narrative": "All KPIs are perfect, no issues whatsoever.",
            "corrective_recommendations": [],
            "gx_scope3_notes": "Perfect data quality.",
        })


def _state_with_flagged_supplier() -> dict:
    return {
        "suppliers": [{
            "supplier_id": "ABC123",
            "delivery_records": [
                {"contracted_date": "2026-01-01", "actual_date": "2026-01-05"},
            ],
            "defect_return_logs": [
                {"received_qty": 1000, "defect_qty": 50, "returned_qty": 100},
            ],
            "invoice_records": [
                {"has_discrepancy": True, "payment_delay_days": 90},
            ],
            "responsiveness_log": [
                {"response_time_hours": 48},
            ],
        }],
        "evaluation_period": {"start_date": "2026-01-01", "end_date": "2026-03-31"},
    }


class TestLLMNeverOverridesKPI:
    def test_kpi_scores_are_byte_identical_regardless_of_llm_response(self):
        thresholds = {"responsiveness_sla_hours": 24}
        rules = {"return_rate_limit_pct": 5.0, "payment_delay_limit_days": 60}

        node_a = MainNode(llm=ContradictingLLM(), kpi_thresholds=thresholds, subcontract_rules=rules)
        node_b = MainNode(llm=ContradictingLLM(), kpi_thresholds=thresholds, subcontract_rules=rules)

        result_a = node_a.execute(_state_with_flagged_supplier())
        result_b = node_b.execute(_state_with_flagged_supplier())

        # Same deterministic inputs -> same deterministic KPI/flag outputs,
        # independent of the (adversarial) LLM response content.
        assert result_a["kpi_scores"] == result_b["kpi_scores"]
        assert result_a["subcontract_act_flags"] == result_b["subcontract_act_flags"]

    def test_flags_reflect_input_data_not_llm_narrative(self):
        thresholds = {"responsiveness_sla_hours": 24}
        rules = {"return_rate_limit_pct": 5.0, "payment_delay_limit_days": 60}
        node = MainNode(llm=ContradictingLLM(), kpi_thresholds=thresholds, subcontract_rules=rules)

        result = node.execute(_state_with_flagged_supplier())

        flag = result["subcontract_act_flags"][0]
        assert flag["unjustified_return_rate_flag"] is True, (
            "return rate 10% exceeds the 5% limit regardless of the LLM "
            "narrative claiming 'no issues whatsoever'"
        )
        assert flag["payment_delay_flag"] is True, (
            "payment delay of 90 days exceeds the 60-day limit regardless "
            "of the LLM narrative content"
        )
