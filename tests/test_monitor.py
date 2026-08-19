from copy import deepcopy
from pathlib import Path

from scripts.update_data import (
    add_sep_comparisons,
    attach_macro_snapshots,
    attach_meeting_outcomes,
    build_change_event,
    parse_calendar_html,
    parse_macro_csv,
    parse_rates_csv,
    parse_sep_html,
    parse_statement_vote,
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


def test_macro_snapshot_uses_pre_meeting_periods_and_yoy_values():
    macro_csv = """observation_date,UNRATE,PCEPI,PCEPILFE,PAYEMS
2024-01-01,3.7,100.0,100.0,150000
2024-02-01,3.8,100.2,100.3,150100
2024-03-01,3.9,100.4,100.6,150250
2024-04-01,3.9,100.6,100.9,150450
2024-05-01,4.0,100.8,101.2,150550
2024-06-01,4.1,101.0,101.5,150700
2024-07-01,4.2,101.2,101.8,150900
2024-08-01,4.2,101.4,102.1,151000
2024-09-01,4.1,101.6,102.4,151150
2024-10-01,4.1,101.8,102.7,151350
2024-11-01,4.2,102.0,103.0,151450
2024-12-01,4.1,102.2,103.3,151600
2025-01-01,4.0,102.5,103.5,151800
2025-02-01,4.1,102.7,103.8,151900
2025-03-01,4.2,102.9,104.1,152050
"""
    macro = parse_macro_csv(macro_csv)
    meetings = {
        "meetings": [
            {
                "end_date": "2025-03-19",
                "outcome": {"summary": "维持目标区间不变。"},
            }
        ]
    }
    attach_macro_snapshots(meetings, macro)
    snapshot = meetings["meetings"][0]["outcome"]["macro_snapshot"]
    assert snapshot["unemployment"] == {
        "period": "2025-02",
        "value": 4.1,
        "series": "UNRATE",
    }
    assert snapshot["pce_yoy"]["period"] == "2025-01"
    assert snapshot["pce_yoy"]["value"] == 2.5
    assert snapshot["core_pce_yoy"]["value"] == 3.5
    assert snapshot["payrolls_3m_average"]["value_thousands"] == 150
    assert snapshot["core_pce_3m_annualized"]["value"] == 3.2
    assert "就业：失业率 4.1%" in snapshot["employment_summary"]
    assert "非农近3个月月均新增 15.0万" in snapshot["employment_summary"]
    assert "核心 PCE 近3个月年化 3.2%" in snapshot["inflation_summary"]


def test_macro_snapshot_uses_first_friday_employment_release_boundary():
    macro_csv = """observation_date,UNRATE,PCEPI,PCEPILFE,PAYEMS
2023-05-01,3.6,99.6,99.6,149500
2023-06-01,3.6,99.7,99.7,149600
2023-07-01,3.6,99.8,99.8,149700
2023-08-01,3.7,99.9,99.9,149800
2023-09-01,3.8,100.0,100.0,149900
2023-10-01,3.9,100.1,100.1,150000
2024-05-01,3.9,102.0,102.1,151000
2024-06-01,4.0,102.1,102.2,151100
2024-07-01,4.0,102.2,102.3,151200
2024-08-01,4.0,102.3,102.5,151300
2024-09-01,4.1,102.5,102.7,151400
2024-10-01,4.2,102.8,103.0,151500
"""
    macro = parse_macro_csv(macro_csv)
    meetings = {
        "meetings": [
            {"end_date": "2024-10-31", "outcome": {"summary": "test"}},
            {"end_date": "2024-11-01", "outcome": {"summary": "test"}},
        ]
    }
    attach_macro_snapshots(meetings, macro)
    periods = [
        item["outcome"]["macro_snapshot"]["unemployment"]["period"]
        for item in meetings["meetings"]
    ]
    assert periods == ["2024-09", "2024-10"]


def test_statement_vote_extracts_dissent_and_preference():
    statement = """<html><body><p>Voting for the monetary policy action were
    Jerome H. Powell, Chair; John C. Williams, Vice Chair; and Lisa D. Cook.
    Voting against this action were Michelle W. Bowman and Christopher J. Waller,
    who preferred to lower the target range for the federal funds rate by 1/4
    percentage point at this meeting. Absent and not voting was Someone Else.</p></body></html>"""
    vote = parse_statement_vote(statement)
    assert vote is not None
    assert vote["support_count"] == 3
    assert vote["against_count"] == 2
    assert vote["against_names"] == ["Michelle W. Bowman", "Christopher J. Waller"]
    assert vote["preference"] == "主张降息25个基点"
    assert vote["summary"].startswith("表决 3–2")


def test_statement_vote_supports_new_count_first_format():
    statement = """<html><body>
    <p>The Federal Open Market Committee approved the following statement for release by a 9 – 3 vote:</p>
    <p>Voting against the monetary policy action were Beth M. Hammack, Neel Kashkari,
    and Lorie K. Logan, who preferred to raise the target range for the federal funds
    rate by 1/4 percentage point at this meeting.</p></body></html>"""
    vote = parse_statement_vote(statement)
    assert vote is not None
    assert vote["support_count"] == 9
    assert vote["against_names"] == ["Beth M. Hammack", "Neel Kashkari", "Lorie K. Logan"]
    assert vote["preference"] == "主张加息25个基点"
    assert vote["summary"].startswith("表决 9–3")


def test_sep_parser_and_comparison_use_published_medians():
    sep_html = """<html><body><table>
      <tr><th>Variable</th><th>Median</th><th>Central Tendency</th><th>Range</th></tr>
      <tr><th>2025</th><th>2026</th><th>Longer run</th><th>2025</th><th>2026</th><th>Longer run</th></tr>
      <tr><th>Memo: Projected appropriate policy path</th></tr>
      <tr><th>Federal funds rate</th><td>3.6</td><td>3.4</td><td>3.0</td><td>3.1–3.9</td><td>2.9–3.6</td><td>2.6–3.6</td></tr>
    </table></body></html>"""
    parsed = parse_sep_html(sep_html)
    assert parsed == {"medians": {"2025": 3.6, "2026": 3.4, "longer_run": 3.0}}

    meetings = {
        "meetings": [
            {
                "year": 2024,
                "outcome": {"sep": {"medians": {"2025": 3.9, "2026": 3.4}}},
            },
            {
                "year": 2025,
                "outcome": {"sep": {"medians": parsed["medians"]}},
            },
        ]
    }
    add_sep_comparisons(meetings)
    latest = meetings["meetings"][1]["outcome"]["sep"]
    assert latest["changes"]["2025"] == -0.3
    assert latest["changes"]["2026"] == 0.0
    assert latest["summary"] == "SEP：2026年末政策利率中位数 3.4%，与上次相同。"
