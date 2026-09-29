# RET-C2-616 — Unit Tests: MainNode

import json

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes.main_node import MainNode

THRESHOLDS = {"responsiveness_sla_hours": 24}
RULES = {"return_rate_limit_pct": 5.0, "payment_delay_limit_days": 60}


class FakeLLM:
    """Returns one canned narrative per prompt."""

    def __init__(self, response=None):
        self._response = response
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append(prompt)
        if self._response is not None:
            return self._response
        return json.dumps({
            "kpi_trend_narrative": "Delivery performance is stable this quarter.",
            "corrective_recommendations": [],
            "gx_scope3_notes": "Data completeness is sufficient for Scope 3 estimation.",
        })


def _supplier(**overrides) -> dict:
    base = {
        "supplier_id": "ABC123",
        "delivery_records": [
            {"contracted_date": "2026-01-10", "actual_date": "2026-01-10"},
        ],
        "defect_return_logs": [
            {"received_qty": 1000, "defect_qty": 10, "returned_qty": 80},
        ],
        "invoice_records": [
            {"has_discrepancy": False, "payment_delay_days": 70},
        ],
        "responsiveness_log": [
            {"response_time_hours": 10},
        ],
    }
    base.update(overrides)
    return base


def _state(**overrides) -> dict:
    base = {
        "suppliers": [_supplier()],
        "evaluation_period": {"start_date": "2026-01-01", "end_date": "2026-03-31"},
    }
    base.update(overrides)
    return base


def _node(llm=None) -> MainNode:
    return MainNode(llm=llm or FakeLLM(), kpi_thresholds=THRESHOLDS, subcontract_rules=RULES)


class TestMainNode:
    def test_success_path_produces_scores_and_narrative(self):
        node = _node()
        result = node.execute(_state())

        assert result["status"] == AgentStatus.SUCCESS.value
        assert len(result["kpi_scores"]) == 1
        assert len(result["subcontract_act_flags"]) == 1
        assert len(result["scorecard_narrative"]) == 1
        assert result["scorecard_narrative"][0]["supplier_id"] == "ABC123"

    def test_no_suppliers_returns_error(self):
        node = _node()
        result = node.execute(_state(suppliers=[]))

        assert result["status"] == AgentStatus.ERROR.value
        assert len(result["error_log"]) > 0

    def test_llm_never_overrides_finalized_kpi_scores(self):
        # CG-01 (docs/03_test_spec.md): LLM narrative contradicts the KPI
        # numbers, but the returned kpi_scores/subcontract_act_flags must
        # remain exactly what KPIScoringNode computed.
        contradicting_llm = FakeLLM(response=json.dumps({
            "kpi_trend_narrative": "Everything is perfect, no compliance issues at all.",
            "corrective_recommendations": [],
            "gx_scope3_notes": "N/A",
        }))
        node = _node(llm=contradicting_llm)
        result = node.execute(_state())

        assert result["subcontract_act_flags"][0]["unjustified_return_rate_flag"] is True
        assert result["subcontract_act_flags"][0]["payment_delay_flag"] is True

    def test_single_supplier_unparseable_response_falls_back_without_retry(self):
        # One supplier out of a two-supplier batch gets a malformed LLM
        # response — this is a one-off glitch, not evidence the LLM is
        # unavailable, so it must fall back rather than trigger a retry.
        class PartialFailureLLM:
            def __init__(self):
                self.call_count = 0

            def complete(self, prompt, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    return "not valid json"
                return json.dumps({
                    "kpi_trend_narrative": "ok",
                    "corrective_recommendations": [],
                    "gx_scope3_notes": "ok",
                })

        node = _node(llm=PartialFailureLLM())
        state = _state(suppliers=[_supplier(supplier_id="ABC123"), _supplier(supplier_id="XYZ789")])
        result = node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        narratives = {n["supplier_id"]: n for n in result["scorecard_narrative"]}
        assert "Narrative unavailable" in narratives["ABC123"]["kpi_trend_narrative"]
        assert narratives["XYZ789"]["kpi_trend_narrative"] == "ok"
        # Fallback still surfaces the Subcontract Act flags as recommendations.
        assert any(
            "payment delay" in rec.lower()
            for rec in narratives["ABC123"]["corrective_recommendations"]
        )

    def test_full_batch_llm_failure_returns_retry_not_silent_fallback(self):
        # FINDING-02 (Turn 1 review): every supplier in the batch falling
        # back to the deterministic narrative indicates the LLM itself is
        # unavailable/broken, not a one-off malformed response — MainNode
        # must request a retry (max_retry, config/agent.yaml, graph-level)
        # rather than silently degrading the whole scorecard.
        node = _node(llm=FakeLLM(response="not valid json"))
        state = _state(suppliers=[_supplier(supplier_id="ABC123"), _supplier(supplier_id="XYZ789")])
        result = node.execute(state)

        assert result["status"] == AgentStatus.RETRY.value
        assert "all 2 suppliers" in result["error_log"][0]

    def test_single_supplier_batch_full_failure_also_retries(self):
        # Degenerate case: a batch of exactly one supplier where that one
        # supplier fails is indistinguishable from "the whole batch failed"
        # — must also retry, not silently fall back.
        node = _node(llm=FakeLLM(response="not valid json"))
        result = node.execute(_state())

        assert result["status"] == AgentStatus.RETRY.value

    # --- S-3 output gate ---

    def test_extra_security_gate_output_passes_well_formed_narrative(self):
        node = _node()
        result = {
            "scorecard_narrative": [
                {
                    "supplier_id": "ABC123",
                    "kpi_trend_narrative": "ok",
                    "corrective_recommendations": [],
                    "gx_scope3_notes": "ok",
                }
            ]
        }
        gated = node._extra_security_gate_output(result)
        assert gated == result

    def test_extra_security_gate_output_blocks_malformed_narrative(self):
        node = _node()
        result = {
            "scorecard_narrative": [
                {"supplier_id": "ABC123", "kpi_trend_narrative": "ok"}  # missing fields
            ]
        }
        with pytest.raises(RuntimeError):
            node._extra_security_gate_output(result)
