# Wakacje Monitor 🏖️
## Automatyczny monitor ofert wakacyjnych — Marsa Alam

Scraper pobierający oferty z 6 serwisów co godzinę i wysyłający powiadomienia
email + Telegram gdy pojawią się nowe pasujące oferty.

### Kryteria wyszukiwania
- Destynacja: Marsa Alam, Egipt
- Termin: 25 maja – 11 czerwca 2025 (elastyczny)
- Długość: 7–10 nocy
- Osoby: 3 dorosłych + dziecko 9 lat
- Wymagania: aquapark, ocena 8.0+

### Serwisy
| Serwis | Metoda |
|--------|--------|
| wakacje.pl | Playwright (JS rendering) |
| itaka.pl | Playwright + scroll |
| tui.pl | Playwright + API intercept |
| rainbow.pl | requests + BS4 |
| coraltravel.pl | Playwright |
| neckermann.pl | Playwright |

---

## Konfiguracja (15 minut)

### Krok 1 — Fork repo na GitHub
1. Wejdź na github.com → New repository → nazwa: `wakacje-monitor`
2. Wrzuć wszystkie pliki z tego projektu
3. Upewnij się że masz plik `.github/workflows/monitor.yml`

### Krok 2 — Gmail: hasło aplikacji
1. Wejdź na myaccount.google.com → Bezpieczeństwo
2. Włącz weryfikację dwuetapową (jeśli nie masz)
3. Wyszukaj "Hasła do aplikacji" → Wygeneruj nowe → nazwa "WakacjeMonitor"
4. Zapisz 16-znakowy kod (np. `abcd efgh ijkl mnop`)

### Krok 3 — Telegram Bot (opcjonalnie)
1. Otwórz Telegram → wyszukaj `@BotFather`
2. Napisz `/newbot` → podaj nazwę → skopiuj TOKEN
3. Napisz `/start` do swojego bota
4. Wejdź na: `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Znajdź `"chat":{"id":NUMER}` — to Twój CHAT_ID

### Krok 4 — Secrets w GitHub
Wejdź w repo → Settings → Secrets and variables → Actions → New repository secret

Dodaj po kolei:
```
EMAIL_FROM       = twoj@gmail.com
EMAIL_TO         = twoj@gmail.com   (lub inny email docelowy)
EMAIL_APP_PASS   = abcdefghijklmnop  (hasło aplikacji bez spacji)
TELEGRAM_TOKEN   = 123456:ABCdef...  (opcjonalnie)
TELEGRAM_CHAT_ID = 123456789         (opcjonalnie)
```

### Krok 5 — Włącz Actions
1. W repo → zakładka Actions → "I understand my workflows, go ahead and enable them"
2. Znajdź workflow "Wakacje Monitor" → "Enable workflow"
3. Kliknij "Run workflow" żeby przetestować od razu

---

## Zmiana kryteriów

Edytuj plik `scrapers/scraper.py`, sekcja `CRITERIA`:

```python
CRITERIA = {
    "destination": "Marsa Alam",
    "date_from": date(2025, 5, 25),   # zmień datę wylotu
    "date_to":   date(2025, 6, 11),   # zmień datę powrotu
    "nights_min": 7,                   # minimalna liczba nocy
    "nights_max": 10,                  # maksymalna liczba nocy
    "adults": 3,
    "child_age": 9,
    "min_rating": 8.0,                 # minimalna ocena
    "must_have": ["aquapark"],
}
```

## Zmiana harmonogramu

Edytuj `.github/workflows/monitor.yml`:
```yaml
- cron: '0 4-21 * * *'   # co godzinę 6:00-23:00 PL
- cron: '0 */2 * * *'    # co 2 godziny
- cron: '0 8,12,16,20 * * *'  # 4x dziennie
```

## Uruchomienie lokalne (testowanie)

```bash
# Instalacja
pip install -r requirements.txt
playwright install chromium

# Konfiguracja emaila
export EMAIL_FROM="twoj@gmail.com"
export EMAIL_TO="twoj@gmail.com"
export EMAIL_APP_PASS="haslo-aplikacji"

# Uruchomienie
python main.py
```

## Wyniki
- `data/last_offers.json` — aktualny stan (JSON z ofertami)
- `data/offers_history.csv` — historia wszystkich znalezionych ofert
- `data/monitor.log` — logi

---

## Co dostaniesz w powiadomieniu

**Email** — pełna tabela HTML z:
- Nazwą hotelu, serwisem, gwiazdkami, oceną
- Liczbą nocy, wyżywieniem
- Ceną za 4 osoby
- Bezpośrednim linkiem do oferty
- Oznaczeniem NOWYCH ofert od ostatniego sprawdzenia

**Telegram** — krótka wiadomość z top 5 nowymi ofertami i linkami

Raport dzienny wysyłany automatycznie o 8:00 nawet bez zmian.
