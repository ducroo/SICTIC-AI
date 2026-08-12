import pytest

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


def test_repair_json_payload_removes_trailing_comma_from_object():
    result = repair_json_payload('{"startup_name": "Acme", "rank": 1,}')

    assert result == {"startup_name": "Acme", "rank": 1}


def test_repair_json_payload_removes_trailing_comma_from_array():
    result = repair_json_payload('[{"rank": 1},]')

    assert result == [{"rank": 1}]


def test_repair_json_payload_removes_nested_trailing_commas():
    result = repair_json_payload(
        '''
        {
          "rankings": [
            {"startup_name": "Acme", "rank": 1,},
          ],
        }
        '''
    )

    assert result == {
        "rankings": [{"startup_name": "Acme", "rank": 1}],
    }


def test_repair_json_payload_preserves_comma_sequences_inside_strings():
    result = repair_json_payload(
        '{"text": "Keep literal ,} and ,] sequences",}'
    )

    assert result["text"] == "Keep literal ,} and ,] sequences"


def test_repair_json_payload_handles_escaped_quotes_while_removing_comma():
    result = repair_json_payload(
        '{"text": "Quote: \\"ok\\", followed by ,}",}'
    )

    assert result["text"] == 'Quote: "ok", followed by ,}'


def test_repair_json_payload_combines_backslash_and_trailing_comma_repairs():
    result = repair_json_payload(
        r'{"summary": "Path C:\Program Files\Demo", "status": "OK",}'
    )

    assert result == {
        "summary": r"Path C:\Program Files\Demo",
        "status": "OK",
    }


def test_repair_json_payload_does_not_repair_unquoted_property_names():
    with pytest.raises(ValueError, match="Expecting property name"):
        repair_json_payload('{startup_name: "Acme",}')
