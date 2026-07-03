import json


def test_extract_json_block_parses_fenced_json():
    from scripts.generate_report import extract_json_block

    text = 'some preamble\n```json\n{"daily_brief": "abc"}\n```\ntrailing text'
    assert extract_json_block(text) == {"daily_brief": "abc"}


def test_extract_json_block_returns_none_when_no_fence():
    from scripts.generate_report import extract_json_block

    assert extract_json_block("no json here") is None


def test_extract_json_block_returns_none_on_invalid_json():
    from scripts.generate_report import extract_json_block

    assert extract_json_block("```json\n{not valid json\n```") is None


def test_validate_narrative_json_lists_missing_fields():
    from scripts.generate_report import validate_narrative_json, REQUIRED_JSON_FIELDS

    assert validate_narrative_json(None) == REQUIRED_JSON_FIELDS
    assert validate_narrative_json({f: None for f in REQUIRED_JSON_FIELDS}) == []
    partial = {f: None for f in REQUIRED_JSON_FIELDS if f != "daily_brief"}
    assert validate_narrative_json(partial) == ["daily_brief"]
