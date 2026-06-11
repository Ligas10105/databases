# Ściąga na obronę — pytania i gotowe odpowiedzi

Format: pytanie → odpowiedź do powiedzenia własnymi słowami (2–5 zdań).
Szczegóły i definicje: `docs/02_baza_danych_od_zera.md`.

---

**Czemu SQLite, a nie PostgreSQL/MySQL?**
PostgreSQL i MySQL to serwery bazodanowe — trzeba je zainstalować, skonfigurować
i utrzymywać jako osobny proces. SQLite to jeden plik na dysku i biblioteka
wbudowana w Pythona, zero administracji. Mój projekt to jedna maszyna, jeden
pisarz i kilkadziesiąt tysięcy wierszy — serwer bazodanowy byłby przerostem
formy. A współbieżność, której potrzebuję (dashboard czyta, gdy kolektor pisze),
SQLite zapewnia trybem WAL.

**Co to jest indeks i po co go założyliście?**
Indeks to posortowana struktura pomocnicza — jak skorowidz w książce: zamiast
kartkować całą tabelę, baza skacze od razu do właściwych wierszy. Mam dwa:
`idx_measurements_city_time` (city_id, timestamp) pod zapytania "pomiary tego
miasta po czasie" i "najnowszy pomiar miasta", oraz `idx_measurements_time`
pod filtrowanie po zakresie dat. Koszt to trochę miejsca i minimalnie wolniejszy
INSERT, ale odczyty dashboardu są dzięki temu natychmiastowe.

**Jak obsługujecie duplikaty?**
Dwuwarstwowo: w schemacie jest więz `UNIQUE(city_id, timestamp)` — baza sama
nie pozwoli zapisać dwóch pomiarów tego samego miasta o tej samej godzinie —
a wstawiam przez `INSERT OR IGNORE`, więc duplikat jest po cichu pomijany
zamiast rzucać błąd. Dzięki temu backfill i kolektor można odpalać wielokrotnie
i baza się nie zaśmieci.

**Co to klucz obcy i normalizacja — czemu dwie tabele?**
Klucz obcy to kolumna wskazująca na klucz główny innej tabeli — u mnie
`measurements.city_id` wskazuje na `cities.id`. Gdybym w każdym pomiarze
zapisywał nazwę i współrzędne miasta, powtarzałbym te same dane tysiące razy
i każda literówka groziłaby niespójnością. Normalizacja to zasada "każda
informacja zapisana raz": miasto jest w jednym wierszu `cities`, a pomiary
trzymają tylko jego numer. Przy odczycie skleja to JOIN.

**Po co tryb WAL?**
U mnie jednocześnie działają dwa procesy: kolektor pisze, dashboard czyta.
W domyślnym trybie SQLite pisarz blokuje czytelników. WAL (Write-Ahead Logging)
zapisuje zmiany najpierw do osobnego pliku-dziennika, więc czytelnicy cały czas
widzą spójny stan bazy i nikt na nikogo nie czeka. Włączam go jedną komendą:
`PRAGMA journal_mode=WAL`.

**Jak działa fallback OWM → Open-Meteo?**
Dla każdego miasta najpierw pytam OpenWeatherMap; jeśli funkcja zwróci None
(błąd HTTP, limit, brak klucza), pytam Open-Meteo, które nie wymaga klucza.
Obie funkcje zwracają ten sam znormalizowany słownik, więc reszta systemu nie
widzi różnicy — tylko kolumna `source` w bazie mówi, skąd przyszedł rekord.
System nie crashuje od padu jednego API.

**Czemu wszystko w UTC?**
Bo miasta są w różnych strefach czasowych i do tego dochodzi czas letni/zimowy
— porównywanie pomiarów w czasach lokalnych to proszenie się o błędy
(np. duplikaty albo dziury przy zmianie czasu). Trzymam wszystko w jednym,
jednoznacznym czasie UTC jako tekst ISO 8601, który dobrze się sortuje
alfabetycznie. Na czas lokalny przeliczać można dopiero przy wyświetlaniu.

**Jak liczona jest agregacja godzinowa/dzienna/tygodniowa?**
W SQL-u: funkcja `strftime` przycina timestamp do wspólnej etykiety — np. dla
agregacji dziennej każdy pomiar z 8 czerwca dostaje etykietę
`2026-06-08T00:00:00Z` — potem `GROUP BY` zbiera wiersze o tej samej parze
(miasto, etykieta), a `AVG` liczy średnią w każdej grupie. Czyli "dzienna
temperatura Warszawy" to średnia ze wszystkich pomiarów Warszawy danego dnia.

**Skąd dane historyczne i czym jest reanaliza ERA5 — to pomiary czy model?**
Historię pobieram skryptem backfill z Historical Weather API Open-Meteo, które
serwuje dane ERA5. ERA5 to reanaliza: ani czysty pomiar, ani czysta symulacja
— model pogodowy, do którego "wprasowano" miliony rzeczywistych obserwacji ze
stacji, satelitów i radarów, żeby odtworzyć spójny stan atmosfery godzina po
godzinie dla całego globu. Jest bardzo blisko rzeczywistości, ale trzeba uczciwie
powiedzieć: to nie jest surowy odczyt z termometru konkretnej stacji. W bazie
te rekordy mają `source = 'open_meteo_archive'`, więc łatwo je odróżnić od
danych zbieranych na żywo.

**Czemu dane historyczne są godzinowe, skoro kolektor chodzi co 30 minut?**
Bo to dwa różne źródła o różnej rozdzielczości: archiwum ERA5 udostępnia dane
co godzinę i gęściej się nie da, a kolektor na żywo odpytuje API co 30 minut.
W bazie jedno i drugie trzymam w tej samej tabeli — kolumna `source` mówi,
co skąd pochodzi.

**Jak filtruje dashboard i czemu filtry są wspólne dla wszystkich zakładek?**
Pasek boczny w `app.py` buduje jeden słownik filtrów (zakres dat, miasta,
parametr, zakres wartości, warunki pogodowe, agregacja) i przekazuje go do
wszystkich trzech zakładek. Klauzulę WHERE z tych filtrów buduje jedna wspólna
funkcja `_build_where` w `data_loader.py`, z której korzystają i wykresy,
i mapa. Dzięki temu wszystkie widoki pokazują dokładnie ten sam wycinek danych
— a logika filtrowania istnieje w jednym miejscu, nie w trzech kopiach.

**Co się stanie, jak oba API padną?**
Nic dramatycznego: miasto jest pomijane w tym przebiegu, licznik błędów rośnie,
a po przejściu wszystkich miast podsumowanie (ile OK, ile padło, jakie źródła)
trafia do tabeli `collection_log`. Program działa dalej i spróbuje ponownie za
30 minut. W danych będzie po prostu dziura — wykres ją pokaże, nic się nie
wysypie.

**Czemu dashboard łączy się z bazą w trybie read-only?**
Bo jedynym pisarzem ma być kolektor — dashboard tylko wyświetla. Otwieram
połączenie z `mode=ro`, więc nawet błąd w kodzie dashboardu fizycznie nie może
zmodyfikować danych. To zasada minimalnych uprawnień: proces dostaje tylko
takie prawa, jakich potrzebuje.

**Co chroni was przed SQL injection?**
Parametryzacja: w zapytaniach nigdy nie wklejam wartości do tekstu SQL-a, tylko
piszę `?`, a wartości podaję osobną listą. Baza dostaje polecenie i dane dwoma
różnymi kanałami, więc dane — choćby zawierały apostrofy czy `DROP TABLE` —
zawsze są traktowane jak zwykły napis, nigdy jak kod.

**Jak mapa wybiera, co pokazać?**
Funkcja `load_latest_per_city_filtered` najpierw przepuszcza pomiary przez te
same filtry co pozostałe zakładki, a potem podzapytaniem z `MAX(timestamp)`
i `GROUP BY city_id` wybiera dla każdego miasta najnowszy pasujący pomiar.
Marker, popup i heatmapa korzystają z tego samego przefiltrowanego zbioru,
więc mapa zawsze zgadza się z wykresami.
