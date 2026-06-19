from lib.json_parser import repair_json_payload


def test_repair_json_payload_escapes_invalid_backslash_in_string():
    result = repair_json_payload(
        r'{"status": "OK", "summary": "Path C:\Program Files\Demo", "concerns": "None"}'
    )

    assert result["summary"] == r"Path C:\Program Files\Demo"


def test_repair_json_payload_preserves_valid_escapes():
    result = repair_json_payload(
        '{"status": "OK", "summary": "Line 1\\nLine 2", "concerns": "Quote: \\"ok\\""}'
    )

    assert result["summary"] == "Line 1\nLine 2"
    assert result["concerns"] == 'Quote: "ok"'
