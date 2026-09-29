# PB-3 (domain): msgpack round-trip verification for formatted_output
# Confirms at runtime — not just by static type inspection — that the
# nested list[dict] structure produced by post_process (json_scorecard +
# markdown_report) survives LangGraph's msgpack checkpoint serialization.

import msgpack

from src.services.output_assembly_service import assemble_json_scorecard, render_markdown_report


def _sample_formatted_output() -> dict:
    json_scorecard = assemble_json_scorecard(
        kpi_scores=[{
            "supplier_id": "ABC123",
            "on_time_delivery_rate": 50.0,
            "defect_ppm": 10000.0,
            "invoice_error_rate": 50.0,
            "responsiveness_sla_score": 50.0,
            "missing_scores": [],
        }],
        subcontract_act_flags=[{
            "supplier_id": "ABC123",
            "unjustified_return_rate_flag": True,
            "payment_delay_flag": False,
            "determination_rationale": "Return rate 8.00% exceeds Subcontract Act limit 5.0%",
        }],
        scorecard_narrative=[{
            "supplier_id": "ABC123",
            "kpi_trend_narrative": "納品パフォーマンスに改善余地あり。",
            "corrective_recommendations": ["Review return process with supplier"],
            "gx_scope3_notes": "データ品質は十分。",
        }],
        evaluation_period={"start_date": "2026-01-01", "end_date": "2026-03-31"},
    )
    markdown_report = render_markdown_report(json_scorecard)
    return {"json_scorecard": json_scorecard, "markdown_report": markdown_report}


class TestMsgpackRoundtrip:
    def test_formatted_output_survives_msgpack_roundtrip(self):
        payload = _sample_formatted_output()

        packed = msgpack.packb(payload, use_bin_type=True)
        unpacked = msgpack.unpackb(packed, raw=False)

        assert unpacked == payload

    def test_japanese_narrative_text_survives_roundtrip_unmangled(self):
        payload = _sample_formatted_output()

        packed = msgpack.packb(payload, use_bin_type=True)
        unpacked = msgpack.unpackb(packed, raw=False)

        narrative = unpacked["json_scorecard"]["suppliers"][0]
        assert narrative["kpi_trend_narrative"] == "納品パフォーマンスに改善余地あり。"
        assert narrative["gx_scope3_notes"] == "データ品質は十分。"

    def test_markdown_report_string_survives_roundtrip(self):
        payload = _sample_formatted_output()

        packed = msgpack.packb(payload, use_bin_type=True)
        unpacked = msgpack.unpackb(packed, raw=False)

        assert "ABC123" in unpacked["markdown_report"]
        assert "下請法" in unpacked["markdown_report"]
