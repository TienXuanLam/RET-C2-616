"""AgentCore Platform v1.0"""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Return AgentStatus enum constants — never plain strings
#  - Read input_context via state.get("input_context", {}) — read-only
#  - Never import from mediator/, api/, or other agents

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.supplier_normalize_service import (
    SupplierPayloadError,
    normalize_evaluation_period,
    normalize_suppliers,
    parse_payload,
)

# S-2 (see docs/02_design.md PreProcessNode spec): reject payloads containing
# more raw records than this before normalization — supplier transaction
# data is confidential business data (proposal §10 Angle 5), so an
# oversized payload is rejected outright rather than partially processed.
MAX_RAW_RECORDS = 5_000


class PreProcessNode(FunctionNode):
    """Validate supplier payload, resolve/dedup supplier IDs, normalize
    the evaluation period, and flag missing KPI input fields."""

    # S-1: enforced per-node inside BaseNode.__call__(), not inherited from
    # config/agent.yaml's manifest-level declaration. Set to
    # VERIFIED_EXTERNAL to match the manifest and prevent an ANONYMOUS
    # caller from invoking this node directly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        # S-2:
        # type + size guard only. JSON-shape validation is left to execute()
        # so that an empty/missing user_input (the framework's own default)
        # is rejected via the normal business-logic error path rather than
        # at the gate — a pattern seen elsewhere in the fleet.
        raw_payload = state.get("user_input", "")
        if not isinstance(raw_payload, str):
            state = dict(state)
            state["status"] = AgentStatus.ERROR.value
            state["error_log"] = ["PreProcessNode: user_input must be a JSON string"]
            return state

        try:
            raw_records = parse_payload(raw_payload) if raw_payload.strip() else []
        except SupplierPayloadError as exc:
            state = dict(state)
            state["status"] = AgentStatus.ERROR.value
            state["error_log"] = [f"PreProcessNode: {exc}"]
            return state

        if len(raw_records) > MAX_RAW_RECORDS:
            state = dict(state)
            state["status"] = AgentStatus.ERROR.value
            state["error_log"] = [
                f"PreProcessNode: payload exceeds {MAX_RAW_RECORDS} record cap "
                "— split into smaller batches before invoking"
            ]
            return state

        return state

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_payload = state.get("user_input", "")
        input_context = state.get("input_context", {})  # read-only

        if not raw_payload.strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: user_input is empty or missing"],
            }

        try:
            raw_records = parse_payload(raw_payload)
        except SupplierPayloadError as exc:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"PreProcessNode: {exc}"],
            }

        if not raw_records:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: payload contains no supplier records"],
            }

        raw_period = input_context.get("evaluation_period", {})
        try:
            evaluation_period = normalize_evaluation_period(raw_period)
        except ValueError as exc:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"PreProcessNode: {exc}"],
            }

        suppliers, missing_field_flags = normalize_suppliers(raw_records, id_prefixes=input_context.get("id_prefixes"))
        if not suppliers:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: no usable supplier records after normalization"],
            }

        emit_trace_event(
            "suppliers_normalized",
            {
                "supplier_count": len(suppliers),
                "missing_field_count": sum(1 for f in missing_field_flags if f["missing_fields"]),
            },
            state,
        )

        return {
            "suppliers": suppliers,
            "missing_field_flags": missing_field_flags,
            "evaluation_period": evaluation_period,
            "status": AgentStatus.SUCCESS.value,
        }
