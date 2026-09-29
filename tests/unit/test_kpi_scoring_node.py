# RET-C2-616 — Unit Tests: KPIScoringNode (step-helper, not a framework node)

from src.nodes.kpi_scoring_node import KPIScoringNode

THRESHOLDS = {"responsiveness_sla_hours": 24}
RULES = {"return_rate_limit_pct": 5.0, "payment_delay_limit_days": 60}


def _supplier(**overrides) -> dict:
    base = {
        "supplier_id": "ABC123",
        "delivery_records": [
            {"contracted_date": "2026-01-10", "actual_date": "2026-01-10"},
            {"contracted_date": "2026-01-15", "actual_date": "2026-01-20"},
        ],
        "defect_return_logs": [
            {"received_qty": 1000, "defect_qty": 10, "returned_qty": 20},
        ],
        "invoice_records": [
            {"has_discrepancy": False, "payment_delay_days": 5},
            {"has_discrepancy": True, "payment_delay_days": 5},
        ],
        "responsiveness_log": [
            {"response_time_hours": 10},
            {"response_time_hours": 30},
        ],
    }
    base.update(overrides)
    return base


class TestKPIScoringNode:
    def setup_method(self):
        self.node = KPIScoringNode(THRESHOLDS, RULES)

    def test_on_time_delivery_rate(self):
        scores, _ = self.node.execute([_supplier()])
        assert scores[0]["on_time_delivery_rate"] == 50.0

    def test_defect_ppm(self):
        scores, _ = self.node.execute([_supplier()])
        assert scores[0]["defect_ppm"] == 10000.0

    def test_invoice_error_rate(self):
        scores, _ = self.node.execute([_supplier()])
        assert scores[0]["invoice_error_rate"] == 50.0

    def test_responsiveness_sla_score(self):
        scores, _ = self.node.execute([_supplier()])
        assert scores[0]["responsiveness_sla_score"] == 50.0

    def test_missing_kpi_field_recorded_not_fatal(self):
        supplier = _supplier(invoice_records=[])
        scores, _ = self.node.execute([supplier])

        assert scores[0]["invoice_error_rate"] is None
        assert "invoice_error_rate" in scores[0]["missing_scores"]
        assert scores[0]["on_time_delivery_rate"] == 50.0  # other KPIs unaffected

    # --- CG-02: unjustified return rate flag ---

    def test_unjustified_return_rate_flag_triggers_above_limit(self):
        supplier = _supplier(defect_return_logs=[
            {"received_qty": 1000, "defect_qty": 10, "returned_qty": 80}
        ])
        _, flags = self.node.execute([supplier])

        assert flags[0]["unjustified_return_rate_flag"] is True
        assert "8.00%" in flags[0]["determination_rationale"]

    def test_unjustified_return_rate_flag_false_below_limit(self):
        supplier = _supplier(defect_return_logs=[
            {"received_qty": 1000, "defect_qty": 10, "returned_qty": 20}
        ])
        _, flags = self.node.execute([supplier])

        assert flags[0]["unjustified_return_rate_flag"] is False

    # --- CG-03: payment delay flag ---

    def test_payment_delay_flag_triggers_above_limit(self):
        supplier = _supplier(invoice_records=[
            {"has_discrepancy": False, "payment_delay_days": 70}
        ])
        _, flags = self.node.execute([supplier])

        assert flags[0]["payment_delay_flag"] is True
        assert "70 days" in flags[0]["determination_rationale"]

    def test_payment_delay_flag_false_below_limit(self):
        supplier = _supplier(invoice_records=[
            {"has_discrepancy": False, "payment_delay_days": 5}
        ])
        _, flags = self.node.execute([supplier])

        assert flags[0]["payment_delay_flag"] is False

    def test_no_flags_rationale_is_explicit(self):
        supplier = _supplier(
            defect_return_logs=[{"received_qty": 1000, "defect_qty": 10, "returned_qty": 20}],
            invoice_records=[{"has_discrepancy": False, "payment_delay_days": 5}],
        )
        _, flags = self.node.execute([supplier])

        assert flags[0]["determination_rationale"] == (
            "No Subcontract Act Article 4 prohibited-act conditions detected"
        )
