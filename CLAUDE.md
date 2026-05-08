# CLAUDE.md — Data Logging & Visualization System

## Project Overview

Build a weather data collection and visualization system:
- Python script collects data from OpenWeatherMap API every 30 minutes
- Data stored in SQLite database
- Interactive Streamlit dashboard with Plotly charts and Folium maps

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Scheduler | APScheduler |
| Database | SQLite (sqlite3) |
| HTTP client | requests |
| Dashboard | Streamlit |
| Charts | Plotly |
| Maps | Folium + streamlit-folium |
| Config | python-dotenv + PyYAML |
| Testing | pytest |

---

## Project Structure

```
weather_system/
├── CLAUDE.md
├── .env                    # OWM_API_KEY=your_key_here (never commit)
├── .gitignore
├── requirements.txt
├── config.yaml             # cities list, intervals, thresholds
├── data/
│   └── weather.db          # SQLite database (auto-created)
├── collector/
│   ├── __init__.py
│   ├── api_client.py       # OpenWeatherMap + Open-Meteo clients
│   ├── db.py               # DB connection, insert functions
│   └── scheduler.py        # APScheduler job setup
├── dashboard/
│   ├── __init__.py
│   ├── app.py              # Streamlit entry point
│   ├── pages/
│   │   ├── time_series.py
│   │   ├── quantitative.py
│   │   └── spatial.py
│   └── data_loader.py      # Query functions for dashboard
├── scripts/
│   └── init_db.py          # One-time DB schema creation
└── tests/
    ├── test_api_client.py
    └── test_db.py
```

---

## Step 1: Environment Setup

Create `requirements.txt`:
```
requests
apscheduler
python-dotenv
pyyaml
streamlit
plotly
folium
streamlit-folium
pandas
pytest
```

Create `.env`:
```
OWM_API_KEY=your_api_key_here
```

Create `.gitignore`:
```
.env
data/
__pycache__/
*.pyc
.pytest_cache/
```

---

## Step 2: config.yaml

```yaml
collection:
  interval_minutes: 30
  cities:
    - {name: Warsaw, country: PL, lat: 52.23, lon: 21.01}
    - {name: Krakow, country: PL, lat: 50.06, lon: 19.94}
    - {name: Berlin, country: DE, lat: 52.52, lon: 13.40}
    - {name: Prague, country: CZ, lat: 50.08, lon: 14.44}
    - {name: Vienna, country: AT, lat: 48.21, lon: 16.37}
    - {name: Paris, country: FR, lat: 48.85, lon: 2.35}
    - {name: Amsterdam, country: NL, lat: 52.37, lon: 4.90}
    - {name: Brussels, country: BE, lat: 50.85, lon: 4.35}
    - {name: Budapest, country: HU, lat: 47.50, lon: 19.04}
    - {name: Bucharest, country: RO, lat: 44.43, lon: 26.10}
    - {name: Sofia, country: BG, lat: 42.70, lon: 23.32}
    - {name: Athens, country: GR, lat: 37.98, lon: 23.73}
    - {name: Rome, country: IT, lat: 41.90, lon: 12.49}
    - {name: Madrid, country: ES, lat: 40.42, lon: -3.70}
    - {name: Lisbon, country: PT, lat: 38.72, lon: -9.14}
    - {name: Stockholm, country: SE, lat: 59.33, lon: 18.07}
    - {name: Oslo, country: NO, lat: 59.91, lon: 10.75}
    - {name: Copenhagen, country: DK, lat: 55.68, lon: 12.57}
    - {name: Helsinki, country: FI, lat: 60.17, lon: 24.94}
    - {name: Zurich, country: CH, lat: 47.38, lon: 8.54}

api:
  openweathermap_base: https://api.openweathermap.org/data/2.5/weather
  open_meteo_base: https://api.open-meteo.com/v1/forecast
  timeout_seconds: 10
  retry_attempts: 3
```

---

## Step 3: Database Schema (scripts/init_db.py)

Create the following tables:

### `cities`
```sql
CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    UNIQUE(name, country)
);
```

### `measurements`
```sql
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL REFERENCES cities(id),
    timestamp TEXT NOT NULL,          -- ISO 8601 UTC
    temp_c REAL,
    feels_like_c REAL,
    temp_min_c REAL,
    temp_max_c REAL,
    humidity_pct INTEGER,
    pressure_hpa INTEGER,
    wind_speed_ms REAL,
    wind_deg INTEGER,
    clouds_pct INTEGER,
    weather_main TEXT,                -- "Rain", "Clear", "Clouds", etc.
    weather_desc TEXT,
    source TEXT DEFAULT 'owm',        -- 'owm' or 'open_meteo'
    UNIQUE(city_id, timestamp)
);
```

### `collection_log`
```sql
CREATE TABLE IF NOT EXISTS collection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    cities_ok INTEGER,
    cities_failed INTEGER,
    source_used TEXT,
    notes TEXT
);
```

Insert the 20 cities from config.yaml during init.

---

## Step 4: API Client (collector/api_client.py)

Implement two functions:

### `fetch_owm(city, api_key) -> dict | None`
- GET `https://api.openweathermap.org/data/2.5/weather?q={city[name]},{city[country]}&appid={api_key}&units=metric`
- Return normalized dict with keys matching DB columns
- Return `None` on any error (log the error)

### `fetch_open_meteo(city) -> dict | None`
- GET `https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&hourly=temperature_2m,relativehumidity_2m,pressure_msl,windspeed_10m,cloudcover`
- Used as fallback when OWM fails
- Return same normalized dict format

**Normalized dict format:**
```python
{
    "timestamp": "2024-01-15T12:00:00Z",  # UTC ISO string
    "temp_c": 5.2,
    "feels_like_c": 2.1,
    "temp_min_c": 3.0,
    "temp_max_c": 7.5,
    "humidity_pct": 78,
    "pressure_hpa": 1013,
    "wind_speed_ms": 4.5,
    "wind_deg": 270,
    "clouds_pct": 40,
    "weather_main": "Clouds",
    "weather_desc": "scattered clouds",
    "source": "owm"
}
```

---

## Step 5: DB Layer (collector/db.py)

Implement:
- `get_connection(db_path) -> sqlite3.Connection` — with WAL mode enabled
- `insert_measurement(conn, city_id, data_dict)` — use INSERT OR IGNORE (skip duplicates by timestamp)
- `log_collection_run(conn, cities_ok, cities_failed, source)` — insert into collection_log
- `get_city_id(conn, city_name, country) -> int`

---

## Step 6: Scheduler (collector/scheduler.py)

```python
# Entry point: python -m collector.scheduler
# Uses APScheduler BlockingScheduler
# Runs collect_all_cities() every 30 minutes
# On startup: runs immediately once, then schedules
# Logs each run result to collection_log table
```

`collect_all_cities()` logic:
1. Load config.yaml
2. For each city: try OWM first, fallback to Open-Meteo if OWM fails
3. Insert to DB
4. Log summary (ok/failed counts)
5. Print status to stdout

---

## Step 7: Streamlit Dashboard (dashboard/app.py)

### Layout
- Sidebar with **global filters** (apply to all pages):
  - Date range picker (default: last 7 days)
  - Multi-select cities
  - Parameter selector (temperature, humidity, pressure, wind_speed, clouds)
  - Value range slider (min/max)
  - Aggregation level (raw / hourly avg / daily avg / weekly avg)
  - Weather condition multi-select (Clear, Rain, Clouds, Snow, etc.)

- 3 pages via `st.tabs`:
  1. **Time Series**
  2. **Statistics**
  3. **Map**

### Page: Time Series (dashboard/pages/time_series.py)
- Plotly line chart: x=timestamp, y=selected parameter, color=city
- Apply all sidebar filters
- Show data table below chart (collapsible)

### Page: Statistics (dashboard/pages/quantitative.py)
- Summary table: min, max, mean, std per city for selected parameter
- Histogram: distribution of selected parameter across filtered data
- Box plot: one box per city, y=selected parameter

### Page: Map (dashboard/pages/spatial.py)
- Folium map (via streamlit-folium) centered on Europe
- Marker per city showing latest value of selected parameter
- HeatMap layer (folium.plugins.HeatMap) for selected parameter
- Popup on marker: city name, latest reading, timestamp

### Data Loader (dashboard/data_loader.py)
- All SQL queries live here, not in page files
- `load_measurements(db_path, filters_dict) -> pd.DataFrame`
- `load_latest_per_city(db_path) -> pd.DataFrame`
- Apply aggregation in SQL using strftime for grouping

---

## Step 8: Running the System

Two processes run concurrently:

```bash
# Terminal 1 — start collector (keep running 24/7)
python -m collector.scheduler

# Terminal 2 — start dashboard
streamlit run dashboard/app.py
```

---

## Step 9: Tests

`tests/test_api_client.py`:
- Mock `requests.get` to test OWM parser
- Test fallback logic when OWM returns 401/429

`tests/test_db.py`:
- Use in-memory SQLite (`:memory:`)
- Test insert + duplicate handling
- Test collection_log insert

Run with: `pytest tests/ -v`

---

## Important Rules

1. **Never hardcode the API key** — always read from `.env` via `python-dotenv`
2. **Always use UTC timestamps** — store as ISO string, display in local time in dashboard
3. **Handle duplicates gracefully** — use `INSERT OR IGNORE` with UNIQUE constraint
4. **Fallback silently** — if OWM fails, use Open-Meteo without crashing
5. **DB path from config** — never hardcode `data/weather.db`, read from config
6. **WAL mode on SQLite** — enables concurrent read (dashboard) + write (collector)

---

## Start Order

1. `pip install -r requirements.txt`
2. Add OWM API key to `.env`
3. `python scripts/init_db.py` — creates DB + inserts cities
4. `python -m collector.scheduler` — **start immediately, needs 2 weeks of data**
5. `streamlit run dashboard/app.py` — can run any time after DB is initialized
