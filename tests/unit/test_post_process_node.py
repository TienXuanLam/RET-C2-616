# RET-C2-616 — Unit Tests: PostProcessNode

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes.post_process_node import PostProcessNode


def _state(**overrides) -> dict:
    base = {
        "kpi_scores": [
            {
                "supplier_id": "ABC123",
                "on_time_delivery_rate": 50.0,
                "defect_ppm": 10000.0,
                "invoice_error_rate": 50.0,
                "responsiveness_sla_score": 50.0,
                "missing_scores": [],
            }
        ],
        "subcontract_act_flags": [
            {
                "supplier_id": "ABC123",
                "unjustified_return_rate_flag": True,
                "payment_delay_flag": True,
                "determination_rationale": "Return rate 8.00% exceeds Subcontract Act limit 5.0%",
            }
        ],
        "scorecard_narrative": [
            {
                "supplier_id": "ABC123",
                "kpi_trend_narrative": "Delivery performance needs attention.",
                "corrective_recommendations": ["Review supplier delivery process"],
                "gx_scope3_notes": "Data complete.",
            }
        ],
        "evaluation_period": {"start_date": "2026-01-01", "end_date": "2026-03-31"},
    }
    base.update(overrides)
    return base


class TestPostProcessNode:
    def setup_method(self):
        self.node = PostProcessNode()

    def test_success_path_assembles_json_and_markdown(self):
        result = self.node.execute(_state())

        assert result["status"] == AgentStatus.SUCCESS.value
        payload = result["formatted_output"]
        assert "json_scorecard" in payload
        assert "markdown_report" in payload
        assert payload["json_scorecard"]["suppliers"][0]["supplier_id"] == "ABC123"
        assert "ABC123" in payload["markdown_report"]

    def test_no_narrative_returns_error(self):
        result = self.node.execute(_state(scorecard_narrative=[]))

        assert result["status"] == AgentStatus.ERROR.value
        assert len(result["error_log"]) > 0

    def test_markdown_report_includes_subcontract_act_flags(self):
        result = self.node.execute(_state())
        markdown = result["formatted_output"]["markdown_report"]

        assert "FLAGGED" in markdown
        assert "下請法" in markdown

    # --- BL-09 (docs/03_test_spec.md): orphaned supplier_id handling ---

    def test_narrative_referencing_unknown_supplier_id_returns_error(self):
        result = self.node.execute(_state(
            scorecard_narrative=[{
                "supplier_id": "GHOST",
                "kpi_trend_narrative": "x",
                "corrective_recommendations": [],
                "gx_scope3_notes": "x",
            }]
        ))

        assert result["status"] == AgentStatus.ERROR.value
        assert "GHOST" in result["error_log"][0]

    # --- S-3 output gate ---

    def test_extra_security_gate_output_blocks_email_pii(self):
        result = {
            "formatted_output": {
                "markdown_report": "Contact supplier at contact@example.com for details.",
            }
        }
        with pytest.raises(RuntimeError):
            self.node._extra_security_gate_output(result)

    def test_extra_security_gate_output_allows_clean_text(self):
        result = {
            "formatted_output": {
                "markdown_report": "# Supplier Quality SLA Scorecard\nAll KPIs nominal.",
            }
        }
        gated = self.node._extra_security_gate_output(result)
        assert gated == result
