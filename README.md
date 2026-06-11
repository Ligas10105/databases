# Weather System — logowanie i wizualizacja danych pogodowych

Skrypt loguje godzinowe dane pogodowe dla 20 europejskich miast z API
Open-Meteo do bazy SQLite, a dashboard Streamlit prezentuje je w trzech
widokach: szeregi czasowe, analiza ilościowa i mapa — każdy z 6 filtrami.

## Wymagania

- Python 3.10+ (nic więcej — Open-Meteo nie wymaga klucza API)

## Instalacja (raz)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uruchomienie

```bash
# 1. Utworzenie bazy + wstawienie miast (raz)
python scripts/init_db.py

# 2. Zalogowanie danych — ostatnie 14 dni co godzinę
python scripts/backfill.py --days 14

# 3. Dashboard
streamlit run dashboard/app.py
```

Dashboard otworzy się pod http://localhost:8501.

Krok 2 można powtarzać (np. przed prezentacją) — skrypt dokleja tylko nowe
godziny, duplikaty pomija.

## Testy

```bash
pytest tests/ -v
```

## Dokumentacja

- `docs/01_przewodnik_po_projekcie.md` — jak system działa (architektura, przepływ danych)
- `docs/02_baza_danych_od_zera.md` — pojęcia bazodanowe wyjaśnione na kodzie projektu
- `docs/03_sciaga_na_obrone.md` — pytania i odpowiedzi na obronę
