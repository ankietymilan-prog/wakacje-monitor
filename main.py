"""
Główny runner — porównuje z poprzednim stanem, wykrywa nowe oferty
Uruchamiany przez GitHub Actions co godzinę
"""

import json
import logging
import os
import sys
from pathlib import Path
from dataclasses import asdict

# Dodaj katalog główny do path
sys.path.insert(0, str(Path(__file__).parent))

from scrapers.scraper import run_all_scrapers, Offer
from notifier.notify import notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/monitor.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

STATE_FILE = Path("data/last_offers.json")


def load_previous_state() -> set[str]:
    """Wczytuje klucze poprzednich ofert."""
    if not STATE_FILE.exists():
        return set()
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("keys", []))
    except Exception as e:
        log.warning(f"Błąd wczytywania stanu: {e}")
        return set()


def save_state(offers: list[Offer]):
    """Zapisuje aktualny stan."""
    STATE_FILE.parent.mkdir(exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "keys": [o.unique_key() for o in offers],
            "offers": [asdict(o) for o in offers],
            "updated_at": __import__("datetime").datetime.now().isoformat(),
            "count": len(offers),
        }, f, ensure_ascii=False, indent=2)
    log.info(f"Stan zapisany: {len(offers)} ofert → {STATE_FILE}")


def save_offers_csv(offers: list[Offer]):
    """Eksportuje oferty do CSV (przydatne do śledzenia historii)."""
    import csv
    from datetime import datetime

    csv_path = Path("data/offers_history.csv")
    file_exists = csv_path.exists()

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "scraped_at", "source", "hotel_name", "nights",
                "board", "price_total", "price_per_person", "rating", "stars", "url"
            ])
        for o in offers:
            writer.writerow([
                o.scraped_at, o.source, o.hotel_name, o.nights,
                o.board, o.price_total, o.price_per_person,
                o.rating, o.stars, o.url
            ])


def main():
    log.info("=" * 60)
    log.info("WAKACJE MONITOR — START")
    log.info("=" * 60)

    # 1. Pobierz poprzedni stan
    previous_keys = load_previous_state()
    log.info(f"Poprzedni stan: {len(previous_keys)} ofert")

    # 2. Scraping wszystkich serwisów
    current_offers = run_all_scrapers()
    log.info(f"Aktualnie znaleziono: {len(current_offers)} ofert spełniających kryteria")

    # 3. Wykryj nowe oferty
    new_offers = [o for o in current_offers if o.unique_key() not in previous_keys]
    log.info(f"Nowych ofert: {len(new_offers)}")

    if new_offers:
        log.info("Nowe oferty:")
        for o in new_offers:
            log.info(f"  + {o.hotel_name} | {o.source} | {o.nights}n | {o.price_total:.0f} zł")

    # 4. Powiadomienia
    notify(new_offers, current_offers)

    # 5. Zapisz aktualny stan
    save_state(current_offers)
    save_offers_csv(current_offers)

    log.info("KONIEC — do następnego uruchomienia!")
    return len(current_offers)


if __name__ == "__main__":
    main()
