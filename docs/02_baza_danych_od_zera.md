# Baza danych od zera — na przykładzie tego projektu

Ten dokument uczy pojęć bazodanowych od podstaw. Każde pojęcie najpierw
tłumaczymy "po ludzku", a potem pokazujemy, **gdzie dokładnie jest w naszym
kodzie**. Wszystkie przykłady SQL pochodzą z tego repozytorium.

---

## 1. Co to jest relacyjna baza danych i tabela

**Po ludzku:** relacyjna baza danych to zbiór tabel, które wyglądają jak
arkusze Excela: wiersze to pojedyncze rekordy (np. jeden pomiar pogody),
kolumny to cechy (temperatura, wilgotność...). "Relacyjna" znaczy, że tabele
mogą się do siebie **odwoływać** — np. pomiar "wie", którego miasta dotyczy,
bo trzyma odnośnik do tabeli miast.

**SQL** to język, którym rozmawiamy z bazą: `SELECT` czyta dane, `INSERT`
wstawia, `CREATE TABLE` zakłada tabelę.

> **ORM (SQLAlchemy).** W tym projekcie SQL-a zwykle **nie piszemy ręcznie** —
> używamy biblioteki SQLAlchemy, która jest **ORM-em** (Object–Relational
> Mapping, mapowanie obiektowo-relacyjne). ORM pozwala opisać tabele jako klasy
> Pythona (np. klasa `City` ↔ tabela `cities`) i operować na obiektach zamiast
> klepać napisy SQL. Zapytania budujemy funkcją `select(...)`, a ORM tłumaczy je
> na SQL i wykonuje. **Pojęcia z tego dokumentu nadal obowiązują** — to dokładnie
> ten SQL, który ORM generuje pod spodem; pokazujemy go, bo to jego trzeba
> rozumieć. Modele (definicje tabel) są w `collector/models.py`.

### Po co SQLite?

Większość baz (PostgreSQL, MySQL) to osobne **serwery** — programy działające
w tle, z którymi łączymy się przez sieć, które trzeba zainstalować,
skonfigurować i utrzymywać. **SQLite to po prostu jeden plik na dysku**
(u nas `data/weather.db`) plus biblioteka wbudowana w Pythona (`import sqlite3`
— zero instalacji). Dla projektu z jednym komputerem, 20 miastami i kilkoma
tysiącami wierszy to idealny wybór: cała "administracja bazą" to skopiowanie
pliku.

**Gdzie w kodzie:** `scripts/init_db.py` tworzy plik bazy i tabele
(wywołując `Base.metadata.create_all` na modelach ORM);
ścieżka do pliku jest w `config.yaml` (`database.path: data/weather.db`).
Sam dostęp do bazy idzie przez SQLAlchemy (ORM), ale silnikiem pod spodem
nadal jest wbudowany w Pythona sterownik `sqlite3` — dochodzi tylko jedna
zależność (`pip install SQLAlchemy`).

---

## 2. Nasze trzy tabele

Schemat (czyli definicje tabel) jest w jednym miejscu: modele ORM w
`collector/models.py` (klasy `City`, `Measurement`, `CollectionLog`).
`init_db.py` zamienia te klasy na tabele przez `Base.metadata.create_all`.
Poniżej dla jasności pokazujemy **SQL, który ORM z tych modeli generuje** —
np. klasie `City` z polami `id`, `name`, `country`, `lat`, `lon` odpowiada:

### `cities` — słownik miast (20 wierszy)

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

Każde miasto ma numer (`id`), nazwę, kraj i współrzędne (do mapy).

### `measurements` — pomiary (rośnie cały czas)

```sql
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL REFERENCES cities(id),
    timestamp TEXT NOT NULL,
    temp_c REAL,
    ...
    source TEXT DEFAULT 'open_meteo',
    UNIQUE(city_id, timestamp)
);
```

Jeden wiersz = jeden odczyt pogody dla jednego miasta o jednej godzinie.
Zamiast nazwy miasta trzymamy `city_id` — numer wiersza z tabeli `cities`
(dlaczego — patrz punkt o kluczu obcym). Kolumna `source` mówi, skąd przyszedł
rekord (u nas: `open_meteo`). To dobra praktyka zwana *pochodzeniem danych*
(data provenance) — gdyby kiedyś doszło drugie źródło, od razu widać, co skąd
jest, i można porównywać źródła jednym `GROUP BY source`.

### `collection_log` — dziennik logowania danych

Po każdym przebiegu backfillu zapisujemy: kiedy, ile miast się udało, ile
padło, ile wierszy weszło. To nie są dane pogodowe, tylko "czarna skrzynka" do
diagnozowania problemów. Wpisy robi `log_collection_run()` w `collector/db.py`.

---

## 3. Klucz główny (PRIMARY KEY) i AUTOINCREMENT

**Po ludzku:** klucz główny to kolumna, która **jednoznacznie identyfikuje
wiersz** — jak PESEL dla człowieka. Dwa wiersze nigdy nie mają tego samego
klucza głównego. `AUTOINCREMENT` znaczy: nie wymyślaj numerów sam, baza nada
kolejne (1, 2, 3...) automatycznie przy każdym `INSERT`.

**Gdzie w kodzie:** każda nasza tabela zaczyna się od
`id INTEGER PRIMARY KEY AUTOINCREMENT`. Wstawiając miasto w `init_db.py`
podajemy tylko nazwę/kraj/współrzędne — `id` nadaje baza.

---

## 4. Klucz obcy (FOREIGN KEY) i normalizacja — po co dwie tabele?

**Po ludzku:** klucz obcy to kolumna, która **wskazuje na klucz główny innej
tabeli**. U nas: `measurements.city_id REFERENCES cities(id)` — każdy pomiar
trzyma numer swojego miasta.

Moglibyśmy w każdym pomiarze zapisywać `"Warsaw", "PL", 52.23, 21.01`...
ale przy 20 miastach × 48 pomiarów dziennie × 14 dni to ~13 000 powtórzeń
tych samych napisów. Problemy: marnowanie miejsca, a co gorsza — gdyby trzeba
było poprawić literówkę w nazwie miasta, trzeba by zmienić tysiące wierszy
(i łatwo o niespójność: pół bazy "Warsaw", pół "Warszawa").

Rozdzielenie danych tak, żeby **każda informacja była zapisana tylko raz**,
nazywa się **normalizacją**. Nazwa i współrzędne Warszawy są w bazie w JEDNYM
wierszu tabeli `cities`; pomiary trzymają tylko numer `city_id = 1`.
Gdy potrzebujemy nazwy przy pomiarze — łączymy tabele JOIN-em (punkt 9).

**Gdzie w kodzie:** klucz obcy deklaruje `ForeignKey("cities.id")` w modelu
`Measurement` (`collector/models.py`); tłumaczenie "nazwa → id" robi
`get_city_id()` w `collector/db.py`; pilnowanie poprawności odnośników włącza
`PRAGMA foreign_keys=ON` ustawiane przy każdym połączeniu silnika w
`get_engine()`.

---

## 5. Więzy UNIQUE i odsiewanie duplikatów

**Po ludzku:** więz (ang. *constraint*) to reguła, której baza pilnuje **sama**
— odrzuci `INSERT`, który ją łamie. `UNIQUE(a, b)` znaczy: kombinacja wartości
w kolumnach `a` i `b` nie może się powtórzyć.

Mamy dwa takie więzy:

- `UNIQUE(name, country)` w `cities` — nie da się dwa razy wstawić
  "Warsaw, PL". Dzięki temu `init_db.py` można odpalać wielokrotnie.
- `UNIQUE(city_id, timestamp)` w `measurements` — jedno miasto nie może mieć
  dwóch pomiarów o tej samej godzinie. **To nasz mechanizm anty-duplikatowy.**

Jak to działa w praktyce? `insert_measurement()` w `collector/db.py` realizuje
tę samą logikę co dawne `INSERT OR IGNORE`, ale środkami ORM:

```python
try:
    with session.begin_nested():   # SAVEPOINT — mała "pod-transakcja"
        session.add(Measurement(city_id=city_id, **values))
    return True                    # zapis się udał — wiersz wszedł
except IntegrityError:
    return False                   # UNIQUE odrzucił duplikat — pomijamy
```

Idea: próbujemy dodać obiekt w obrębie **zagnieżdżonej transakcji** (SAVEPOINT).
Jeśli wstawienie złamie więz UNIQUE, baza zgłasza `IntegrityError`; my go
łapiemy i zwracamy `False`, a SAVEPOINT jest wycofywany — **wycofuje się tylko
ten jeden wiersz**, wcześniej dodane w sesji pomiary zostają nienaruszone.
Gdy wiersz wejdzie poprawnie — zwracamy `True`. Efekt jest identyczny jak
`INSERT OR IGNORE`: backfill można odpalić pięć razy z rzędu i baza się nie
zaśmieci — drugi i kolejne przebiegi zobaczą same duplikaty.

---

## 6. Indeksy — skorowidz w książce

**Po ludzku:** żeby znaleźć w książce hasło "fotosynteza", nie czytasz całej
książki — zaglądasz do skorowidzu na końcu, który mówi "strona 142". **Indeks
w bazie to dokładnie to**: posortowana struktura pomocnicza, dzięki której baza
nie musi przeglądać całej tabeli (tzw. *full table scan*), tylko skacze prosto
do właściwych wierszy.

Nasze indeksy (zadeklarowane w modelu `Measurement` przez `Index(...)`,
co ORM tłumaczy na):

```sql
CREATE INDEX idx_measurements_city_time ON measurements(city_id, timestamp);
CREATE INDEX idx_measurements_time      ON measurements(timestamp);
```

- `idx_measurements_city_time` przyspiesza pytania typu "pomiary miasta 5
  posortowane po czasie" i "najnowszy pomiar miasta 5" — czyli dokładnie to,
  co robią `load_measurements` i `load_latest_per_city*` w `data_loader.py`.
- `idx_measurements_time` przyspiesza filtrowanie po samym zakresie dat
  (`timestamp >= ? AND timestamp <= ?`), gdy pytamy o wszystkie miasta naraz.

Koszt: indeks zajmuje miejsce i odrobinę spowalnia `INSERT` (trzeba dopisać
wpis do skorowidzu). Przy naszej skali (backfill wstawia kilka tysięcy wierszy
w parę sekund) to pomijalne, a odczyty dashboardu są dzięki temu natychmiastowe.

---

## 7. Tryb WAL — czytanie i pisanie jednocześnie

**Problem:** do bazy może jednocześnie sięgać **dwóch klientów**: backfill
(pisze, gdy odświeżamy dane) i dashboard (czyta przy każdym przeładowaniu
strony) — np. dogrywasz świeże godziny tuż przed prezentacją, nie zamykając
dashboardu. W domyślnym trybie SQLite pisarz potrafi zablokować czytelników —
dashboard dostawałby błąd "database is locked".

**Rozwiązanie:** `PRAGMA journal_mode=WAL` (Write-Ahead Logging — "dziennik
z wyprzedzeniem"). Po ludzku: zamiast nadpisywać główny plik bazy, pisarz
dopisuje zmiany do osobnego pliku-dziennika (`weather.db-wal` — można go
zobaczyć w katalogu `data/`), a czytelnicy w tym czasie spokojnie czytają
ostatni spójny stan głównego pliku. Co jakiś czas dziennik jest scalany do
głównego pliku. Efekt: **czytanie i pisanie nie blokują się nawzajem**.

**Gdzie w kodzie:** `get_engine()` w `collector/db.py` rejestruje nasłuch
zdarzenia `connect` silnika SQLAlchemy, który wykonuje `PRAGMA journal_mode=WAL;`
przy każdym nowym połączeniu (z tego silnika korzysta i backfill, i `init_db.py`).

---

## 8. Połączenie tylko-do-odczytu w dashboardzie

`_read_engine()` w `dashboard/data_loader.py` tworzy silnik SQLAlchemy
otwierający bazę przez URI w trybie tylko-do-odczytu:

```python
create_engine(f"sqlite:///file:{abs_path}?mode=ro&uri=true")
```

`mode=ro` = *read-only*. Dashboard fizycznie **nie może** nic zapisać ani
zmienić — każda próba skończy się błędem. Po co?

1. **Podział ról:** jedynym pisarzem jest backfill. Mniej pisarzy = mniej
   konfliktów i prostsze rozumowanie o systemie.
2. **Bezpieczeństwo:** błąd w kodzie dashboardu (albo złośliwe dane w filtrze)
   nie ma prawa uszkodzić ani zmodyfikować danych.
3. To ta sama zasada co "minimalne uprawnienia": dajemy programowi tylko tyle
   praw, ile potrzebuje do działania.

---

## 9. Rozbiór zapytań SQL z `data_loader.py`

Wszystkie poniższe zapytania budujemy w `data_loader.py` **przez ORM** —
funkcją `select(...)` na modelach (`select(City.id, ..., Measurement.temp_c)
.join(City).where(*warunki).order_by(...)`). Pokazany niżej SQL to **to, co
SQLAlchemy z tych wyrażeń generuje** i faktycznie wysyła do bazy — rozumienie
tego SQL-a jest sednem projektu, więc rozbieramy go po kawałku.

### 9a. SELECT z JOIN — łączenie pomiarów z miastami

Serce `load_measurements` (tryb `raw`):

```sql
SELECT c.name AS city, c.country, c.lat, c.lon,
       m.timestamp, m.temp_c, ...
FROM measurements m
JOIN cities c ON c.id = m.city_id
WHERE m.timestamp >= ? AND m.timestamp <= ?
ORDER BY m.timestamp ASC
```

Linijka po linijce:
- `FROM measurements m` — bierzemy tabelę pomiarów; `m` to skrót (alias),
  żeby dalej pisać `m.temp_c` zamiast `measurements.temp_c`.
- `JOIN cities c ON c.id = m.city_id` — **doklej do każdego pomiaru wiersz
  miasta o pasującym id**. To jest odwrotność normalizacji: w bazie trzymamy
  tylko numer, a przy odczycie "skręcamy" pełny widok z nazwą i współrzędnymi.
- `WHERE ...` — przepuść tylko wiersze spełniające warunki (filtry).
- `ORDER BY m.timestamp ASC` — posortuj rosnąco po czasie (wykres liniowy
  potrzebuje punktów po kolei).
- `SELECT ... AS city` — wybierz kolumny; `AS` nadaje im czytelne nazwy
  w wyniku.

### 9b. Najnowszy pomiar per miasto — podzapytanie

`load_latest_per_city` (wariant bez filtrów):

```sql
SELECT c.name AS city, ..., m.timestamp, m.temp_c, ...
FROM cities c
LEFT JOIN measurements m ON m.id = (
    SELECT id FROM measurements
    WHERE city_id = c.id
    ORDER BY timestamp DESC
    LIMIT 1
)
```

**Podzapytanie** (zapytanie w nawiasie, w środku innego) wykonuje się dla
każdego miasta: "weź pomiary tego miasta, posortuj od najnowszego
(`DESC` = malejąco), weź pierwszy (`LIMIT 1`) i zwróć jego id". Zewnętrzne
zapytanie dokleja do miasta dokładnie ten jeden wiersz. `LEFT JOIN` (zamiast
zwykłego `JOIN`) oznacza: pokaż miasto **nawet jeśli nie ma żadnego pomiaru**
— wtedy kolumny pomiaru będą puste (NULL).

### 9c. `load_latest_per_city_filtered` — wersja z filtrami (mapa)

Nowsza funkcja, używana przez zakładkę Mapa — najnowszy pomiar per miasto,
ale **tylko spośród pomiarów spełniających filtry** z paska bocznego:

```sql
SELECT c.name AS city, ..., m.timestamp, m.temp_c, ...
FROM measurements m
JOIN cities c ON c.id = m.city_id
JOIN (
    SELECT m.city_id AS cid, MAX(m.timestamp) AS max_ts
    FROM measurements m
    WHERE <warunki z filtrów>
    GROUP BY m.city_id
) latest ON latest.cid = m.city_id AND latest.max_ts = m.timestamp
ORDER BY c.name
```

Czytamy od środka:
1. Podzapytanie `latest`: spośród pomiarów **przepuszczonych przez filtry**
   (zakres dat, wybrane miasta, zakres wartości, warunki pogodowe) policz dla
   każdego miasta (`GROUP BY m.city_id`) najpóźniejszy czas (`MAX(timestamp)`).
   Wynik to mini-tabelka: (id miasta, czas jego najnowszego pasującego pomiaru).
2. Zewnętrzny `JOIN ... ON latest.cid = m.city_id AND latest.max_ts = m.timestamp`
   — dla każdej pary z mini-tabelki znajdź pełny wiersz pomiaru.
3. Sztuczka: warunków filtra **nie trzeba powtarzać** na zewnątrz, bo więz
   `UNIQUE(city_id, timestamp)` gwarantuje, że para (miasto, czas) wskazuje
   dokładnie jeden wiersz — ten sam, który przeszedł filtry w podzapytaniu.

Warunki WHERE buduje wspólna funkcja `_build_where(filters)` — ta sama,
której używa `load_measurements`. Dzięki temu mapa, wykresy i statystyki
filtrują **identycznie** i nie ma dwóch kopii tej logiki do utrzymywania.

### 9d. Agregacja w czasie — strftime + GROUP BY + AVG

Gdy użytkownik wybierze agregację dzienną/tygodniową,
`load_measurements` zamiast surowych punktów liczy średnie w "kubełkach" czasu:

```sql
SELECT c.name AS city,
       strftime(?, m.timestamp) AS timestamp,   -- np. '%Y-%m-%dT00:00:00Z'
       AVG(m.temp_c) AS temp_c, ...
FROM measurements m
JOIN cities c ON c.id = m.city_id
GROUP BY c.id, strftime(?, m.timestamp)
```

Jak to działa:
- `strftime(format, timestamp)` **przycina** datę do wspólnej etykiety.
  Nasze timestampy to teksty ISO, np. `2026-06-08T14:30:00Z`. Format
  `'%Y-%m-%dT00:00:00Z'` zamienia każdą godzinę tego dnia na tę samą etykietę
  `2026-06-08T00:00:00Z` — wszystkie pomiary z 8 czerwca "wpadają do jednego
  kubełka". Analogicznie `'%Y-W%W'` kubełkuje po tygodniach (rok + numer
  tygodnia, np. `2026-W23`). Po godzinach (`'%Y-%m-%dT%H:00:00Z'`) **nie**
  agregujemy — dane ze źródła są już godzinowe, więc wynik byłby identyczny
  z `raw`.
- `GROUP BY` zbiera wiersze o tej samej parze (miasto, etykieta) w grupy.
- `AVG(...)` liczy średnią w każdej grupie. Czyli "dzienna temperatura
  Warszawy" = średnia ze wszystkich pomiarów Warszawy danego dnia.

### 9e. Parametryzacja — ochrona przed SQL injection

W całym projekcie wartości NIGDY nie są wklejane do SQL-a jako tekst — i tu ORM
pomaga "z urzędu". Pisząc warunek przez `select()`:

```python
select(City.id).where(City.name == "Warsaw", City.country == "PL")
```

SQLAlchemy **samo** zamienia stałe na parametry i generuje
`... WHERE name = ? AND country = ?`, podając wartości osobnym kanałem — nigdy
nie skleja ich z tekstem zapytania.

Dlaczego to ważne? Wyobraź sobie naiwną wersję:

```python
query = f"SELECT id FROM cities WHERE name = '{user_input}'"
```

Jeśli użytkownik wpisze `'; DROP TABLE measurements; --`, sklejony napis
stanie się **dwoma poleceniami**: niegroźnym SELECT-em i kasowaniem tabeli.
To jest atak **SQL injection** — dane użytkownika "wstrzykują się" w kod
zapytania. Przy parametryzacji `?` baza dostaje zapytanie i dane **osobnymi
kanałami**: wartość jest zawsze traktowana jako dana (zwykły napis), nigdy
jako fragment polecenia. Apostrofy i średniki w danych nic nie znaczą.
Bonus: parametryzacja załatwia też poprawne typy i kodowanie znaków.

W `_build_where()` widać to w praktyce — nawet listy (`Measurement.city_id
.in_(city_ids)`) ORM rozpisuje na bezpieczne `IN (?,?,?)` z wartościami podanymi
osobno. Pisząc przez ORM, praktycznie nie da się przypadkiem wkleić wartości do
tekstu SQL-a.

---

## 10. Najczęstsze pojęcia w 1 zdaniu (mini-słowniczek)

- **Tabela** — "arkusz" z danymi: wiersze to rekordy, kolumny to cechy.
- **Wiersz / rekord** — jeden obiekt, np. jeden pomiar pogody.
- **SQL** — język zapytań do bazy (SELECT/INSERT/CREATE...).
- **SQLite** — baza w jednym pliku, bez serwera, wbudowana w Pythona.
- **ORM (SQLAlchemy)** — mapowanie obiektowo-relacyjne: tabela ↔ klasa Pythona, wiersz ↔ obiekt; zapytania piszemy przez `select()`, a biblioteka generuje SQL.
- **Model** — klasa opisująca tabelę (u nas `City`, `Measurement`, `CollectionLog` w `collector/models.py`).
- **Klucz główny (PRIMARY KEY)** — kolumna jednoznacznie identyfikująca wiersz.
- **AUTOINCREMENT** — baza sama nadaje kolejne numery id.
- **Klucz obcy (FOREIGN KEY)** — kolumna wskazująca na klucz główny innej tabeli (`city_id` → `cities.id`).
- **Normalizacja** — projektowanie tabel tak, by każda informacja była zapisana tylko raz.
- **Więz (constraint)** — reguła, której baza pilnuje sama (NOT NULL, UNIQUE...).
- **UNIQUE** — zakaz powtórzeń wartości (u nas: pary city_id+timestamp).
- **INSERT OR IGNORE** — wstaw, a jeśli duplikat — po cichu pomiń (u nas realizowane przez ORM: SAVEPOINT + przechwycenie `IntegrityError`).
- **SAVEPOINT (transakcja zagnieżdżona)** — punkt wewnątrz transakcji, do którego można wycofać tylko część zmian; ORM otwiera go przez `session.begin_nested()`.
- **Indeks** — "skorowidz" przyspieszający wyszukiwanie kosztem odrobiny miejsca.
- **JOIN** — sklejenie wierszy z dwóch tabel po pasującym kluczu.
- **LEFT JOIN** — jak JOIN, ale zachowuje wiersze z lewej tabeli bez pary (z NULL-ami).
- **Podzapytanie** — zapytanie zagnieżdżone w innym zapytaniu.
- **GROUP BY + AVG** — podziel wiersze na grupy i policz np. średnią w każdej.
- **strftime** — formatowanie/przycinanie daty; u nas służy do kubełkowania czasu.
- **Parametryzacja `?`** — przekazywanie wartości osobno od SQL-a; chroni przed SQL injection.
- **SQL injection** — atak polegający na wstrzyknięciu kodu SQL przez dane wejściowe.
- **WAL** — tryb dziennika pozwalający czytać i pisać jednocześnie bez blokad.
- **Tryb read-only (`mode=ro`)** — połączenie, przez które nie da się nic zapisać.
- **Transakcja** — paczka operacji wykonywana "w całości albo wcale".
