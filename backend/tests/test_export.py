"""Tests for chat export HTML/table handling."""

from routers.export import _build_html, _merge_history_tables


def test_merge_history_tables_recovers_missing_table_by_content():
    messages = [
        {
            "role": "assistant",
            "content": "There are 29 vehicle theft cases.",
            "has_table": True,
            "table_data": [],
        }
    ]
    history = [
        {
            "role": "assistant",
            "content": "There are 29 vehicle theft cases.",
            "table": [
                {"FIR_NUMBER": "FIR/2025/MAL/0001", "VEHICLE_MAKE": "Honda"}
            ],
        }
    ]

    merged = _merge_history_tables(messages, history)

    assert merged[0]["has_table"] is True
    assert merged[0]["table_data"] == history[0]["table"]


def test_build_html_renders_escaped_table_rows_and_record_count():
    html = _build_html(
        "Officer <One>",
        "KSP-1",
        "Vehicle theft <cases>",
        [
            {"role": "user", "content": "show vehicles <all>"},
            {
                "role": "assistant",
                "content": "Found rows",
                "table_data": [
                    {"FIR_NUMBER": "FIR/2025/MAL/0001", "VEHICLE_MAKE": "Honda"},
                    {"FIR_NUMBER": "FIR/2025/JAY/0001", "VEHICLE_MAKE": "<Tata>"},
                ],
            },
        ],
    )

    assert "<table>" in html
    assert "<th>FIR_NUMBER</th>" in html
    assert "FIR/2025/MAL/0001" in html
    assert "&lt;Tata&gt;" in html
    assert "2 records." in html
    assert "Officer &lt;One&gt;" in html
    assert "Vehicle theft &lt;cases&gt;" in html
