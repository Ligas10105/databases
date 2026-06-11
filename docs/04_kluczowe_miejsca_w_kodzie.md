# Kluczowe miejsca w kodzie — filtry, agregacja, zapis i odczyt

Ten dokument to mapa „gdzie to dokładnie jest w kodzie". Dla każdego mechanizmu
(filtr, agregacja, zapis, odczyt) pokazujemy trzy rzeczy: **gdzie się zaczyna
w UI**, **gdzie zamienia się w zapytanie**, i **jaki SQL z tego wychodzi**.
Odnośniki `plik:linia` prowadzą do prawdziwego kodu (mogą się przesunąć przy
edycji, ale nazwy funkcji są stałe).

Pojęcia bazodanowe tłumaczy `02_baza_danych_od_zera.md`; tu skupiamy się na
„pokaż mi linijkę".

---

## 1. Droga filtra: od kliknięcia w sidebarze do SQL

Wszystkie filtry przechodzą tę samą trasę:

```
sidebar (app.py)  ──►  jeden słownik `filters`  ──►  _build_where(filters)  ──►  warunki ORM  ──►  SQL WHERE
```

1. **`dashboard/app.py`, `_build_sidebar()`** rysuje widżety i pakuje ich
   wartości w jeden słownik `filters` (`app.py:111`).
2. Ten sam słownik trafia do **wszystkich trzech zakładek** (`app.py:138-143`)
   — dlatego wykresy, statystyki i mapa filtrują identycznie.
3. **`dashboard/data_loader.py`, `_build_where(filters)`** (`data_loader.py:80`)
   zamienia słownik na listę warunków ORM (`conds`), wspólną dla
   `load_measurements` i `load_latest_per_city_filtered`.

Słownik `filters` budowany w `app.py:111`:

```python
return {
    "start": start_iso,                     # zakres dat — początek (ISO UTC)
    "end": end_iso,                         # zakres dat — koniec
    "city_ids": selected_city_ids,          # wybrane miasta (lista id)
    "parameter": parameter,                 # parametr (temp/wilgotność/...)
    "value_min": value_min,                 # zakres wartości — dół
    "value_max": value_max,                 # zakres wartości — góra
    "weather_conditions": selected_conditions,  # warunki pogodowe
    "aggregation": aggregation,             # raw / daily / weekly
}
```

---

## 2. Sześć filtrów — po kolei

Dla każdego: **(A)** widżet w sidebarze, **(B)** warunek w `_build_where`,
**(C)** wynikowy fragment SQL.

### Filtr 1 — zakres dat

**(A)** `app.py:50` — `st.sidebar.date_input("Date range", ...)`; daty zamieniane
na ISO UTC w `app.py:102-107` (`start_iso`, `end_iso`).

**(B)** `data_loader.py:90-93`:
```python
if filters.get("start"):
    conds.append(Measurement.timestamp >= filters["start"])
if filters.get("end"):
    conds.append(Measurement.timestamp <= filters["end"])
```

**(C)** `... WHERE m.timestamp >= ? AND m.timestamp <= ?`
(timestampy to tekst ISO, więc porównanie `>=`/`<=` działa jak sortowanie
alfabetyczne — dlatego trzymamy je w UTC, patrz dok 02).

### Filtr 2 — wybór miast

**(A)** `app.py:61` — `st.sidebar.multiselect("Cities", ...)`. Etykiety
„Warsaw, PL" mapowane na `id` w `app.py:60`, wynik to lista `city_ids`.

**(B)** `data_loader.py:96-99`:
```python
city_ids = filters.get("city_ids")
if city_ids:
    city_ids = list(city_ids)
    if city_ids:
        conds.append(Measurement.city_id.in_(city_ids))
```

**(C)** `... WHERE m.city_id IN (?, ?, ?, ...)` — ORM sam rozpisuje listę na
odpowiednią liczbę parametrów (bezpiecznie, bez sklejania napisów).

### Filtr 3 — parametr

Parametr działa inaczej niż reszta: **nie jest warunkiem WHERE**, tylko wybiera,
**która kolumna** podlega filtrowi zakresu wartości (filtr 4) i jest rysowana.

**(A)** `app.py:68` — `st.sidebar.selectbox("Parameter", options=list(PARAM_COLUMNS.keys()))`.

**(B)** mapowanie nazwa → kolumna modelu, `data_loader.py:28` i `:56`:
```python
PARAM_COLUMNS = {
    "temperature": "temp_c", "feels_like": "feels_like_c",
    "humidity": "humidity_pct", "pressure": "pressure_hpa",
    "wind_speed": "wind_speed_ms", "clouds": "clouds_pct",
}

def _param_column(parameter: str):
    return getattr(Measurement, PARAM_COLUMNS.get(parameter, "temp_c"))
```
`PARAM_COLUMNS` jest też używane przez widoki (`views/*.py`) do wskazania,
którą kolumnę DataFrame rysować.

### Filtr 4 — zakres wartości

**(A)** `app.py:76` — `st.sidebar.slider("Value range", ...)`; granice suwaka
biorą się z `get_value_range()` (MIN/MAX kolumny w bazie, `data_loader.py:281`).

**(B)** `data_loader.py:87` + `:101-104` — `column` to kolumna wybrana przez
filtr 3:
```python
column = _param_column(filters.get("parameter", "temperature"))
...
if filters.get("value_min") is not None:
    conds.append(column >= filters["value_min"])
if filters.get("value_max") is not None:
    conds.append(column <= filters["value_max"])
```

**(C)** np. dla temperatury: `... WHERE m.temp_c >= ? AND m.temp_c <= ?`.

### Filtr 5 — poziom agregacji

To filtr, ale steruje **kształtem zapytania**, nie warunkiem WHERE — opisany
osobno w sekcji 3.

### Filtr 6 — warunki pogodowe

**(A)** `app.py:94` — `st.sidebar.multiselect("Weather conditions", ...)`;
dostępne wartości z `list_weather_conditions()` (`SELECT DISTINCT weather_main`).

**(B)** `data_loader.py:106-110`:
```python
conditions = filters.get("weather_conditions")
if conditions:
    conditions = list(conditions)
    if conditions:
        conds.append(Measurement.weather_main.in_(conditions))
```

**(C)** `... WHERE m.weather_main IN (?, ?, ...)`.

### Jak warunki są wstrzykiwane do zapytania

`_build_where` zwraca listę `conds`, a zapytanie ją rozpakowuje przez `.where(*conds)`
(`data_loader.py:149` dla trybu raw, `:178` dla agregacji). Pusta lista = brak
`WHERE` = wszystkie wiersze.

---

## 3. Agregacja (raw / daily / weekly)

Trzy poziomy. `raw` zwraca surowe pomiary; `daily`/`weekly` liczą średnie
w „kubełkach" czasu. (Świadomie **nie ma** „hourly" — źródło Open-Meteo jest już
godzinowe, więc wynik byłby identyczny z `raw`.)

**(A) Wybór w UI** — `app.py:87`:
```python
aggregation = st.sidebar.selectbox("Aggregation", options=["raw", "daily", "weekly"], index=0)
```

**(B) Rozgałęzienie zapytania** — `data_loader.py:148` (raw) vs `:153` (agregacja).
Tryb `raw` to zwykły `SELECT ... JOIN ... WHERE ... ORDER BY timestamp`
(`data_loader.py:130-150`).

Tryb agregowany — `data_loader.py:153-180`:
```python
bucket_fmt = {
    "hourly": "%Y-%m-%dT%H:00:00Z",   # zostawione w kodzie, nieużywane w UI
    "daily":  "%Y-%m-%dT00:00:00Z",
    "weekly": "%Y-W%W",
}[aggregation]
bucket = func.strftime(bucket_fmt, Measurement.timestamp).label("timestamp")
stmt = (
    select(
        City.id.label("city_id"), City.name.label("city"), ...,
        bucket,
        func.avg(Measurement.temp_c).label("temp_c"),
        func.avg(Measurement.feels_like_c).label("feels_like_c"),
        ...
    )
    .join(City, City.id == Measurement.city_id)
    .where(*conds)
    .group_by(City.id, func.strftime(bucket_fmt, Measurement.timestamp))
    .order_by(bucket.asc())
)
```

**(C) Wynikowy SQL** (daily):
```sql
SELECT c.id AS city_id, c.name AS city, ...,
       strftime('%Y-%m-%dT00:00:00Z', m.timestamp) AS timestamp,
       AVG(m.temp_c) AS temp_c, AVG(m.humidity_pct) AS humidity_pct, ...
FROM measurements m
JOIN cities c ON c.id = m.city_id
WHERE <warunki z _build_where>
GROUP BY c.id, strftime('%Y-%m-%dT00:00:00Z', m.timestamp)
ORDER BY timestamp ASC
```

Mechanizm: `strftime` przycina każdy timestamp do wspólnej etykiety
(np. wszystkie godziny 8 czerwca → `2026-06-08T00:00:00Z`), `GROUP BY` zbiera je
w grupy (miasto, etykieta), a `AVG` liczy średnią. Tygodniowa daje etykiety typu
`2026-W23`.

**Dostosowanie wykresu do agregacji** — `views/time_series.py:19-41`:
```python
aggregation = filters.get("aggregation", "raw")
x_label = {"weekly": "Week (ISO)", "daily": "Day (UTC)", "hourly": "Hour (UTC)"}.get(aggregation, "Time (UTC)")
# mało punktów na miasto (np. weekly) → linia bez markerów byłaby niewidoczna:
max_points = int(df.groupby("city")["timestamp"].nunique().max())
markers = max_points <= 31
fig = px.line(df, x="timestamp", y=column, color="city", markers=markers,
              labels={column: parameter, "timestamp": x_label},
              title=f"{parameter} over time ({aggregation})")
```
Tu rozwiązaliśmy dwa problemy: (1) tygodniowa z 1 punktem była niewidoczna
→ włączamy markery przy małej liczbie punktów; (2) oś X nie kłamie
→ etykieta zależy od poziomu agregacji.

---

## 4. Odczyt: połączenie read-only + pandas

Dashboard **tylko czyta**. Silnik tworzony w trybie read-only —
`data_loader.py:39`:
```python
@lru_cache(maxsize=None)
def _read_engine_cached(abs_path: str) -> Engine:
    return create_engine(f"sqlite:///file:{abs_path}?mode=ro&uri=true", future=True)
```
Każda funkcja odczytu wykonuje zapytanie ORM i oddaje `pandas.DataFrame`
(`pd.read_sql_query(stmt, conn)`), który widoki rysują. Konwersja tekstowego
timestampu na typ czasowy: `data_loader.py:186-187` (dla raw/daily; weekly
zostaje etykietą `2026-W23`).

Najważniejsze funkcje odczytu:
- `load_measurements` (`:115`) — wykresy i statystyki (raw lub agregacja),
- `load_latest_per_city_filtered` (`:230`) — mapa (najnowszy pomiar per miasto
  w ramach filtrów; podzapytanie z `MAX(timestamp)` + `GROUP BY city_id`),
- `list_cities` / `list_weather_conditions` / `get_value_range` — zasilają sidebar.

---

## 5. Zapis: „wstaw albo pomiń duplikat" (ORM)

**`collector/db.py`, `insert_measurement()`** (`db.py:71`):
```python
try:
    with session.begin_nested():        # SAVEPOINT — mała pod-transakcja
        session.add(measurement)
    return True                         # wszedł
except IntegrityError:
    return False                        # UNIQUE(city_id, timestamp) odrzucił duplikat
```
To odpowiednik `INSERT OR IGNORE`: duplikat (ta sama para miasto+godzina) jest
po cichu pomijany, a wycofuje się **tylko** ten jeden wiersz. Dlatego backfill
można odpalać wielokrotnie — patrz `scripts/backfill.py` (pętla po miastach,
`session.commit()` na końcu).

**Silnik zapisu z WAL i kluczami obcymi** — `db.py:39-48` (PRAGMA przy każdym
połączeniu: `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`).

---

## 6. Schemat = modele ORM

Definicja tabel (kolumny, klucz obcy, `UNIQUE`, indeksy) jest w
**`collector/models.py`** jako klasy `City`, `Measurement`, `CollectionLog`.
`scripts/init_db.py` tworzy z nich bazę przez `Base.metadata.create_all`.
Filtry i agregacje operują na atrybutach tych klas (`Measurement.timestamp`,
`Measurement.temp_c`, `Measurement.city_id`, `Measurement.weather_main`).

---

## Ściąga „gdzie co jest" (1 tabela)

| Mechanizm | UI (sidebar) | Logika / SQL |
|---|---|---|
| Zakres dat | `app.py:50` | `data_loader.py:90-93` |
| Miasta | `app.py:61` | `data_loader.py:96-99` |
| Parametr | `app.py:68` | `data_loader.py:28`, `:56` |
| Zakres wartości | `app.py:76` | `data_loader.py:101-104` |
| Agregacja | `app.py:87` | `data_loader.py:153-180`, widok `time_series.py:19-41` |
| Warunki pogodowe | `app.py:94` | `data_loader.py:106-110` |
| Wspólny `WHERE` | — | `data_loader.py:80` (`_build_where`) |
| Zapis (dedup) | — | `db.py:71` (`insert_measurement`) |
| Read-only | — | `data_loader.py:39` (`_read_engine`) |
| Schemat (ORM) | — | `collector/models.py` |
