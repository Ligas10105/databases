# Ściąga na obronę — pytania i gotowe odpowiedzi

Format: pytanie → odpowiedź do powiedzenia własnymi słowami (2–5 zdań).
Szczegóły i definicje: `docs/02_baza_danych_od_zera.md`.

---

**Jak realizujecie "logowanie danych ze źródła online do własnej bazy"?**
Skrypt `backfill.py` odpytuje API Open-Meteo dla 20 miast, normalizuje
odpowiedź (jednostki, kody pogody, czas UTC) i wstawia pomiary godzinowe do
naszej bazy SQLite, którą sami zaprojektowaliśmy (trzy tabele, klucze, indeksy).
Każdy przebieg jest odnotowany w tabeli `collection_log`. Skrypt można odpalać
wielokrotnie — dzięki ochronie przed duplikatami dokleja tylko nowe godziny.

**Czemu SQLite, a nie PostgreSQL/MySQL?**
PostgreSQL i MySQL to serwery bazodanowe — trzeba je zainstalować, skonfigurować
i utrzymywać jako osobny proces. SQLite to jeden plik na dysku i biblioteka
wbudowana w Pythona, zero administracji. Mój projekt to jedna maszyna, jeden
pisarz i kilkadziesiąt tysięcy wierszy — serwer bazodanowy byłby przerostem
formy.

**Używacie ORM-a? Jakiego i po co?**
Tak — SQLAlchemy. ORM (Object–Relational Mapping) to warstwa, która mapuje
tabele na klasy Pythona: `City`, `Measurement`, `CollectionLog` w
`collector/models.py` to jednocześnie definicja schematu (z nich tworzę bazę
przez `Base.metadata.create_all`) i obiekty, na których operuję. Zapis robię na
sesji ORM (`session.add(...)`), a zapytania dashboardu buduję funkcją
`select(...)` zamiast sklejać napisy SQL. Zyski: jedno źródło prawdy o
schemacie, automatyczna parametryzacja (ochrona przed SQL injection) i kod,
który czyta się obiektowo. SQL nadal rozumiem — ORM generuje go pod spodem
i potrafię pokazać, co dokładnie leci do bazy.

**Skąd dane — czy to pomiary, czy model?**
Z Open-Meteo, darmowego API bez klucza, które udostępnia dane narodowych służb
meteorologicznych. Parametr `past_days` zwraca ostatnie dni godzina po godzinie
z analiz modeli pogodowych — czyli z modelu, w który na bieżąco "wprasowywane"
są rzeczywiste obserwacje ze stacji, satelitów i radarów. To nie jest surowy
odczyt z termometru konkretnej stacji, ale rekonstrukcja bardzo bliska
rzeczywistości — i trzeba to umieć uczciwie powiedzieć.

**Czemu rozdzielczość godzinowa?**
Bo taką rozdzielczość udostępnia źródło — dane historyczne Open-Meteo są
godzinowe. Dla analiz pogodowych (trendy, rozkłady, porównania miast) to w
zupełności wystarcza, a dane są równomierne, więc agregacje dzienne/tygodniowe
liczą się uczciwie.

**Co to jest indeks i po co go założyliście?**
Indeks to posortowana struktura pomocnicza — jak skorowidz w książce: zamiast
kartkować całą tabelę, baza skacze od razu do właściwych wierszy. Mam dwa:
`idx_measurements_city_time` (city_id, timestamp) pod zapytania "pomiary tego
miasta po czasie" i "najnowszy pomiar miasta", oraz `idx_measurements_time`
pod filtrowanie po zakresie dat. Koszt to trochę miejsca i minimalnie wolniejszy
INSERT, ale odczyty dashboardu są dzięki temu natychmiastowe.

**Jak obsługujecie duplikaty?**
Dwuwarstwowo: w schemacie jest więz `UNIQUE(city_id, timestamp)` — baza sama
nie pozwoli zapisać dwóch pomiarów tego samego miasta o tej samej godzinie.
Wstawiam przez ORM w zagnieżdżonej transakcji (SAVEPOINT): jeśli więz odrzuci
duplikat, łapię `IntegrityError`, wycofuję tylko ten jeden wiersz i jadę dalej —
to odpowiednik `INSERT OR IGNORE`. Dzięki temu backfill można odpalać codziennie
i baza się nie zaśmieci — dokleja tylko nowe godziny.

**Co to klucz obcy i normalizacja — czemu dwie tabele?**
Klucz obcy to kolumna wskazująca na klucz główny innej tabeli — u mnie
`measurements.city_id` wskazuje na `cities.id`. Gdybym w każdym pomiarze
zapisywał nazwę i współrzędne miasta, powtarzałbym te same dane tysiące razy
i każda literówka groziłaby niespójnością. Normalizacja to zasada "każda
informacja zapisana raz": miasto jest w jednym wierszu `cities`, a pomiary
trzymają tylko jego numer. Przy odczycie skleja to JOIN.

**Po co kolumna `source`?**
To pochodzenie danych (data provenance): każdy rekord mówi, z jakiego źródła
przyszedł. U nas źródło jest jedno (`open_meteo`), ale dzięki tej kolumnie
system jest otwarty na kolejne — wystarczy wstawiać rekordy z inną etykietą
i można porównywać źródła jednym `GROUP BY source`.

**Po co tryb WAL?**
Żeby można było czytać i pisać jednocześnie: dashboard ma otwartą bazę, a ja
mogę w tym czasie dograć świeże dane backfillem — bez WAL-a pisarz blokowałby
czytelników i dashboard dostawałby błąd "database is locked". WAL (Write-Ahead
Logging) zapisuje zmiany najpierw do osobnego pliku-dziennika, więc czytelnicy
cały czas widzą spójny stan. Włącza się jedną komendą: `PRAGMA journal_mode=WAL`.

**Czemu dashboard łączy się z bazą w trybie read-only?**
Bo jedynym pisarzem ma być backfill — dashboard tylko wyświetla. Otwieram
połączenie z `mode=ro`, więc nawet błąd w kodzie dashboardu fizycznie nie może
zmodyfikować danych. To zasada minimalnych uprawnień: proces dostaje tylko
takie prawa, jakich potrzebuje.

**Czemu wszystko w UTC?**
Bo miasta są w różnych strefach czasowych i do tego dochodzi czas letni/zimowy
— porównywanie pomiarów w czasach lokalnych to proszenie się o błędy
(np. duplikaty albo dziury przy zmianie czasu). Trzymam wszystko w jednym,
jednoznacznym czasie UTC jako tekst ISO 8601, który dobrze się sortuje
alfabetycznie. Na czas lokalny przeliczać można dopiero przy wyświetlaniu.

**Jak liczona jest agregacja dzienna/tygodniowa?**
W SQL-u (generowanym przez ORM): funkcja `strftime` przycina timestamp do
wspólnej etykiety — np. dla agregacji dziennej każdy pomiar z 8 czerwca dostaje
etykietę `2026-06-08T00:00:00Z` — potem `GROUP BY` zbiera wiersze o tej samej
parze (miasto, etykieta), a `AVG` liczy średnią w każdej grupie. Czyli "dzienna
temperatura Warszawy" to średnia ze wszystkich pomiarów Warszawy danego dnia.
Agregacji godzinowej świadomie nie dajemy — źródło jest już godzinowe, więc
byłaby identyczna z `raw`.

**Jakie macie filtry i czemu są wspólne dla wszystkich widoków?**
Sześć: zakres dat, wybór miast, parametr, zakres wartości, poziom agregacji
i warunki pogodowe (wymagane było min. 5 na widok). Pasek boczny w `app.py`
buduje jeden słownik filtrów i przekazuje go do wszystkich trzech zakładek,
a klauzulę WHERE buduje jedna wspólna funkcja `_build_where` w
`data_loader.py`. Dzięki temu wszystkie widoki pokazują dokładnie ten sam
wycinek danych, a logika filtrowania istnieje w jednym miejscu, nie w trzech
kopiach.

**Jak mapa wybiera, co pokazać?**
Funkcja `load_latest_per_city_filtered` najpierw przepuszcza pomiary przez te
same filtry co pozostałe zakładki, a potem podzapytaniem z `MAX(timestamp)`
i `GROUP BY city_id` wybiera dla każdego miasta najnowszy pasujący pomiar.
Marker, popup i heatmapa korzystają z tego samego przefiltrowanego zbioru,
więc mapa zawsze zgadza się z wykresami.

**Co chroni was przed SQL injection?**
Parametryzacja — i robi ją za mnie ORM. Buduję zapytania przez `select(...)`
z warunkami w stylu `City.name == wartosc`, a SQLAlchemy samo zamienia wartości
na parametry (`?`) i podaje je osobnym kanałem niż treść zapytania. Dane —
choćby zawierały apostrofy czy `DROP TABLE` — zawsze są traktowane jak zwykły
napis, nigdy jak kod.

**Co się stanie, jak API padnie podczas logowania?**
Nic dramatycznego: miasto, dla którego zapytanie się nie powiodło, jest
pomijane w tym przebiegu, a podsumowanie (ile miast OK, ile padło) trafia do
tabeli `collection_log`. Przy następnym uruchomieniu backfill uzupełni braki —
duplikaty godzin, które już są, odsieje opisany wyżej mechanizm "wstaw albo
pomiń" (SAVEPOINT + `IntegrityError` w ORM).

**Skąd na mapie "najnowsze" dane, skoro to dane historyczne?**
`past_days` w Open-Meteo zwraca dane aż do bieżącej godziny, więc wystarczy
odpalić backfill tuż przed prezentacją i "najnowszy pomiar" jest z ostatniej
godziny. Skrypt dodatkowo odcina godziny z przyszłości — API dorzuca prognozę
na resztę doby, a my logujemy wyłącznie to, co już się wydarzyło.
