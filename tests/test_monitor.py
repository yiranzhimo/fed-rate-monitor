from copy import deepcopy
from pathlib import Path

from scripts.update_data import build_change_event, parse_calendar_html, parse_rates_csv


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_calendar_extracts_dates_and_documents():
    result = parse_calendar_html((FIXTURES / "calendar.html").read_text())
    meeting = result["meetings"][0]
    assert meeting["start_date"] == "2026-03-17"
    assert meeting["end_date"] == "2026-03-18"
    assert meeting["has_sep"] is True
    assert meeting["minutes_release_date"] == "2026-04-08"
    assert meeting["documents"]["statement_html"].endswith("monetary20260318a.htm")
    assert meeting["documents"]["implementation_note"].endswith("monetary20260318a1.htm")
    assert meeting["documents"]["projections_html"].endswith("fomcprojtabl20260318.htm")


def test_parse_rates_compresses_history_and_classifies_moves():
    result = parse_rates_csv((FIXTURES / "rates.csv").read_text())
    assert result["current"] == {"as_of": "2025-05-08", "upper": 4.5, "lower": 4.25, "midpoint": 4.375}
    assert len(result["history"]) == 3
    assert result["history"][1]["decision"] == "cut"
    assert result["history"][1]["delta_bps"] == -25
    assert result["latest_change"]["decision"] == "hike"


def test_initialization_does_not_notify():
    meetings = parse_calendar_html((FIXTURES / "calendar.html").read_text())
    rates = parse_rates_csv((FIXTURES / "rates.csv").read_text())
    event = build_change_event(None, meetings, None, rates)
    assert event["initialized"] is True
    assert event["has_changes"] is False


def test_rate_and_document_changes_notify():
    meetings = parse_calendar_html((FIXTURES / "calendar.html").read_text())
    rates = parse_rates_csv((FIXTURES / "rates.csv").read_text())
    old_meetings = deepcopy(meetings)
    del old_meetings["meetings"][0]["documents"]["minutes_html"]
    old_rates = deepcopy(rates)
    old_rates["current"]["lower"] = 4.0
    old_rates["current"]["upper"] = 4.25
    event = build_change_event(old_meetings, meetings, old_rates, rates)
    assert event["has_changes"] is True
    assert {item["kind"] for item in event["changes"]} == {"rate_change", "document_added"}
