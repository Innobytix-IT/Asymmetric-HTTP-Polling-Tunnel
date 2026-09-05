# AHPT/1 — Protokollvertrag

Sprachneutral. Wer einen Agenten in Go, Rust oder C schreibt, braucht dieses
Dokument und sonst nichts. Begruendungen stehen in `ARCHITEKTUR.md`; hier
steht nur, was gilt.

Protokollfassung: **1**. Jede Nachricht traegt sie im Feld `v`. Ein
abweichender Wert wird **abgewiesen**, nie gedeutet.

---

## 1. Rollen

| Rolle | tut | erreicht |
|---|---|---|
| Besucher | stellt Frage, holt Antwort | Webspace ueber https |
| Vermittler | nimmt Frage und Antwort entgegen | wird erreicht |
| Agent | holt Frage, loest sie lokal, legt Antwort ab | Webspace ueber https |

Der Agent nimmt **nie** eine Verbindung an. Er baut jede selbst auf, nach
aussen.

---

## 2. Ablage auf dem Webspace

Basis ist ein Verzeichnis, im Folgenden `<basis>`. Darin:

| Pfad | von wem geschrieben | von wem gelesen | PHP? |
|---|---|---|---|
| `<basis>/relay.php` | — | Besucher (POST), Agent (POST) | ja |
| `<basis>/ahpt/warteschlange.json` | Vermittler | Agent (GET) | **nein** |
| `<basis>/ahpt/frage_<marke>.json` | Vermittler | Agent (GET) | **nein** |
| `<basis>/ahpt/antwort_<marke>.json` | Vermittler | Besucher (GET) | **nein** |
| `<basis>/ahpt/antwort_<marke>_<teil>_<disk>.json` | Vermittler | Besucher (GET) | **nein** |
| `<basis>/relay_token.php` | Mensch | Vermittler (lokal) | nie ausgeliefert |
| `<basis>/relay_state.php` | Vermittler | Vermittler (lokal) | nie ausgeliefert |

**Es gibt keinen Weg, ueber `relay.php` etwas zu LESEN.** Wer einen
einbaut, verlegt das Warten auf den teuren Weg und hebt den Entwurf auf.

`<marke>` ist genau 32 Kleinbuchstaben-Hexzeichen (128 Bit aus einem
kryptografischen Zufallsquell). `<teil>` ist eine Dezimalzahl ab 0.
`<disk>` sind 4 Hexzeichen, siehe 6.2.

---

## 3. Umschlag

Jede Nutzlast — Frage wie Antwort — liegt in diesem Umschlag:

```json
{
  "v": 1,
  "marke": "0123456789abcdef0123456789abcdef",
  "teil": 0,
  "teile": 1,
  "krypto": "keine",
  "nutzlast": { }
}
```

| Feld | Typ | Regel |
|---|---|---|
| `v` | Zahl | muss `1` sein, sonst abweisen |
| `marke` | Text | `^[0-9a-f]{32}$` |
| `teil` | Zahl | `0 <= teil < teile` |
| `teile` | Zahl | `1 <= teile <= 256` |
| `krypto` | Text | derzeit **ausschliesslich** `"keine"`. Jeder andere Wert wird abgewiesen — auch ein Wert, der nach einem gueltigen Verfahren aussieht. |
| `nutzlast` | Objekt oder Text | siehe 4 und 5 |

---

## 4. Frage

`nutzlast` einer Frage:

```json
{ "dienst": "wiki", "aktion": "suche", "daten": { "begriff": "Wasser" } }
```

| Feld | Regel — geprueft vom Vermittler |
|---|---|
| `dienst` | `^[a-z][a-z0-9_]{0,31}$` |
| `aktion` | `^[a-z][a-z0-9_]{0,31}$` |
| `daten` | Objekt. Inhalt **ungeprueft** durchgereicht, nur groessenbegrenzt. |

Der Vermittler prueft **die Form, nie den Sinn**. Er weiss nicht, welche
Dienste es gibt. Ob `dienst` existiert, entscheidet allein der Agent gegen
seine lokale Konfiguration.

`dienst` und `aktion` erscheinen **niemals** in einem Dateinamen, Pfad oder
Kopfzeilenwert. Die Formregel oben ist die zweite Schranke dagegen, nicht
die erste.

---

## 5. Antwort

`nutzlast` einer Antwort:

```json
{
  "gefunden": true,
  "titel": "Wasser",
  "quelle": "wiki",
  "inhalt_typ": "text",
  "inhalt": "..."
}
```

| Feld | Typ | Bedeutung |
|---|---|---|
| `gefunden` | Wahrheitswert | `false` heisst „bearbeitet, nichts gefunden", nicht „Fehler" |
| `titel` | Text | Anzeigename, darf leer sein |
| `quelle` | Text | welcher Dienst geantwortet hat |
| `inhalt_typ` | `"text"` oder `"base64"` | `base64` fuer Bytes |
| `inhalt` | Text | die Nutzlast |

`inhalt` ist **reiner Text oder Base64, niemals HTML zum Einbetten.** Der
Besucher darf ihn nie als Markup in seine Seite haengen. Das ist die
Schranke, die verhindert, dass Archiv- oder Dateiinhalt zu Skript wird.

---

## 6. Stueckelung

### 6.1 Wann

Wenn `inhalt` groesser ist als `MAX_STUECK` (Vorgabe 48 KiB nach Base64),
wird gestueckelt. Sonst nicht — `teile: 1`, `teil: 0`, keine Stueckdateien.

### 6.2 Dateinamen

```
antwort_<marke>.json                       das Verzeichnis
antwort_<marke>_<teil>_<disk>.json         ein Stueck
```

`<disk>` sind die ersten 4 Zeichen von

```
sha256( marke + "|" + dezimal(teil) )
```

in Kleinbuchstaben-Hex.

**Warum:** Fortlaufende Namen unterscheiden sich um genau ein Zeichen, und
`mod_speling` leitet dann von einem noch fehlenden Stueck stillschweigend
auf ein vorhandenes um (HTTP 301). Der Client baut dann eine verfaelschte
Datei zusammen, ohne dass irgendwo ein Fehler entsteht. Mit `<disk>` liegen
benachbarte Namen mehrere Zeichen auseinander.

Der Client **berechnet `<disk>` nicht selbst und raet ihn nicht** — er liest
den Dateinamen aus dem Verzeichnis.

### 6.3 Verzeichnis

```json
{
  "v": 1, "marke": "...", "teil": 0, "teile": 5, "krypto": "keine",
  "nutzlast": {
    "gefunden": true, "titel": "handbuch.pdf", "quelle": "dateien",
    "inhalt_typ": "base64", "inhalt": "",
    "stuecke": [
      { "teil": 0, "datei": "antwort_<marke>_0_1a2b.json", "bytes": 49152 },
      { "teil": 1, "datei": "antwort_<marke>_1_c3d4.json", "bytes": 49152 }
    ],
    "bytes_gesamt": 240000
  }
}
```

Bei `teile > 1` ist `inhalt` im Verzeichnis **leer**. Der ganze Inhalt steht
in den Stuecken.

### 6.4 Reihenfolge — verbindlich

1. Agent legt **alle** Stuecke ab.
2. Agent legt **danach** das Verzeichnis ab.

Andersherum verweist ein Verzeichnis auf Dateien, die es noch nicht gibt.

### 6.5 Pruefung durch den Client — verbindlich

Fuer jedes geholte Stueck:

- `marke` im Stueck **muss** der erwarteten gleichen,
- `teil` im Stueck **muss** der erwarteten gleichen,
- `teile` im Stueck **muss** dem Verzeichnis gleichen.

Bei Abweichung: **abbrechen und melden**, nicht weiterbauen. Eine
Abweichung heisst, dass eine Umleitung im Spiel war.

---

## 7. Ablauf

### 7.1 Besucher stellt eine Frage

```
POST <basis>/relay.php?action=frage
Content-Type: application/json

{ "v":1, "krypto":"keine", "nutzlast":{ "dienst":"...", "aktion":"...", "daten":{ } } }
```

`marke`, `teil`, `teile` fehlen hier — die Marke vergibt der Vermittler.

Antwort bei Erfolg:

```json
{ "ok": true, "marke": "...", "ttl": 120, "abholen": "ahpt/antwort_<marke>.json" }
```

| Lage | HTTP |
|---|---|
| angenommen | 200 |
| Form falsch, Fassung falsch, zu gross | 400 |
| zu viele offene Fragen dieses Absenders | 429 |
| Vermittler ausgelastet | 503 |
| Ablage nicht schreibbar | 500 |

### 7.2 Agent holt Arbeit

```
GET <basis>/ahpt/warteschlange.json
If-None-Match: <letztes ETag>
```

- `304` — nichts Neues. **Der Normalfall.** Kostet null Bytes und kein PHP.
- `404` — es hat noch nie jemand gefragt. **Kein Fehler.**
- `200` — Inhalt:

```json
{ "stand": 1756800000, "folge": 42,
  "offen": [ { "marke": "...", "ts": 1756799990 } ] }
```

Die Warteschlange enthaelt **nur** `marke` und `ts`. Kein Absender, kein
Dienst, kein Inhalt.

`folge` zaehlt jede Aenderung der Warteschlange hoch. Der Agent merkt sich
den zuletzt gesehenen Wert. Springt er weiter, als der Agent gesehen hat,
ist ihm eine Aenderung entgangen -- siehe 7.2.1.

Der Agent ueberspringt Marken, die er schon bearbeitet hat (eigenes
Gedaechtnis, Vorgabe 600 s), und Marken, die aelter sind als
`FRAGE_MAX_ALTER`.

### 7.2.1 Der ETag reicht nicht -- verbindlich

Apache bildet den ETag standardmaessig aus **Aenderungszeit in ganzen
Sekunden** und **Groesse** (`FileETag MTime Size`). Zwei Warteschlangen mit
je einem Eintrag sind **exakt gleich lang**: Marke (32 Zeichen) und
Zeitstempel (10 Ziffern) haben feste Breite.

Am 02.09.2026 nachgestellt und gemessen:

```
Warteschlange mit Marke A       97 Bytes   ETag "6a9825a5-61"
... beantwortet, Schlange leer  34 Bytes   ETag "6a9825a5-22"
Warteschlange mit Marke B       97 Bytes   ETag "6a9825a5-61"   <-- gleich
```

Hat der Agent den leeren Zwischenstand **nicht** gesehen -- weil die
naechste Frage vor seinem naechsten Abruf eintraf --, ist die neue Datei
von der alten nicht zu unterscheiden. Er bekommt `304` und uebersieht die
Frage. Und weil die Datei danach nicht mehr angefasst wird, bekommt er bei
**jedem** weiteren Abruf wieder `304`: Die Frage bleibt bis zum Verfall
unbeantwortet, waehrend der Besucher wartet. Kein Fehler, keine Meldung.

Ein Agent MUSS deshalb alle drei Vorkehrungen tragen:

1. **Unbedingter Abruf** ohne `If-None-Match` spaetestens alle
   `UNBEDINGT_NACH` Sekunden (Vorgabe 30). Das wirkt ohne jede
   Serverkonfiguration.
2. **`folge` vergleichen.** Ist sie um mehr als 1 gesprungen, waehrend nur
   `304` kam, wurde eine Aenderung uebersehen -- der Agent zaehlt und
   meldet das, statt es zu verschweigen.
3. Auf dem Server **`FileETag INode MTime Size`**. Jedes atomare `rename()`
   erzeugt eine neue Inode-Nummer, also einen neuen ETag. Behebt es an der
   Wurzel -- aber nur auf Apache, und nur wenn die `.htaccess` ankommt.

### 7.3 Agent holt die Frage

```
GET <basis>/ahpt/frage_<marke>.json
```

Statisch, kein PHP. Weiterleitungen **aus**.

### 7.4 Agent legt die Antwort ab

Erst je Stueck (nur wenn `teile > 1`):

```
POST <basis>/relay.php?action=stueck
X-AHPT-Auth: <geheimnis>
```

Dann genau einmal:

```
POST <basis>/relay.php?action=antwort
X-AHPT-Auth: <geheimnis>
```

| Lage | HTTP |
|---|---|
| abgelegt | 200 |
| Geheimnis fehlt oder falsch | 403 |
| Marke unbekannt oder verfallen | 404 |
| zu gross | 413 |
| Vermittler ausgelastet | **503 — wiederholen** |

**503 ist auf gedeckelten Webspaces der Normalbetrieb**, nicht ein Defekt.
Ein Agent, der nicht wiederholt, verliert Antworten lautlos: der Besucher
wartet einfach weiter. Vorgabe: 4 Versuche, Wartezeit 0,4 s verdoppelnd.

### 7.5 Besucher holt die Antwort

```
GET <basis>/ahpt/antwort_<marke>.json
```

Statisch, kein PHP, in Abstaenden bis `ttl` abgelaufen ist. `404` heisst
„noch nicht da", nicht „Fehler". Bei `teile > 1` danach die Stuecke nach 6.5.

**Der Client prueft `marke` in der Antwort gegen die erwartete.** Ohne diese
Pruefung ist eine Umleitung auf eine fremde Datei nicht zu bemerken.

---

## 8. Geheimnis

- Geteiltes Geheimnis, mindestens 16 Zeichen, Vergleich in konstanter Zeit
  (`hash_equals` oder gleichwertig).
- Reist **nur** in der Kopfzeile `X-AHPT-Auth`, **nur** ueber `https`.
  Ausnahme allein Loopback (`127.0.0.1`, `localhost`, `::1`), wo es keinen
  Zwischenknoten gibt.
- Erscheint in **keiner** Fehlermeldung, keinem Protokolleintrag, keiner
  Diagnoseausgabe.
- Nur der Agent weist sich aus. Der Besucher nicht — er ist die
  Oeffentlichkeit.

Ohne Ausweis des Agenten koennte jeder eine Antwort einschleusen, und sie
erschiene beim Besucher als echter Inhalt.

---

## 9. Deckel

| Name | Vorgabe | wogegen |
|---|---|---|
| `MARKE_TTL` | 120 s | liegengebliebene Fragen |
| `ANTWORT_TTL` | 120 s | liegengebliebene Antworten (Inodes) |
| `MAX_OFFEN` | 40 | Auslastung insgesamt |
| `MAX_JE_IP` | 5 | ein Absender allein |
| `MAX_FRAGE` | 4 KiB | Fragegroesse |
| `MAX_STUECK` | 48 KiB | ein Stueck |
| `MAX_TEILE` | 256 | Antwort gesamt ~12 MiB |
| `FRAGE_MAX_ALTER` | 110 s | knapp unter `MARKE_TTL` |
| `POLL_ABSTAND` | 1,0 s | — |
| `UNBEDINGT_NACH` | 30 s | uebersehene ETags (7.2.1) |

`FRAGE_MAX_ALTER` muss **unter** `MARKE_TTL` liegen. Sonst bearbeitet der
Agent eine Frage, deren Marke waehrenddessen verfaellt, und legt die Antwort
in ein Nichts.

---

## 10. Aufraeumen

Der Vermittler fuehrt zwei Listen und raeumt bei **jeder** Zustandsaenderung:

| Liste | Eintritt | Austritt | dann geloescht |
|---|---|---|---|
| `offen` | Frage angenommen | Antwort abgelegt, oder `MARKE_TTL` abgelaufen | `frage_<marke>.json` und alle Stuecke |
| `fertig` | Antwort abgelegt | `ANTWORT_TTL` abgelaufen | `antwort_<marke>.json` und alle Stuecke |

Nur `offen` steht in der oeffentlichen Warteschlange.

Beim Loeschen der Stuecke muss die Stueckzahl aus der Liste kommen, nicht
aus einem Verzeichnislisting — `Options -Indexes` verhindert letzteres, und
darauf soll sich das Aufraeumen nicht stuetzen.

---

## 11. Was ein Agent niemals tun darf

1. Eine **Adresse** aus der Nachricht abrufen. Es gibt kein solches Feld;
   wer eines einfuehrt, macht den Agenten zum offenen Proxy ins Heimnetz.
2. Einer **Weiterleitung folgen** — weder beim Webspace noch beim lokalen
   Dienst. Ein Redirect kann aus `127.0.0.1` etwas anderes machen.
3. Einen **Dienst bedienen, der nicht in der lokalen Konfiguration steht.**
4. Eine unbekannte `v` oder ein unbekanntes `krypto` **deuten** statt
   abzuweisen.
5. Das **Geheimnis ausgeben**, in welcher Form auch immer.
6. Einen Fehlschlag **verschweigen**. Jede Fehlerart wird gezaehlt und
   mindestens einmal genannt.
7. Sich allein auf `If-None-Match` verlassen. Siehe 7.2.1 -- ein `304` ist
   kein Beweis, dass sich nichts geaendert hat.
