"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption.  Extend AgentState with agent-specific
# fields only.  Do NOT add credentials, secrets, or Pydantic models.

from typing import Any

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Agent state for RetailSupplierQualitySLAScorecardAgent.

    All shared fields (user_input, status, session_id, node_history,
    error_log, hitl_*, etc.) are inherited from AgentState. Fields below
    are specific to the supplier SLA scoring + Subcontract Act compliance
    pipeline. See docs/02_design.md "State Definition" for the field-by-field
    producer/consumer mapping.
    """

    # Caller-supplied invocation parameters, copied out of input_context by
    # pre_process; input_context itself remains read-only.
    evaluation_period: dict[str, str]  # {"start_date": str, "end_date": str}

    # Produced by pre_process
    suppliers: list[
        dict[str, Any]
    ]  # [{"supplier_id", "delivery_records", "defect_return_logs", "invoice_records", "responsiveness_log"}, ...]
    missing_field_flags: list[dict[str, Any]]  # [{"supplier_id", "missing_fields": [str, ...]}, ...]

    # Produced by main (KPIScoringNode step)
    kpi_scores: list[
        dict[str, Any]
    ]  # [{"supplier_id", "on_time_delivery_rate", "defect_ppm", "invoice_error_rate", "responsiveness_sla_score", "missing_scores"}, ...]
    subcontract_act_flags: (
        list[
            dict[str, Any]
        ]  # [{"supplier_id", "unjustified_return_rate_flag", "payment_delay_flag", "determination_rationale"}, ...]
    )

    # Produced by main (DocGenerationNode step)
    scorecard_narrative: (
        list[
            dict[str, Any]
        ]  # [{"supplier_id", "kpi_trend_narrative", "corrective_recommendations", "gx_scope3_notes"}, ...]
    )

    # Produced by post_process
    formatted_output: dict[str, Any]  # {"json_scorecard": dict, "markdown_report": str}
