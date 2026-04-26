"""
System powiadomień — Email (Gmail SMTP) + Telegram Bot
"""

import os
import json
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests as req

log = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _stars(n):
    return "★" * int(n) + "☆" * (5 - int(n)) if n else "?"


def _fmt_price(p):
    return f"{p:,.0f} zł".replace(",", " ") if p else "—"


# ── Email ─────────────────────────────────────────────────────────────────────

def _build_html(offers, new_keys: set) -> str:
    rows = []
    for o in sorted(offers, key=lambda x: x.price_total or 9_999_999):
        is_new = o.key() in new_keys
        badge = '<span style="background:#e74c3c;color:#fff;padding:2px 6px;border-radius:3px;font-size:11px">NOWA</span> ' if is_new else ""
        rows.append(f"""
        <tr style="background:{'#fff8f0' if is_new else '#fff'}">
          <td style="padding:8px 12px">{badge}{o.hotel}</td>
          <td style="padding:8px 12px;text-align:center">{o.source}</td>
          <td style="padding:8px 12px;text-align:center">{_stars(o.stars)}</td>
          <td style="padding:8px 12px;text-align:center">{o.rating or '—'}</td>
          <td style="padding:8px 12px;text-align:center">{o.nights}n</td>
          <td style="padding:8px 12px;text-align:center">{o.board or '—'}</td>
          <td style="padding:8px 12px;text-align:right;font-weight:bold">{_fmt_price(o.price_total)}</td>
          <td style="padding:8px 12px;text-align:center">
            <a href="{o.url}" style="color:#2980b9">🔗 Sprawdź</a>
          </td>
        </tr>""")

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:960px;margin:auto">
    <h2 style="color:#2c3e50">🏖️ Wakacje Monitor — Marsa Alam</h2>
    <p style="color:#7f8c8d">Raport z {datetime.now().strftime('%d.%m.%Y %H:%M')} |
       Znaleziono <b>{len(offers)}</b> ofert, w tym <b>{len(new_keys)}</b> nowych</p>
    <table border="0" cellspacing="0" cellpadding="0"
           style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="background:#2c3e50;color:#fff">
          <th style="padding:10px 12px;text-align:left">Hotel</th>
          <th style="padding:10px 12px">Serwis</th>
          <th style="padding:10px 12px">Gwiazdki</th>
          <th style="padding:10px 12px">Ocena</th>
          <th style="padding:10px 12px">Noce</th>
          <th style="padding:10px 12px">Wyżywienie</th>
          <th style="padding:10px 12px">Cena (4 os.)</th>
          <th style="padding:10px 12px">Link</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <p style="color:#bdc3c7;font-size:12px;margin-top:20px">
      Wakacje Monitor · GitHub Actions · automatyczny raport
    </p>
    </body></html>"""


def send_email(offers, new_keys: set):
    email_from = os.getenv("EMAIL_FROM")
    email_to   = os.getenv("EMAIL_TO")
    app_pass   = os.getenv("EMAIL_APP_PASS")

    if not all([email_from, email_to, app_pass]):
        log.warning("Email: brak konfiguracji (EMAIL_FROM/EMAIL_TO/EMAIL_APP_PASS)")
        return

    subject = (
        f"🏖️ [{len(offers)} ofert, {len(new_keys)} nowych] Marsa Alam "
        f"{datetime.now().strftime('%d.%m %H:%M')}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email_from
    msg["To"]      = email_to
    msg.attach(MIMEText(_build_html(offers, new_keys), "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(email_from, app_pass)
            s.sendmail(email_from, email_to, msg.as_string())
        log.info(f"Email wysłany → {email_to}")
    except Exception as e:
        log.error(f"Email błąd: {e}")


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(offers, new_keys: set):
    token   = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not all([token, chat_id]):
        log.warning("Telegram: brak konfiguracji (TELEGRAM_TOKEN/TELEGRAM_CHAT_ID)")
        return

    new_offers = [o for o in offers if o.key() in new_keys]
    top = sorted(new_offers or offers, key=lambda x: x.price_total or 9_999_999)[:5]

    lines = [
        f"🏖️ *Wakacje Monitor — Marsa Alam*",
        f"📊 {len(offers)} ofert łącznie, *{len(new_keys)} nowych*",
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
        "🔥 *Top oferty:*",
    ]
    for o in top:
        lines.append(
            f"• {o.hotel} | {o.nights}n | {_fmt_price(o.price_total)}\n"
            f"  ⭐{o.rating or '—'} | {o.board or '—'} | [Sprawdź]({o.url})"
        )

    text = "\n".join(lines)
    url  = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        r = req.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, timeout=15)
        r.raise_for_status()
        log.info("Telegram: wiadomość wysłana")
    except Exception as e:
        log.error(f"Telegram błąd: {e}")


# ── main dispatcher ───────────────────────────────────────────────────────────

def notify(offers, new_keys: set):
    """Wyślij powiadomienia jeśli są nowe oferty lub jest raport dzienny."""
    if not offers:
        log.info("Brak ofert — pomijam powiadomienia")
        return

    send_email(offers, new_keys)
    send_telegram(offers, new_keys)
