#!/usr/bin/env python3
"""Send an SMTP email when update_data.py detects a meaningful FOMC change."""

from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def recipients_from(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def build_bodies(event: dict[str, Any], site_url: str) -> tuple[str, str]:
    changes = event.get("changes", [])
    plain_lines = ["美联储利率监控检测到以下变化：", ""]
    html_items: list[str] = []
    for item in changes:
        title = str(item.get("title", "FOMC 更新"))
        detail = str(item.get("detail", ""))
        url = str(item.get("url", ""))
        plain_lines.extend([f"- {title}", f"  {detail}", f"  {url}", ""])
        html_items.append(
            "<li style='margin:0 0 16px'>"
            f"<strong>{html.escape(title)}</strong><br>"
            f"<span style='color:#475569'>{html.escape(detail)}</span><br>"
            f"<a href='{html.escape(url, quote=True)}'>查看官方来源</a>"
            "</li>"
        )

    if site_url:
        plain_lines.extend(["仪表盘：", site_url])
    checked_at = str(event.get("checked_at", ""))
    html_body = f"""
<!doctype html>
<html lang="zh-CN">
<body style="margin:0;background:#f4f1e8;font-family:Arial,'PingFang SC',sans-serif;color:#102a2a">
  <div style="max-width:640px;margin:0 auto;padding:28px 18px">
    <div style="background:#0d3937;color:white;padding:24px;border-radius:16px 16px 0 0">
      <div style="font-size:12px;letter-spacing:.12em;color:#9ed2c8">FED RATE MONITOR</div>
      <h1 style="font-size:24px;margin:8px 0 0">FOMC 数据更新</h1>
    </div>
    <div style="background:white;padding:24px;border-radius:0 0 16px 16px">
      <ul style="padding-left:20px;margin:0">{''.join(html_items)}</ul>
      {f'<p><a href="{html.escape(site_url, quote=True)}" style="display:inline-block;background:#d96c3b;color:white;text-decoration:none;padding:10px 16px;border-radius:999px">打开仪表盘</a></p>' if site_url else ''}
      <p style="font-size:12px;color:#64748b;margin-top:24px">检测时间：{html.escape(checked_at)}（UTC）</p>
    </div>
  </div>
</body>
</html>
""".strip()
    return "\n".join(plain_lines).strip(), html_body


def send_message(message: EmailMessage, host: str, port: int, username: str, password: str) -> None:
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=45) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=45) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(username, password)
            server.send_message(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, default=ROOT / "runtime" / "change.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "email_preview.html")
    args = parser.parse_args()

    event = load_json(args.event)
    if not event.get("has_changes"):
        print("No meaningful FOMC change; email skipped.")
        return 0

    site_url = os.environ.get("SITE_URL", "").strip()
    plain_body, html_body = build_bodies(event, site_url)
    if args.dry_run:
        args.out.write_text(html_body + "\n", encoding="utf-8")
        print(f"Email preview written to {args.out}")
        return 0

    if os.environ.get("EMAIL_ENABLED", "false").strip().lower() not in {"1", "true", "yes"}:
        print("EMAIL_ENABLED is not true; email skipped.")
        return 0

    settings = {
        "SMTP_HOST": os.environ.get("SMTP_HOST", "").strip(),
        "SMTP_USERNAME": os.environ.get("SMTP_USERNAME", "").strip(),
        "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD", ""),
        "EMAIL_TO": os.environ.get("EMAIL_TO", "").strip(),
    }
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise ValueError(f"Missing email settings: {', '.join(missing)}")

    port = int(os.environ.get("SMTP_PORT", "").strip() or "465")
    sender = os.environ.get("EMAIL_FROM", "").strip() or settings["SMTP_USERNAME"]
    recipients = recipients_from(settings["EMAIL_TO"])
    first_title = str(event["changes"][0].get("title", "FOMC 数据更新"))

    message = EmailMessage()
    message["Subject"] = f"[美联储监控] {first_title}"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(plain_body)
    message.add_alternative(html_body, subtype="html")
    send_message(message, settings["SMTP_HOST"], port, settings["SMTP_USERNAME"], settings["SMTP_PASSWORD"])
    print(f"Notification sent to {len(recipients)} recipient(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"email failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
