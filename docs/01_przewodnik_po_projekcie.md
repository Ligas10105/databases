# Przewodnik po projekcie — widok z lotu ptaka

## Co system robi i po co

System zbiera dane pogodowe dla 20 europejskich miast (lista w `config.yaml`),
zapisuje je do lokalnej bazy SQLite i prezentuje na interaktywnym dashboardzie.
Kolektor działa w tle i co 30 minut pobiera aktualną pogodę z API
OpenWeatherMap (a gdy ono zawiedzie — z Open-Meteo). Dashboard w Streamlit
pokazuje te dane na trzy sposoby: wykresy w czasie, statystyki i mapę Europy.
Dodatkowo skrypt `scripts/backfill.py` potrafi jednorazowo zasilić bazę
prawdziwą historią pogody (np. 2 tygodnie wstecz), żeby było co pokazywać
od razu, bez czekania aż kolektor nazbiera dane.

## Przepływ danych — krok po kroku

```
API pogodowe (OWM / Open-Meteo)
        │  HTTP GET, odpowiedź JSON
        ▼
KOLEKTOR  collector/api_client.py  →  collector/db.py
        │  znormalizowany słownik → INSERT do SQLite
        ▼
BAZA      data/weather.db (SQLite, 3 tabele)
        │  zapytania SELECT (tylko odczyt)
        ▼
DASHBOARD dashboard/data_loader.py  →  dashboard/views/*.py
        │  pandas DataFrame → wykresy/mapa
        ▼
PRZEGLĄDARKA (Streamlit)
```

Wyjaśnienie każdego kroku:

1. **API → kolektor.** Funkcja `fetch_owm()` w `collector/api_client.py` wysyła
   zapytanie HTTP do OpenWeatherMap i dostaje JSON z aktualną pogodą. Odpowiedź
   jest od razu **normalizowana** — czyli przerabiana na jeden wspólny format
   słownika (klucze: `temp_c`, `humidity_pct`, `timestamp` itd.), niezależnie
   z którego API przyszła. Dzięki temu reszta systemu nie musi wiedzieć, skąd
   pochodzą dane.
2. **Fallback.** Jeśli OWM zwróci błąd (np. brak klucza, limit zapytań),
   `fetch_owm()` zwraca `None`, a scheduler próbuje `fetch_open_meteo()` —
   darmowego API bez klucza. System nie crashuje, tylko po cichu zmienia źródło.
3. **Kolektor → baza.** `collector/db.py` otwiera połączenie do SQLite
   (`get_connection`) i wstawia pomiar (`insert_measurement`). Duplikaty
   (ten sam pomiar dwa razy) są automatycznie pomijane.
4. **Baza → dashboard.** Wszystkie zapytania SQL dashboardu mieszkają w jednym
   pliku: `dashboard/data_loader.py`. Strony dashboardu (`views/`) nie piszą
   SQL-a same — proszą data_loader o gotowe dane w formie tabel pandas.
5. **Dashboard → użytkownik.** `dashboard/app.py` rysuje pasek filtrów
   i trzy zakładki; każda zakładka dostaje te same filtry i te same dane.

## Rola każdego pliku

| Plik | Za co odpowiada |
|---|---|
| `config.yaml` | Konfiguracja: lista 20 miast, interwał zbierania (30 min), adresy API, ścieżka do bazy (`database.path`) |
| `.env` | Klucz API do OpenWeatherMap (`OWM_API_KEY`) — nigdy nie trafia do gita |
| `scripts/init_db.py` | Jednorazowe utworzenie bazy: 3 tabele + 2 indeksy + wstawienie 20 miast |
| `scripts/backfill.py` | Jednorazowe zasilenie bazy historią pogody (godzinową) z archiwum Open-Meteo; tryb główny `--start/--end` |
| `collector/api_client.py` | Klienci HTTP: `fetch_owm()` (główne źródło) i `fetch_open_meteo()` (zapasowe); normalizacja odpowiedzi do wspólnego słownika |
| `collector/db.py` | Warstwa zapisu do bazy: połączenie (WAL), `insert_measurement` (z odsiewaniem duplikatów), `log_collection_run` |
| `collector/scheduler.py` | Punkt startowy kolektora: APScheduler odpala `collect_all_cities()` co 30 min; logika fallbacku OWM→Open-Meteo |
| `dashboard/app.py` | Punkt startowy dashboardu: pasek filtrów (sidebar) + 3 zakładki |
| `dashboard/data_loader.py` | WSZYSTKIE zapytania SQL dashboardu; wspólny budowniczy filtrów `_build_where()` |
| `dashboard/views/time_series.py` | Zakładka 1: wykres liniowy parametru w czasie (Plotly) |
| `dashboard/views/quantitative.py` | Zakładka 2: statystyki (min/max/średnia/odchylenie), histogram, box plot |
| `dashboard/views/spatial.py` | Zakładka 3: mapa Folium — marker per miasto z najnowszym pomiarem + heatmapa |
| `tests/test_db.py`, `tests/test_api_client.py` | Testy: baza w pamięci + zamockowane odpowiedzi HTTP |

## Jak działa kolektor (`collector/scheduler.py`)

1. Przy starcie wczytuje `.env` (klucz API) i `config.yaml` (miasta, interwał).
2. Wykonuje **od razu** jedno zbieranie (`collect_all_cities()`), a potem
   ustawia w APSchedulerze zadanie cykliczne co `interval_minutes` (30 min).
3. `collect_all_cities()` dla każdego z 20 miast:
   - próbuje `fetch_owm(city, api_key)` — jeśli zwróci `None` (błąd HTTP,
     brak klucza), próbuje `fetch_open_meteo(city)`;
   - jeśli oba zawiodą — miasto jest pomijane (licznik `failed`), program
     działa dalej;
   - wstawia pomiar do bazy; jeśli identyczny timestamp już jest — loguje `DUP`.
4. Po przejściu wszystkich miast zapisuje podsumowanie do tabeli
   `collection_log` (ile miast OK, ile padło, z jakich źródeł dane).

## Jak działa dashboard (`dashboard/app.py`)

- **Wspólny pasek filtrów** budowany w `_build_sidebar()`: zakres dat
  (domyślnie ostatnie 7 dni), multiselect miast, wybór parametru (temperatura,
  wilgotność, ciśnienie, wiatr, zachmurzenie...), suwak zakresu wartości,
  poziom agregacji (raw/godzinowa/dzienna/tygodniowa) i warunki pogodowe
  (Clear, Rain...). Wynik to jeden słownik `filters`, przekazywany do
  **wszystkich trzech zakładek** — dlatego każdy widok filtruje identycznie.
- **Zakładki** (`st.tabs`):
  1. *Time Series* — przebieg parametru w czasie, kolor = miasto.
  2. *Statistics* — tabela statystyk per miasto, histogram, box plot.
  3. *Map* — mapa Europy; dla każdego miasta najnowszy pomiar **mieszczący się
     w filtrach** (funkcja `load_latest_per_city_filtered`), marker z popupem
     i warstwa heatmapy.
- Dashboard łączy się z bazą **tylko do odczytu** — nigdy nie pisze.

## Uruchomienie krok po kroku

```bash
# 0. Zależności (raz)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Utworzenie bazy + wstawienie 20 miast (raz)
python scripts/init_db.py

# 2a. Zasilenie historią (np. 2 tygodnie, archiwum bywa opóźnione 2-5 dni)
python scripts/backfill.py --start 2026-05-28 --end 2026-06-08

# 2b. ...i/lub zbieranie na żywo co 30 min (zostawić włączone)
python -m collector.scheduler

# 3. Dashboard (w drugim terminalu)
streamlit run dashboard/app.py
```

Backfill i kolektor mogą działać równolegle z dashboardem — patrz tryb WAL
w `docs/02_baza_danych_od_zera.md`.
