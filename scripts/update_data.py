#!/usr/bin/env python3
"""Fetch and normalize official FOMC calendar and federal-funds data."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RUNTIME_DIR = ROOT / "runtime"

CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
RATES_CSV_URL = (
    "https://fred.stlouisfed.org/graph/fredgraph.csv?"
    "id=DFEDTARU,DFEDTARL,DFEDTAR,DFF"
)
MACRO_CSV_URL = (
    "https://fred.stlouisfed.org/graph/fredgraph.csv?"
    "id=UNRATE,PCEPI,PCEPILFE"
)
USER_AGENT = "fed-rate-monitor/1.0 (+https://github.com/)"

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

NOTIFY_DOCUMENTS = {
    "statement_html": "政策声明",
    "implementation_note": "实施说明",
    "projections_html": "经济预测（SEP）",
    "minutes_html": "会议纪要",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_text(url: str, timeout: int = 30) -> str:
    """Fetch a URL with bounded retries and an explicit user agent."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/csv,*/*"},
                timeout=timeout,
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            return response.text.lstrip("\ufeff")
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def _document_key(label: str, href: str) -> str | None:
    label_lower = label.lower()
    href_lower = href.lower()
    suffix = "pdf" if href_lower.endswith(".pdf") else "html"

    if "fomcminutes" in href_lower:
        return f"minutes_{suffix}"
    if "fomcprojtabl" in href_lower:
        return f"projections_{suffix}"
    if "fomcpresconf" in href_lower:
        return "press_conference"
    if "implementation note" in label_lower:
        return "implementation_note"
    if (
        "/monetarypolicy/files/monetary" in href_lower
        or "/newsevents/pressreleases/monetary" in href_lower
    ):
        return f"statement_{suffix}"
    return None


def parse_calendar_html(html_text: str) -> dict[str, Any]:
    soup = BeautifulSoup(html_text, "html.parser")
    meetings: list[dict[str, Any]] = []

    for heading in soup.select(".panel-heading h4"):
        match = re.search(r"(20\d{2})\s+FOMC Meetings", heading.get_text(" ", strip=True))
        if not match:
            continue
        year = int(match.group(1))
        panel = heading.find_parent("div", class_="panel")
        if panel is None:
            continue

        for row in panel.select(".fomc-meeting"):
            month_node = row.select_one(".fomc-meeting__month")
            date_node = row.select_one(".fomc-meeting__date")
            if month_node is None or date_node is None:
                continue

            month_text = month_node.get_text(" ", strip=True).lower()
            month = MONTHS.get(month_text)
            raw_dates = date_node.get_text(" ", strip=True)
            days = [int(value) for value in re.findall(r"\d{1,2}", raw_dates)]
            if month is None or not days:
                continue

            start_date = f"{year:04d}-{month:02d}-{days[0]:02d}"
            end_date = f"{year:04d}-{month:02d}-{days[-1]:02d}"
            documents: dict[str, str] = {}
            for anchor in row.find_all("a", href=True):
                label = anchor.get_text(" ", strip=True)
                href = str(anchor["href"])
                key = _document_key(label, href)
                if key:
                    documents.setdefault(key, urljoin(CALENDAR_URL, href))

            row_text = row.get_text(" ", strip=True)
            released = re.search(r"Released\s+([A-Za-z]+\s+\d{1,2},\s+20\d{2})", row_text)
            minutes_release_date = None
            if released:
                try:
                    minutes_release_date = datetime.strptime(
                        released.group(1), "%B %d, %Y"
                    ).date().isoformat()
                except ValueError:
                    minutes_release_date = None

            meetings.append(
                {
                    "id": end_date,
                    "year": year,
                    "month": month,
                    "start_date": start_date,
                    "end_date": end_date,
                    "date_label": raw_dates.replace("*", "").strip(),
                    "has_sep": "*" in raw_dates,
                    "is_notation_vote": "notation vote" in raw_dates.lower(),
                    "minutes_release_date": minutes_release_date,
                    "documents": documents,
                }
            )

    if not meetings:
        raise ValueError("No FOMC meetings found; calendar markup may have changed")

    meetings.sort(key=lambda item: item["end_date"])
    return {"source": CALENDAR_URL, "meetings": meetings}


def _number(value: str | None) -> float | None:
    if value is None or value.strip() in {"", "."}:
        return None
    return float(value)


def _clean_bps(value: float) -> int | float:
    rounded = round(value, 4)
    return int(rounded) if rounded.is_integer() else rounded


def parse_rates_csv(csv_text: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    rows = list(reader)
    if not rows:
        raise ValueError("FRED rates CSV is empty")

    policy_rows: list[tuple[str, float, float, str]] = []
    effr_rows: list[tuple[str, float]] = []
    for row in rows:
        date = (row.get("observation_date") or "").strip()
        upper = _number(row.get("DFEDTARU"))
        lower = _number(row.get("DFEDTARL"))
        single_target = _number(row.get("DFEDTAR"))
        effr = _number(row.get("DFF"))
        if date and upper is not None and lower is not None:
            policy_rows.append((date, upper, lower, "target_range"))
        elif date and single_target is not None:
            policy_rows.append((date, single_target, single_target, "single_target"))
        if date and effr is not None:
            effr_rows.append((date, effr))

    if not policy_rows:
        raise ValueError("No policy-target observations found in FRED CSV")
    if not effr_rows:
        raise ValueError("No effective-rate observations found in FRED CSV")

    history: list[dict[str, Any]] = []
    previous: tuple[float, float, str] | None = None
    for date, upper, lower, regime in policy_rows:
        current = (upper, lower, regime)
        if current == previous:
            continue
        midpoint = round((upper + lower) / 2, 4)
        if previous is None:
            delta_bps: int | float = 0
            decision = "initial"
        else:
            previous_midpoint = (previous[0] + previous[1]) / 2
            delta_bps = _clean_bps((midpoint - previous_midpoint) * 100)
            if previous[2] != regime:
                decision = "regime_change"
            else:
                decision = "hike" if delta_bps > 0 else "cut" if delta_bps < 0 else "range_change"
        history.append(
            {
                "effective_date": date,
                "upper": upper,
                "lower": lower,
                "midpoint": midpoint,
                "regime": regime,
                "delta_bps": delta_bps,
                "decision": decision,
            }
        )
        previous = current

    latest_date, latest_upper, latest_lower, latest_regime = policy_rows[-1]
    effr_date, effr = effr_rows[-1]
    latest_change = next((item for item in reversed(history) if item["decision"] != "initial"), None)
    return {
        "source": RATES_CSV_URL,
        "series": {
            "single_target": "DFEDTAR",
            "upper": "DFEDTARU",
            "lower": "DFEDTARL",
            "effective_rate": "DFF",
        },
        "current": {
            "as_of": latest_date,
            "upper": latest_upper,
            "lower": latest_lower,
            "midpoint": round((latest_upper + latest_lower) / 2, 4),
            "regime": latest_regime,
        },
        "effective_rate": {"as_of": effr_date, "value": effr},
        "latest_change": latest_change,
        "history": history,
    }


def parse_macro_csv(csv_text: str) -> dict[str, Any]:
    """Parse official employment and PCE price-index series from FRED."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    expected = {"UNRATE", "PCEPI", "PCEPILFE"}
    if not reader.fieldnames or not expected.issubset(reader.fieldnames):
        raise ValueError("FRED macro CSV is missing required series")

    observations: dict[str, list[dict[str, Any]]] = {series: [] for series in expected}
    for row in reader:
        observation_date = (row.get("observation_date") or "").strip()
        if not observation_date:
            continue
        for series in expected:
            value = _number(row.get(series))
            if value is not None:
                observations[series].append({"date": observation_date, "value": value})

    if any(not observations[series] for series in expected):
        raise ValueError("FRED macro CSV contains an empty required series")

    return {
        "source": MACRO_CSV_URL,
        "series": {
            "unemployment_rate": "UNRATE",
            "pce_price_index": "PCEPI",
            "core_pce_price_index": "PCEPILFE",
        },
        "observations": observations,
    }


def _month_offset(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _latest_observation(
    observations: list[dict[str, Any]], cutoff: date
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in reversed(observations)
            if date.fromisoformat(item["date"]) <= cutoff
        ),
        None,
    )


def _year_over_year(
    observations: list[dict[str, Any]], cutoff: date
) -> dict[str, Any] | None:
    current = _latest_observation(observations, cutoff)
    if current is None:
        return None
    previous_date = _month_offset(date.fromisoformat(current["date"]), -12).isoformat()
    previous = next((item for item in observations if item["date"] == previous_date), None)
    if previous is None or previous["value"] == 0:
        return None
    return {
        "period": current["date"][:7],
        "value": round((current["value"] / previous["value"] - 1) * 100, 1),
    }


def _unemployment_cutoff(meeting_end: date) -> date:
    """Estimate the latest released reference month conservatively.

    The Employment Situation is normally published on the first Friday after its
    reference month. This rule avoids selecting the current meeting month while
    correctly handling early-month FOMC meetings on either side of that Friday.
    """
    first_day = meeting_end.replace(day=1)
    first_friday_day = 1 + (4 - first_day.weekday()) % 7
    lag = -1 if meeting_end.day >= first_friday_day else -2
    return _month_offset(meeting_end, lag)


def attach_macro_snapshots(
    meetings_data: dict[str, Any], macro_data: dict[str, Any]
) -> dict[str, Any]:
    """Add a conservative meeting-time employment and inflation snapshot.

    FRED's keyless CSV provides current revised observations, not ALFRED vintages.
    To avoid selecting a month that had not yet been released, unemployment uses
    the prior month once the next month's first Friday has passed, while PCE uses
    two months back. Periods and the revision limitation are stored explicitly.
    """
    observations = macro_data["observations"]
    for meeting in meetings_data.get("meetings", []):
        outcome = meeting.get("outcome")
        if not outcome:
            continue

        end_date = date.fromisoformat(meeting["end_date"])
        unemployment_cutoff = _unemployment_cutoff(end_date)
        pce_cutoff = _month_offset(end_date, -2)

        unemployment = _latest_observation(observations["UNRATE"], unemployment_cutoff)
        pce = _year_over_year(observations["PCEPI"], pce_cutoff)
        core_pce = _year_over_year(observations["PCEPILFE"], pce_cutoff)
        if unemployment is None or pce is None or core_pce is None:
            continue

        snapshot = {
            "unemployment": {
                "period": unemployment["date"][:7],
                "value": round(unemployment["value"], 1),
                "series": "UNRATE",
            },
            "pce_yoy": {**pce, "series": "PCEPI"},
            "core_pce_yoy": {**core_pce, "series": "PCEPILFE"},
            "method": "conservative_release_lag_current_vintage",
            "source": macro_data["source"],
        }
        snapshot["summary"] = (
            f"会议前宏观数据：失业率 {snapshot['unemployment']['value']:.1f}%"
            f"（{snapshot['unemployment']['period']}）；PCE 通胀 {pce['value']:.1f}%、"
            f"核心 PCE 通胀 {core_pce['value']:.1f}%（同比，{pce['period']}）。"
        )
        outcome["macro_snapshot"] = snapshot

    return meetings_data


def _rate_range_text(lower: float, upper: float) -> str:
    return f"{lower:.2f}%–{upper:.2f}%"


def attach_meeting_outcomes(
    meetings_data: dict[str, Any], rates_data: dict[str, Any]
) -> dict[str, Any]:
    """Attach concise, deterministic outcomes to meetings with official statements.

    Target changes can become effective shortly after the meeting ends. A meeting is
    therefore described as a hold only after the rate series has advanced beyond the
    two-day confirmation window; until then it remains explicitly pending.
    """
    history = rates_data.get("history", [])
    data_as_of = date.fromisoformat(rates_data["current"]["as_of"])

    for meeting in meetings_data.get("meetings", []):
        meeting.pop("outcome", None)
        documents = meeting.get("documents", {})
        if not documents.get("statement_html"):
            continue

        start_date = date.fromisoformat(meeting["start_date"])
        end_date = date.fromisoformat(meeting["end_date"])
        if end_date > data_as_of:
            continue

        if meeting.get("is_notation_vote"):
            meeting["outcome"] = {
                "status": "confirmed",
                "action": "notation_vote",
                "summary": "书面表决，不属于常规利率决议。",
                "statement_url": documents["statement_html"],
            }
            continue

        before = next(
            (
                item
                for item in reversed(history)
                if date.fromisoformat(item["effective_date"]) < start_date
            ),
            None,
        )
        if before is None:
            continue

        confirmation_end = end_date + timedelta(days=2)
        changes = [
            item
            for item in history
            if start_date <= date.fromisoformat(item["effective_date"]) <= confirmation_end
        ]

        if changes:
            result = changes[-1]
            delta_bps = result["delta_bps"]
            action = "hike" if delta_bps > 0 else "cut" if delta_bps < 0 else "change"
            action_text = "加息" if action == "hike" else "降息" if action == "cut" else "调整"
            summary = (
                f"{action_text} {abs(delta_bps):g} 个基点，目标区间调整至 "
                f"{_rate_range_text(result['lower'], result['upper'])}"
            )
            effective_date = result["effective_date"]
        elif data_as_of <= confirmation_end:
            meeting["outcome"] = {
                "status": "pending_confirmation",
                "action": "pending",
                "summary": "政策声明已发布，目标利率结果等待官方序列确认。",
                "statement_url": documents["statement_html"],
            }
            continue
        else:
            result = before
            delta_bps = 0
            action = "hold"
            summary = f"维持目标区间 {_rate_range_text(result['lower'], result['upper'])} 不变"
            effective_date = meeting["end_date"]

        summary += "；发布经济预测（SEP）。" if meeting.get("has_sep") else "；未发布 SEP。"
        meeting["outcome"] = {
            "status": "confirmed",
            "action": action,
            "delta_bps": delta_bps,
            "lower": result["lower"],
            "upper": result["upper"],
            "effective_date": effective_date,
            "summary": summary,
            "statement_url": documents["statement_html"],
            "rate_source": rates_data["source"],
        }

    return meetings_data


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
            return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def build_change_event(
    old_meetings: dict[str, Any] | None,
    new_meetings: dict[str, Any],
    old_rates: dict[str, Any] | None,
    new_rates: dict[str, Any],
) -> dict[str, Any]:
    initialized = old_meetings is None or old_rates is None
    changes: list[dict[str, str]] = []

    if not initialized:
        old_current = old_rates.get("current", {})
        new_current = new_rates.get("current", {})
        old_range = (old_current.get("lower"), old_current.get("upper"))
        new_range = (new_current.get("lower"), new_current.get("upper"))
        if old_range != new_range:
            latest = new_rates.get("latest_change") or {}
            delta = latest.get("delta_bps", 0)
            action = "加息" if delta > 0 else "降息" if delta < 0 else "调整目标区间"
            changes.append(
                {
                    "kind": "rate_change",
                    "title": f"美联储{action} {abs(delta):g} 个基点",
                    "detail": (
                        f"目标区间由 {old_range[0]:g}%–{old_range[1]:g}% "
                        f"变为 {new_range[0]:g}%–{new_range[1]:g}%"
                    ),
                    "url": CALENDAR_URL,
                }
            )

        old_items = {item["id"]: item for item in old_meetings.get("meetings", [])}
        new_items = {item["id"]: item for item in new_meetings.get("meetings", [])}
        old_schedule = {(item["start_date"], item["end_date"]) for item in old_items.values()}
        new_schedule = {(item["start_date"], item["end_date"]) for item in new_items.values()}
        if old_schedule != new_schedule:
            changes.append(
                {
                    "kind": "schedule_change",
                    "title": "FOMC 会议日程发生变化",
                    "detail": "官方会议日历新增、删除或调整了会议日期。",
                    "url": CALENDAR_URL,
                }
            )

        for meeting_id, new_item in new_items.items():
            old_item = old_items.get(meeting_id)
            if old_item is None:
                continue
            old_docs = old_item.get("documents", {})
            for key, label in NOTIFY_DOCUMENTS.items():
                new_url = new_item.get("documents", {}).get(key)
                if new_url and not old_docs.get(key):
                    changes.append(
                        {
                            "kind": "document_added",
                            "title": f"FOMC 发布{label}",
                            "detail": f"对应会议结束日期：{meeting_id}",
                            "url": new_url,
                        }
                    )

    return {
        "checked_at": utc_now(),
        "initialized": initialized,
        "has_changes": bool(changes),
        "changes": changes,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calendar-file", type=Path, help="Use a local calendar HTML fixture")
    parser.add_argument("--rates-file", type=Path, help="Use a local rates CSV fixture")
    parser.add_argument("--macro-file", type=Path, help="Use a local macro CSV fixture")
    args = parser.parse_args()

    old_meetings = load_json(DATA_DIR / "meetings.json")
    old_rates = load_json(DATA_DIR / "rates.json")

    calendar_html = (
        args.calendar_file.read_text(encoding="utf-8")
        if args.calendar_file
        else fetch_text(CALENDAR_URL)
    )
    rates_csv = (
        args.rates_file.read_text(encoding="utf-8")
        if args.rates_file
        else fetch_text(RATES_CSV_URL)
    )
    macro_csv = (
        args.macro_file.read_text(encoding="utf-8")
        if args.macro_file
        else fetch_text(MACRO_CSV_URL)
    )

    meetings = parse_calendar_html(calendar_html)
    rates = parse_rates_csv(rates_csv)
    macro = parse_macro_csv(macro_csv)
    attach_meeting_outcomes(meetings, rates)
    attach_macro_snapshots(meetings, macro)
    event = build_change_event(old_meetings, meetings, old_rates, rates)

    data_changed = meetings != old_meetings or rates != old_rates
    if meetings != old_meetings:
        write_json(DATA_DIR / "meetings.json", meetings)
    if rates != old_rates:
        write_json(DATA_DIR / "rates.json", rates)
    if data_changed:
        write_json(
            DATA_DIR / "metadata.json",
            {
                "updated_at": utc_now(),
                "calendar_source": CALENDAR_URL,
                "rates_source": RATES_CSV_URL,
                "macro_source": MACRO_CSV_URL,
                "methodology": (
                    "Before 2008-12-16 the path uses the official single target rate. "
                    "From that date onward it uses the midpoint of the official target "
                    "range while retaining the original upper and lower bounds. Meeting "
                    "macro snapshots use conservative publication lags and current revised "
                    "FRED values; they are not ALFRED point-in-time vintages."
                ),
            },
        )
    write_json(RUNTIME_DIR / "change.json", event)

    print(
        json.dumps(
            {
                "meetings": len(meetings["meetings"]),
                "rate_changes": len(rates["history"]),
                "data_changed": data_changed,
                "notifications": len(event["changes"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # Keep a concise, actionable Actions log.
        print(f"update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
