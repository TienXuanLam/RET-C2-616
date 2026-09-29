# RET-C2-616 — Unit Tests: PreProcessNode

import json

from framework.schemas.agent_status import AgentStatus
from src.nodes.pre_process_node import PreProcessNode, MAX_RAW_RECORDS

SAMPLE_PAYLOAD = json.dumps([
    {
        "supplier_id": "SAP-ABC123",
        "delivery_records": [
            {"contracted_date": "2026-01-10", "actual_date": "2026-01-10"},
            {"contracted_date": "2026-01-15", "actual_date": "2026-01-20"},
        ],
        "defect_return_logs": [
            {"received_qty": 1000, "defect_qty": 10, "returned_qty": 20},
        ],
        "invoice_records": [
            {"has_discrepancy": False, "payment_delay_days": 5},
        ],
        "responsiveness_log": [
            {"response_time_hours": 10},
        ],
    }
])


def _base_context(**overrides) -> dict:
    ctx = {"evaluation_period": {"start_date": "2026-01-01", "end_date": "2026-03-31"}}
    ctx.update(overrides)
    return ctx


class TestPreProcessNode:
    def setup_method(self):
        self.node = PreProcessNode()

    def test_success_path_normalizes_supplier_and_period(self):
        state = {"user_input": SAMPLE_PAYLOAD, "input_context": _base_context()}
        result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        assert len(result["suppliers"]) == 1
        assert result["suppliers"][0]["supplier_id"] == "ABC123"  # SAP- prefix stripped
        assert result["evaluation_period"] == {"start_date": "2026-01-01", "end_date": "2026-03-31"}

    def test_empty_payload_returns_error(self):
        state = {"user_input": "[]", "input_context": _base_context()}
        result = self.node.execute(state)

        assert result["status"] == AgentStatus.ERROR.value
        assert len(result["error_log"]) > 0

    def test_invalid_evaluation_period_returns_error(self):
        state = {
            "user_input": SAMPLE_PAYLOAD,
            "input_context": _base_context(
                evaluation_period={"start_date": "2026-04-01", "end_date": "2026-01-01"}
            ),
        }
        result = self.node.execute(state)

        assert result["status"] == AgentStatus.ERROR.value

    def test_missing_fields_flagged_not_fatal(self):
        payload = json.dumps([{"supplier_id": "XYZ789", "delivery_records": [
            {"contracted_date": "2026-01-01", "actual_date": "2026-01-01"}
        ]}])
        state = {"user_input": payload, "input_context": _base_context()}
        result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        flags = result["missing_field_flags"][0]["missing_fields"]
        assert "defect_return_logs" in flags
        assert "invoice_records" in flags
        assert "responsiveness_log" in flags

    def test_dedups_supplier_id_across_records(self):
        payload = json.dumps([
            {"supplier_id": "SAP-ABC123", "delivery_records": [
                {"contracted_date": "2026-01-01", "actual_date": "2026-01-01"}
            ]},
            {"supplier_id": "ABC123", "invoice_records": [
                {"has_discrepancy": False, "payment_delay_days": 0}
            ]},
        ])
        state = {"user_input": payload, "input_context": _base_context()}
        result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        assert len(result["suppliers"]) == 1
        merged = result["suppliers"][0]
        assert "delivery_records" in merged
        assert "invoice_records" in merged

    # --- CG-05 (docs/03_test_spec.md): S-2 payload size gate ---

    def test_extra_security_gate_input_rejects_oversized_payload(self):
        oversized_payload = json.dumps([{"supplier_id": f"S{i}"} for i in range(MAX_RAW_RECORDS + 1)])
        state = {"user_input": oversized_payload}

        gated_state = self.node._extra_security_gate_input(state)

        assert gated_state["status"] == AgentStatus.ERROR.value
        assert "record cap" in gated_state["error_log"][0].lower()

    def test_extra_security_gate_input_rejects_malformed_json(self):
        state = {"user_input": "not valid json"}

        gated_state = self.node._extra_security_gate_input(state)

        assert gated_state["status"] == AgentStatus.ERROR.value

    def test_extra_security_gate_input_accepts_normal_payload(self):
        state = {"user_input": SAMPLE_PAYLOAD}

        gated_state = self.node._extra_security_gate_input(state)

        assert "status" not in gated_state or gated_state.get("status") != AgentStatus.ERROR.value

    def test_extra_security_gate_input_rejects_non_string_input(self):
        state = {"user_input": 12345}

        gated_state = self.node._extra_security_gate_input(state)

        assert gated_state["status"] == AgentStatus.ERROR.value
