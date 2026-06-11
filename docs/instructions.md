# Brief dla Claude Code — projekt weather_system

## Kontekst projektu
System zbierania i wizualizacji danych pogodowych. Stack:
- Python 3.10+, SQLite (sqlite3), APScheduler (kolektor), requests
- Dashboard: Streamlit + Plotly (wykresy) + Folium (mapa)
- Źródła danych: OpenWeatherMap (primary) + Open-Meteo (fallback)

Struktura:
- collector/        — api_client.py, db.py, scheduler.py
- dashboard/        — app.py, data_loader.py, views/{time_series,quantitative,spatial}.py
- scripts/          — init_db.py, backfill.py
- tests/            — test_db.py, test_api_client.py

ZASADY OGÓLNE:
- NIE zmieniaj architektury. Rób minimalne, chirurgiczne zmiany.
- Wszystkie timestampy w UTC.
- Nie commituj pliku bazy (data/) ani .env.
- Po wszystkich zmianach uruchom `pytest tests/ -v` i upewnij się, że przechodzi.
- Komentarze i dokumentacja PO POLSKU (projekt oddawany w Polsce).

═══════════════════════════════════════════════════════════════
## ZADANIE 1: Filtrowanie na mapie (widok Spatial)
═══════════════════════════════════════════════════════════════

PROBLEM:
Widoki Time Series i Statistics używają `load_measurements(db_path, filters)`
i poprawnie respektują wszystkie filtry z paska bocznego (zakres dat, miasta,
zakres wartości, warunki pogodowe). Widok mapy (dashboard/views/spatial.py)
wywołuje `load_latest_per_city(db_path)`, które IGNORUJE słownik `filters` —
zawsze pokazuje ostatni pomiar dla WSZYSTKICH 20 miast. Łamie to wymaganie
projektu: każdy widok musi mieć min. 5 filtrów.

OCZEKIWANY EFEKT:
Mapa respektuje filtry z paska bocznego: zakres dat (start/end), wybrane
miasta (city_ids), zakres wartości (value_min/value_max), warunki pogodowe
(weather_conditions) oraz parametr (steruje kolorem markera/heatmapą).
Dla każdego przefiltrowanego miasta pokazujemy jego NAJNOWSZY pomiar
mieszczący się w filtrach (marker + popup + warstwa HeatMap).

PODEJŚCIE (preferowane):
- W dashboard/data_loader.py dodaj funkcję
  `load_latest_per_city_filtered(db_path, filters)`.
- Wydziel budowanie klauzuli WHERE + params do wspólnego prywatnego helpera
  (np. `_build_where(filters)`), żeby NIE duplikować logiki, której obecnie
  używa `load_measurements`. Zrefaktoruj `load_measurements`, żeby też z niego
  korzystała.
- Nowa funkcja: te same warunki WHERE co load_measurements, a następnie wybór
  ostatniego rekordu per miasto (podzapytanie z MAX(timestamp) per city_id albo
  funkcja okna). Zwraca te same kolumny co obecne `load_latest_per_city`
  (city, country, lat, lon, timestamp, kolumny parametrów, weather_main).
- W spatial.py podmień wywołanie na `load_latest_per_city_filtered(db_path, filters)`.

WAŻNE:
- NIE usuwaj istniejącej `load_latest_per_city` (zostaw, dodaj nową obok).
- Zachowaj obecne zachowanie przy pustym wyniku (st.info z komunikatem).
- Zachowaj obsługę braku współrzędnych (dropna lat/lon) i wartości NaN w popupach.
- Markery i heatmapa korzystają z tego samego przefiltrowanego zbioru.

WERYFIKACJA RĘCZNA:
- Filtr do jednego miasta → jeden marker.
- Zakres dat bez danych → st.info, brak crasha.
- Zmiana parametru → zmieniają się wartości w popupach i intensywność heatmapy.

═══════════════════════════════════════════════════════════════
## ZADANIE 2: Backfill realnych danych historycznych (zakres dat)
═══════════════════════════════════════════════════════════════

CEL:
Wypełnić bazę PRAWDZIWĄ historią pogody, podając zakres dat (od–do).
Na prezentacji pokazujemy ok. 2 TYGODNIE historii dla 20 miast, w rozdzielczości
GODZINOWEJ (kolektor na żywo działa co 30 min, ale dane historyczne z archiwum
są godzinowe, bo taką rozdzielczość udostępnia źródło ERA5).

ŹRÓDŁO — Open-Meteo Historical Weather API (ERA5, bez klucza, JSON jak forecast):
  https://archive-api.open-meteo.com/v1/archive
Parametry:
  - latitude, longitude
  - start_date=YYYY-MM-DD, end_date=YYYY-MM-DD
  - hourly=temperature_2m,apparent_temperature,relativehumidity_2m,pressure_msl,
           windspeed_10m,winddirection_10m,cloudcover,weathercode
  - timezone=GMT

DO ZROBIENIA — przerób scripts/backfill.py:
  1. Dodaj argumenty CLI `--start YYYY-MM-DD` i `--end YYYY-MM-DD`.
     Gdy podane → uderzaj w archive-api.open-meteo.com/v1/archive z start_date/end_date.
     Pozostaw istniejący tryb `--days` (past_days) jako alternatywę, ale
     `--start/--end` ma być trybem głównym używanym do demo.
  2. Parser wiersza godzinowego jest niemal identyczny jak obecny `fetch_history`
     (ten sam blok hourly: time[], temperature_2m[], itd.). Wydziel wspólne
     mapowanie wiersza do JEDNEJ funkcji i użyj w obu trybach (wykorzystaj
     istniejące _normalize_ts, _to_int, _kmh_to_ms oraz _wmo_to_main/_wmo_to_desc).
  3. source dla tych rekordów: "open_meteo_archive".
  4. WALIDACJA:
     - poprawny format dat (YYYY-MM-DD), sensowny komunikat błędu;
     - start_date <= end_date.
  5. Loguj per miasto: liczba pobranych wierszy, inserted, dup. Na końcu wpis
     do collection_log (jak obecnie) z source_used i podsumowaniem.

PUŁAPKI:
  - Archive API (ERA5) bywa OPÓŹNIONE o ok. 2–5 dni względem dziś — dla
    najświeższych dni może brakować danych. Jeśli end_date jest blisko teraz,
    część ostatnich godzin może być pusta — to NORMALNE, nie traktuj jako błąd.
  - Duplikaty obsłużone przez UNIQUE(city_id, timestamp) + INSERT OR IGNORE,
    więc wielokrotne odpalenie jest bezpieczne.
  - Zachowaj `time.sleep` między miastami (parametr --sleep), żeby nie
    przeciążać API.

URUCHOMIENIE (po implementacji — NIE rób tego automatycznie, tylko podaj komendy):
  python scripts/init_db.py
  python scripts/backfill.py --start <14 dni temu> --end <kilka dni temu>

═══════════════════════════════════════════════════════════════
## ZADANIE 3: Dokumentacja do nauki i obrony (folder docs/)
═══════════════════════════════════════════════════════════════

WAŻNY KONTEKST O ODBIORCY:
Autor będzie bronił projektu, ale SŁABO ZNA SIĘ NA BAZACH DANYCH (nadrabia
semestr). Dokumentacja ma nie tylko OPISYWAĆ projekt, ale UCZYĆ pojęć od podstaw,
szczególnie bazodanowych. Pisz prostym językiem, z analogiami, tłumacz KAŻDE
pojęcie zanim go użyjesz. Odwołuj się do KONKRETNEGO kodu z tego repo
(nazwy plików, funkcji, fragmenty SQL), nie do abstrakcji.

Utwórz folder `docs/` i trzy pliki Markdown PO POLSKU:

--- docs/01_przewodnik_po_projekcie.md ---
Widok „z lotu ptaka". Zawiera:
- Co system robi i po co (1 akapit).
- Diagram przepływu danych słowny: API (OWM / Open-Meteo) → kolektor
  (api_client → db) → SQLite → dashboard (data_loader → views). Wyjaśnij każdy krok.
- Rola każdego pliku/modułu (tabelka: plik → za co odpowiada).
- Jak działa kolektor (scheduler.py, co N minut, fallback OWM→Open-Meteo).
- Jak działa dashboard (3 zakładki, wspólny pasek filtrów w app.py).
- Jak uruchomić system krok po kroku (init_db → backfill/scheduler → streamlit).

--- docs/02_baza_danych_od_zera.md ---
NAJWAŻNIEJSZY dokument. Uczy bazy danych od podstaw na przykładzie TEGO projektu.
Każde pojęcie: najpierw „co to jest po ludzku", potem „gdzie to jest w naszym
kodzie". Pokryj:
- Co to relacyjna baza i tabela; po co SQLite (plik, bez serwera).
- Nasze 3 tabele (cities, measurements, collection_log) — co przechowują.
- Klucz główny (PRIMARY KEY) i AUTOINCREMENT — na przykładzie id.
- Klucz obcy (FOREIGN KEY) — city_id w measurements wskazuje na cities(id);
  po co rozdzielać dane na dwie tabele (normalizacja, brak powtarzania nazw miast).
- Więzy UNIQUE — UNIQUE(name,country) i UNIQUE(city_id,timestamp); jak dzięki
  temu działa odsiewanie duplikatów przez `INSERT OR IGNORE` (db.insert_measurement).
- Indeksy — czym jest indeks (analogia: skorowidz w książce), po co
  idx_measurements_city_time i idx_measurements_time, jak przyspieszają zapytania.
- Tryb WAL (PRAGMA journal_mode=WAL) — po co: dashboard czyta, kolektor pisze
  JEDNOCZEŚNIE bez blokady. Wyjaśnij prosto.
- Połączenie read-only dashboardu (file:...?mode=ro) — dlaczego dashboard nie
  powinien pisać do bazy.
- Rozbiór zapytań SQL z data_loader.py „po ludzku", linijka po linijce:
    * proste SELECT z JOIN cities↔measurements,
    * podzapytanie wybierające ostatni pomiar per miasto (load_latest_per_city)
      ORAZ nowa load_latest_per_city_filtered z Zadania 1,
    * agregacja: strftime(...) do „kubełkowania" czasu + GROUP BY + AVG
      (hourly/daily/weekly) — wyjaśnij jak strftime grupuje godziny/dni/tygodnie,
    * parametryzacja `?` — co to i DLACZEGO chroni przed SQL injection
      (na prostym przykładzie).
Na końcu sekcja „Najczęstsze pojęcia w 1 zdaniu" (mini-słowniczek).

--- docs/03_sciaga_na_obrone.md ---
Format pytanie → krótka, gotowa odpowiedź (2–5 zdań, język mówiony).
Pokryj co najmniej:
- Czemu SQLite, a nie PostgreSQL/MySQL? (lekkość, plik, brak serwera, skala projektu)
- Co to indeks i po co go założyliśmy?
- Jak obsługujecie duplikaty? (UNIQUE + INSERT OR IGNORE)
- Co to klucz obcy i normalizacja, czemu dwie tabele?
- Po co tryb WAL?
- Jak działa fallback OWM → Open-Meteo?
- Czemu wszystko w UTC?
- Jak liczona jest agregacja godzinowa/dzienna/tygodniowa?
- Skąd dane historyczne i czym jest reanaliza ERA5 — czy to POMIARY, czy MODEL?
  (ważne: Archive API = reanaliza ERA5, łączy obserwacje ze stacji/satelitów/
   radarów z modelem; bardzo blisko rzeczywistości, ale to nie surowy odczyt
   ze stacji — trzeba to umieć powiedzieć).
- Czemu dane są godzinowe, skoro kolektor chodzi co 30 min? (archiwum ERA5
  ma rozdzielczość godzinową; kolektor na żywo zbiera co 30 min).
- Jak filtruje dashboard i czemu filtry są wspólne dla wszystkich zakładek?
- Co się stanie, jak oba API padną? (miasto pomijane, log, brak crasha)

═══════════════════════════════════════════════════════════════
## KOLEJNOŚĆ I WERYFIKACJA
═══════════════════════════════════════════════════════════════
1. Zadanie 1 (kod) → uruchom pytest.
2. Jeśli dodałeś funkcję w data_loader, dorzuć krótki test w tests/test_db.py
   (in-memory SQLite, jak istniejące testy): 2 miasta + po 2 pomiary, sprawdź
   że load_latest_per_city_filtered z filtrem po city_id i zakresie dat zwraca
   poprawny „ostatni pomiar per miasto".
3. Zadanie 2 (kod) → uruchom pytest, podaj komendy do backfillu (nie odpalaj sam).
4. Zadanie 3 (docs) → na końcu, gdy kod jest już ustabilizowany, żeby dokumentacja
   opisywała stan faktyczny (nową funkcję mapy i tryb --start/--end).
5. Na koniec: `pytest tests/ -v` musi przechodzić w całości.