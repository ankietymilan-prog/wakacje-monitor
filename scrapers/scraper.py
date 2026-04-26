"""
Wakacje Monitor — Scraper v2
Używa bezpośrednich zapytań HTTP do API serwisów zamiast Playwright.
"""

import requests
import logging
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
import urllib3
urllib3.disable_warnings()

log = logging.getLogger(__name__)

CRITERIA = {
    "destination": "Marsa Alam",
    "date_from": date(2025, 5, 25),
    "date_to":   date(2025, 6, 11),
    "nights_min": 7,
    "nights_max": 10,
    "adults": 3,
    "child_age": 9,
    "min_rating": 8.0,
    "must_have": ["aquapark"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html,*/*",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

@dataclass
class Offer:
    hotel: str
    source: str
    stars: int
    rating: float
    nights: int
    board: str
    price_total: float
    url: str
    departure_date: str
    amenities: list = field(default_factory=list)

    def key(self):
        return f"{self.source}:{self.hotel}:{self.departure_date}:{self.nights}"


def generate_date_range():
    """Generuje wszystkie możliwe daty wylotu w oknie."""
    dates = []
    current = CRITERIA["date_from"]
    while current <= CRITERIA["date_to"] - timedelta(days=CRITERIA["nights_min"]):
        dates.append(current)
        current += timedelta(days=1)
    return dates


def scrape_wakacje_pl() -> list[Offer]:
    """Scraper wakacje.pl — API JSON."""
    offers = []
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        for dep_date in generate_date_range():
            for nights in range(CRITERIA["nights_min"], CRITERIA["nights_max"] + 1):
                url = (
                    "https://www.wakacje.pl/wczasy/egipt/marsa-alam/"
                    f"?adults={CRITERIA['adults']}"
                    f"&children=1&childAge={CRITERIA['child_age']}"
                    f"&dateFrom={dep_date.strftime('%Y-%m-%d')}"
                    f"&nights={nights}"
                )
                # Próba API endpoint
                api_url = (
                    "https://www.wakacje.pl/api/v3/offers/search"
                    f"?destination=marsa-alam"
                    f"&adults={CRITERIA['adults']}"
                    f"&children=1&childAge[]={CRITERIA['child_age']}"
                    f"&dateFrom={dep_date.strftime('%Y-%m-%d')}"
                    f"&nights={nights}"
                    f"&amenities[]=aquapark"
                    f"&ratingMin={CRITERIA['min_rating']}"
                    f"&page=1&perPage=50"
                )
                try:
                    r = session.get(api_url, timeout=15)
                    if r.status_code == 200:
                        data = r.json()
                        items = data.get("offers", data.get("results", data.get("data", [])))
                        for item in items:
                            rating = float(item.get("rating", item.get("score", 0)) or 0)
                            if rating < CRITERIA["min_rating"]:
                                continue
                            amenities = [a.get("name", a) if isinstance(a, dict) else str(a)
                                        for a in item.get("amenities", item.get("facilities", []))]
                            has_aquapark = any("aqua" in str(a).lower() or "park" in str(a).lower()
                                             for a in amenities)
                            if not has_aquapark:
                                continue
                            price = float(item.get("price", item.get("pricePerPerson", 0)) or 0)
                            if price > 0 and price < 5000:
                                price = price * (CRITERIA["adults"] + 1)
                            offers.append(Offer(
                                hotel=item.get("hotelName", item.get("name", "Nieznany")),
                                source="wakacje.pl",
                                stars=int(item.get("stars", item.get("hotelStars", 0)) or 0),
                                rating=rating,
                                nights=nights,
                                board=item.get("board", item.get("boardType", "?")),
                                price_total=price,
                                url=item.get("url", item.get("offerUrl", url)),
                                departure_date=dep_date.strftime("%Y-%m-%d"),
                                amenities=amenities,
                            ))
                except Exception:
                    pass
        log.info(f"[wakacje.pl] Znaleziono {len(offers)} ofert")
    except Exception as e:
        log.error(f"[wakacje.pl] Błąd: {e}")
    return offers


def scrape_itaka() -> list[Offer]:
    """Scraper itaka.pl — API JSON."""
    offers = []
    try:
        session = requests.Session()
        session.headers.update({**HEADERS, "X-Requested-With": "XMLHttpRequest"})

        for dep_date in generate_date_range():
            for nights in range(CRITERIA["nights_min"], CRITERIA["nights_max"] + 1):
                api_url = (
                    "https://www.itaka.pl/api/search/offers"
                    f"?departureDate={dep_date.strftime('%Y-%m-%d')}"
                    f"&returnDate={(dep_date + timedelta(days=nights)).strftime('%Y-%m-%d')}"
                    f"&adults={CRITERIA['adults']}"
                    f"&children={CRITERIA['child_age']}"
                    f"&destination[]=EGMA"  # kod Marsa Alam
                    f"&amenity[]=aquapark"
                    f"&minRating={CRITERIA['min_rating']}"
                    f"&page=1&size=50"
                )
                try:
                    r = session.get(api_url, timeout=15)
                    if r.status_code == 200:
                        data = r.json()
                        items = (data.get("offers") or data.get("results") or
                                data.get("data", {}).get("offers", []))
                        for item in items:
                            rating = float(item.get("rating", item.get("hotelRating", 0)) or 0)
                            if rating < CRITERIA["min_rating"]:
                                continue
                            price = float(item.get("price", item.get("totalPrice", 0)) or 0)
                            if price > 0 and price < 5000:
                                price *= (CRITERIA["adults"] + 1)
                            offers.append(Offer(
                                hotel=item.get("hotelName", item.get("name", "Nieznany")),
                                source="itaka.pl",
                                stars=int(item.get("stars", item.get("hotelCategory", 0)) or 0),
                                rating=rating,
                                nights=nights,
                                board=item.get("board", item.get("mealType", "?")),
                                price_total=price,
                                url="https://www.itaka.pl" + item.get("url", item.get("offerUrl", "")),
                                departure_date=dep_date.strftime("%Y-%m-%d"),
                            ))
                except Exception:
                    pass
        log.info(f"[itaka.pl] Znaleziono {len(offers)} ofert")
    except Exception as e:
        log.error(f"[itaka.pl] Błąd: {e}")
    return offers


def scrape_tui() -> list[Offer]:
    """Scraper TUI.pl — API JSON."""
    offers = []
    try:
        session = requests.Session()
        session.headers.update({**HEADERS, "Accept": "application/json"})

        for dep_date in generate_date_range():
            for nights in range(CRITERIA["nights_min"], CRITERIA["nights_max"] + 1):
                api_url = (
                    "https://www.tui.pl/api/v1/offers/search"
                    f"?departureDate={dep_date.strftime('%Y-%m-%d')}"
                    f"&duration={nights}"
                    f"&adults={CRITERIA['adults']}"
                    f"&childrenAges={CRITERIA['child_age']}"
                    f"&destinationCode=EG-RED-MAA"
                    f"&amenity=aquapark"
                    f"&minRating={CRITERIA['min_rating']}"
                )
                try:
                    r = session.get(api_url, timeout=15)
                    if r.status_code == 200:
                        data = r.json()
                        items = data.get("offers", data.get("results", []))
                        for item in items:
                            rating = float(item.get("rating", item.get("tripadvisorRating", 0)) or 0)
                            if rating < CRITERIA["min_rating"]:
                                continue
                            price = float(item.get("totalPrice", item.get("price", 0)) or 0)
                            offers.append(Offer(
                                hotel=item.get("hotelName", item.get("name", "Nieznany")),
                                source="tui.pl",
                                stars=int(item.get("hotelCategory", item.get("stars", 0)) or 0),
                                rating=rating,
                                nights=nights,
                                board=item.get("boardBasis", item.get("board", "?")),
                                price_total=price,
                                url="https://www.tui.pl" + item.get("offerUrl", item.get("url", "")),
                                departure_date=dep_date.strftime("%Y-%m-%d"),
                            ))
                except Exception:
                    pass
        log.info(f"[tui.pl] Znaleziono {len(offers)} ofert")
    except Exception as e:
        log.error(f"[tui.pl] Błąd: {e}")
    return offers


def scrape_rainbow() -> list[Offer]:
    """Scraper Rainbow.pl — API JSON."""
    offers = []
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        session.verify = False

        for dep_date in generate_date_range():
            for nights in range(CRITERIA["nights_min"], CRITERIA["nights_max"] + 1):
                api_url = (
                    "https://www.rainbow.pl/api/offers"
                    f"?country=egipt&region=marsa-alam"
                    f"&dateFrom={dep_date.strftime('%d.%m.%Y')}"
                    f"&duration={nights}"
                    f"&adults={CRITERIA['adults']}"
                    f"&children=1&childAge={CRITERIA['child_age']}"
                )
                try:
                    r = session.get(api_url, timeout=15, verify=False)
                    if r.status_code == 200:
                        data = r.json()
                        items = data.get("offers", data.get("results", []))
                        for item in items:
                            rating = float(item.get("rating", item.get("score", 0)) or 0)
                            if rating < CRITERIA["min_rating"]:
                                continue
                            attrs = str(item.get("attributes", item.get("amenities", ""))).lower()
                            if "aqua" not in attrs and "park" not in attrs:
                                continue
                            price = float(item.get("price", item.get("totalPrice", 0)) or 0)
                            if price > 0 and price < 5000:
                                price *= (CRITERIA["adults"] + 1)
                            offers.append(Offer(
                                hotel=item.get("hotelName", item.get("name", "Nieznany")),
                                source="rainbow.pl",
                                stars=int(item.get("stars", item.get("category", 0)) or 0),
                                rating=rating,
                                nights=nights,
                                board=item.get("board", item.get("mealType", "?")),
                                price_total=price,
                                url="https://www.rainbow.pl" + item.get("url", item.get("offerUrl", "")),
                                departure_date=dep_date.strftime("%Y-%m-%d"),
                            ))
                except Exception:
                    pass
        log.info(f"[rainbow.pl] Znaleziono {len(offers)} ofert")
    except Exception as e:
        log.error(f"[rainbow.pl] Błąd: {e}")
    return offers


def scrape_neckermann() -> list[Offer]:
    """Scraper Neckermann.pl — API JSON."""
    offers = []
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        for dep_date in generate_date_range():
            for nights in range(CRITERIA["nights_min"], CRITERIA["nights_max"] + 1):
                api_url = (
                    "https://www.neckermann.pl/api/offers/search"
                    f"?destination=marsa-alam"
                    f"&departureDate={dep_date.strftime('%Y-%m-%d')}"
                    f"&nights={nights}"
                    f"&adults={CRITERIA['adults']}"
                    f"&childrenAges={CRITERIA['child_age']}"
                    f"&facilities=aquapark"
                    f"&minRating={CRITERIA['min_rating']}"
                )
                try:
                    r = session.get(api_url, timeout=15)
                    if r.status_code == 200:
                        data = r.json()
                        items = data.get("offers", data.get("results", data.get("data", [])))
                        for item in items:
                            rating = float(item.get("rating", item.get("hotelRating", 0)) or 0)
                            if rating < CRITERIA["min_rating"]:
                                continue
                            price = float(item.get("price", item.get("totalPrice", 0)) or 0)
                            if price > 0 and price < 5000:
                                price *= (CRITERIA["adults"] + 1)
                            offers.append(Offer(
                                hotel=item.get("hotelName", item.get("name", "Nieznany")),
                                source="neckermann.pl",
                                stars=int(item.get("stars", item.get("hotelStars", 0)) or 0),
                                rating=rating,
                                nights=nights,
                                board=item.get("board", item.get("boardType", "?")),
                                price_total=price,
                                url="https://www.neckermann.pl" + item.get("url", item.get("offerUrl", "")),
                                departure_date=dep_date.strftime("%Y-%m-%d"),
                            ))
                except Exception:
                    pass
        log.info(f"[neckermann.pl] Znaleziono {len(offers)} ofert")
    except Exception as e:
        log.error(f"[neckermann.pl] Błąd: {e}")
    return offers


def scrape_coraltravel() -> list[Offer]:
    """Scraper Coral Travel — API JSON."""
    offers = []
    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        for dep_date in generate_date_range():
            for nights in range(CRITERIA["nights_min"], CRITERIA["nights_max"] + 1):
                api_url = (
                    "https://www.coraltravel.pl/api/search"
                    f"?destination=EGMA"
                    f"&departureDate={dep_date.strftime('%Y-%m-%d')}"
                    f"&nights={nights}"
                    f"&adults={CRITERIA['adults']}"
                    f"&children=1&childAge={CRITERIA['child_age']}"
                )
                try:
                    r = session.get(api_url, timeout=15)
                    if r.status_code == 200:
                        data = r.json()
                        items = data.get("offers", data.get("hotels", []))
                        for item in items:
                            rating = float(item.get("rating", item.get("score", 0)) or 0)
                            if rating < CRITERIA["min_rating"]:
                                continue
                            attrs = str(item.get("amenities", item.get("services", ""))).lower()
                            if "aqua" not in attrs:
                                continue
                            price = float(item.get("price", item.get("totalPrice", 0)) or 0)
                            if price > 0 and price < 5000:
                                price *= (CRITERIA["adults"] + 1)
                            offers.append(Offer(
                                hotel=item.get("hotelName", item.get("name", "Nieznany")),
                                source="coraltravel.pl",
                                stars=int(item.get("stars", item.get("category", 0)) or 0),
                                rating=rating,
                                nights=nights,
                                board=item.get("board", item.get("mealType", "?")),
                                price_total=price,
                                url="https://www.coraltravel.pl" + item.get("url", item.get("offerUrl", "")),
                                departure_date=dep_date.strftime("%Y-%m-%d"),
                            ))
                except Exception:
                    pass
        log.info(f"[coraltravel.pl] Znaleziono {len(offers)} ofert")
    except Exception as e:
        log.error(f"[coraltravel.pl] Błąd: {e}")
    return offers


def run_all_scrapers() -> list[Offer]:
    """Uruchamia wszystkie scrapery i zwraca połączone wyniki."""
    all_offers = []
    scrapers = [
        scrape_wakacje_pl,
        scrape_itaka,
        scrape_tui,
        scrape_rainbow,
        scrape_neckermann,
        scrape_coraltravel,
    ]
    for scraper in scrapers:
        try:
            results = scraper()
            all_offers.extend(results)
        except Exception as e:
            log.error(f"Błąd scrapera {scraper.__name__}: {e}")

    # Deduplikacja po kluczu
    seen = set()
    unique = []
    for offer in all_offers:
        k = offer.key()
        if k not in seen:
            seen.add(k)
            unique.append(offer)

    log.info(f"Łącznie unikalnych ofert: {len(unique)}")
    return unique
