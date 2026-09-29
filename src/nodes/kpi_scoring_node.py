"""AgentCore Platform v1.0"""

# Step-helper class — NOT a framework node. AgentBaseGraph exposes exactly
# 3 fixed domain slots (pre_process/main/post_process); there is no 4th slot
# to register "KPI scoring" into. This class is pure Python, called from
# inside src/nodes/main_node.py's execute() (the real FunctionNode
# registered in the "main" slot) — see docs/02_design.md "Node mapping note".
#
# Do NOT inherit BaseNode/FunctionNode here, and do NOT call self.execute()
# from LangGraph — this class has no __call__() security pipeline; its
# gates (S-1/S-2/S-3/S-4) are provided entirely by MainNode.__call__().

from __future__ import annotations

from typing import Any

import yaml


class KPIScoringNode:
    """Tool 1-4 KPI scoring + Subcontract Act Article 4 prohibited-act
    flagging — see docs/02_design.md KPIScoringNode spec."""

    def __init__(self, kpi_thresholds: dict[str, Any], subcontract_rules: dict[str, Any]) -> None:
        self._kpi_thresholds = kpi_thresholds
        self._subcontract_rules = subcontract_rules

    def execute(self, suppliers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Score all four KPI dimensions and evaluate Subcontract Act flags
        for every supplier. Returns (kpi_scores, subcontract_act_flags)."""
        kpi_scores = []
        subcontract_act_flags = []

        for supplier in suppliers:
            supplier_id = supplier["supplier_id"]
            missing_scores: list[str] = []

            on_time_rate = self._score_on_time_delivery(supplier, missing_scores)
            defect_ppm = self._score_defect_ppm(supplier, missing_scores)
            invoice_error_rate = self._score_invoice_error_rate(supplier, missing_scores)
            responsiveness_score = self._score_responsiveness_sla(supplier, missing_scores)

            kpi_scores.append(
                {
                    "supplier_id": supplier_id,
                    "on_time_delivery_rate": on_time_rate,
                    "defect_ppm": defect_ppm,
                    "invoice_error_rate": invoice_error_rate,
                    "responsiveness_sla_score": responsiveness_score,
                    "missing_scores": missing_scores,
                }
            )

            subcontract_act_flags.append(self._check_subcontract_act(supplier))

        return kpi_scores, subcontract_act_flags

    # --- Tool 1: on-time delivery rate ---

    def _score_on_time_delivery(self, supplier: dict[str, Any], missing_scores: list[str]) -> float | None:
        records = supplier.get("delivery_records", [])
        if not records:
            missing_scores.append("on_time_delivery_rate")
            return None

        on_time = sum(1 for r in records if r.get("actual_date", "") <= r.get("contracted_date", ""))
        return float(round(on_time / len(records) * 100, 2))

    # --- Tool 2: defect PPM ---

    def _score_defect_ppm(self, supplier: dict[str, Any], missing_scores: list[str]) -> float | None:
        records = supplier.get("defect_return_logs", [])
        if not records:
            missing_scores.append("defect_ppm")
            return None

        received_qty = sum(r.get("received_qty", 0) for r in records)
        defect_qty = sum(r.get("defect_qty", 0) for r in records)
        if received_qty == 0:
            missing_scores.append("defect_ppm")
            return None

        return float(round(defect_qty / received_qty * 1_000_000, 2))

    # --- Tool 3: invoice error rate ---

    def _score_invoice_error_rate(self, supplier: dict[str, Any], missing_scores: list[str]) -> float | None:
        records = supplier.get("invoice_records", [])
        if not records:
            missing_scores.append("invoice_error_rate")
            return None

        discrepancies = sum(1 for r in records if r.get("has_discrepancy"))
        return float(round(discrepancies / len(records) * 100, 2))

    # --- Tool 4: responsiveness SLA score ---

    def _score_responsiveness_sla(self, supplier: dict[str, Any], missing_scores: list[str]) -> float | None:
        records = supplier.get("responsiveness_log", [])
        if not records:
            missing_scores.append("responsiveness_sla_score")
            return None

        sla_standard = self._kpi_thresholds.get("responsiveness_sla_hours", 24)
        within_sla = sum(1 for r in records if r.get("response_time_hours", float("inf")) <= sla_standard)
        return float(round(within_sla / len(records) * 100, 2))

    # --- Subcontract Act Article 4 prohibited-act determination ---

    def _check_subcontract_act(self, supplier: dict[str, Any]) -> dict[str, Any]:
        supplier_id = supplier["supplier_id"]
        rationale_parts: list[str] = []

        return_rate_flag = self._check_unjustified_return_rate(supplier, rationale_parts)
        payment_delay_flag = self._check_payment_delay(supplier, rationale_parts)

        rationale = (
            "; ".join(rationale_parts)
            if rationale_parts
            else "No Subcontract Act Article 4 prohibited-act conditions detected"
        )

        return {
            "supplier_id": supplier_id,
            "unjustified_return_rate_flag": return_rate_flag,
            "payment_delay_flag": payment_delay_flag,
            "determination_rationale": rationale,
        }

    def _check_unjustified_return_rate(self, supplier: dict[str, Any], rationale_parts: list[str]) -> bool:
        records = supplier.get("defect_return_logs", [])
        if not records:
            return False

        received_qty = sum(r.get("received_qty", 0) for r in records)
        returned_qty = sum(r.get("returned_qty", 0) for r in records)
        if received_qty == 0:
            return False

        return_rate = returned_qty / received_qty * 100
        limit = self._subcontract_rules.get("return_rate_limit_pct", 5.0)
        flagged = bool(return_rate > limit)
        if flagged:
            rationale_parts.append(f"Return rate {return_rate:.2f}% exceeds Subcontract Act limit {limit}%")
        return flagged

    def _check_payment_delay(self, supplier: dict[str, Any], rationale_parts: list[str]) -> bool:
        records = supplier.get("invoice_records", [])
        delay_limit_days = self._subcontract_rules.get("payment_delay_limit_days", 60)

        flagged = False
        for record in records:
            delay_days = record.get("payment_delay_days", 0)
            if delay_days > delay_limit_days:
                flagged = True
                rationale_parts.append(
                    f"Payment delay {delay_days} days exceeds Subcontract Act "
                    f"Article 4 limit {delay_limit_days} days"
                )
                break
        return flagged


def load_kpi_thresholds(path: str) -> dict[str, Any]:
    """Load config/kpi_thresholds.yaml (proposal §4 note: configurable per
    evaluation cycle without redeployment)."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_subcontract_rules(path: str) -> dict[str, Any]:
    """Load config/subcontract_rules.yaml (proposal §11 Risk #2: rule
    config must be updatable without redeployment when regulations change)."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
