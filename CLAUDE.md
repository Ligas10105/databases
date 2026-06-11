# CLAUDE.md — Weather System (logowanie + wizualizacja danych pogodowych)

## Czym jest ten projekt

Projekt zaliczeniowy (broniony w Polsce). Wymagania uczelni:
- logowanie danych z wybranego źródła online do własnej bazy,
- system wizualizacji: prezentacja statystyczna + min. jedna z kategorii
  (time series / analiza ilościowa / analiza przestrzenna) — mamy wszystkie trzy,
- każdy sposób prezentacji z min. 5 filtrami — mamy 6 wspólnych.

Architektura (celowo prosta, bez kolektora na żywo):
- `scripts/backfill.py` — logowanie danych: pobiera godzinową historię
  z Open-Meteo (`past_days`, bez klucza API) i wstawia do SQLite;
  odpalany wielokrotnie dokleja tylko nowe godziny (INSERT OR IGNORE).
- `scripts/init_db.py` — schemat (cities, measurements, collection_log
  + 2 indeksy) i wstawienie 20 miast z `config.yaml`.
- `collector/db.py` — warstwa zapisu (WAL, insert_measurement, log_collection_run).
- `dashboard/` — Streamlit: `app.py` (sidebar z 6 filtrami + 3 zakładki),
  `data_loader.py` (CAŁY SQL dashboardu, wspólny `_build_where`),
  `views/{time_series,quantitative,spatial}.py`.
- `tests/` — pytest: `test_db.py`, `test_backfill.py`.

## Stack

Python 3.10+, sqlite3, requests, PyYAML, Streamlit, Plotly, Folium
(+ streamlit-folium), pandas, pytest. Środowisko: `.venv/bin/python`
(systemowego `python` brak).

## Uruchomienie

```bash
python scripts/init_db.py
python scripts/backfill.py --days 14
streamlit run dashboard/app.py
```

## Zasady

1. **Minimalne, chirurgiczne zmiany** — nie zmieniaj architektury bez prośby.
2. **Komentarze i dokumentacja PO POLSKU** (projekt oddawany w Polsce);
   UI dashboardu po angielsku.
3. **Wszystkie timestampy w UTC** — ISO 8601 z `Z`, jako TEXT.
4. **Duplikaty**: UNIQUE(city_id, timestamp) + INSERT OR IGNORE.
5. **Ścieżka bazy z config.yaml** (`database.path`), nigdy na sztywno.
6. **Dashboard czyta read-only** (`file:...?mode=ro`); jedynym pisarzem jest backfill.
7. **Nie commituj `data/` ani `.env`** (są w .gitignore).
8. Po każdej zmianie kodu: `pytest tests/ -v` musi przechodzić w całości.
9. Przy zmianach w SQL/architekturze aktualizuj `docs/01..03_*.md` —
   dokumentacja uczy autora pojęć bazodanowych i musi opisywać stan faktyczny.
