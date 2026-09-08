# Offene Punkte

Was bekannt ist und absichtlich noch nicht erledigt. Kein Wunschzettel --
hier steht nur, was jemand aufgeschrieben hat, weil er es sonst vergisst,
mitsamt dem Grund, warum es liegen blieb.

Stand: 08.09.2026

---

## 1. Die Erfolgsmeldung der App wurde nie auf dem Bildschirm gesehen

Die Verbindungspruefung (`messeVerbindung`, Werkzeugleiste) ist geprueft --
aber nicht ihre Anzeige im Erfolgsfall.

**Was geprueft ist:** Der Knopf sitzt an der richtigen Stelle (im Emulator
gesehen), `:app:assembleDebug` laeuft, 16 von 16 Kern-Tests bestehen, und
das Meldungsfeld kann nicht abschneiden -- es ist eine `Surface` mit
`fillMaxWidth` und einem `Text` ohne `maxLines`. Dieselbe Logik laeuft im
Portal und auf der Kommandozeile nachweislich richtig.

**Was fehlt:** ein Bild der Meldung mit echten Zahlen. Beim Versuch verlor
der Emulator die Netzverbindung.

**Zum Nachholen:** Emulator starten, App gegen einen erreichbaren Vermittler
richten, Netz-Symbol antippen.

---

## 2. Die App verliert ein Byte, wenn der Server per Verbindungsabbau rahmt

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

## 3. Der Notbehelf in relay.php bleibt vorerst drin

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

## 4. `ahpt-portal-lokal.html` kommt in der README nicht vor

Der Einrichtungs-Assistent verweist den Anwender ausdruecklich auf diese
Datei ("muss wirklich AUF diesem Geraet liegen"). Sie ist aber ein
Bauerzeugnis aus `portal/baue_einzeldatei.py` und liegt deshalb **nicht im
Repo** -- und die README erwaehnt weder die Datei noch das Skript.

Wer das Repo klont, findet das Portal also nur als drei Einzeldateien und
erfaehrt nirgends, wie daraus die eine wird, von der der Assistent spricht.

---

## 5. `D:\AHPT Cloud 3000\ahpt` haengt hinter GitHub

Der oertliche Ordner des Cloud-3000-Abzweigs ist aelter als der Stand im
Repo: Das `kennung`-Feature (User-Agent, `netz.setze_kennung`) und
`tests/pruefe_transport.py` gibt es nur dort.

**Wichtig vor jeder Weiterarbeit dort:** erst den Ordner auffrischen. Ein
Push von oertlich wuerde beides loeschen. GitHub ist der massgebliche Stand.
