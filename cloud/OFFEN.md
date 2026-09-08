# Offene Punkte

Was bekannt ist und absichtlich noch nicht erledigt. Kein Wunschzettel --
hier steht nur, was jemand aufgeschrieben hat, weil er es sonst vergisst,
mitsamt dem Grund, warum es liegen blieb.

Stand: 08.09.2026

---

## 1. Eine abgeschnittene Antwort, die sich nicht wieder einfangen laesst

Am 08.09.2026 im Emulator EINMAL gesehen:

```
kode=200  laenge=137  text={"ok":true,...,"antwort_add81a….json"     <- } fehlt
```

Die Antwort war 138 Byte lang, angekommen sind 137, das JSON war
unbrauchbar, und auf dem Schirm stand "Abgewiesen (HTTP 200): keine
Begruendung".

**Die damals notierte Ursache ist widerlegt.** Sie lautete: `php -S` rahmt
durch Verbindungsabbau, und Javas `HttpURLConnection` verliere dabei das
letzte Byte. Nachgemessen wurde das am 08.09.2026 abends in drei
Umgebungen, jeweils mit demselben 138-Byte-Koerper, dessen letztes Zeichen
die Klammer ist:

| Umgebung                             | Pruefung                          | Ergebnis |
|--------------------------------------|-----------------------------------|----------|
| JVM                                  | `kern/.../NetzRahmungTest`        | 138/138  |
| SM-G970F, Android 12                 | `app/.../NetzRahmungGeraetTest`   | 138/138  |
| Emulator, durch die Netz-Nachbildung | dieselbe Pruefung ueber 10.0.2.2  | 138/138  |

Geprueft sind alle vier Rahmungen, die AHPT antrifft: `Content-Length`,
`chunked`, HTTP/1.1 mit blossem Verbindungsabbau, HTTP/1.0 ohne jede
Laengenangabe. Ausserdem nachgesehen, was `php -S` wirklich sendet: fuer
statische Dateien `Content-Length`, fuer erzeugte Ausgabe nur
`Connection: close` -- und `curl` bekommt auch dann alle 138 Byte.

**Was bleibt:** eine einzelne Beobachtung ohne Erklaerung. Der Verdacht
liegt jetzt auf der Serverseite jenes Aufbaus -- eine Antwort, die schon
unvollstaendig entstand -- aber die Artefakte von damals gibt es nicht
mehr, und ohne sie ist jede weitere Zuordnung geraten.

**Warum der Punkt trotzdem stehen bleibt:** weil "nicht reproduzierbar"
nicht "war nicht da" heisst. Kaeme es wieder, waere der erste Griff der
Vergleich von `rumpf_bytes` und `content_length` -- siehe Punkt 2, der
genau dafuer gebaut ist.

Die Pruefungen bleiben ebenfalls stehen. Sie kosten nichts und decken eine
Klasse von Fehlern ab, die man sonst erst im Betrieb bemerkt.

## 2. Der Notbehelf in relay.php bleibt vorerst drin

`relay.php` schreibt bei abgewiesener Protokollfassung nach
`ahpt/protokollfehler.log` und nennt sich dort selbst TEMPORAER -- angelegt
wegen der Stueck-Ausfaelle vom 05.09.2026.

**Stand:** Die Datei existiert auf dem Webspace nicht (HTTP 404,
nachgesehen am 08.09.2026 abends; `selbsttest` antwortet, der Vermittler
lebt also und schweigt nicht bloss). Seit dem 05.09. hat kein einziger
Aufruf diesen Zweig erreicht.

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

- **08.09.2026 -- `ahpt-portal-lokal.html` steht jetzt in der README.**
  Ein eigener Abschnitt: wie sie gebaut wird (`portal/baue_einzeldatei.py`),
  warum sie nicht im Repo liegt (Bauerzeugnis, das sonst veraltet), warum
  sie wirklich auf dem Geraet liegen muss, und wann Doppelklick reicht und
  wann es `starte_lokal.py` braucht. Der Assistent verweist auf sie, ohne
  dass die README sie kannte -- das war die Luecke.

- **08.09.2026 -- `D:\AHPT Cloud 3000\ahpt` ist aufgefrischt.** Vorher
  gesichert nach `ahpt.vor_auffrischen_<Stempel>`, dann elf Dateien aus dem
  Repo uebernommen (neun aelter als dort, zwei fehlten ganz:
  `tests/pruefe_transport.py`, `tests/gmx_webdav_test.py`). Beim Uebernehmen
  wurde die Anonymisierung zurueckgesetzt: Wo im Repo `/home/DEIN-NUTZER`
  steht, steht oertlich wieder der echte Pfad. Ergebnis: 41 Dateien
  gleich, abweichend nur
  `config-beispiel.toml` (die Falle selbst), oertlich zusaetzlich nur
  `client.toml`, das Gesundheits-Gedaechtnis und das gebaute Portal.

  **Nebenbefund, ungeprueft:** Die 3000-README im Repo ist eine echte
  Neufassung, keine Fortschreibung. Ein paar Abschnitte der Cloud-README
  stehen nicht mehr darin. Bei den meisten ist das einleuchtend (sie
  handeln vom PHP-Weg), bei "Ordner anlegen -- und warum es keinen
  Abgleich gibt" nicht: Der Abschnitt gilt fuer 3000 genauso. Nicht
  angefasst, weil das eine Entscheidung ueber einen anderen Zweig waere.

- **08.09.2026 -- Der Restzeit-Takt behauptet nichts mehr, was er nicht
  weiss.** Vorher zaehlte er stur bis Null und blieb bei "noch 0 s" stehen.
  Jetzt misst der Dialog, wie lange nichts mehr hereinkam -- das ist eine
  Messung, keine Schaetzung, denn der Zeitpunkt der letzten
  Fortschrittsmeldung steht im Zustand. Ab zwanzig Sekunden Stille steht
  dort "seit 25 s still" statt einer Restzeit. Zwanzig und nicht zehn, weil
  ein Stueck von 48 KiB ueber eine schlechte Mobilfunkstrecke gut dreizehn
  Sekunden dauern kann; das ist langsam, nicht kaputt. Ist die Schaetzung
  aufgebraucht, kommt aber noch etwas an, heisst es "gleich fertig".
