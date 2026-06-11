# CLAUDE.md — Weather System (logowanie + wizualizacja danych pogodowych)

## Czym jest ten projekt

Projekt zaliczeniowy (broniony w Polsce). Wymagania uczelni:
- logowanie danych z wybranego źródła online do własnej bazy,
- system wizualizacji: prezentacja statystyczna + min. jedna z kategorii
  (time series / analiza ilościowa / analiza przestrzenna) — mamy wszystkie trzy,
- każdy sposób prezentacji z min. 5 filtrami — mamy 6 wspólnych.

Cały dostęp do bazy idzie przez ORM (SQLAlchemy) — modele mapują tabele na klasy.

Architektura (celowo prosta, bez kolektora na żywo):
- `collector/models.py` — modele ORM (SQLAlchemy): `City`, `Measurement`,
  `CollectionLog` = definicja schematu (tabele, FK, UNIQUE, 2 indeksy).
- `scripts/backfill.py` — logowanie danych: pobiera godzinową historię
  z Open-Meteo (`past_days`, bez klucza API) i wstawia do SQLite przez sesję ORM;
  odpalany wielokrotnie dokleja tylko nowe godziny (SAVEPOINT + IntegrityError,
  odpowiednik INSERT OR IGNORE).
- `scripts/init_db.py` — tworzy schemat z modeli (`Base.metadata.create_all`)
  i wstawia 20 miast z `config.yaml`.
- `collector/db.py` — warstwa zapisu (ORM): `get_engine` (WAL), sesje,
  `insert_measurement`, `log_collection_run`.
- `dashboard/` — Streamlit: `app.py` (sidebar z 6 filtrami + 3 zakładki),
  `data_loader.py` (CAŁY odczyt dashboardu — zapytania ORM `select()`,
  read-only; wspólny `_build_where`),
  `views/{time_series,quantitative,spatial}.py`.
- `tests/` — pytest: `test_db.py`, `test_backfill.py`.

## Stack

Python 3.10+, SQLAlchemy (ORM) na SQLite (sqlite3), requests, PyYAML,
Streamlit, Plotly, Folium (+ streamlit-folium), pandas, pytest.
Środowisko: `.venv/bin/python` (systemowego `python` brak).

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
4. **Duplikaty**: UNIQUE(city_id, timestamp); wstawianie przez ORM
   (SAVEPOINT `begin_nested` + przechwycenie `IntegrityError`) = INSERT OR IGNORE.
5. **Ścieżka bazy z config.yaml** (`database.path`), nigdy na sztywno.
6. **Dashboard czyta read-only** (`file:...?mode=ro`); jedynym pisarzem jest backfill.
7. **Nie commituj `data/` ani `.env`** (są w .gitignore).
8. Po każdej zmianie kodu: `pytest tests/ -v` musi przechodzić w całości.
9. Przy zmianach w SQL/architekturze aktualizuj `docs/01..03_*.md` —
   dokumentacja uczy autora pojęć bazodanowych i musi opisywać stan faktyczny.
