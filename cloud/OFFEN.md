# Offene Punkte

Was bekannt ist und absichtlich noch nicht erledigt. Kein Wunschzettel --
hier steht nur, was jemand aufgeschrieben hat, weil er es sonst vergisst,
mitsamt dem Grund, warum es liegen blieb.

Stand: 08.09.2026

---

## 1. Die App verliert ein Byte, wenn der Server per Verbindungsabbau rahmt

Am 08.09.2026 im Emulator gemessen:

```
kode=200  laenge=137  text={"ok":true,...,"antwort_add81a….json"     <- } fehlt
```

Der Vermittler sendet 138 Byte, die App liest 137, das JSON ist kaputt, und
auf dem Schirm steht "Abgewiesen (HTTP 200): keine Begruendung".

**Ursache der Rahmung, nicht der Menge:** `php -S` sendet weder
`Content-Length` noch `Transfer-Encoding` -- es schliesst nur die
Verbindung. Javas `HttpURLConnection` verliert dabei das letzte Byte. Sobald
eine Laengenangabe da war, war der Fehler weg. Python (Kommandozeile) und
der Browser (Portal) kommen mit der Abbau-Rahmung klar.

**In der Praxis nicht erreichbar:** bplaced liefert `Transfer-Encoding:
chunked`, und die App laeuft dort. Es bleibt aber eine echte Ungleichheit
zwischen den drei Clients.

**Warum nicht behoben:** Die Ursache in Java ist nicht zu Ende untersucht.
Eine geratene Reparatur an der Stelle, an der Bytes gezaehlt werden, ist
schlechter als ein bekannter, eingegrenzter Mangel.

---

## 2. Der Notbehelf in relay.php bleibt vorerst drin

`relay.php` schreibt bei abgewiesener Protokollfassung nach
`ahpt/protokollfehler.log` und nennt sich dort selbst TEMPORAER -- angelegt
wegen der Stueck-Ausfaelle vom 05.09.2026.

**Stand:** Die Datei existiert auf dem Webspace nicht (HTTP 404). Seit dem
05.09. hat also kein einziger Aufruf diesen Zweig erreicht.

**Warum er bleibt:** "Nicht wieder aufgetreten" ist nicht "verstanden". Der
konkrete Verdacht ist eine Drosselung durch den Hoster, und der Block ist
genau darauf gebaut: Er protokolliert `rumpf_bytes` NEBEN `content_length`.
Weichen die beiden voneinander ab, war der Rumpf unvollstaendig -- und damit
ist "abgeschnitten" von "echte Fassungsabweichung" unterschieden. Falls es
wiederkommt, steht die Antwort in einer Zeile.

Nebenbei: Die Datei laege im oeffentlich lesbaren Ablage-Ordner. Sie
enthaelt nichts Geheimes (Zeitstempel, Aktion, Byte-Zahlen) und ist bei
1 MB gedeckelt.

---

## 3. `ahpt-portal-lokal.html` kommt in der README nicht vor

Der Einrichtungs-Assistent verweist den Anwender ausdruecklich auf diese
Datei ("muss wirklich AUF diesem Geraet liegen"). Sie ist aber ein
Bauerzeugnis aus `portal/baue_einzeldatei.py` und liegt deshalb **nicht im
Repo** -- und die README erwaehnt weder die Datei noch das Skript.

Wer das Repo klont, findet das Portal also nur als drei Einzeldateien und
erfaehrt nirgends, wie daraus die eine wird, von der der Assistent spricht.

---

## 4. `D:\AHPT Cloud 3000\ahpt` haengt hinter GitHub

Der oertliche Ordner des Cloud-3000-Abzweigs ist aelter als der Stand im
Repo: Das `kennung`-Feature (User-Agent, `netz.setze_kennung`) und
`tests/pruefe_transport.py` gibt es nur dort.

**Wichtig vor jeder Weiterarbeit dort:** erst den Ordner auffrischen. Ein
Push von oertlich wuerde beides loeschen. GitHub ist der massgebliche Stand.

---

## 5. Der Restzeit-Takt laeuft auch, wenn nichts mehr passiert

Der Uebertragungsdialog hat eine eigene Uhr im Sekundentakt, damit die
Restzeit zwischen zwei Fortschrittsmeldungen weiterlaeuft. Sie zaehlt aber
stur herunter, auch wenn die Uebertragung wirklich haengt: Bei Null bleibt
"noch 0 s" stehen, und das sieht dann wieder aus wie der Stillstand, den der
Dialog gerade beheben sollte.

**Warum nicht sofort behoben:** Was dort stattdessen stehen sollte, haengt
davon ab, wie oft das im Betrieb ueberhaupt vorkommt. "Dauert laenger als
gedacht" waere ehrlich, ist aber geraten, solange niemand einen Fall gesehen
hat.

---

## Erledigt

- **08.09.2026 -- Die Erfolgsmeldung der App auf dem Bildschirm gesehen.**
  Auf einem SM-G970F gegen den echten Webspace:

  ```
  Verbindung steht. Ein Rundlauf hat 1,1 s gebraucht.
  Frage ablegen: 91 ms / Warten auf den Agenten: 896 ms (3 Abfragen) /
  Antwort holen: 67 ms
  ```

  Damit ist auch die Sorge erledigt, das Meldungsfeld koenne abschneiden.

- **08.09.2026 -- "Abbrechen" wirkt sofort.** Zwei Fehler steckten
  dahinter, und beide sahen von aussen gleich aus. Der Rueckruf wurde nur
  ZWISCHEN den Bloecken gefragt -- bei 4 MiB je Block hat eine 8-MB-Datei
  genau eine Pruefstelle, und der Bildschirmabzug zeigte "Wird
  abgebrochen ..." bei exakt "4,0 MB von 8,0 MB". Ausserdem ueberschrieb
  die naechste Stueckmeldung den Satz nach Sekundenbruchteilen wieder.
  Beides behoben (`eb43494a`), auf einem SM-G970F nachgeprueft.

  Nebenbei richtiggestellt: In der ersten Fassung dieses Punktes stand,
  der Rueckruf werde "zwischen den Bloecken UND zwischen den Stuecken"
  gefragt. Das war falsch. Jetzt stimmt es.

- **08.09.2026 -- Die Einzelsperre ist ueber die Oberflaeche nicht zu
  erreichen, und das ist die Antwort.** Beim Versuch, sie auszuloesen, kam
  heraus: Der Uebertragungsdialog ist modal. Solange er steht, erreicht
  kein Fingertipp die Liste oder den Hochladen-Knopf dahinter -- und alle
  drei Einstiege fuehren ueber genau diese beiden. Die Meldung "Es laeuft
  schon eine Uebertragung" kann also niemand sehen.

  Die Sperre bleibt trotzdem: Die Modalitaet ist eine Entscheidung der
  Oberflaeche, die Bedingung eine des Modells. Sobald der Dialog wegtippbar
  wird oder eine Uebertragung in den Hintergrund darf, ist sie das einzige,
  was noch haelt. Die Begruendung im Code sagt das jetzt so.
