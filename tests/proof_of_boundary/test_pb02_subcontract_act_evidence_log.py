# PB-2 (domain): Subcontract Act compliance evidence audit log
# Verifies PostProcessNode's S-4 emit_trace_event("scorecard_assembled", ...)
# payload carries the Subcontract Act flags — this event IS the compliance
# evidence log the proposal requires for JFTC investigation response
# (see docs/02_design.md Framework Utilization).

from unittest.mock import patch

from src.nodes.post_process_node import PostProcessNode


def _state_with_flagged_supplier() -> dict:
    return {
        "kpi_scores": [{
            "supplier_id": "ABC123",
            "on_time_delivery_rate": 50.0,
            "defect_ppm": 10000.0,
            "invoice_error_rate": 50.0,
            "responsiveness_sla_score": 50.0,
            "missing_scores": [],
        }],
        "subcontract_act_flags": [{
            "supplier_id": "ABC123",
            "unjustified_return_rate_flag": True,
            "payment_delay_flag": True,
            "determination_rationale": "Return rate 8.00% exceeds Subcontract Act limit 5.0%",
        }],
        "scorecard_narrative": [{
            "supplier_id": "ABC123",
            "kpi_trend_narrative": "Needs attention.",
            "corrective_recommendations": ["Review supplier"],
            "gx_scope3_notes": "Complete.",
        }],
        "evaluation_period": {"start_date": "2026-01-01", "end_date": "2026-03-31"},
    }


class TestSubcontractActEvidenceLog:
    def test_scorecard_assembled_event_carries_subcontract_act_flags(self):
        node = PostProcessNode()

        with patch("src.nodes.post_process_node.emit_trace_event") as mock_emit:
            result = node.execute(_state_with_flagged_supplier())

        assert result["status"] == "success"
        mock_emit.assert_called_once()
        event_type, payload, _state = mock_emit.call_args[0]

        assert event_type == "scorecard_assembled"
        assert "subcontract_act_flags" in payload
        assert payload["subcontract_act_flags"][0]["unjustified_return_rate_flag"] is True
        assert payload["subcontract_act_flags"][0]["payment_delay_flag"] is True
        assert "Return rate 8.00%" in payload["subcontract_act_flags"][0]["determination_rationale"]
