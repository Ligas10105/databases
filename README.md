# Weather System — zbieranie i wizualizacja danych pogodowych

Kolektor pobiera co 30 minut pogodę dla 20 europejskich miast
(OpenWeatherMap, z fallbackiem do Open-Meteo), zapisuje do SQLite,
a dashboard Streamlit pokazuje wykresy, statystyki i mapę.

## Wymagania

- Python 3.10+
- (opcjonalnie) klucz API OpenWeatherMap — bez niego system korzysta z Open-Meteo

## Instalacja (raz)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# opcjonalnie: klucz OWM
echo "OWM_API_KEY=twoj_klucz" > .env
```

## Uruchomienie

```bash
# 1. Utworzenie bazy + wstawienie miast (raz)
python scripts/init_db.py

# 2. Zasilenie historią ~2 tygodni (archiwum ERA5 bywa opóźnione 2-5 dni,
#    więc --end ustaw kilka dni wstecz)
python scripts/backfill.py --start 2026-05-28 --end 2026-06-08

# 3. Kolektor na żywo — zostaw włączony (terminal 1)
python -m collector.scheduler

# 4. Dashboard (terminal 2)
streamlit run dashboard/app.py
```

Dashboard otworzy się pod http://localhost:8501.

## Testy

```bash
pytest tests/ -v
```

## Dokumentacja

- `docs/01_przewodnik_po_projekcie.md` — jak system działa (architektura, przepływ danych)
- `docs/02_baza_danych_od_zera.md` — pojęcia bazodanowe wyjaśnione na kodzie projektu
- `docs/03_sciaga_na_obrone.md` — pytania i odpowiedzi na obronę
