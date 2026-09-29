"""AgentCore Platform v1.0"""

# Service layer: supplier payload parsing, ID resolution/dedup, evaluation
# period normalization, and missing-KPI-field detection. Must NOT contain
# framework imports (no BaseNode/FunctionNode/AgentState here) — pure domain
# logic called by src/nodes/pre_process_node.py.

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

# Required per-supplier record groups (proposal_en.md §4 PreProcessNode spec).
_REQUIRED_RECORD_GROUPS = [
    "delivery_records",
    "defect_return_logs",
    "invoice_records",
    "responsiveness_log",
]

# Known ERP/WMS supplier ID prefixes to strip when resolving to a canonical
# ID (proposal §5: "Japan retail ERP/WMS-specific supplier ID formats
# (SAP/FutureShop, etc.)"). Caller may extend via input_context["id_prefixes"].
_DEFAULT_ID_PREFIXES = ["SAP-", "FS-", "WMS-"]

_DATE_FORMAT = "%Y-%m-%d"


class SupplierPayloadError(ValueError):
    """Raised when the raw payload cannot be parsed at all."""


def parse_payload(raw_payload: str) -> list[dict[str, Any]]:
    """Parse the caller-supplied JSON payload into a list of raw supplier
    records. Raises SupplierPayloadError on malformed JSON or wrong shape —
    caller (PreProcessNode) converts this into a status=error state update."""
    try:
        parsed = json.loads(raw_payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SupplierPayloadError(f"payload is not valid JSON: {exc}") from exc

    if not isinstance(parsed, list):
        raise SupplierPayloadError("payload must be a JSON array of supplier records")

    return parsed


def resolve_supplier_id(raw_id: str, extra_prefixes: list[str] | None = None) -> str:
    """Strip known ERP/WMS ID prefixes to produce a canonical supplier ID."""
    prefixes = list(_DEFAULT_ID_PREFIXES)
    if extra_prefixes:
        prefixes.extend(p for p in extra_prefixes if p not in prefixes)

    canonical = raw_id
    for prefix in prefixes:
        if canonical.startswith(prefix):
            canonical = canonical[len(prefix) :]
            break
    return canonical.strip().upper()


def normalize_evaluation_period(raw_period: dict[str, Any]) -> dict[str, str]:
    """Validate and normalize the caller-supplied evaluation period to
    ISO-8601 date strings. Raises ValueError on invalid/out-of-order dates."""
    start_raw = raw_period.get("start_date", "")
    end_raw = raw_period.get("end_date", "")

    try:
        start = datetime.strptime(start_raw, _DATE_FORMAT).date()
        end = datetime.strptime(end_raw, _DATE_FORMAT).date()
    except (ValueError, TypeError) as exc:
        raise ValueError(f"evaluation_period dates must be YYYY-MM-DD: {exc}") from exc

    if end < start:
        raise ValueError("evaluation_period end_date must not precede start_date")

    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def detect_missing_fields(record: dict[str, Any]) -> list[str]:
    """Return the list of required record groups absent from this supplier's
    raw record (proposal §11 Risk #4: missing KPI input, e.g. no invoice
    error rate data for some suppliers)."""
    return [group for group in _REQUIRED_RECORD_GROUPS if not record.get(group)]


def normalize_suppliers(
    raw_records: list[dict[str, Any]], id_prefixes: list[str] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve/dedup supplier IDs and detect missing fields across the raw
    payload. Returns (normalized_suppliers, missing_field_flags).

    Dedup: multiple raw records resolving to the same canonical supplier_id
    (e.g. one ERP export per data type) are merged — record groups from
    later entries fill in groups absent from earlier ones, so partial
    per-type exports for the same supplier don't produce duplicate entries.
    """
    merged: dict[str, dict[str, Any]] = {}
    for raw in raw_records:
        raw_id = raw.get("supplier_id", "")
        canonical_id = resolve_supplier_id(raw_id, extra_prefixes=id_prefixes)

        existing = merged.setdefault(canonical_id, {"supplier_id": canonical_id})
        for group in _REQUIRED_RECORD_GROUPS:
            if raw.get(group):
                existing.setdefault(group, [])
                existing[group] = existing[group] + raw[group]

    suppliers = list(merged.values())
    missing_field_flags = [
        {"supplier_id": s["supplier_id"], "missing_fields": detect_missing_fields(s)} for s in suppliers
    ]
    return suppliers, missing_field_flags
