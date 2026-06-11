# Ściąga na 1 stronę — Weather System (do wydruku)

**Co to jest:** logowanie godzinowych danych pogodowych z Open-Meteo do własnej
bazy SQLite (przez ORM) + dashboard Streamlit z 3 widokami i 6 filtrami.
Spełnia wymagania: *źródło online → własna baza* + *statystyka + 3 kategorie
wizualizacji (time series / ilościowa / przestrzenna)* + *≥5 filtrów na widok*.

**Przepływ:** Open-Meteo API → `backfill.py` (ORM) → SQLite (`data/weather.db`)
→ `data_loader.py` (read-only, `select()`) → `views/*` → Streamlit.

**Uruchomienie:**
```bash
python scripts/init_db.py            # schemat z modeli + 20 miast
python scripts/backfill.py --days 60 # historia (max 92 dni)
streamlit run dashboard/app.py
```

---

### Baza — 3 tabele (schemat = modele ORM w `collector/models.py`)
- **cities** — 20 miast: `id, name, country, lat, lon`; `UNIQUE(name, country)`.
- **measurements** — pomiary: `city_id→cities.id`, `timestamp`, temp/wilgotność/...;
  `UNIQUE(city_id, timestamp)` + 2 indeksy.
- **collection_log** — log przebiegów backfillu.

**Klucze pojęcia:** PRIMARY KEY = unikalny id; FOREIGN KEY = `city_id` wskazuje
na `cities.id`; **normalizacja** = nazwa miasta zapisana raz; indeks = „skorowidz".

---

### ORM (SQLAlchemy) — co robi i gdzie
Mapuje tabelę↔klasę, wiersz↔obiekt; zapytania piszemy `select()`, ORM generuje SQL.
- **Modele** = schemat → `collector/models.py`
- **Engine** (połączenie, WAL) → `db.py:41`; **read-only** → `data_loader.py:45`
- **Session** (zapis) → `db.py`, `backfill.py`
- **`select()`** (odczyt) → `data_loader.py`
- Zyski: jedno źródło schematu, **auto-parametryzacja = brak SQL injection**, czytelność.

---

### 6 filtrów (UI w `app.py` → warunek w `data_loader.py:_build_where`)
| Filtr | UI | Warunek ORM → SQL |
|---|---|---|
| Zakres dat | `app.py:50` | `timestamp >= ? AND <= ?` |
| Miasta | `app.py:61` | `city_id IN (...)` |
| Parametr | `app.py:68` | wybór kolumny (`PARAM_COLUMNS`) |
| Zakres wartości | `app.py:76` | `<kolumna> >= ? AND <= ?` |
| Agregacja | `app.py:87` | kształt zapytania (niżej) |
| Warunki pogodowe | `app.py:94` | `weather_main IN (...)` |

Wspólny słownik `filters` → wszystkie 3 zakładki filtrują identycznie
(`_build_where`, `data_loader.py:80`).

---

### Agregacja: raw / daily / weekly  (`data_loader.py:153`)
`strftime(format, timestamp)` przycina czas do etykiety → `GROUP BY` → `AVG`.
- daily `'%Y-%m-%dT00:00:00Z'` → wszystkie godziny dnia w 1 kubełku
- weekly `'%Y-W%W'` → `2026-W23`
- **brak „hourly"** — źródło jest już godzinowe, byłoby = raw.
Wykres: markery włączają się przy ≤31 pkt/miasto (by weekly było widoczne),
oś X zależna od agregacji (`time_series.py:19`).

---

### Duplikaty (anty-zaśmiecanie) — `db.py:71`
`UNIQUE(city_id, timestamp)` + zapis przez ORM: `session.begin_nested()` (SAVEPOINT)
→ przy duplikacie `IntegrityError` → wycofuje **tylko ten wiersz**.
= odpowiednik `INSERT OR IGNORE`; backfill można odpalać wielokrotnie.

---

### Zasady techniczne (gotowe odpowiedzi)
- **WAL** (`PRAGMA journal_mode=WAL`) — dashboard czyta, backfill pisze naraz, bez „database is locked".
- **Read-only** (`mode=ro`) — dashboard fizycznie nie zapisze; jedyny pisarz = backfill.
- **UTC wszędzie** — ISO 8601 z `Z` jako TEXT; dobrze się sortuje, brak problemów ze strefami.
- **Źródło** — Open-Meteo (`past_days`, bez klucza); to reanaliza modelu z obserwacjami, nie surowy termometr.
- **Czemu SQLite** — jeden plik, bez serwera, skala projektu; PostgreSQL byłby przerostem.
- **SQL injection** — ORM parametryzuje automatycznie (wartości osobnym kanałem niż treść SQL).

---

### Mapa plików
`models.py` (schemat) · `db.py` (zapis/silnik) · `init_db.py` (tworzy bazę) ·
`backfill.py` (logowanie) · `data_loader.py` (cały odczyt) ·
`app.py` (sidebar+zakładki) · `views/{time_series,quantitative,spatial}.py` ·
`tests/` (pytest). Pełne dokumenty: `docs/01`–`docs/05`.
