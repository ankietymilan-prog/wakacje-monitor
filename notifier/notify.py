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

# ─── Konfiguracja (z zmiennych środowiskowych) ────────────────────────────────

EMAIL_FROM    = os.getenv("EMAIL_FROM", "")          # Twój Gmail
EMAIL_TO      = os.getenv("EMAIL_TO", "")            # Docelowy email
EMAIL_PASS    = os.getenv("EMAIL_APP_PASS", "")      # Hasło aplikacji Gmail
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")     # Token bota Telegram
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")   # Chat ID

BOARD_LABELS = {"AI": "All Inclusive", "HB": "Half Board", "BB": "Bed & Breakfast", "FB": "Full Board"}


# ─── Formatowanie HTML emaila ─────────────────────────────────────────────────

def build_email_html(new_offers: list, all_offers: list) -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    rows = ""
    for o in all_offers[:20]:  # max 20 w emailu
        rating_str = f"{o.rating:.1f}" if o.rating else "—"
        stars_str = f"{'★' * (o.stars or 0)}" if o.stars else "—"
        badge = "🆕 NOWA" if any(n.unique_key() == o.unique_key() for n in new_offers) else ""
        price_str = f"{o.price_total:,.0f} zł".replace(",", " ")

        rows += f"""
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:10px 8px;font-weight:500;">{badge} {o.hotel_name}</td>
          <td style="padding:10px 8px;color:#555;">{o.source}</td>
          <td style="padding:10px 8px;">{stars_str}</td>
          <td style="padding:10px 8px;font-weight:500;color:#185FA5;">{rating_str}</td>
          <td style="padding:10px 8px;">{o.nights} nocy</td>
          <td style="padding:10px 8px;">{BOARD_LABELS.get(o.board, o.board)}</td>
          <td style="padding:10px 8px;font-weight:700;color:#0a7c3e;">{price_str}</td>
          <td style="padding:10px 8px;">
            <a href="{o.url}" style="background:#185FA5;color:white;padding:4px 10px;border-radius:4px;text-decoration:none;font-size:12px;">Zobacz</a>
          </td>
        </tr>"""

    new_count = len(new_offers)
    subject_prefix = f"🆕 {new_count} nowych ofert! " if new_count else "✅ Monitoring: "

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#222;">

  <div style="background:#185FA5;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
    <h1 style="margin:0;font-size:20px;">Wakacje Monitor — Marsa Alam</h1>
    <p style="margin:4px 0 0;font-size:13px;opacity:0.85;">Raport z {now}</p>
  </div>

  <div style="background:#f8f9fa;padding:14px 24px;border:1px solid #e0e0e0;border-top:0;">
    <strong>Kryteria:</strong>
    25 maja–11 czerwca 2025 &nbsp;·&nbsp;
    7–10 nocy &nbsp;·&nbsp;
    3 dorosłych + dziecko 9 lat &nbsp;·&nbsp;
    Aquapark &nbsp;·&nbsp;
    Ocena 8.0+
  </div>

  <div style="padding:12px 24px;background:#fff3cd;border:1px solid #ffc107;border-top:0;">
    <strong>{'🆕 ' + str(new_count) + ' nowych ofert od ostatniego sprawdzenia!' if new_count else '✅ Brak nowych ofert od ostatniego sprawdzenia.'}</strong>
    &nbsp;Łącznie znaleziono <strong>{len(all_offers)}</strong> pasujących ofert.
  </div>

  <table style="width:100%;border-collapse:collapse;border:1px solid #e0e0e0;border-top:0;">
    <thead>
      <tr style="background:#f1f3f4;font-size:12px;text-transform:uppercase;color:#666;">
        <th style="padding:8px;text-align:left;">Hotel</th>
        <th style="padding:8px;text-align:left;">Serwis</th>
        <th style="padding:8px;text-align:left;">Gwiazdki</th>
        <th style="padding:8px;text-align:left;">Ocena</th>
        <th style="padding:8px;text-align:left;">Noce</th>
        <th style="padding:8px;text-align:left;">Wyżywienie</th>
        <th style="padding:8px;text-align:left;">Cena (4os.)</th>
        <th style="padding:8px;text-align:left;">Link</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>

  <p style="font-size:11px;color:#999;margin-top:16px;text-align:center;">
    Wakacje Monitor · Automatyczny raport · Dane orientacyjne, sprawdź aktualne ceny na stronie touroperatora
  </p>
</body>
</html>"""


# ─── Wysyłka email ────────────────────────────────────────────────────────────

def send_email(new_offers: list, all_offers: list):
    if not EMAIL_FROM or not EMAIL_TO or not EMAIL_PASS:
        log.warning("Email nie skonfigurowany — pomijam")
        return

    new_count = len(new_offers)
    subject = (
        f"🆕 Wakacje Marsa Alam — {new_count} nowych ofert! ({len(all_offers)} łącznie)"
        if new_count else
        f"✅ Wakacje Monitor — {len(all_offers)} ofert (bez zmian)"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO

    html_content = build_email_html(new_offers, all_offers)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASS)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info(f"Email wysłany → {EMAIL_TO}")
    except Exception as e:
        log.error(f"Błąd wysyłki emaila: {e}")


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(new_offers: list, all_offers: list):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.warning("Telegram nie skonfigurowany — pomijam")
        return

    new_count = len(new_offers)
    now = datetime.now().strftime("%d.%m %H:%M")

    if new_count:
        header = f"🆕 *{new_count} nowych ofert!* Marsa Alam · {now}\n\n"
        offers_to_show = new_offers[:5]  # tylko nowe na Telegram
    else:
        header = f"✅ *Monitoring Marsa Alam* · {now}\nBrak nowych ofert. Łącznie: {len(all_offers)}\n\n"
        offers_to_show = all_offers[:3]  # top 3 na przypomnienie

    lines = []
    for o in offers_to_show:
        price_str = f"{o.price_total:,.0f} zł".replace(",", " ")
        rating_str = f"{o.rating:.1f}" if o.rating else "—"
        lines.append(
            f"🏨 *{o.hotel_name}*\n"
            f"   {o.source} · {o.nights}n · {BOARD_LABELS.get(o.board, o.board)}\n"
            f"   Ocena: {rating_str} · Cena: {price_str} (4 os.)\n"
            f"   [Zobacz ofertę]({o.url})"
        )

    text = header + "\n\n".join(lines)
    if len(all_offers) > 5:
        text += f"\n\n_...i {len(all_offers) - 5} więcej. Szczegóły w emailu._"

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        resp = req.post(url, json=payload, timeout=10)
        if resp.ok:
            log.info("Telegram: wiadomość wysłana")
        else:
            log.error(f"Telegram error: {resp.text}")
    except Exception as e:
        log.error(f"Telegram wyjątek: {e}")


# ─── Główna funkcja notify ────────────────────────────────────────────────────

def notify(new_offers: list, all_offers: list):
    """Wysyła powiadomienia jeśli są nowe oferty (lub codziennie rano)."""
    now_hour = datetime.now().hour

    # Wysyłamy zawsze gdy są nowe oferty, albo o 8:00 rano (raport dzienny)
    should_send = len(new_offers) > 0 or now_hour == 8

    if should_send:
        log.info(f"Wysyłanie powiadomień ({len(new_offers)} nowych, {len(all_offers)} łącznie)")
        send_email(new_offers, all_offers)
        send_telegram(new_offers, all_offers)
    else:
        log.info("Brak nowych ofert i nie pora na raport dzienny — pomijam powiadomienia")
