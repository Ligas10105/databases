# Przewodnik po projekcie — widok z lotu ptaka

## Co system robi i po co

System loguje dane pogodowe dla 20 europejskich miast (lista w `config.yaml`)
do własnej bazy SQLite i prezentuje je na interaktywnym dashboardzie.
Dane pobiera skrypt `scripts/backfill.py` z API Open-Meteo — jedno uruchomienie
ściąga historię godzinową z ostatnich N dni (domyślnie 14) i wstawia ją do bazy;
ponowne uruchomienie dokleja tylko nowe godziny. Dashboard w Streamlit pokazuje
dane na trzy sposoby: wykresy w czasie (time series), statystyki (analiza
ilościowa) i mapę Europy (analiza przestrzenna) — każdy widok z 6 wspólnymi
filtrami.

Tak realizujemy wymagania projektu: *logowanie danych ze źródła online do
własnej bazy* + *system wizualizacji ze statystyką i min. jedną z trzech
kategorii* (mamy wszystkie trzy) + *min. 5 sposobów filtrowania na widok*.

## Przepływ danych — krok po kroku

```
ŹRÓDŁO    Open-Meteo API (api.open-meteo.com/v1/forecast, past_days=N)
        │  HTTP GET, odpowiedź JSON z blokiem hourly
        ▼
LOGGER    scripts/backfill.py  →  collector/db.py
        │  mapowanie na wiersze → INSERT OR IGNORE do SQLite
        ▼
BAZA      data/weather.db (SQLite, 3 tabele: cities, measurements, collection_log)
        │  zapytania SELECT (tylko odczyt)
        ▼
DASHBOARD dashboard/data_loader.py  →  dashboard/views/*.py
        │  pandas DataFrame → wykresy / statystyki / mapa
        ▼
PRZEGLĄDARKA (Streamlit, localhost:8501)
```

Wyjaśnienie każdego kroku:

1. **Źródło → logger.** `fetch_history()` w `scripts/backfill.py` wysyła dla
   każdego miasta jedno zapytanie HTTP do Open-Meteo z parametrem
   `past_days=N` — odpowiedź to JSON z tablicami godzinowymi (czas,
   temperatura, wilgotność, ciśnienie, wiatr, zachmurzenie, kod pogody).
2. **Normalizacja.** `_hourly_to_rows()` przerabia odpowiedź na wiersze
   pasujące do naszej tabeli: km/h → m/s, kod pogody WMO → kategoria tekstowa
   ("Rain", "Clouds"...), czas → ISO UTC. Godziny z przyszłości (API dorzuca
   prognozę na resztę doby) są odcinane — logujemy tylko przeszłość.
3. **Logger → baza.** `collector/db.py` wstawia wiersze przez
   `INSERT OR IGNORE` — duplikaty (godziny, które już są w bazie) są pomijane,
   więc skrypt można odpalać codziennie i baza tylko przyrasta.
   Podsumowanie każdego przebiegu ląduje w tabeli `collection_log`.
4. **Baza → dashboard.** Wszystkie zapytania SQL dashboardu mieszkają w jednym
   pliku: `dashboard/data_loader.py`. Widoki (`views/`) nie piszą SQL-a same —
   dostają gotowe tabele pandas. Dashboard łączy się z bazą **tylko do odczytu**.
5. **Dashboard → użytkownik.** `dashboard/app.py` rysuje pasek filtrów
   i trzy zakładki; każda zakładka dostaje ten sam słownik filtrów.

## Rola każdego pliku

| Plik | Za co odpowiada |
|---|---|
| `config.yaml` | Konfiguracja: lista 20 miast (nazwa, kraj, współrzędne) i ścieżka do bazy (`database.path`) |
| `scripts/init_db.py` | Jednorazowe utworzenie bazy: 3 tabele + 2 indeksy + wstawienie 20 miast |
| `scripts/backfill.py` | Logowanie danych: pobiera historię godzinową z Open-Meteo i wstawia do bazy |
| `collector/db.py` | Warstwa zapisu: połączenie (tryb WAL), `insert_measurement` (z odsiewaniem duplikatów), `log_collection_run` |
| `dashboard/app.py` | Punkt startowy dashboardu: pasek filtrów (sidebar) + 3 zakładki |
| `dashboard/data_loader.py` | WSZYSTKIE zapytania SQL dashboardu; wspólny budowniczy filtrów `_build_where()` |
| `dashboard/views/time_series.py` | Zakładka 1: wykres liniowy parametru w czasie (Plotly) |
| `dashboard/views/quantitative.py` | Zakładka 2: statystyki (min/max/średnia/odchylenie), histogram, box plot |
| `dashboard/views/spatial.py` | Zakładka 3: mapa Folium — marker per miasto z najnowszym pomiarem + heatmapa |
| `tests/test_db.py`, `tests/test_backfill.py` | Testy: baza w pamięci/pliku tymczasowym + parser odpowiedzi API |

## Jak działa backfill (`scripts/backfill.py`)

1. Wczytuje `config.yaml` (miasta, ścieżka bazy) i zapamiętuje bieżący czas
   UTC jako granicę (cutoff) odcinania przyszłych godzin.
2. Dla każdego z 20 miast: jedno zapytanie HTTP → mapowanie na wiersze →
   `INSERT OR IGNORE`. Loguje per miasto: ile wierszy pobrano, ile wstawiono,
   ile było duplikatów. Między miastami krótka pauza (`--sleep`), żeby nie
   zalewać API.
3. Jeśli zapytanie dla miasta padnie — miasto jest pomijane (licznik failed),
   skrypt działa dalej; przy następnym uruchomieniu uzupełni braki.
4. Na końcu wpis do `collection_log`: ile miast OK / failed, ile wierszy weszło.

## Jak działa dashboard (`dashboard/app.py`)

- **Wspólny pasek filtrów** budowany w `_build_sidebar()` — 6 filtrów:
  1. zakres dat (domyślnie ostatnie 7 dni),
  2. multiselect miast,
  3. wybór parametru (temperatura, odczuwalna, wilgotność, ciśnienie, wiatr, zachmurzenie),
  4. suwak zakresu wartości,
  5. poziom agregacji (raw / godzinowa / dzienna / tygodniowa),
  6. warunki pogodowe (Clear, Rain, Clouds...).

  Wynik to jeden słownik `filters`, przekazywany do **wszystkich trzech
  zakładek** — dlatego każdy widok filtruje identycznie (klauzulę WHERE buduje
  jedna wspólna funkcja `_build_where()` w `data_loader.py`).
- **Zakładki** (`st.tabs`):
  1. *Time Series* — przebieg parametru w czasie, kolor = miasto.
  2. *Statistics* — tabela statystyk per miasto, histogram, box plot.
  3. *Map* — mapa Europy; dla każdego miasta najnowszy pomiar **mieszczący się
     w filtrach** (`load_latest_per_city_filtered`), marker z popupem
     i warstwa heatmapy.

## Uruchomienie krok po kroku

```bash
# 0. Zależności (raz)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Utworzenie bazy + wstawienie 20 miast (raz)
python scripts/init_db.py

# 2. Zalogowanie danych — ostatnie 14 dni co godzinę
python scripts/backfill.py --days 14

# 3. Dashboard
streamlit run dashboard/app.py
```

Przed prezentacją wystarczy powtórzyć krok 2 — skrypt doklei brakujące godziny
(duplikaty pominie), więc mapa "latest readings" pokaże dane z ostatniej godziny.
