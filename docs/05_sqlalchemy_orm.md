# SQLAlchemy (ORM) — co to jest, co robi i gdzie go używamy

Ten dokument tłumaczy, **czym jest SQLAlchemy**, **co konkretnie dla nas robi**
i **w których linijkach kodu** każdy element występuje. To uzupełnienie:
`02_baza_danych_od_zera.md` uczy pojęć SQL, `04_kluczowe_miejsca_w_kodzie.md`
pokazuje filtry/agregacje — tutaj skupiamy się na samej bibliotece.

---

## 1. Co to jest SQLAlchemy i ORM (po ludzku)

**SQLAlchemy** to najpopularniejsza w Pythonie biblioteka do pracy z bazami SQL.
Używamy jej jako **ORM** (Object–Relational Mapping, mapowanie
obiektowo-relacyjne). ORM to tłumacz między dwoma światami:

- świat bazy: **tabele i wiersze**,
- świat Pythona: **klasy i obiekty**.

Zamiast pisać SQL z palca, opisujemy tabelę jako klasę (np. `City`), a wiersz
staje się obiektem tej klasy. Zapytania budujemy funkcją `select(...)`, a
SQLAlchemy **sama generuje SQL** i go wykonuje. Pod spodem i tak działa zwykłe
SQLite — ORM to warstwa wygody i bezpieczeństwa nad nim.

**Po co nam to (4 konkretne zyski):**
1. **Jedno źródło prawdy o schemacie** — tabele opisane raz, jako klasy
   (`collector/models.py`); z nich tworzymy bazę.
2. **Automatyczna parametryzacja** — wartości nigdy nie są sklejane z tekstem
   SQL, więc z urzędu jesteśmy odporni na SQL injection.
3. **Kod czytelny obiektowo** — `Measurement.temp_c >= 10` zamiast ręcznych
   napisów i osobnej listy parametrów.
4. **Przenośność** — ten sam kod działałby na PostgreSQL/MySQL po zmianie
   jednego adresu połączenia (my zostajemy przy SQLite).

---

## 2. Cztery filary SQLAlchemy w naszym projekcie

| Filar | Co robi | Gdzie |
|---|---|---|
| **Modele (Declarative)** | klasy = definicja tabel/schematu | `collector/models.py` |
| **Engine** | połączenie z plikiem bazy (+ PRAGMA/tryb ro) | `collector/db.py:41`, `dashboard/data_loader.py:45` |
| **Session** | „rozmowa" z bazą przy zapisie (dodaj/commit) | `collector/db.py`, `scripts/backfill.py`, `scripts/init_db.py` |
| **`select()`** | budowanie zapytań odczytu | `dashboard/data_loader.py` |

---

## 3. Modele — `collector/models.py`

Tu klasy stają się tabelami. Importy SQLAlchemy — `models.py:17` i `:26`:
```python
from sqlalchemy import Float, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
```

**Klasa bazowa** (`models.py:29`) — wszystkie modele po niej dziedziczą; trzyma
rejestr tabel (`Base.metadata`):
```python
class Base(DeclarativeBase):
    ...
```

**Model = tabela** (`models.py:50`, fragment `Measurement`):
```python
class Measurement(Base):
    __tablename__ = "measurements"                       # nazwa tabeli
    __table_args__ = (
        UniqueConstraint("city_id", "timestamp", name="uq_measurements_city_ts"),  # więz UNIQUE
        Index("idx_measurements_city_time", "city_id", "timestamp"),               # indeks złożony
        Index("idx_measurements_time", "timestamp"),                               # indeks
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # klucz główny
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), nullable=False)   # klucz obcy
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    temp_c: Mapped[float | None] = mapped_column(Float)                             # kolumna opcjonalna
    ...
    source: Mapped[str | None] = mapped_column(Text, server_default=text("'open_meteo'"))  # DEFAULT w DDL

    city: Mapped["City"] = relationship(back_populates="measurements")              # powiązanie z City
```

Co robi który element:
- **`__tablename__`** — nazwa tabeli w bazie.
- **`mapped_column(...)`** — definicja kolumny. `Integer`/`Float`/`Text` to typ,
  `primary_key=True` = klucz główny, `nullable=False` = NOT NULL.
- **`Mapped[int]` / `Mapped[int | None]`** — adnotacja typu Pythona; `| None`
  mówi, że kolumna może być pusta (NULL).
- **`ForeignKey("cities.id")`** — klucz obcy: `city_id` wskazuje na `cities.id`.
- **`UniqueConstraint(...)`** — więz UNIQUE (nasz mechanizm anty-duplikatowy na
  parze `city_id, timestamp`).
- **`Index(...)`** — indeks przyspieszający odczyty.
- **`server_default=text("'open_meteo'")`** — wartość domyślna zapisana w DDL
  (`DEFAULT 'open_meteo'`).
- **`relationship(...)`** — wygodne powiązanie obiektowe (z obiektu `City`
  można sięgnąć po jego pomiary i odwrotnie); nie tworzy kolumny.

> **Dla obrony:** klasy `City`, `Measurement`, `CollectionLog` to **cały schemat**
> bazy. Nie ma osobnego pliku z `CREATE TABLE` — te `CREATE TABLE` generuje
> SQLAlchemy z tych klas (patrz sekcja 5).

---

## 4. Engine — połączenie z bazą

**Engine** to obiekt, który wie, jak się połączyć z konkretną bazą.

**Silnik do zapisu** (z trybem WAL i kluczami obcymi) — `db.py:41-51`:
```python
engine = create_engine(f"sqlite:///{db_path}", echo=echo, future=True)

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")      # czytanie i pisanie naraz
    cur.execute("PRAGMA foreign_keys=ON;")       # egzekwowanie kluczy obcych
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.close()
```
- **`create_engine("sqlite:///...")`** — adres bazy; `sqlite:///` = sterownik
  SQLite. Zmiana tego adresu = zmiana bazy (stąd przenośność ORM).
- **`@event.listens_for(engine, "connect")`** — „hak": SQLAlchemy uruchamia tę
  funkcję przy każdym nowym połączeniu, my ustawiamy w niej PRAGMA.

**Silnik do odczytu** (read-only, dla dashboardu) — `data_loader.py:45`:
```python
return create_engine(f"sqlite:///file:{abs_path}?mode=ro&uri=true", future=True)
```
`mode=ro` = tylko odczyt; dashboard fizycznie nie może nic zapisać.
`@lru_cache` (`data_loader.py:39`) sprawia, że silnik tworzymy raz na ścieżkę.

---

## 5. Session — zapis (backfill, init_db)

**Session** to „bieżąca rozmowa" z bazą: zbiera zmiany i wysyła je przy
`commit()`. Fabryki sesji — `db.py:54-61` (`sessionmaker`, `get_session`).

**Tworzenie schematu z modeli** — `scripts/init_db.py:34`:
```python
Base.metadata.create_all(engine)     # zamienia klasy-modele na CREATE TABLE ... + indeksy
```
To jest moment, w którym klasy z sekcji 3 stają się realnymi tabelami.

**Dodanie wiersza** — `scripts/init_db.py:44` i `:53`:
```python
session.add(City(name=..., country=..., lat=..., lon=...))   # obiekt → INSERT
...
count = session.execute(select(func.count()).select_from(City)).scalar_one()
```

**Zapis z odsiewaniem duplikatów (SAVEPOINT)** — `collector/db.py:71-86`:
```python
try:
    with session.begin_nested():     # SAVEPOINT — zagnieżdżona pod-transakcja
        session.add(measurement)
    return True                      # wszedł
except IntegrityError:               # UNIQUE odrzucił duplikat
    return False                     # wycofuje się TYLKO ten jeden wiersz
```
- **`session.add(obj)`** — zaplanuj wstawienie obiektu (INSERT).
- **`session.begin_nested()`** — SAVEPOINT; pozwala wycofać tylko ostatnią próbę
  zamiast całej transakcji (kluczowe, by jeden duplikat nie kasował wcześniej
  dodanych pomiarów w backfillu).
- **`IntegrityError`** — wyjątek SQLAlchemy rzucany, gdy złamany zostaje więz
  (u nas `UNIQUE(city_id, timestamp)`). To nasz odpowiednik `INSERT OR IGNORE`.

`scripts/backfill.py` używa tego w pętli: dla każdego miasta `session.add`
przez `insert_measurement`, a na końcu `session.commit()`.

---

## 6. `select()` — odczyt (dashboard)

Cały odczyt dashboardu to zapytania `select()` na modelach.
Importy — `data_loader.py:16-17`:
```python
from sqlalchemy import Engine, create_engine, func, null, select
from sqlalchemy.orm import aliased
```

**Proste zapytanie** — `list_cities`, `data_loader.py:62-66`:
```python
stmt = select(City.id, City.name, City.country, City.lat, City.lon).order_by(City.name)
with _read_engine(db_path).connect() as conn:
    return pd.read_sql_query(stmt, conn)     # wynik prosto do pandas
```

**JOIN + WHERE + ORDER BY** — `load_measurements` (tryb raw), `data_loader.py:131-150`:
```python
select(City.id.label("city_id"), City.name.label("city"), ..., Measurement.temp_c, ...)
    .join(City, City.id == Measurement.city_id)
    .where(*conds)                            # conds z _build_where (filtry)
    .order_by(Measurement.timestamp.asc())
```

**Agregacja: funkcje SQL** — `data_loader.py:158-179`:
```python
bucket = func.strftime(bucket_fmt, Measurement.timestamp).label("timestamp")  # strftime(...)
...
func.avg(Measurement.temp_c).label("temp_c")    # AVG(...)
null().label("weather_main")                    # NULL AS weather_main
...
.group_by(City.id, func.strftime(bucket_fmt, Measurement.timestamp))          # GROUP BY
```
- **`func.xxx(...)`** — dowolna funkcja SQL: `func.avg`, `func.strftime`,
  `func.max`, `func.min`, `func.count`. SQLAlchemy wstawia ją 1:1 do SQL.
- **`.label("...")`** — aliasy kolumn (`AS city`) — ustalają nazwy kolumn
  w DataFrame, których oczekują widoki.
- **`null()`** — literał `NULL` w wyniku.

**Podzapytania i aliasy** — `load_latest_per_city_filtered`, `data_loader.py:241-272`:
```python
latest = (
    select(Measurement.city_id.label("cid"), func.max(Measurement.timestamp).label("max_ts"))
    .where(*conds)
    .group_by(Measurement.city_id)
    .subquery()                               # podzapytanie jako tabelka pomocnicza
)
... .join(latest, (latest.c.cid == Measurement.city_id) & (latest.c.max_ts == Measurement.timestamp))
```
- **`.subquery()`** — zamienia `select()` w podzapytanie, do którego można
  dołączyć JOIN-em; kolumny dostępne przez `latest.c.<nazwa>`.
- **`.scalar_subquery()`** (`data_loader.py:199`) — podzapytanie zwracające
  jedną wartość (użyte w `load_latest_per_city`).
- **`aliased(Measurement)`** (`data_loader.py:201`) — drugi „egzemplarz" tej
  samej tabeli w jednym zapytaniu (gdy łączymy measurements same ze sobą).

**Wykonanie zapytania** — dwa sposoby:
- `pd.read_sql_query(stmt, conn)` — wynik od razu jako DataFrame (większość funkcji).
- `conn.execute(stmt)` + `.scalar_one()` / `.one()` — gdy chcemy surowe wiersze,
  np. `get_value_range`, `data_loader.py:283-285`:
  ```python
  stmt = select(func.min(column), func.max(column)).where(column.is_not(None))
  row = conn.execute(stmt).one()
  ```

---

## 7. Pojęcie ORM → co generuje w SQL

| Kod SQLAlchemy | Wynikowy SQL |
|---|---|
| `class Measurement(Base): __tablename__="measurements"` | `CREATE TABLE measurements (...)` |
| `mapped_column(Integer, primary_key=True)` | `id INTEGER PRIMARY KEY` |
| `ForeignKey("cities.id")` | `REFERENCES cities(id)` |
| `UniqueConstraint("city_id","timestamp")` | `UNIQUE(city_id, timestamp)` |
| `Index("idx_...", "city_id","timestamp")` | `CREATE INDEX idx_... ON ...` |
| `select(City.name).where(City.country=="PL")` | `SELECT name FROM cities WHERE country = ?` |
| `.join(City, City.id==Measurement.city_id)` | `JOIN cities ON cities.id = measurements.city_id` |
| `Measurement.city_id.in_([1,2])` | `city_id IN (?, ?)` |
| `func.avg(Measurement.temp_c)` | `AVG(temp_c)` |
| `func.strftime(fmt, Measurement.timestamp)` | `strftime(?, timestamp)` |
| `.group_by(...)` / `.order_by(...)` | `GROUP BY ...` / `ORDER BY ...` |
| `session.add(obj)` + `commit()` | `INSERT INTO ...` |
| `begin_nested()` + `IntegrityError` | odpowiednik `INSERT OR IGNORE` |

---

## 8. Mini-słowniczek SQLAlchemy

- **ORM** — mapowanie tabela↔klasa, wiersz↔obiekt.
- **Declarative / `DeclarativeBase`** — styl, w którym tabelę opisujemy jako klasę.
- **Model** — klasa-tabela (`City`, `Measurement`, `CollectionLog`).
- **`mapped_column`** — definicja kolumny w modelu.
- **Engine** — obiekt połączenia z bazą (`create_engine`).
- **Session** — sesja zapisu: zbiera zmiany, `commit()` je wysyła.
- **`select()`** — budowniczy zapytania odczytu.
- **`func`** — dostęp do funkcji SQL (`avg`, `max`, `strftime`, `count`).
- **`.label()`** — alias kolumny (`AS`).
- **`.subquery()` / `.scalar_subquery()`** — zapytanie użyte wewnątrz innego.
- **`aliased()`** — drugi egzemplarz tej samej tabeli w zapytaniu.
- **SAVEPOINT (`begin_nested`)** — pod-transakcja, którą można wycofać osobno.
- **`IntegrityError`** — wyjątek przy złamaniu więzu (np. UNIQUE).
- **`Base.metadata.create_all`** — utworzenie wszystkich tabel z modeli.

---

## 9. Ściąga „gdzie SQLAlchemy" (1 tabela)

| Element SQLAlchemy | Plik:linia |
|---|---|
| Import ORM (Declarative) | `collector/models.py:17`, `:26` |
| Definicje tabel (modele) | `collector/models.py:33`, `:50`, `:78` |
| `create_engine` (zapis + WAL) | `collector/db.py:41` |
| Hak PRAGMA (`event.listens_for`) | `collector/db.py:43` |
| `create_engine` (read-only) | `dashboard/data_loader.py:45` |
| `sessionmaker` / `Session` | `collector/db.py:54`, `:59` |
| `Base.metadata.create_all` | `scripts/init_db.py:34` |
| `session.add` (INSERT) | `scripts/init_db.py:44`, `collector/db.py:83` |
| SAVEPOINT + `IntegrityError` | `collector/db.py:82-85` |
| `select()` (odczyt) | `dashboard/data_loader.py:62`, `:131`, `:160`, `:250` |
| `func.avg` / `func.strftime` / `func.max` | `dashboard/data_loader.py:158`, `:167`, `:243` |
| `.subquery()` / `aliased()` | `dashboard/data_loader.py:247`, `:201` |
| `pd.read_sql_query` (do pandas) | `dashboard/data_loader.py:66`, `:184` |
