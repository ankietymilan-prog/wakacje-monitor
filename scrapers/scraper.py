"""
Wakacje Monitor — Scraper v3
Używa Playwright z prawidłowym czekaniem na załadowanie ofert przez JS.
Skupia się na wakacje.pl i travelplanet.pl które NA PEWNO mają oferty.
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
    "date_from": date(2025, 5, 25),
    "date_to":   date(2025, 6, 11),
    "nights_min": 7,
    "nights_max": 10,
    "adults": 3,
    "child_age": 9,
    "min_rating": 8.0,
    "must_have": ["aquapark"],
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


async def scrape_wakacje_pl(browser) -> list[Offer]:
    """Scraper wakacje.pl — czeka na załadowanie ofert przez JS."""
    offers = []
    url = (
        "https://www.wakacje.pl/lastminute/marsa-el-alam/"
        "?od-2026-05-25,do-2026-06-11,ocena-8,z-aquaparkiem,"
        "3dorosle-1dziecko-20161207"
    )
    
    try:
        page = await browser.new_page()
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "pl-PL,pl;q=0.9",
        })
        
        log.info("[wakacje.pl] Ładowanie strony...")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        # Czekaj na załadowanie ofert — szukamy kart hotelowych
        try:
            await page.wait_for_selector("article, [class*='offer'], [class*='hotel'], [data-testid*='offer']", timeout=20000)
        except PlaywrightTimeout:
            log.warning("[wakacje.pl] Timeout czekania na oferty, próbuję parsować co jest")
        
        # Scroll żeby załadować więcej
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(1)
        
        # Pobierz dane z __NEXT_DATA__ lub ze struktury HTML
        try:
            next_data = await page.evaluate("""
                () => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (!el) return null;
                    const data = JSON.parse(el.textContent);
                    // Szukamy ofert w różnych miejscach struktury
                    const stores = data?.props?.stores;
                    if (!stores) return null;
                    
                    // Sprawdź różne store'y
                    for (const key of Object.keys(stores)) {
                        const store = stores[key];
                        if (store?.offers && Array.isArray(store.offers) && store.offers.length > 0) {
                            return store.offers;
                        }
                        if (store?._offers && Array.isArray(store._offers) && store._offers.length > 0) {
                            return store._offers;
                        }
                    }
                    return null;
                }
            """)
            
            if next_data and len(next_data) > 0:
                log.info(f"[wakacje.pl] Znaleziono {len(next_data)} ofert w __NEXT_DATA__")
                for item in next_data:
                    try:
                        rating = float(item.get("rating") or item.get("score") or item.get("hotelRating") or 0)
                        if rating < CRITERIA["min_rating"]:
                            continue
                        price = float(item.get("price") or item.get("totalPrice") or item.get("priceTotal") or 0)
                        if 0 < price < 3000:
                            price *= (CRITERIA["adults"] + 1)
                        nights = int(item.get("nights") or item.get("duration") or 7)
                        offers.append(Offer(
                            hotel=item.get("hotelName") or item.get("name") or "Nieznany",
                            source="wakacje.pl",
                            stars=int(item.get("stars") or item.get("hotelStars") or item.get("category") or 0),
                            rating=rating,
                            nights=nights,
                            board=item.get("board") or item.get("boardType") or item.get("mealType") or "?",
                            price_total=price,
                            url="https://www.wakacje.pl" + (item.get("url") or item.get("offerUrl") or ""),
                            departure_date=str(item.get("departureDate") or item.get("dateFrom") or ""),
                        ))
                    except Exception:
                        continue
        except Exception as e:
            log.warning(f"[wakacje.pl] Błąd __NEXT_DATA__: {e}")
        
        # Jeśli __NEXT_DATA__ nie zadziałało, parsuj HTML
        if not offers:
            log.info("[wakacje.pl] Próba parsowania HTML...")
            cards = await page.query_selector_all("article, [class*='OfferCard'], [class*='offer-card'], [class*='HotelCard']")
            log.info(f"[wakacje.pl] Znaleziono {len(cards)} kart HTML")
            
            for card in cards:
                try:
                    text = await card.inner_text()
                    
                    # Wyciągnij nazwę hotelu
                    hotel_el = await card.query_selector("h2, h3, [class*='name'], [class*='title']")
                    hotel = await hotel_el.inner_text() if hotel_el else "Nieznany"
                    hotel = hotel.strip()
                    
                    # Wyciągnij cenę
                    price_el = await card.query_selector("[class*='price'], [class*='Price']")
                    price_text = await price_el.inner_text() if price_el else "0"
                    price_nums = re.findall(r'\d+[\s\d]*', price_text.replace('\xa0', ''))
                    price = float(''.join(price_nums[0].split())) if price_nums else 0
                    
                    # Wyciągnij ocenę
                    rating_el = await card.query_selector("[class*='rating'], [class*='Rating'], [class*='score']")
                    rating_text = await rating_el.inner_text() if rating_el else "0"
                    rating_nums = re.findall(r'\d+[.,]\d+|\d+', rating_text)
                    rating = float(rating_nums[0].replace(',', '.')) if rating_nums else 0
                    
                    if rating < CRITERIA["min_rating"] and rating > 0:
                        continue
                    
                    # Wyciągnij link
                    link_el = await card.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else ""
                    full_url = "https://www.wakacje.pl" + href if href and href.startswith("/") else href or ""
                    
                    if hotel and hotel != "Nieznany":
                        offers.append(Offer(
                            hotel=hotel,
                            source="wakacje.pl",
                            stars=0,
                            rating=rating,
                            nights=7,
                            board="?",
                            price_total=price,
                            url=full_url,
                            departure_date="2026-05-25",
                        ))
                except Exception:
                    continue
        
        await page.close()
        log.info(f"[wakacje.pl] Znaleziono {len(offers)} ofert")
    except Exception as e:
        log.error(f"[wakacje.pl] Błąd: {e}")
    
    return offers


async def scrape_travelplanet(browser) -> list[Offer]:
    """Scraper travelplanet.pl — czeka na załadowanie ofert."""
    offers = []
    url = (
        "https://www.travelplanet.pl/wakacje/"
        "?destination=egipt-marsa-alam"
        "&dateFrom=2026-05-25&dateTo=2026-06-11"
        "&adults=3&children=9"
        "&nights=7,10"
        "&facilities=aquapark"
        "&rating=4"
    )
    
    # Alternatywny URL — taki jak widzieliśmy w przeglądarce
    url2 = "https://www.travelplanet.pl/wakacje/?destination=egipt-marsa-alam&dateFrom=2026-05-25&dateTo=2026-06-11&adults=3&children=9"
    
    try:
        page = await browser.new_page()
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "pl-PL,pl;q=0.9",
        })
        
        log.info("[travelplanet.pl] Ładowanie strony...")
        await page.goto(url2, wait_until="domcontentloaded", timeout=30000)
        
        # Czekaj na karty ofert
        try:
            await page.wait_for_selector("[class*='offer'], [class*='hotel'], [class*='card'], article", timeout=20000)
        except PlaywrightTimeout:
            log.warning("[travelplanet.pl] Timeout, próbuję dalej")
        
        await asyncio.sleep(3)
        
        # Scroll
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(1)
        
        # Parsuj karty
        cards = await page.query_selector_all("[class*='OfferItem'], [class*='offer-item'], [class*='HotelItem'], article")
        log.info(f"[travelplanet.pl] Znaleziono {len(cards)} kart")
        
        for card in cards:
            try:
                hotel_el = await card.query_selector("h2, h3, [class*='name'], [class*='title']")
                if not hotel_el:
                    continue
                hotel = (await hotel_el.inner_text()).strip()
                if not hotel or len(hotel) < 3:
                    continue
                
                price_el = await card.query_selector("[class*='price'], [class*='Price']")
                price_text = await price_el.inner_text() if price_el else "0"
                price_nums = re.findall(r'[\d\s]+', price_text.replace('\xa0', ' ').replace(' ', ''))
                price = float(price_nums[0]) if price_nums else 0
                
                rating_el = await card.query_selector("[class*='rating'], [class*='score'], [class*='grade']")
                rating_text = await rating_el.inner_text() if rating_el else "0"
                rating_nums = re.findall(r'\d+[.,]\d+|\d+', rating_text)
                rating = float(rating_nums[0].replace(',', '.')) if rating_nums else 0
                # travelplanet używa skali 1-5, przelicz na 1-10
                if rating > 0 and rating <= 5:
                    rating = rating * 2
                
                if rating < CRITERIA["min_rating"] and rating > 0:
                    continue
                
                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                full_url = "https://www.travelplanet.pl" + href if href and href.startswith("/") else href or ""
                
                nights_el = await card.query_selector("[class*='night'], [class*='duration'], [class*='days']")
                nights_text = await nights_el.inner_text() if nights_el else "7"
                nights_nums = re.findall(r'\d+', nights_text)
                nights = int(nights_nums[0]) if nights_nums else 7
                
                offers.append(Offer(
                    hotel=hotel,
                    source="travelplanet.pl",
                    stars=0,
                    rating=rating,
                    nights=nights,
                    board="All Inclusive",
                    price_total=price,
                    url=full_url,
                    departure_date="2026-05-25",
                ))
            except Exception:
                continue
        
        await page.close()
        log.info(f"[travelplanet.pl] Znaleziono {len(offers)} ofert")
    except Exception as e:
        log.error(f"[travelplanet.pl] Błąd: {e}")
    
    return offers


async def scrape_all_async() -> list[Offer]:
    """Uruchamia wszystkie scrapery asynchronicznie."""
    all_offers = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox", 
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )
        
        # Ukryj że to bot
        await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            viewport={"width": 1920, "height": 1080},
        )
        
        tasks = [
            scrape_wakacje_pl(browser),
            scrape_travelplanet(browser),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_offers.extend(result)
            elif isinstance(result, Exception):
                log.error(f"Błąd scrapera: {result}")
        
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
    """Synchroniczny wrapper dla async scraperów."""
    return asyncio.run(scrape_all_async())
