from copy import deepcopy
from pathlib import Path

from scripts.update_data import (
    attach_meeting_outcomes,
    build_change_event,
    parse_calendar_html,
    parse_rates_csv,
)


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
    assert result["current"] == {
        "as_of": "2025-05-08",
        "upper": 4.5,
        "lower": 4.25,
        "midpoint": 4.375,
        "regime": "target_range",
    }
    assert len(result["history"]) == 6
    assert result["history"][0]["regime"] == "single_target"
    assert result["history"][0]["effective_date"] == "1982-09-27"
    assert result["history"][2]["decision"] == "regime_change"
    assert result["history"][2]["midpoint"] == 0.125
    cut = next(item for item in result["history"] if item["effective_date"] == "2025-03-20")
    assert cut["decision"] == "cut"
    assert cut["delta_bps"] == -25
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


def test_meeting_outcomes_distinguish_cut_hike_and_hold():
    rates = parse_rates_csv((FIXTURES / "rates.csv").read_text())
    meetings = {
        "meetings": [
            {
                "start_date": "2025-02-01",
                "end_date": "2025-02-01",
                "has_sep": False,
                "is_notation_vote": False,
                "documents": {"statement_html": "https://example.com/hold"},
            },
            {
                "start_date": "2025-03-19",
                "end_date": "2025-03-19",
                "has_sep": True,
                "is_notation_vote": False,
                "documents": {"statement_html": "https://example.com/cut"},
            },
            {
                "start_date": "2025-05-07",
                "end_date": "2025-05-07",
                "has_sep": False,
                "is_notation_vote": False,
                "documents": {"statement_html": "https://example.com/hike"},
            },
        ]
    }
    attach_meeting_outcomes(meetings, rates)
    hold, cut, hike = [item["outcome"] for item in meetings["meetings"]]
    assert hold["action"] == "hold"
    assert "维持目标区间 4.25%–4.50%" in hold["summary"]
    assert cut["action"] == "cut"
    assert cut["delta_bps"] == -25
    assert "发布经济预测" in cut["summary"]
    assert hike["action"] == "hike"
    assert hike["delta_bps"] == 25
