"""
Wakacje Monitor — Scraper v4
Skupia się wyłącznie na travelplanet.pl z poprawnym URL z filtrami.
"""

import asyncio
import logging
import re
from datetime import date
from dataclasses import dataclass, field
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger(__name__)

CRITERIA = {
    "destination": "Marsa Alam",
    "date_from": date(2026, 5, 25),
    "date_to":   date(2026, 6, 11),
    "nights_min": 7,
    "nights_max": 10,
    "adults": 3,
    "child_age": 9,
    "min_rating": 8.0,
    "must_have": ["aquapark"],
}

# URL z filtrami — travelplanet używa ścieżek semantycznych + parametrów GET
# Format dat: YYYY-MM-DD, osoby: adults=3&children=1&childAge[0]=9
# Aquapark = facilities=aquapark, ocena 8+ = minRating=4 (skala 1-5)
TRAVELPLANET_URLS = [
    # URL z pełnymi filtrami — wylot z Warszawy
    (
        "https://www.travelplanet.pl/wakacje/egipt/marsa-alam/"
        "?dateFrom=2026-05-25&dateTo=2026-06-11"
        "&adults=3&children=1&childAge%5B0%5D=9"
        "&durationFrom=7&durationTo=10"
        "&facilities=aquapark"
        "&minRating=4"
        "&departureRegion=6"
    ),
    # URL z Łodzi (region 11)
    (
        "https://www.travelplanet.pl/wakacje/egipt/marsa-alam/"
        "?dateFrom=2026-05-25&dateTo=2026-06-11"
        "&adults=3&children=1&childAge%5B0%5D=9"
        "&durationFrom=7&durationTo=10"
        "&facilities=aquapark"
        "&minRating=4"
        "&departureRegion=11"
    ),
    # URL bez regionu (wszystkie wyloty)
    (
        "https://www.travelplanet.pl/wakacje/egipt/marsa-alam/"
        "?dateFrom=2026-05-25&dateTo=2026-06-11"
        "&adults=3&children=1&childAge%5B0%5D=9"
        "&durationFrom=7&durationTo=10"
        "&facilities=aquapark"
        "&minRating=4"
    ),
]


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


async def scrape_travelplanet_url(page, url: str) -> list[Offer]:
    """Scrapuje jeden URL travelplanet.pl i zwraca oferty."""
    offers = []
    
    log.info(f"[travelplanet.pl] Ładowanie: {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        log.error(f"[travelplanet.pl] Błąd ładowania strony: {e}")
        return offers

    # Poczekaj na załadowanie ofert
    await asyncio.sleep(4)
    
    # Próba czekania na karty ofert
    selectors_to_try = [
        "[class*='OfferItem']",
        "[class*='offer-item']",
        "[class*='offer_item']",
        "[data-testid*='offer']",
        "article",
        "[class*='HotelCard']",
        "[class*='hotel-card']",
    ]
    
    found_selector = None
    for sel in selectors_to_try:
        try:
            await page.wait_for_selector(sel, timeout=5000)
            count = len(await page.query_selector_all(sel))
            if count > 0:
                found_selector = sel
                log.info(f"[travelplanet.pl] Znaleziono {count} kart z selektorem: {sel}")
                break
        except PlaywrightTimeout:
            continue

    # Scroll żeby załadować więcej
    for _ in range(4):
        await page.evaluate("window.scrollBy(0, 1000)")
        await asyncio.sleep(1.5)

    # Pobierz HTML i sprawdź co jest na stronie
    title = await page.title()
    log.info(f"[travelplanet.pl] Tytuł strony: {title}")
    
    # Zlicz oferty przez JavaScript
    offer_count_js = await page.evaluate("""
        () => {
            // Spróbuj różnych selektorów
            const selectors = [
                '[class*="OfferItem"]',
                '[class*="offer-item"]', 
                '[class*="offer_item"]',
                'article',
                '[class*="HotelCard"]',
                '[class*="ListItem"]',
                '[class*="list-item"]',
            ];
            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                if (els.length > 2) return {selector: sel, count: els.length};
            }
            return {selector: null, count: 0};
        }
    """)
    log.info(f"[travelplanet.pl] JS znalazł: {offer_count_js}")
    
    if found_selector or (offer_count_js and offer_count_js.get('count', 0) > 0):
        sel = found_selector or offer_count_js.get('selector')
        cards = await page.query_selector_all(sel)
        log.info(f"[travelplanet.pl] Parsowanie {len(cards)} kart...")
        
        for card in cards:
            try:
                # Hotel
                hotel_el = await card.query_selector("h2, h3, h4, [class*='name'], [class*='title'], [class*='Name'], [class*='Title']")
                if not hotel_el:
                    continue
                hotel = (await hotel_el.inner_text()).strip()
                if not hotel or len(hotel) < 3:
                    continue

                # Cena
                price_el = await card.query_selector("[class*='price'], [class*='Price'], [class*='cost'], [class*='Cost']")
                price_text = (await price_el.inner_text()).strip() if price_el else "0"
                # Usuń spacje, zamień przecinki
                price_clean = re.sub(r'[^\d]', '', price_text.replace('\xa0', ''))
                price = float(price_clean) if price_clean else 0

                # Ocena (travelplanet skala 1-5 lub 1-10)
                rating_el = await card.query_selector("[class*='rating'], [class*='Rating'], [class*='score'], [class*='Score'], [class*='grade'], [class*='Grade']")
                rating_text = (await rating_el.inner_text()).strip() if rating_el else "0"
                rating_nums = re.findall(r'\d+[.,]\d+|\d+', rating_text)
                rating = float(rating_nums[0].replace(',', '.')) if rating_nums else 0
                # Normalizuj do skali 10
                if 0 < rating <= 5:
                    rating = rating * 2

                # Filtr oceny
                if rating > 0 and rating < CRITERIA["min_rating"]:
                    continue

                # Noce
                nights_el = await card.query_selector("[class*='night'], [class*='Night'], [class*='duration'], [class*='Duration'], [class*='days'], [class*='Days']")
                nights_text = (await nights_el.inner_text()).strip() if nights_el else "7"
                nights_nums = re.findall(r'\d+', nights_text)
                nights = int(nights_nums[0]) if nights_nums else 7

                # Wyżywienie
                board_el = await card.query_selector("[class*='board'], [class*='Board'], [class*='meal'], [class*='Meal'], [class*='food'], [class*='Food']")
                board = (await board_el.inner_text()).strip() if board_el else "All Inclusive"

                # Link
                link_el = await card.query_selector("a[href]")
                href = await link_el.get_attribute("href") if link_el else ""
                if href and href.startswith("/"):
                    full_url = "https://www.travelplanet.pl" + href
                elif href and href.startswith("http"):
                    full_url = href
                else:
                    full_url = url

                offers.append(Offer(
                    hotel=hotel,
                    source="travelplanet.pl",
                    stars=0,
                    rating=rating,
                    nights=nights,
                    board=board or "All Inclusive",
                    price_total=price,
                    url=full_url,
                    departure_date="2026-05-25",
                ))
            except Exception as e:
                log.debug(f"[travelplanet.pl] Błąd parsowania karty: {e}")
                continue

    # Jeśli nadal 0 ofert — spróbuj przez tekst strony
    if not offers:
        log.warning("[travelplanet.pl] Brak ofert z selektorów — sprawdzam tekst strony")
        body_text = await page.evaluate("() => document.body.innerText")
        log.info(f"[travelplanet.pl] Tekst strony (pierwsze 500 znaków): {body_text[:500]}")

    log.info(f"[travelplanet.pl] Znaleziono {len(offers)} ofert z {url[:60]}...")
    return offers


async def scrape_all_async() -> list[Offer]:
    """Uruchamia scrapery dla wszystkich URL."""
    all_offers = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            viewport={"width": 1920, "height": 1080},
        )

        # Ukryj webdriver
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        # Sprawdź wszystkie URL — zatrzymaj się gdy znajdzie oferty
        for url in TRAVELPLANET_URLS:
            page = await context.new_page()
            try:
                offers = await scrape_travelplanet_url(page, url)
                all_offers.extend(offers)
                if offers:
                    log.info(f"[travelplanet.pl] Znaleziono oferty — pomijam pozostałe URL")
                    await page.close()
                    break
            except Exception as e:
                log.error(f"Błąd URL {url}: {e}")
            finally:
                await page.close()

        await browser.close()

    # Deduplikacja
    seen = set()
    unique = []
    for offer in all_offers:
        k = offer.key()
        if k not in seen:
            seen.add(k)
            unique.append(offer)

    log.info(f"Łącznie unikalnych ofert: {len(unique)}")
    return unique


def run_all_scrapers() -> list[Offer]:
    """Synchroniczny wrapper."""
    return asyncio.run(scrape_all_async())


# Alias dla kompatybilności z main.py
scrape_all = run_all_scrapers
