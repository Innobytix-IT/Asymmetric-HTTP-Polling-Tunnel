# AHPT Cloud 3000

**Dieselbe persoenliche Cloud wie `../cloud/` — aber nicht mehr an einen
einzigen Vermittler gebunden. Mehrere Wege nebeneinander, darunter der
WebDAV-Speicher, den fast jeder E-Mail-Anbieter kostenlos mitliefert.
Faellt einer aus, nimmt die naechste Nachricht den naechsten.**

Ein eigenstaendiger Zweig neben AHPT und AHPT Cloud, nicht deren Ersatz.
Die Frage, die dieses Projekt beantwortet:

> Kann ein WebDAV-Speicher, wie ihn viele E-Mail-Anbieter kostenlos
> mitliefern, denselben Zweck erfuellen wie der PHP-Webspace bei AHPT
> Cloud — als Treffpunkt zwischen Heimserver und Aussenwelt, ohne VPS,
> ohne Portfreigabe?

Die Antwort ist ja, mit Einschraenkungen, und sie steht unten
nachgemessen. Wie es zu der Idee kam, steht in [`../GESCHICHTE.md`](../GESCHICHTE.md).

---

## Der Unterschied in einem Satz

`cloud/` kennt genau einen Weg zum Vermittler: den PHP-Webspace. Hier
duerfen mehrere nebeneinander stehen, und **jede einzelne Nachricht sucht
sich der Reihe nach einen aus, der gerade traegt**.

Wie man auf den Vermittler schreibt, ist damit austauschbar geworden:

| | `cloud/` | `cloud3000/` |
|---|---|---|
| Wer schreibt auf den Vermittler | `relay.php` | `relay.php` **oder** WebDAV |
| Eigener Code auf dem Vermittler | ja | bei WebDAV: **keiner** |
| Zahl der Wege | einer | beliebig viele |
| Ausfall eines Wegs | Betrieb steht | naechste Nachricht weicht aus |

Bei WebDAV liegt auf dem Vermittler **kein eigener Code** — WebDAV ist ein
Standardprotokoll fuer Dateizugriff (PUT, GET, DELETE, PROPFIND), das der
Anbieter ohnehin mitbringt. Alles, was `relay.php` sonst serverseitig
erledigt (Buchfuehrung, Deckel, Warteschlange), steckt dafuer im
Transportweg selbst — siehe [`transport.py`](transport.py).

Am Bedrohungsmodell aendert das **nichts**: Der Vermittler bleibt
inhaltsblind, Frage und Antwort sind weiterhin Ende zu Ende mit Noise IK
verschluesselt. Was hinzukommt, ist ein zweiter Mitwisser der *Umstaende*
und ein Konto, das man verlieren kann — beides in
[`SICHERHEIT.md`](SICHERHEIT.md).

---

## Mehrere Wege einrichten

`[relay]` in der Konfiguration bleibt der erste Weg, unter dem Namen
`php`. Ohne einen einzigen `[[transport]]`-Abschnitt verhaelt sich alles
**genau wie `cloud/`**. Jeder Abschnitt kommt hinzu:

```toml
[[transport]]
art            = "webdav"
name           = "cloud-des-mailanbieters"
rolle          = "beide"          # oder "frage" / "antwort"
basis          = "https://webdav.example.net"
benutzer       = "konto@example.net"
passwort_datei = "~/.ahpt/webdav.passwort"
```

Vollstaendig kommentiert in [`config-beispiel.toml`](config-beispiel.toml).
Dasselbe gilt fuer den Client (`client.toml`) — die Wege stehen dort in
derselben Form.

**`rolle` teilt die Richtungen auf.** Ein WebDAV-Speicher nimmt grosse
Antworten in einem Stueck (siehe Messungen), waehrend die kleinen Fragen
weiter ueber PHP gehen koennen — `rolle = "antwort"` hier,
`rolle = "frage"` dort.

**Faellt ein Weg wiederholt aus, wird er voruebergehend gesperrt**
(`transport.Gesundheit`), statt bei jeder Nachricht erneut seine volle
Frist verstreichen zu lassen. Nach der Sperrzeit genau ein Testversuch,
kein Dauerfeuer gegen einen Weg, der ohnehin nicht antwortet. Der
Kommandozeilen-Client merkt sich das ueber seine Aufrufe hinweg in einer
Datei, weil sein Prozess nach jedem Aufruf endet.

---

## Messungen

Gegen `https://webdav.mc.gmx.net` mit
[`tests/gmx_webdav_test.py`](tests/gmx_webdav_test.py), 06.09.2026. Das
Werkzeug braucht ein echtes Konto und laeuft nicht ohne.

### Grundfunktion und wiederholte Umlaeufe

```
Einzelner Umlauf (PUT+GET+DELETE):   0,65s / 0,19s / 0,18s
100 Umlaeufe, je eigener Pfad:       0 von 100 Fehlern
  Schreiben:  min 0,16s  mittel 0,22s  max 0,48s
  Lesen:      min 0,13s  mittel 0,16s  max 0,24s
```

**Eine Einschraenkung, die zuerst wie ein Fehler aussah:** Beim schnellen
*Ueberschreiben desselben Pfads* (Abstand 0,3s) schlugen 6 von 10
Versuchen fehl — teils mit HTTP 409, einmal mit falschem Inhalt trotz
gemeldetem Erfolg (HTTP 204). Ursache eingegrenzt: ein reines
Geschwindigkeitsproblem beim Ersetzen derselben Datei. Mit einem eigenen
Pfad pro Nachricht — dem Muster, das AHPT ohnehin nutzt — oder mit 1,5s
Abstand: 0 von 8 Fehlern in beiden Faellen.

### Dauerpollen

```
1x/Sekunde, 90s:              90/90 erfolgreich, 0,13-0,20s je Abruf
Beide Seiten alle 0,1s, 30s:  383 Anfragen (12,7/s erreicht), 0 Fehler
Beide Seiten alle 0,1s, 5min: 2.576 Anfragen (8,6/s erreicht), 0 Fehler
                              mittel 0,23s, max 0,65s
```

Die erreichte Rate liegt unter der angestrebten, weil jede Anfrage selbst
schon ~0,15-0,2s braucht — das ist die praktische Grenze fuer
sequenzielles Pollen ueber diese Verbindung, keine kuenstliche Drosselung
des Anbieters. Ueber die vollen 5 Minuten schwankte die Antwortzeit leicht
zwischen ~0,15s und ~0,3s je 30s-Fenster; Ursache nicht abschliessend
geklaert (Lastverteiler? eigenes Netz?), aber keine durchgehende
Verlangsamung und kein einziger Fehler.

### Grosse Dateien — der auffaelligste Unterschied

```
2 MB in einem Stueck:   PUT 1,3s   GET 0,5s
12 MB in einem Stueck:  PUT 5,5s   GET 2,2s
```

Zum Vergleich: dieselbe Groessenordnung brauchte bei `cloud/` ueber
bplaced rund 3,5 Minuten und etwa 260 Stuecke a 48 KB, weil dort nur
kleine PHP-Aufrufe moeglich sind. Hier: **ein einziger PUT, keine
Stueckelung noetig**, bis mindestens 12 MB nachgewiesen.

---

## Was noch offen ist

1. **Nutzungsbedingungen.** Kein ausdrueckliches Verbot fuer
   automatisierten Zugriff auf die eigene Cloud gefunden, aber auch keine
   ausdrueckliche Erlaubnis — die AGB sind auf Privatnutzer
   zugeschnitten, nicht auf Programme. Graubereich, kein gruenes Licht.
   Die Fundstellen stehen in [`SICHERHEIT.md`](SICHERHEIT.md).
2. **Obergrenze unbekannt.** Gefunden ist eine *untere* Schranke
   (~13 Anfragen/s sequenziell, 5 Minuten durchgehalten), nicht die
   tatsaechliche Grenze. Echte parallele Last ist ungetestet.
3. **Kein echter Push.** Trotz kurzer Umlaufzeiten bleibt es Pollen, kein
   dauerhaft offener Kanal — die strukturelle Grenze von AHPT (kein
   Prozess auf dem Vermittler) gilt unveraendert. Sie faellt hier nur
   praktisch kaum ins Gewicht.
4. **Nur GMX und freenet geprueft.** WEB.DE und Strato HiDrive bieten laut
   Doku ebenfalls WebDAV, sind aber ungeprueft. Bei jedem neuen Anbieter
   ist zuerst die Verzeichnisliste verdaechtig: Das Namensraum-Kuerzel im
   PROPFIND-XML waehlt jeder Server frei (siehe unten).

---

## Einrichten

Wie bei `cloud/`, plus die Transportwege oben.

### 1. Auf dem Heimserver

```bash
pip install cryptography            # nur fuer die Verschluesselung noetig
python3 krypto.py --erzeuge ~/.ahpt/agent.key
```

Der Befehl gibt den **oeffentlichen** Schluessel aus. Den brauchst du
gleich.

```bash
cp config-beispiel.toml ~/.ahpt/agent.toml     # und anpassen
python3 relay_agent.py --konfig ~/.ahpt/agent.toml --selbsttest
python3 relay_agent.py --konfig ~/.ahpt/agent.toml
```

### 2. Auf den Webspace — nur fuer den PHP-Weg

```
relay.php
.htaccess                 (aus htaccess-beispiel)
relay_token.php           <?php exit; ?> und darunter das Geheimnis
portal/index.html
portal/noise.js
portal/ahpt.js
portal/.htaccess          Passwortschutz
```

`ausliefern.sh` erledigt das und **misst hinterher nach** — es prueft
ueber HTTP(S), ob wirklich angekommen ist, was hochgeladen wurde. Am
02.09.2026 meldete ein FTP-Programm zweimal einen gruenen Haken, waehrend
auf dem Server die alte Datei lag.

**Fuer einen reinen WebDAV-Weg entfaellt dieser ganze Schritt.** Dort
gibt es nichts auszuliefern: kein `relay.php`, kein Geheimnis, keine
`.htaccess`. Nur ein Konto und ein Passwort in einer Datei.

### 3. Auf dem Geraet, mit dem du unterwegs bist

```bash
python3 krypto.py --erzeuge ~/.ahpt/client.key
```

Der oeffentliche Teil gehoert in die `clients`-Liste des Agenten. **Von
Hand uebertragen** — per SSH, USB-Stick, abgetippt. Niemals ueber den
Vermittler: Was dort liegt, kann der Betreiber austauschen, und genau das
soll die Verschluesselung verhindern.

---

## Benutzen

### Auf der Kommandozeile

```bash
python3 ahpt_client.py --konfig client.toml liste
python3 ahpt_client.py --konfig client.toml liste Belege
python3 ahpt_client.py --konfig client.toml hole Belege/rechnung.pdf
python3 ahpt_client.py --konfig client.toml lege ~/scan.pdf --nach Belege/scan.pdf
python3 ahpt_client.py --konfig client.toml ordner Rechnungen_2026
```

### Im Browser

`portal/index.html` oeffnen. Beim ersten Mal fragt es nach dem Schluessel
des Agenten und erzeugt einen eigenen fuer dieses Geraet — dessen
oeffentlichen Teil traegst du beim Agenten ein.

Danach: Dateiliste mit Ordnern, Herunterladen, Hochladen per Ziehen und
Ablegen (auch mehrere auf einmal, mit Fortschritt), Ordner anlegen,
Filtern, Vorschau fuer Bilder, PDF und Text.

**Das Portal spricht bisher nur den PHP-Weg.** Die Transportwege aus
`[[transport]]` gelten fuer Agent und Kommandozeilen-Client; im Browser
laeuft weiterhin genau ein Vermittler.

---

## Zwei Dinge, die man beim Portal wissen muss

### Der Browser gibt Verschluesselung nur im sicheren Zusammenhang frei

`crypto.subtle` gibt es **nur** ueber `https://`, auf `localhost` oder bei
einer lokal geoeffneten Datei (`file://`). Ueber gewoehnliches `http://`
ist es schlicht nicht vorhanden — das ist eine Browserregel, keine
Einstellung.

Ohne Verschluesselung arbeitet dieses Portal **nicht**. Es sagt das beim
Start und verweigert den Dienst, statt unverschluesselt weiterzumachen.

**Am 03.09.2026 gemessen:** bplaced-frei liefert ueber `https` gar nicht
den eigenen Webspace aus — Port 443 zeigt eine fremde Standardseite von
2018, die eigenen Dateien sind dort nicht zu finden (HTTP 404, ueber http
200). Auf einem solchen Hoster laesst sich das Portal also **nicht von
der eigenen Adresse aus im Browser betreiben**.

### Deshalb: das Portal von der eigenen Maschine ausliefern

**Auf dem Geraet, an dem du SITZT** — nicht auf dem Heimserver. Dort
liegen die Dateien ohnehin schon; interessant wird es vom Laptop aus.

```
Windows:   Doppelklick auf  "Portal starten.cmd"
           oder:  python "…\portal\starte_lokal.py"

Linux/Mac: python3 portal/starte_lokal.py
```

**Ueber das LAN geht es nicht.** `http://192.168.x.y:8770` waere kein
sicherer Kontext, also gaebe es dort wieder keine Verschluesselung. Nur
`localhost` zaehlt — deshalb hoert der Server ausschliesslich auf
127.0.0.1, und das ist keine Vorsicht, sondern die einzige Betriebsart,
in der das Portal ueberhaupt arbeitet.

**Warum nicht einfach die Datei doppelklicken?** Zwei Browserregeln
ziehen gegeneinander: `crypto.subtle` gibt es nur im sicheren Kontext
(dazu zaehlt `file://`) — aber eine Seite im sicheren Kontext darf keine
unsicheren Inhalte nachladen. Eine `file://`-Seite kann deshalb je nach
Browser NICHT mehr auf einen `http`-Webspace zugreifen.
`http://localhost` loest beides: sicherer Kontext, und weil die Seite
selbst `http` ist, entsteht gar keine Mischung. Am 03.09.2026 im Browser
nachgemessen.

Der Gewinn ist in beiden Faellen derselbe, und er ist der eigentliche
Grund:

| | Portal vom Webspace | Portal von der eigenen Maschine |
|---|---|---|
| Schutz gegen Fremde im Netz | ja | ja |
| Schutz gegen den **Hoster** | **nein** | **ja** |
| Braucht https beim Hoster | ja | nein |

Kaeme die Seite vom Webspace, koennte der Hoster sie austauschen — und
mit ihr den Schluessel, gegen den verschluesselt wird. Dann
verschluesselte das Portal brav gegen seinen Schluessel, und niemandem
fiele etwas auf. Verschluesselung, deren Schluessel vom Unvertrauten
geliefert wird, ist keine.

---

## Was geprueft ist

```
relay.php, statisch                       14 Pruefungen
Noise IK in Python                        53 Pruefungen   gegen offizielle Testvektoren
Noise IK in JavaScript                    13 Pruefungen   gegen dieselben Vektoren
Transportwege ohne Netz                   44 Pruefungen   tests/pruefe_transport.py
Durchstich mit Client, Portal, Angriffen  34 Pruefungen
Portal gegen den laufenden Betrieb         6 Pruefungen   ueber bplaced, echtes PHP
WebDAV gegen ein echtes Konto             gemessen        tests/gmx_webdav_test.py
```

Die Krypto-Umsetzungen sind **nicht ausgedacht, sondern nachgerechnet**:
`tests/ik_vektoren.json` enthaelt die offiziellen Noise-Testvektoren aus
*snow*, und beide Umsetzungen treffen jeden Geheimtext Byte fuer Byte.

`tests/pruefe_transport.py` laeuft ohne Netz und ohne Konto — es ersetzt
den Netzzugriff durch eine Attrappe und prueft, ob wir eine Antwort
richtig **verstehen**. Das ist der Teil, der bei einem neuen Anbieter
bricht, und einer der beiden Fehler unten ist genau daran gestorben.

### Zwei Fehler, die nur der echte Betrieb finden konnte

**Das Namensraum-Kuerzel im PROPFIND-XML.** WebDAV-Server waehlen es
frei: GMX schreibt `D:href`, freenet `x1:href` — beides gueltig, beides
dieselbe Bedeutung. Ein Regex auf ein festes Kuerzel fand bei freenet
nichts, obwohl die Datei nachweislich dalag (07.09.2026). Aufgeloest wird
jetzt ueber den Namensraum (`DAV:`) selbst, mit einem echten XML-Parser.

**Ein 404 vom Hoster kommt ohne CORS-Kopfzeile.** Das Portal fragte im
Takt nach der Antwortdatei und bekam bis zu deren Eintreffen lauter 404 —
die im Browser nicht als 404 ankommen, sondern als Netzfehler. Node kennt
keine CORS-Pruefung, die Attrappe lief gleiche Herkunft; nur ein echter
Browser gegen einen echten Hoster konnte es zeigen. Behoben im Protokoll:
Die Warteschlange nennt in `fertig` die Marken, deren Antwort
bereitliegt.

---

## Was es nicht gibt, und warum

- **Kein Loeschen und kein Ueberschreiben.** Wer ueberschreiben kann, kann
  loeschen — und ein Loeschen, das als Hochladen daherkommt, faellt
  niemandem auf. Gibt es den Namen schon, zaehlt der Agent hoch:
  `bericht.pdf` wird zu `bericht (2).pdf`, und der Client sagt es.
- **Kein Streaming, kein VPN.** Der Weg traegt Frage und Antwort, keinen
  Paketstrom. Ein bis drei Sekunden Mindestverzoegerung sind die Bauart.
- **Kein `exec`-Handler.** Eine Zeile Konfiguration von einer
  Fernsteuerung entfernt.
- **Kein Mehrbenutzerbetrieb.** Ein Nutzer, ein Schluesselpaar.
- **Keine Wege im Portal.** Siehe oben — der Browser spricht nur PHP.

Schreibende Aktionen (`lege`, `neuer_ordner`) laesst der Agent **nur mit
eingeschalteter Verschluesselung** zu und weist sie sonst schon beim Start
ab. Ohne Noise gaebe es keinen Absender, den man pruefen koennte — jeder,
der die Adresse kennt, duerfte dann Dateien ablegen.

---

## http statt https — wann das vertretbar ist

Der Agent besteht auf `https`, **solange nicht verschluesselt wird**. Mit
Noise IK laesst er `http` zu und sagt es beim Start laut. Die Rechnung
dahinter:

- Frage und Antwort sind verschluesselt. Ein Mitleser sieht Rauschen.
- Offen liegt allein die Kopfzeile `X-AHPT-Auth` — das Geheimnis, mit dem
  der Agent beim **Vermittler** schreiben darf.
- Wer es stiehlt, kann gefaelschte Antworten ablegen. Die scheitern beim
  Client an der Noise-Pruefung. Er kann **stoeren**, aber nichts mitlesen
  und nichts unterschieben.

**Fuer WebDAV gilt das nicht.** Dort weist sich der Agent mit Konto und
Passwort aus, und die reisen bei Basic-Auth in jeder einzelnen Anfrage
mit. Ein WebDAV-Weg ohne `https` gaebe das Passwort preis — und mit ihm
in aller Regel das dazugehoerige E-Mail-Postfach.

---

## Was der Vermittler trotzdem sieht

Verschluesselung verbirgt den Inhalt, nicht die Umstaende: **wann** etwas
abgerufen wird, **wie oft**, **wie gross** die Antwort war und **aus wie
vielen Stuecken** sie bestand. Wer daraus schliessen will, ob jemand zu
Hause ist, kann das.

Mit mehreren Wegen bei mehreren Anbietern verteilt sich das — jeder sieht
nur seinen Teil —, aber es verschwindet nicht. Und es kommt etwas hinzu:
Beim WebDAV-Weg ist der Vermittler nicht mehr ein anonymer Webspace,
sondern ein **Konto mit Namen**. Mehr dazu in
[`SICHERHEIT.md`](SICHERHEIT.md).
