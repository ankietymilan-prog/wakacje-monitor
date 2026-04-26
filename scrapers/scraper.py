"""
Wakacje Monitor — scraper wielu serwisów
Obsługuje: wakacje.pl, itaka.pl, tui.pl, neckermann.pl, coraltravel.pl, rainbow.pl
"""

import requests
import json
import time
import random
import logging
from datetime import datetime, date
from dataclasses import dataclass, asdict
from typing import Optional
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Konfiguracja ────────────────────────────────────────────────────────────

CRITERIA = {
    "destination": "Marsa Alam",
    "date_from": date(2025, 5, 25),
    "date_to": date(2025, 6, 11),
    "nights_min": 7,
    "nights_max": 10,
    "adults": 3,
    "child_age": 9,
    "min_rating": 8.0,
    "must_have": ["aquapark"],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─── Model danych ─────────────────────────────────────────────────────────────

@dataclass
class Offer:
    source: str           # nazwa serwisu
    hotel_name: str
    destination: str
    date_from: str
    date_to: str
    nights: int
    adults: int
    children: int
    board: str            # AI, HB, BB, FB
    price_total: float    # cena za wszystkich
    price_per_person: float
    rating: Optional[float]
    stars: Optional[int]
    has_aquapark: bool
    url: str
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.now().isoformat()

    def matches_criteria(self) -> bool:
        c = CRITERIA
        ok = (
            self.nights >= c["nights_min"]
            and self.nights <= c["nights_max"]
            and self.has_aquapark
            and (self.rating is None or self.rating >= c["min_rating"])
        )
        return ok

    def unique_key(self) -> str:
        return f"{self.hotel_name}_{self.date_from}_{self.nights}_{self.price_total}"


# ─── Pomocnicze ───────────────────────────────────────────────────────────────

def sleep_random(min_s=2, max_s=5):
    time.sleep(random.uniform(min_s, max_s))


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def detect_aquapark(text: str) -> bool:
    keywords = ["aquapark", "aqua park", "water park", "waterpark", "zjeżdżalnia", "basen ze zjeżdżalnią"]
    text_lower = text.lower()
    return any(k in text_lower for k in keywords)


# ─── Scraper bazowy ───────────────────────────────────────────────────────────

class BaseScraper:
    name = "base"

    def scrape(self) -> list[Offer]:
        raise NotImplementedError

    def safe_scrape(self) -> list[Offer]:
        try:
            log.info(f"[{self.name}] Startowanie...")
            offers = self.scrape()
            log.info(f"[{self.name}] Znaleziono {len(offers)} ofert")
            return offers
        except Exception as e:
            log.error(f"[{self.name}] Błąd: {e}")
            return []


# ─── Wakacje.pl ───────────────────────────────────────────────────────────────

class WakacjePLScraper(BaseScraper):
    name = "wakacje.pl"

    def scrape(self) -> list[Offer]:
        offers = []
        c = CRITERIA

        # Wakacje.pl używa API JSON — odpytujemy je bezpośrednio
        url = (
            "https://www.wakacje.pl/wczasy/"
            f"?destination=marsa-alam"
            f"&dateFrom={c['date_from'].strftime('%Y-%m-%d')}"
            f"&dateTo={c['date_to'].strftime('%Y-%m-%d')}"
            f"&adults={c['adults']}"
            f"&children=1"
            f"&childrenAges={c['child_age']}"
            f"&nightsFrom={c['nights_min']}"
            f"&nightsTo={c['nights_max']}"
            f"&attributes=aquapark"
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(extra_http_headers=HEADERS)
            page.goto(url, wait_until="networkidle", timeout=30000)
            sleep_random(3, 6)

            # Czekamy na załadowanie ofert
            try:
                page.wait_for_selector("[data-testid='offer-card'], .offer-card, article.offer", timeout=15000)
            except Exception:
                log.warning(f"[{self.name}] Brak selektora ofert — próba parsowania HTML")

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")

        # Szukamy kart ofert (różne możliwe selektory wakacje.pl)
        cards = (
            soup.select("[data-testid='offer-card']")
            or soup.select(".offer-card")
            or soup.select("article.offer")
            or soup.select(".hotel-offer")
        )

        for card in cards:
            try:
                name = (
                    card.select_one("[data-testid='hotel-name'], .hotel-name, h2, h3")
                    or card.find(class_=lambda c: c and "name" in c)
                )
                name = name.get_text(strip=True) if name else "Nieznany hotel"

                price_el = card.select_one(
                    "[data-testid='price'], .price, .offer-price, [class*='price']"
                )
                price_text = price_el.get_text(strip=True) if price_el else "0"
                price = float("".join(filter(str.isdigit, price_text)) or 0)

                nights_el = card.select_one("[data-testid='nights'], [class*='night'], [class*='noc']")
                nights_text = nights_el.get_text(strip=True) if nights_el else ""
                nights = int("".join(filter(str.isdigit, nights_text)) or c["nights_min"])

                rating_el = card.select_one("[data-testid='rating'], .rating, [class*='rating'], [class*='ocena']")
                rating = None
                if rating_el:
                    try:
                        rating = float(rating_el.get_text(strip=True).replace(",", "."))
                    except ValueError:
                        pass

                card_text = card.get_text()
                has_aqua = detect_aquapark(card_text)

                link_el = card.select_one("a[href]")
                offer_url = link_el["href"] if link_el else url
                if offer_url.startswith("/"):
                    offer_url = "https://www.wakacje.pl" + offer_url

                board = "AI"
                for b_key, b_val in [("All Inclusive", "AI"), ("Half Board", "HB"), ("Bed & Breakfast", "BB"), ("Full Board", "FB")]:
                    if b_key.lower() in card_text.lower():
                        board = b_val
                        break

                o = Offer(
                    source=self.name,
                    hotel_name=name,
                    destination="Marsa Alam",
                    date_from=c["date_from"].strftime("%Y-%m-%d"),
                    date_to=c["date_to"].strftime("%Y-%m-%d"),
                    nights=nights,
                    adults=c["adults"],
                    children=1,
                    board=board,
                    price_total=price,
                    price_per_person=round(price / (c["adults"] + 1), 2) if price else 0,
                    rating=rating,
                    stars=None,
                    has_aquapark=has_aqua,
                    url=offer_url,
                )
                offers.append(o)
            except Exception as e:
                log.debug(f"[{self.name}] Błąd parsowania karty: {e}")

        return [o for o in offers if o.matches_criteria()]


# ─── Itaka.pl ─────────────────────────────────────────────────────────────────

class ItakaScraper(BaseScraper):
    name = "itaka.pl"

    def scrape(self) -> list[Offer]:
        offers = []
        c = CRITERIA

        url = (
            "https://www.itaka.pl/wczasy/egipt/marsa-alam/"
            f"?DepartureDate={c['date_from'].strftime('%d-%m-%Y')}"
            f"&ReturnDate={c['date_to'].strftime('%d-%m-%Y')}"
            f"&DurationFrom={c['nights_min']}&DurationTo={c['nights_max']}"
            f"&Adults={c['adults']}&Children=1&ChildrenAges={c['child_age']}"
            f"&Attributes%5B%5D=aquapark"
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(extra_http_headers=HEADERS)
            page.goto(url, wait_until="networkidle", timeout=30000)
            sleep_random(3, 5)

            # Scroll żeby załadować lazy-load
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 1000)")
                sleep_random(1, 2)

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")
        cards = (
            soup.select(".offer-list__item")
            or soup.select("[data-cy='offer-tile']")
            or soup.select(".hotel-tile")
            or soup.select("article[class*='offer']")
        )

        for card in cards:
            try:
                name_el = card.select_one("h2, h3, [class*='title'], [class*='name']")
                name = name_el.get_text(strip=True) if name_el else "Nieznany hotel"

                price_el = card.select_one("[class*='price'], [data-cy='price']")
                price_text = price_el.get_text(strip=True) if price_el else "0"
                price = float("".join(filter(str.isdigit, price_text)) or 0)

                nights_el = card.select_one("[class*='duration'], [class*='night'], [class*='noc']")
                nights = c["nights_min"]
                if nights_el:
                    try:
                        nights = int("".join(filter(str.isdigit, nights_el.get_text())))
                    except Exception:
                        pass

                rating_el = card.select_one("[class*='rating'], [class*='score'], [class*='ocena']")
                rating = None
                if rating_el:
                    try:
                        rating = float(rating_el.get_text(strip=True).replace(",", "."))
                    except Exception:
                        pass

                stars_el = card.select_one("[class*='star'], [class*='category']")
                stars = None
                if stars_el:
                    filled = stars_el.select("[class*='filled'], [class*='active']")
                    stars = len(filled) if filled else None

                card_text = card.get_text()
                has_aqua = detect_aquapark(card_text)

                link_el = card.select_one("a[href]")
                offer_url = link_el["href"] if link_el else url
                if offer_url.startswith("/"):
                    offer_url = "https://www.itaka.pl" + offer_url

                board = "AI"
                for b_key, b_val in [("All Inclusive", "AI"), ("Half Board", "HB"), ("Bed & Breakfast", "BB")]:
                    if b_key.lower() in card_text.lower():
                        board = b_val
                        break

                o = Offer(
                    source=self.name,
                    hotel_name=name,
                    destination="Marsa Alam",
                    date_from=c["date_from"].strftime("%Y-%m-%d"),
                    date_to=c["date_to"].strftime("%Y-%m-%d"),
                    nights=nights,
                    adults=c["adults"],
                    children=1,
                    board=board,
                    price_total=price,
                    price_per_person=round(price / (c["adults"] + 1), 2) if price else 0,
                    rating=rating,
                    stars=stars,
                    has_aquapark=has_aqua,
                    url=offer_url,
                )
                offers.append(o)
            except Exception as e:
                log.debug(f"[{self.name}] Błąd karty: {e}")

        return [o for o in offers if o.matches_criteria()]


# ─── TUI.pl ───────────────────────────────────────────────────────────────────

class TUIScraper(BaseScraper):
    name = "tui.pl"

    def scrape(self) -> list[Offer]:
        offers = []
        c = CRITERIA

        # TUI ma API JSON — próbujemy je interceptować przez Playwright
        captured = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def handle_response(response):
                if "api" in response.url and "offer" in response.url:
                    try:
                        data = response.json()
                        captured.append(data)
                    except Exception:
                        pass

            page.on("response", handle_response)

            url = (
                "https://www.tui.pl/wypoczynek/egipt/marsa-alam/"
                f"?adults={c['adults']}&children={c['child_age']}"
                f"&departureDate={c['date_from'].strftime('%Y-%m-%d')}"
                f"&returnDate={c['date_to'].strftime('%Y-%m-%d')}"
                f"&duration={c['nights_min']}-{c['nights_max']}"
                f"&amenities=aquapark"
            )
            page.goto(url, wait_until="networkidle", timeout=30000)
            sleep_random(4, 7)

            # Scroll dla lazy-load
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            sleep_random(2, 3)

            html = page.content()
            browser.close()

        # Parsujemy HTML fallback
        soup = BeautifulSoup(html, "html.parser")
        cards = (
            soup.select("[class*='OfferCard'], [class*='offer-card'], [data-testid*='offer']")
            or soup.select("article")
        )

        for card in cards:
            try:
                name_el = card.select_one("h2, h3, [class*='Name'], [class*='title']")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)

                price_el = card.select_one("[class*='Price'], [class*='price']")
                price_text = price_el.get_text(strip=True) if price_el else "0"
                price = float("".join(filter(str.isdigit, price_text)) or 0)

                card_text = card.get_text()
                has_aqua = detect_aquapark(card_text)

                link_el = card.select_one("a[href]")
                offer_url = link_el["href"] if link_el else url
                if offer_url.startswith("/"):
                    offer_url = "https://www.tui.pl" + offer_url

                rating_el = card.select_one("[class*='Rating'], [class*='rating'], [class*='score']")
                rating = None
                if rating_el:
                    try:
                        rating = float(rating_el.get_text(strip=True).replace(",", "."))
                    except Exception:
                        pass

                o = Offer(
                    source=self.name,
                    hotel_name=name,
                    destination="Marsa Alam",
                    date_from=c["date_from"].strftime("%Y-%m-%d"),
                    date_to=c["date_to"].strftime("%Y-%m-%d"),
                    nights=c["nights_min"],
                    adults=c["adults"],
                    children=1,
                    board="AI",
                    price_total=price,
                    price_per_person=round(price / (c["adults"] + 1), 2) if price else 0,
                    rating=rating,
                    stars=None,
                    has_aquapark=has_aqua,
                    url=offer_url,
                )
                offers.append(o)
            except Exception as e:
                log.debug(f"[{self.name}] Błąd karty: {e}")

        return [o for o in offers if o.matches_criteria()]


# ─── Rainbow.pl ───────────────────────────────────────────────────────────────

class RainbowScraper(BaseScraper):
    name = "rainbow.pl"

    def scrape(self) -> list[Offer]:
        offers = []
        c = CRITERIA

        url = (
            "https://www.rainbow.pl/wypoczynek/egipt/marsa-alam"
            f"?dateFrom={c['date_from'].strftime('%Y-%m-%d')}"
            f"&dateTo={c['date_to'].strftime('%Y-%m-%d')}"
            f"&adults={c['adults']}&children=1&childAge={c['child_age']}"
            f"&nightsMin={c['nights_min']}&nightsMax={c['nights_max']}"
        )

        sess = get_session()
        resp = sess.get(url, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")

        cards = soup.select(".offer-item, .hotel-item, article[class*='offer']")

        for card in cards:
            try:
                name_el = card.select_one("h2, h3, .name, .title")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)

                price_el = card.select_one(".price, [class*='price']")
                price_text = price_el.get_text(strip=True) if price_el else "0"
                price = float("".join(filter(str.isdigit, price_text)) or 0)

                card_text = card.get_text()
                has_aqua = detect_aquapark(card_text)

                link_el = card.select_one("a[href]")
                offer_url = link_el["href"] if link_el else url
                if offer_url.startswith("/"):
                    offer_url = "https://www.rainbow.pl" + offer_url

                o = Offer(
                    source=self.name,
                    hotel_name=name,
                    destination="Marsa Alam",
                    date_from=c["date_from"].strftime("%Y-%m-%d"),
                    date_to=c["date_to"].strftime("%Y-%m-%d"),
                    nights=c["nights_min"],
                    adults=c["adults"],
                    children=1,
                    board="AI",
                    price_total=price,
                    price_per_person=round(price / (c["adults"] + 1), 2) if price else 0,
                    rating=None,
                    stars=None,
                    has_aquapark=has_aqua,
                    url=offer_url,
                )
                offers.append(o)
            except Exception as e:
                log.debug(f"[{self.name}] Błąd: {e}")

        return [o for o in offers if o.matches_criteria()]


# ─── Coral Travel ─────────────────────────────────────────────────────────────

class CoralTravelScraper(BaseScraper):
    name = "coral.pl"

    def scrape(self) -> list[Offer]:
        offers = []
        c = CRITERIA

        url = (
            "https://www.coraltravel.pl/oferty/egipt/marsa-alam"
            f"?from={c['date_from'].strftime('%d.%m.%Y')}"
            f"&to={c['date_to'].strftime('%d.%m.%Y')}"
            f"&adults={c['adults']}&children=1&childAge={c['child_age']}"
            f"&nights={c['nights_min']}-{c['nights_max']}"
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(extra_http_headers=HEADERS)
            try:
                page.goto(url, wait_until="networkidle", timeout=25000)
                sleep_random(2, 4)
                html = page.content()
            except Exception:
                html = ""
            browser.close()

        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".offer, .hotel-card, [class*='offer-item']")

        for card in cards:
            try:
                name_el = card.select_one("h2, h3, .name")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)

                price_el = card.select_one(".price, [class*='price']")
                price_text = price_el.get_text(strip=True) if price_el else "0"
                price = float("".join(filter(str.isdigit, price_text)) or 0)

                card_text = card.get_text()
                has_aqua = detect_aquapark(card_text)

                link_el = card.select_one("a[href]")
                offer_url = link_el["href"] if link_el else url
                if offer_url.startswith("/"):
                    offer_url = "https://www.coraltravel.pl" + offer_url

                o = Offer(
                    source=self.name,
                    hotel_name=name,
                    destination="Marsa Alam",
                    date_from=c["date_from"].strftime("%Y-%m-%d"),
                    date_to=c["date_to"].strftime("%Y-%m-%d"),
                    nights=c["nights_min"],
                    adults=c["adults"],
                    children=1,
                    board="AI",
                    price_total=price,
                    price_per_person=round(price / (c["adults"] + 1), 2) if price else 0,
                    rating=None,
                    stars=None,
                    has_aquapark=has_aqua,
                    url=offer_url,
                )
                offers.append(o)
            except Exception as e:
                log.debug(f"[{self.name}] Błąd: {e}")

        return [o for o in offers if o.matches_criteria()]


# ─── Neckermann.pl ────────────────────────────────────────────────────────────

class NeckermannScraper(BaseScraper):
    name = "neckermann.pl"

    def scrape(self) -> list[Offer]:
        offers = []
        c = CRITERIA

        url = (
            "https://www.neckermann.pl/oferty/egipt/marsa-alam/"
            f"?dateFrom={c['date_from'].strftime('%Y-%m-%d')}"
            f"&dateTo={c['date_to'].strftime('%Y-%m-%d')}"
            f"&adults={c['adults']}&child1={c['child_age']}"
            f"&nights={c['nights_min']},{c['nights_max']}"
            f"&attributes=aquapark"
        )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(extra_http_headers=HEADERS)
            try:
                page.goto(url, wait_until="networkidle", timeout=25000)
                sleep_random(3, 5)
                html = page.content()
            except Exception:
                html = ""
            browser.close()

        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".offer-tile, .offer-card, [data-offer], article")

        for card in cards:
            try:
                name_el = card.select_one("h2, h3, .hotel-name, [class*='name']")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)

                price_el = card.select_one(".price, [class*='price'], [class*='koszt']")
                price_text = price_el.get_text(strip=True) if price_el else "0"
                price = float("".join(filter(str.isdigit, price_text)) or 0)

                card_text = card.get_text()
                has_aqua = detect_aquapark(card_text)

                link_el = card.select_one("a[href]")
                offer_url = link_el["href"] if link_el else url
                if offer_url.startswith("/"):
                    offer_url = "https://www.neckermann.pl" + offer_url

                o = Offer(
                    source=self.name,
                    hotel_name=name,
                    destination="Marsa Alam",
                    date_from=c["date_from"].strftime("%Y-%m-%d"),
                    date_to=c["date_to"].strftime("%Y-%m-%d"),
                    nights=c["nights_min"],
                    adults=c["adults"],
                    children=1,
                    board="AI",
                    price_total=price,
                    price_per_person=round(price / (c["adults"] + 1), 2) if price else 0,
                    rating=None,
                    stars=None,
                    has_aquapark=has_aqua,
                    url=offer_url,
                )
                offers.append(o)
            except Exception as e:
                log.debug(f"[{self.name}] Błąd: {e}")

        return [o for o in offers if o.matches_criteria()]


# ─── Główna funkcja ───────────────────────────────────────────────────────────

def run_all_scrapers() -> list[Offer]:
    scrapers = [
        WakacjePLScraper(),
        ItakaScraper(),
        TUIScraper(),
        RainbowScraper(),
        CoralTravelScraper(),
        NeckermannScraper(),
    ]

    all_offers = []
    for scraper in scrapers:
        offers = scraper.safe_scrape()
        all_offers.extend(offers)
        sleep_random(3, 6)  # przerwa między serwisami

    # Deduplicacja po kluczu (ten sam hotel + data + cena)
    seen = set()
    unique = []
    for o in all_offers:
        k = o.unique_key()
        if k not in seen:
            seen.add(k)
            unique.append(o)

    # Sortowanie: najpierw ocena, potem cena
    unique.sort(key=lambda x: (-(x.rating or 0), x.price_total))
    return unique


if __name__ == "__main__":
    offers = run_all_scrapers()
    print(f"\n=== Znaleziono {len(offers)} unikalnych ofert ===\n")
    for o in offers:
        print(f"{o.source} | {o.hotel_name} | {o.nights}n | {o.board} | {o.price_total:.0f} zł | ocena: {o.rating}")
