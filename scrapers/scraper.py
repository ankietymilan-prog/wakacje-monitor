"""
Wakacje Monitor — Scraper v5
Używa prawdziwego URL z travelplanet.pl skopiowanego z przeglądarki po wyszukaniu.
"""

import asyncio
import logging
import re
import json
from datetime import date
from dataclasses import dataclass, field
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger(__name__)

CRITERIA = {
    "destination": "Marsa Alam",
    "date_from": date(2026, 5, 25),
    "date_to":   date(2026, 6, 11),
    "nights_min": 7,
    "nights_max": 12,
    "adults": 3,
    "child_age": 9,
    "min_rating": 8.0,
}

# Prawdziwy URL skopiowany z przeglądarki po ręcznym wyszukaniu z filtrami
TRAVELPLANET_URL = (
    "https://www.travelplanet.pl/wakacje/"
    "?s_action=TRIPS_SEARCH"
    "&d_start_from=25.05.2026"
    "&d_end_to=30.06.2026"
    "&nl_transportation_id%5B%5D=3_PL"
    "&s_holiday_target=tours"
    "&sort=nl_sell"
    "&page=1"
    "&nl_length_from=7"
    "&nl_length_to=12"
    "&nl_airport_radius=0"
    "&nl_occupancy_children=1"
    "&nl_occupancy_adults=3"
    "&nl_ages_children%5B%5D=9"
    "&nl_locality_parent_id%5B%5D=626"
    "&nl_hotel_attribute_type_id%5B%5D=21"
    "&nl_locality_id%5B%5D=626"
)


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


async def scrape_travelplanet(browser) -> list[Offer]:
    offers = []

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
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )

    page = await context.new_page()

    try:
        log.info("[travelplanet.pl] Ładowanie strony wyników...")
        await page.goto(TRAVELPLANET_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(5)

        # Spróbuj poczekać na karty ofert
        card_selectors = [
            "[class*='OfferItem']", "[class*='offer-item']",
            "[class*='TripItem']", "[class*='trip-item']",
            "[class*='HotelItem']", "[class*='hotel-item']",
            "[class*='ResultItem']", "[class*='result-item']",
            "article", "li[class*='item']",
        ]

        found_selector = None
        for sel in card_selectors:
            try:
                await page.wait_for_selector(sel, timeout=4000)
                count = len(await page.query_selector_all(sel))
                if count > 2:
                    found_selector = sel
                    log.info(f"[travelplanet.pl] Selektor '{sel}' — {count} kart")
                    break
            except PlaywrightTimeout:
                continue

        # Scroll
        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(1)

        title = await page.title()
        log.info(f"[travelplanet.pl] Tytuł: {title}")

        # Sprawdź elementy przez JS
        js_result = await page.evaluate("""
            () => {
                const candidates = [
                    '[class*="OfferItem"]', '[class*="offer-item"]',
                    '[class*="TripItem"]', '[class*="trip-item"]',
                    '[class*="HotelItem"]', '[class*="hotel-item"]',
                    '[class*="ResultItem"]', '[class*="result-item"]',
                    '[class*="ListItem"]', '[class*="list-item"]',
                    'article', 'li[class*="item"]',
                ];
                const results = {};
                for (const sel of candidates) {
                    const count = document.querySelectorAll(sel).length;
                    if (count > 0) results[sel] = count;
                }
                const bodyText = document.body.innerText;
                const match = bodyText.match(/(\\d+)\\s*(ofert|wynik|hotel|wyjazd)/i);
                results['_oferty_w_tekscie'] = match ? match[0] : 'brak';
                results['_current_url'] = window.location.href;
                return results;
            }
        """)
        log.info(f"[travelplanet.pl] Elementy: {json.dumps(js_result, ensure_ascii=False)}")

        sel = found_selector
        if not sel and js_result:
            for s, c in js_result.items():
                if not s.startswith('_') and isinstance(c, int) and c > 2:
                    sel = s
                    break

        if sel:
            cards = await page.query_selector_all(sel)
            log.info(f"[travelplanet.pl] Parsowanie {len(cards)} kart ({sel})")

            for card in cards:
                try:
                    hotel_el = await card.query_selector(
                        "h2, h3, h4, "
                        "[class*='name'], [class*='Name'], "
                        "[class*='title'], [class*='Title']"
                    )
                    if not hotel_el:
                        continue
                    hotel = (await hotel_el.inner_text()).strip()
                    if not hotel or len(hotel) < 3:
                        continue

                    price_el = await card.query_selector(
                        "[class*='price'], [class*='Price'], "
                        "[class*='cost'], [class*='Cost'], "
                        "[class*='amount'], [class*='Amount']"
                    )
                    price_text = (await price_el.inner_text()).strip() if price_el else "0"
                    price_clean = re.sub(r'[^\d]', '', price_text.replace('\xa0', ''))
                    price = float(price_clean) if price_clean else 0

                    rating_el = await card.query_selector(
                        "[class*='rating'], [class*='Rating'], "
                        "[class*='score'], [class*='Score'], "
                        "[class*='grade'], [class*='Grade']"
                    )
                    rating_text = (await rating_el.inner_text()).strip() if rating_el else "0"
                    rating_nums = re.findall(r'\d+[.,]\d+|\d+', rating_text)
                    rating = float(rating_nums[0].replace(',', '.')) if rating_nums else 0
                    if 0 < rating <= 5:
                        rating = rating * 2

                    if rating > 0 and rating < CRITERIA["min_rating"]:
                        continue

                    nights_el = await card.query_selector(
                        "[class*='night'], [class*='Night'], "
                        "[class*='duration'], [class*='Duration'], "
                        "[class*='length'], [class*='Length']"
                    )
                    nights_text = (await nights_el.inner_text()).strip() if nights_el else "7"
                    nights_nums = re.findall(r'\d+', nights_text)
                    nights = int(nights_nums[0]) if nights_nums else 7

                    board_el = await card.query_selector(
                        "[class*='board'], [class*='Board'], "
                        "[class*='meal'], [class*='Meal'], "
                        "[class*='catering'], [class*='Catering']"
                    )
                    board = (await board_el.inner_text()).strip() if board_el else "All Inclusive"

                    date_el = await card.query_selector(
                        "[class*='date'], [class*='Date'], "
                        "[class*='departure'], [class*='Departure']"
                    )
                    dep_date = (await date_el.inner_text()).strip() if date_el else "2026-05-25"
                    dep_date = dep_date[:10] if len(dep_date) >= 10 else dep_date

                    link_el = await card.query_selector("a[href]")
                    href = await link_el.get_attribute("href") if link_el else ""
                    if href and href.startswith("/"):
                        full_url = "https://www.travelplanet.pl" + href
                    elif href and href.startswith("http"):
                        full_url = href
                    else:
                        full_url = TRAVELPLANET_URL

                    offers.append(Offer(
                        hotel=hotel,
                        source="travelplanet.pl",
                        stars=0,
                        rating=rating,
                        nights=nights,
                        board=board or "All Inclusive",
                        price_total=price,
                        url=full_url,
                        departure_date=dep_date,
                    ))

                except Exception as e:
                    log.debug(f"[travelplanet.pl] Błąd karty: {e}")
                    continue

        if not offers:
            html_snippet = await page.evaluate(
                "() => document.body.innerHTML.substring(0, 3000)"
            )
            log.warning(f"[travelplanet.pl] Brak ofert. HTML:\n{html_snippet}")

    except Exception as e:
        log.error(f"[travelplanet.pl] Błąd główny: {e}")
    finally:
        await page.close()
        await context.close()

    log.info(f"[travelplanet.pl] Łącznie: {len(offers)} ofert")
    return offers


async def scrape_all_async() -> list[Offer]:
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
        try:
            result = await scrape_travelplanet(browser)
            all_offers.extend(result)
        except Exception as e:
            log.error(f"Błąd scrapera: {e}")
        finally:
            await browser.close()

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
    return asyncio.run(scrape_all_async())


# Alias dla kompatybilności z main.py
scrape_all = run_all_scrapers
