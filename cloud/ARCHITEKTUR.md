# AHPT — Architektur der generischen Fassung

Stand 02.09.2026. Dieses Dokument entscheidet, wie aus der OWLP-Sonderloesung
ein Protokoll fuer beliebige Dienste wird. Es entscheidet auch, was dabei
ausdruecklich NICHT gebaut wird.

Die Referenzumsetzung im Elternverzeichnis (`tunnel.php`, `tunnel_agent.py`)
bleibt unberuehrt und in Betrieb. Was hier entsteht, laeuft daneben, mit
eigenen Dateinamen und eigenem Endpunkt.

---

## 1. Der eine Satz, an dem alles haengt

Die heutige Fassung ist sicher, weil sie dumm ist: `{typ, archiv, begriff}`,
drei feste Felder, alles andere abgewiesen. Wer sie generisch macht, gibt
diese Dummheit auf — und genau da liegt die Falle, die `Zukunftsmusik.txt`
unter 3B benennt.

Die Aufloesung ist, dass **zwei verschiedene Dinge dumm sind** und man nur
eines davon aufgeben darf:

- Der **Vermittler** ist dumm im Sinne von *inhaltsblind*. Er weiss nicht,
  was ein Dienst ist. Das darf er verlieren — er hat es nie gebraucht.
- Der **Agent** ist dumm im Sinne von *nicht ueberredbar*. Das darf er
  niemals verlieren.

Daraus der tragende Satz dieser Architektur, die woertliche
Verallgemeinerung von „es reist niemals eine URL":

> **Was geschehen kann, wird ausschliesslich zu Hause festgelegt.
> Von aussen kommt nur die Auswahl daraus.**

Heute waehlt `archiv` aus einer festen Zuordnung im Quelltext. Kuenftig
waehlt `dienst` aus einer festen Zuordnung in `config.toml`. Der Unterschied
ist, dass die Liste zu Daten wird — **nicht**, dass sie von aussen kommt.
Sie kommt nie von aussen. Kein Feld im Protokoll traegt eine Adresse, einen
Befehl, einen Pfad ausserhalb einer Wurzel oder eine Faehigkeit.

Wer dem Protokoll ein Feld hinzufuegt, in das eine Zieladresse passt, hat
AHPT in einen offenen Proxy ins Heimnetz verwandelt. Das ist der eine
Fehler, der alles kaputtmacht, und er ist hier baulich ausgeschlossen: es
gibt kein solches Feld.

---

## 2. Schichten

```
[ Browser ]                    relay-client.js
     |  POST Frage (PHP)  +  GET Antwort (statisch, kein PHP)
     v
[ Vermittler auf Webspace ]    relay.php  --  inhaltsblinder Briefkasten
     ^  GET Warteschlange (statisch, 304)  +  POST Antwort (PHP)
     |
[ Agent zu Hause ]             relay_agent.py  --  Transport, kennt keinen Dienst
     |  ruft auf
     v
[ Handler ]                    handler/kiwix.py, handler/datei.py, ...
     |
     v
[ Lokale Dienste ]             kiwix, Dateien, Sensorik, ...
```

Das Kostenmodell bleibt unveraendert und ist weiterhin der Grund fuer den
ganzen Aufbau: **zwei PHP-Aufrufe je Vorgang, beide kurz, beide
Schreibvorgaenge.** Jedes Warten laeuft ueber statische Dateien. Wer eine
Abhol-Aktion in `relay.php` einbaut, hat den Aufbau nicht verstanden.

---

## 3. Die Nachricht

Heute fest verdrahtet, kuenftig Daten — die Struktur ist dieselbe:

| heute | kuenftig | was es ist |
|---|---|---|
| `archiv` | `dienst` | welcher Handler, Name aus `config.toml` |
| `typ` | `aktion` | was er tun soll, aus der Weissliste des Handlers |
| `begriff` | `daten` | die Parameter, vom Handler geprueft |

```json
{ "dienst": "wiki", "aktion": "suche", "daten": { "begriff": "Wasser" } }
```

`dienst` und `aktion` muessen `^[a-z][a-z0-9_]{0,31}$` erfuellen. Nicht,
weil der Vermittler wuesste, welche es gibt — sondern damit sie unter keinen
Umstaenden in einen Dateinamen, einen Pfad oder eine Kopfzeile ausbrechen
koennen. Der Vermittler prueft die Form, nie den Sinn.

`daten` reicht er unverstanden durch. Er prueft daran nur Groesse und
JSON-Gueltigkeit. Bei eingeschalteter Verschluesselung ist es ohnehin nur
Rauschen (Abschnitt 8).

**Dateinamen enthalten niemals `dienst` oder `aktion`** — ausschliesslich
die Marke. Das ist heute so und bleibt so.

---

## 4. Der Umschlag

Damit Stueckelung und Verschluesselung spaeter nicht das Format brechen,
liegt um jede Nutzlast ein Umschlag mit festen Feldern:

```json
{
  "v": 1,
  "marke": "<32 Hexzeichen>",
  "teil": 0,
  "teile": 1,
  "krypto": "keine",
  "nutzlast": { }
}
```

`v` wird beim Empfang geprueft und bei Abweichung abgewiesen — nicht
ignoriert. Ein Agent, der eine unbekannte Protokollfassung stillschweigend
zu deuten versucht, ist ein Agent, der irgendwann etwas Falsches tut und es
nicht meldet.

---

## 5. Der Vermittler (`relay.php`)

**Was er behaelt** — jede einzelne Sicherheitsentscheidung der
Referenzumsetzung, unveraendert:

1. `<?php exit;` als erste Zeile von Geheimnis- und Zustandsdatei. Der
   Schutz steckt in der Datei, nicht in der Konfiguration. Begruendung im
   Eltern-README: eine `.htaccess` kann beim Hochladen verlorengehen, und
   ein ungeschuetztes Geheimnis funktioniert genauso gut wie ein
   geschuetztes — nichts faellt auf.
2. Atomares Schreiben ueber Temporaerdatei und `rename`.
3. Gesalzener Absenderkennwert, Salz je Installation. Ohne Salz waere ein
   SHA-256 ueber eine IPv4 eine Adresse in Verkleidung.
4. Deckel an jeder Stelle: Lebensdauer, Gesamtzahl, Zahl je Absender,
   Nutzlastgroesse.
5. `hash_equals` gegen das geteilte Geheimnis.
6. Getrennte Namensstaemme `frage_` und `antwort_` wegen `mod_speling`.
7. Jede Antwort traegt ihre eigene Marke im Inhalt.
8. Keine Abhol-Aktion. Nie.
9. Selbsttest-Aktion, die sagt, OB das Geheimnis lesbar ist, nie WELCHES.

**Was er verliert:** `ERLAUBTE_ARCHIVE`, `ERLAUBTE_TYPEN` und die Feldnamen
`typ`/`archiv`/`begriff`. Die Kopfzeile heisst `X-AHPT-Auth` statt
`X-OWLP-Tunnel`.

**Was er gewinnt:** Stueckelung, eine zweite Zustandsliste (Abschnitt 7)
und ein Protokollfeld `v`.

### Die Falle beim Nachbauen bleibt

**Nie die Zeichenfolge Fragezeichen-Groesserzeichen in einen `//`-Kommentar
schreiben.** Sie beendet den PHP-Modus auch dort. Am 02.09.2026 ging so ein
Kommentarrest als HTML hinaus; damit waren die Kopfzeilen gesendet und
`http_response_code()` wirkungslos — **jede** Antwort kam mit HTTP 200
zurueck, auch jede Ablehnung. In Blockkommentaren ist dieselbe Zeichenfolge
harmlos.

`tests/pruefe_relay_php.py` sucht genau danach, weil auf dem Entwicklungs-
rechner kein PHP liegt und `php -l` es sonst niemand fragt.

---

## 6. Stueckelung — und ein Fallstrick, der Daten still verfaelscht

Die Grenze von 64 KiB ist heute sichtbar vernarbt: `bearbeite()` kappt
Artikel und haengt „[Artikel hier gekuerzt]" an. Fuer Dateien, Bilder oder
PDF ist eine solche Grenze kein Schoenheitsfehler, sondern das Ende der
Brauchbarkeit. Also wird gestueckelt.

Der Agent legt zuerst die Stuecke ab, **danach** das Verzeichnis. Wer es
umgekehrt macht, veroeffentlicht ein Verzeichnis auf Dateien, die es noch
nicht gibt.

### Der Fallstrick

Fortlaufend nummerierte Stuecke heissen `..._0.json`, `..._1.json`,
`..._2.json` — **sie unterscheiden sich um genau ein Zeichen.** Das ist
exakt die Bedingung, unter der `mod_speling` am 02.09.2026 zugeschlagen
hat. Fehlt Stueck 3 noch, weil der Agent es gerade hochlaedt, antwortet
Apache nicht mit 404, sondern leitet per 301 auf Stueck 2 um. `fetch` folgt
stillschweigend, und der Browser setzt eine Datei zusammen, in der Stueck 2
zweimal steht.

Das Ergebnis ist keine Fehlermeldung, sondern eine **stillschweigend
verfaelschte Datei** — die schlimmste Sorte Fehler in diesem Projekt.

Drei Schranken dagegen, weil eine zu wenig ist — dieselbe Antwort wie
damals:

1. **Der Name traegt eine Unterscheidung.** Ein Stueck heisst
   `antwort_<marke>_<teil>_<4 Hexzeichen>.json`, wobei die vier Zeichen aus
   Marke und Stuecknummer abgeleitet sind. Damit liegen zwei benachbarte
   Stuecke nie eine Zeichenaenderung auseinander. Strukturell erledigt,
   nicht durch Konfiguration.
2. **Das Stueck traegt seine Nummer im Inhalt**, und der Client prueft sie
   gegen die erwartete. Ein umgeleitetes Stueck faellt auf.
3. **`CheckSpelling Off`** in der `.htaccess` — als dritte Schranke, nicht
   als erste, weil eine `.htaccess` ankommen muss und das nachweislich
   nicht immer tut.

Das Verzeichnis (`antwort_<marke>.json`) nennt Stueckzahl, Gesamtlaenge und
je Stueck den Dateinamen. Der Client raet keinen Namen; er liest ihn.

---

## 7. Aufraeumen — ein Leck im Bestand

`Zukunftsmusik.txt` warnt unter 3C vor Inodes und verlangt einen
„absolut fehlerfrei und aggressiv" raeumenden Sammler.

**Der heutige `tunnel.php` hat fuer den Normalfall gar keinen.**

Nachvollziehbar an den beiden Stellen: `zustand_aendern()` raeumt beim
Durchgehen von `$d['offen']` alles weg, dessen Marke verfallen ist. Bei
`action=antwort` wird die Marke aber aus `$d['offen']` **entfernt** und
danach `antwort_<marke>.json` geschrieben. Die Marke steht ab da in keiner
Liste mehr — also sieht der Sammler sie nie wieder, und die Antwortdatei
bleibt fuer immer liegen.

Geraeumt wird heute nur die Frage, die **niemand beantwortet hat**. Jeder
erfolgreiche Vorgang hinterlaesst dauerhaft eine Datei. Im Live-Lauf vom
02.09. ist es nicht aufgefallen, weil dort `0 beantwortet` stand.

Die neue Fassung fuehrt deshalb **zwei** Listen:

| Liste | Inhalt | Lebensdauer | beim Verfall geloescht |
|---|---|---|---|
| `offen` | gefragt, noch nicht beantwortet | `MARKE_TTL` (120 s) | Frage + etwaige Stuecke |
| `fertig` | beantwortet, wartet auf Abholung | `ANTWORT_TTL` (120 s) | Verzeichnis + alle Stuecke |

Nur `offen` wird in die oeffentliche Warteschlange projiziert — der Agent
soll beantwortete Marken nicht noch einmal sehen.

**Warum nicht beim Abholen loeschen:** Weil die Abholung statisch ist. PHP
sieht sie nie. Das ist kein Versaeumnis, sondern der Kern des Entwurfs; eine
Ablaufzeit ist die einzige Handhabe, die es geben kann. Sie muss deshalb
grosszuegig genug fuer langsame Leitungen und knapp genug fuer die Inodes
sein.

---

## 7a. Ein zweiter Fund: der ETag reicht nicht

Beim ersten lokalen Durchstich fiel eine Frage stillschweigend unter den
Tisch. Die Ursache ist keine Eigenheit des Testaufbaus, sondern Apaches
Vorgabe — und sie betrifft die laufende Referenzumsetzung genauso.

`FileETag MTime Size` bildet den ETag aus **ganzen Sekunden** und
**Groesse**. Eine Warteschlange mit einem Eintrag ist immer gleich lang:

```
Warteschlange mit Marke A       97 Bytes   ETag "6a9825a5-61"
... beantwortet, Schlange leer  34 Bytes   ETag "6a9825a5-22"
Warteschlange mit Marke B       97 Bytes   ETag "6a9825a5-61"   <-- gleich
```

Trifft Marke B ein, **bevor** der Agent den leeren Zwischenstand gesehen
hat, ist die neue Datei von der alten nicht zu unterscheiden. Er bekommt
`304`. Und da die Datei danach nicht mehr angefasst wird, bekommt er bei
jedem weiteren Abruf wieder `304` — bis die Marke nach 120 s verfaellt.

**Der Besucher wartet, der Agent meldet „keine Fehler", und niemand hat
einen Anhaltspunkt.** Das ist genau die Fehlerklasse, gegen die dieses
Projekt sonst ueberall Vorkehrungen trifft.

Drei Schranken, weil eine zu wenig ist:

1. **Unbedingter Abruf alle 30 s** (`unbedingt_nach`). Wirkt ohne jede
   Serverkonfiguration und kostet eine kleine statische Datei je halbe
   Minute — gegen 30 kostenlose 304er ist das nichts.
2. **`folge` in der Warteschlange.** Springt sie weiter, als der Agent
   gesehen hat, weiss er, dass er etwas uebersehen hat, und sagt es. Aus
   einem stillen Fehlschlag wird ein gezaehlter.
3. **`FileETag INode MTime Size`** in der `.htaccess`. Jedes atomare
   `rename()` erzeugt eine neue Inode, also einen neuen ETag. Behebt es an
   der Wurzel — aber nur auf Apache und nur, wenn die Datei ankommt.

Die Reihenfolge ist Absicht: Die Schranke, die verlorengehen kann, steht an
dritter Stelle.

`tests/durchstich_lokal.py` fuehrt die Falle **gezielt** herbei, statt zu
warten, ob sie zufaellig zuschnappt — und stellt fest, ob sie wirklich
zugeschnappt ist, bevor es die Gegenmassnahme prueft. Ein Test, der still
danebengreift, meldet sonst Erfolg, wo nichts geprueft wurde.

---

## 8. Vertraulichkeit — entworfen, nicht gebaut

Das README nennt sie „der groesste offene Punkt". Sie bleibt es, und zwar
mit Ansage.

**Der Entwurf:** Der Agent haelt ein langlebiges X25519-Schluesselpaar; sein
oeffentlicher Teil liegt als statische Datei auf dem Webspace. Der Browser
erzeugt je Vorgang ein fluechtiges Paar, leitet ueber ECDH und HKDF einen
Sitzungsschluessel ab und verschluesselt `daten` mit AES-GCM. Der oeffentliche
Teil des fluechtigen Schluessels reist im Umschlag mit. Der Webspace sieht
Rauschen; die Antwort geht denselben Weg zurueck. `krypto` im Umschlag sagt,
welches Verfahren gilt.

**Warum es hier trotzdem `"keine"` gibt und sonst nichts:**

Ohne Fremdbibliothek gibt es in Python kein X25519 und kein AES-GCM. Es
gaebe drei Auswege, und alle drei sind schlechter als warten:

- `cryptography` als Abhaengigkeit — bricht die 0-Abhaengigkeits-Zusage, die
  ein erklaertes Ziel dieses Projekts ist.
- X25519 in reinem Python nachbauen — machbar, aber selbstgeschriebene
  Kryptografie im Ernstfall.
- Etwas Einfacheres, das nach Verschluesselung aussieht.

Der dritte Weg ist der gefaehrlichste, und er ist derselbe Fehler wie das
verbotene Mini-Archiv: **eine Antwort, die geglaubt wird, ist schlimmer als
keine.** Wer glaubt, sein Kanal sei vertraulich, schickt Dinge hindurch, die
er sonst nicht schicken wuerde.

Deshalb: Der Umschlag traegt das Feld `krypto` von Anfang an. Es hat heute
genau einen erlaubten Wert, und der heisst `keine`. Der Agent weist jeden
anderen Wert ab, statt ihn zu ignorieren. Und im README steht, was auch
heute dort steht: **ueber diesen Weg reist nichts, was nicht oeffentlich
sein darf.**

Wenn Vertraulichkeit gebaut wird, dann als eigener, gemessener Schritt —
nicht nebenbei.

---

## 9. Die Handler-Schnittstelle

Sprachneutral formuliert, damit ein Go-Port eine Uebersetzung ist und keine
Neuerfindung. Der vollstaendige Vertrag steht in `PROTOKOLL.md`.

Ein Handler
- nennt die **Aktionen**, die er kennt (Weissliste, keine Ausschlussliste),
- **prueft seine Konfiguration beim Start** und bricht ab, wenn etwas fehlt,
- prueft **jedes** Feld aus `daten` selbst, auch wenn schon jemand geprueft
  hat,
- gibt Text oder Bytes zurueck, nie HTML zum Einbetten,
- und bringt **seinen eigenen Selbsttest mit**.

Der letzte Punkt ist der wichtigste. Die 27 Agent-Pruefungen der
Referenzumsetzung waren kein Beiwerk — sie sind der Grund, warum man dem
Agenten glauben kann. Sie wandern deshalb dorthin, wo die Schranken stehen:
in die Handler. **Ein Handler ohne Selbsttest wird nicht geladen.** Das ist
keine Stilregel, sondern die einzige Art, wie eine Weissliste mitwachsen
kann, ohne dass jemand sie im Kopf behalten muss.

```
Kern                              Handler
----                              -------
liest config.toml            ->   __init__(konfig)  prueft und wirft
kennt keinen Dienst          ->   AKTIONEN          Weissliste
Frage kommt herein           ->   bearbeite(aktion, daten) -> Antwort
Start / --selbsttest         ->   selbsttest()      eigene Schranken
```

Der Kern prueft: Protokollfassung, Marke, Form von `dienst`/`aktion`, ob der
Dienst in der Konfiguration steht, Groesse und Zeitlimit. Danach ruft er
auf. **Inhaltlich prueft der Kern nichts** — er koennte es nicht, ohne die
Dienste zu kennen, und genau das soll er nicht.

---

## 10. `config.toml` statt `config.yaml`

`Zukunftsmusik.txt` schlaegt YAML vor. Hier steht TOML, und das ist eine
bewusste Abweichung:

- `tomllib` ist seit Python 3.11 **in der Standardbibliothek**. YAML
  braeuchte PyYAML — eine Abhaengigkeit, ausgerechnet fuer die Datei, die
  jeder Nutzer als erstes anfasst.
- YAML ist an den Raendern ueberraschend (Einrueckung, `no` als Wahrheits-
  wert, mehrdeutige Zeichenketten). Eine Konfigurationsdatei, die sich
  anders liest als sie aussieht, erzeugt genau die stillen Fehlschlaege,
  gegen die dieses Projekt sonst ueberall Vorkehrungen trifft.
- Fuer Go gibt es TOML ebenso gut wie YAML.

Fuer Python 3.8 bis 3.10 wird `config.json` mit demselben Schema gelesen.
Damit gilt die 0-Abhaengigkeits-Zusage auf jeder Version — und der Agent
sagt beim Start, welchen Weg er genommen hat, statt es offenzulassen.

```toml
[relay]
basis           = "https://example.de/ahpt"
geheimnis_datei = "~/.ahpt/geheimnis"
poll_abstand    = 1.0

[[dienst]]
name     = "wiki"          # das reist ueber die Leitung
art      = "kiwix"         # das waehlt den Handler
ziel     = "http://127.0.0.1:8081"
aktionen = ["suche", "artikel"]
```

`name` und `art` sind getrennt, und das ist keine Umstaendlichkeit: Zwei
kiwix-Instanzen sind zwei Dienste mit einem Handler. Genau die heutige
Aufteilung `allgemein`/`medizin` — nur als Daten statt als Quelltext.

---

## 11. Was bewusst nicht gebaut wird

- **Kein Streaming, keine Live-Uebertragung.** Der Weg traegt Anfrage und
  Antwort, nicht eine Verbindung. Die Mindestverzoegerung von ein bis drei
  Sekunden ist keine Einstellung, sondern die Bauart.
- **Kein `exec`-Handler.** `Zukunftsmusik.txt` nennt ihn als Beispiel. Ein
  Handler, der Befehle aus einer Konfigurationszeile ausfuehrt, ist eine
  Zeile von einer Fernsteuerung entfernt, und diese Zeile wird jemand
  schreiben. Wer so etwas braucht, schreibt einen eigenen Handler fuer genau
  seinen Zweck — dann steht die Weissliste im Quelltext und nicht in einer
  Textdatei.
- **Kein Hochladen durch Besucher.** Der Weg geht in eine Richtung: fragen,
  antworten. Ein Besucher, der Bytes auf den Heimserver legen kann, ist ein
  anderes Sicherheitsmodell.
- **Keine Vertraulichkeit** (Abschnitt 8).

---

## 12. Der Weg zum Go-Port

`PROTOKOLL.md` beschreibt Dateinamen, Felder, Zeitlimits und Reihenfolgen
ohne eine Zeile Python. Ein Go-Agent ist fertig, wenn er
`tests/durchstich.sh` besteht — der Test spricht ueber HTTP und weiss
nicht, was auf der anderen Seite laeuft.

Was beim Uebersetzen mitwandern muss und leicht vergessen wird:

- Weiterleitungen **aus**, auf beiden Seiten. Ein Redirect kann aus
  127.0.0.1 etwas anderes machen.
- Wiederholung bei HTTP 503. Auf diesem Webspace heisst 503 „gerade zu
  viele PHP-Prozesse", nicht „kaputt". Wer nicht wiederholt, verliert
  Antworten — lautlos, weil der Besucher nur weiter wartet.
- `If-None-Match`. Ohne bedingte Abrufe kostet das Warten wieder etwas, und
  der ganze Entwurf ist hinfaellig.
- Das Geheimnis reist nur in der Kopfzeile, nur ueber https, und steht in
  keiner Fehlermeldung.
