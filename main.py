"""
Wakacje Monitor — główny skrypt
Sprawdza travelplanet.pl co godzinę i wysyła powiadomienia.
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# ── ścieżki ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
os.makedirs(ROOT / "data", exist_ok=True)

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ROOT / "data" / "monitor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("main")

# ── importy projektu ──────────────────────────────────────────────────────────
from scrapers.scraper import scrape_all
from notifier.notify import notify

# ── stan (poprzednie oferty) ──────────────────────────────────────────────────
STATE_FILE = ROOT / "data" / "last_offers.json"
HISTORY_FILE = ROOT / "data" / "offers_history.csv"


def load_previous_keys() -> set:
    if not STATE_FILE.exists():
        return set()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(data.get("keys", []))
    except Exception:
        return set()


def save_state(offers):
    keys = [o.key() for o in offers]
    STATE_FILE.write_text(
        json.dumps({"keys": keys, "updated": datetime.now().isoformat()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_history(offers):
    write_header = not HISTORY_FILE.exists()
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        if write_header:
            f.write("timestamp,source,hotel,stars,rating,nights,board,price_total,url\n")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        for o in offers:
            row = ",".join([
                ts,
                o.source,
                f'"{o.hotel}"',
                str(o.stars or ""),
                str(o.rating or ""),
                str(o.nights or ""),
                o.board or "",
                str(int(o.price_total)) if o.price_total else "",
                o.url,
            ])
            f.write(row + "\n")


# ── główna logika ─────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info(f"Start monitoringu: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    log.info("=" * 60)

    # Pobierz oferty (tylko travelplanet)
    current_offers = scrape_all()
    log.info(f"Łącznie znaleziono: {len(current_offers)} ofert")

    if not current_offers:
        log.warning("Brak ofert — kończę bez powiadomień")
        return

    # Wypisz oferty w logach
    for o in sorted(current_offers, key=lambda x: x.price_total or 9_999_999):
        log.info(f"  {o.hotel} | {o.source} | {o.nights}n | {o.price_total:.0f} zł")

    # Znajdź nowe oferty
    previous_keys = load_previous_keys()
    new_keys = {o.key() for o in current_offers} - previous_keys
    log.info(f"Nowych ofert: {len(new_keys)} (poprzednio: {len(previous_keys)})")

    # Czy wysłać powiadomienie?
    hour = datetime.now().hour
    is_daily_report = (hour == 8)  # raport dzienny o 8:00

    if new_keys or is_daily_report:
        log.info("Wysyłam powiadomienia...")
        notify(current_offers, new_keys)
    else:
        log.info("Brak nowych ofert, pomijam powiadomienia")

    # Zapisz stan i historię
    save_state(current_offers)
    append_history(current_offers)
    log.info("Stan i historia zapisane")
    log.info("Koniec monitoringu")


if __name__ == "__main__":
    main()
