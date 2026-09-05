# AHPT Cloud

**Deine eigenen Dateien vom Heimserver holen und dort ablegen — von
unterwegs, ohne offenen Port, ohne VPS, mit einem gewoehnlichen Webspace
als Briefkasten. Ende zu Ende verschluesselt.**

Eine Nutzungsart von AHPT (siehe [`../kern/`](../kern/)) fuer **einen
einzigen Nutzer**.

Im generischen Kern weist sich nur der Agent aus, und der Inhalt ist
oeffentlich lesbar -- das passt fuer ein Lexikon, nicht fuer eigene
Dateien. Hier dreht sich das Bedrohungsmodell um: **Beide** Seiten
weisen sich aus (Noise IK), der Inhalt ist geheim, und zusaetzlich zum
Lesen kommt das Schreiben dazu. Ein Schreibzugang ins Heimnetz ist der
Fehler, der alles kaputtmacht, wenn er nicht sauber eingegrenzt ist --
deshalb die vier Schranken in "Was es nicht gibt, und warum" weiter
unten.

---

## Der Unterschied in einem Satz

Im oeffentlichen AHPT weist sich nur der Agent aus, und der Inhalt ist
oeffentlich. Hier weisen sich **beide** aus — und der Vermittler versteht
keinen von beiden.

```
Was auf dem Webspace liegt:   {"v":1,"krypto":"noise_ik","nutzlast":
                               {"chiffre":"y8K3n2Rf…"}}
Was darin steckt:             Dienst, Aktion, Dateiname, Inhalt
Was der Hoster davon sieht:   nichts
```

Nachgemessen am laufenden System mit `tests/was_sieht_der_webspace.py` — es
holt die oeffentliche Warteschlange samt aller Frage- und Antwortdateien,
genau wie ein Fremder es koennte, und sucht darin nach Klartext. Keine der
neun Nadeln taucht auf.

---

## Einrichten

### 1. Auf dem Heimserver

```bash
pip install cryptography            # nur fuer die Verschluesselung noetig
python3 krypto.py --erzeuge ~/.ahpt/agent.key
```

Der Befehl gibt den **oeffentlichen** Schluessel aus. Den brauchst du gleich.

```bash
cp config-beispiel.toml ~/.ahpt/agent.toml     # und anpassen
python3 relay_agent.py --konfig ~/.ahpt/agent.toml --selbsttest
python3 relay_agent.py --konfig ~/.ahpt/agent.toml
```

### 2. Auf den Webspace

```
relay.php
.htaccess                 (aus htaccess-beispiel)
relay_token.php           <?php exit; ?> und darunter das Geheimnis
portal/index.html
portal/noise.js
portal/ahpt.js
portal/.htaccess          Passwortschutz
```

`ausliefern.sh` erledigt das und **misst hinterher nach** — es prueft ueber
HTTP(S), ob wirklich angekommen ist, was hochgeladen wurde. Am 02.09.2026
meldete ein FTP-Programm zweimal einen gruenen Haken, waehrend auf dem
Server die alte Datei lag.

### 3. Auf dem Geraet, mit dem du unterwegs bist

```bash
python3 krypto.py --erzeuge ~/.ahpt/client.key
```

Der oeffentliche Teil gehoert in die `clients`-Liste des Agenten. **Von Hand
uebertragen** — per SSH, USB-Stick, abgetippt. Niemals ueber den Webspace:
Was dort liegt, kann der Hoster austauschen, und genau das soll die
Verschluesselung verhindern.

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
Ablegen (auch mehrere auf einmal, mit Fortschritt), Ordner anlegen, Filtern,
Vorschau fuer Bilder, PDF und Text.

---

## Zwei Dinge, die man beim Portal wissen muss

### Der Browser gibt Verschluesselung nur im sicheren Zusammenhang frei

`crypto.subtle` gibt es **nur** ueber `https://`, auf `localhost` oder bei
einer lokal geoeffneten Datei (`file://`). Ueber gewoehnliches `http://` ist
es schlicht nicht vorhanden — das ist eine Browserregel, keine Einstellung.

Ohne Verschluesselung arbeitet dieses Portal **nicht**. Es sagt das beim
Start und verweigert den Dienst, statt unverschluesselt weiterzumachen.

**Am 03.09.2026 gemessen:** bplaced-frei liefert ueber `https` gar nicht den
eigenen Webspace aus — Port 443 zeigt eine fremde Standardseite von 2018,
die eigenen Dateien sind dort nicht zu finden (HTTP 404, ueber http 200).
Auf einem solchen Hoster laesst sich das Portal also **nicht von der eigenen
Adresse aus im Browser betreiben**.

### Deshalb: das Portal von der eigenen Maschine ausliefern

**Auf dem Geraet, an dem du SITZT** -- nicht auf dem Heimserver. Dort liegen
die Dateien ohnehin schon; interessant wird es vom Laptop aus.

```
Windows:   Doppelklick auf  "Portal starten.cmd"
           oder:  python "…hpt\portal\starte_lokal.py"

Linux/Mac: python3 portal/starte_lokal.py
```

**Ueber das LAN geht es nicht.** `http://192.168.x.y:8770` waere kein
sicherer Kontext, also gaebe es dort wieder keine Verschluesselung. Nur
`localhost` zaehlt -- deshalb hoert der Server ausschliesslich auf
127.0.0.1, und das ist keine Vorsicht, sondern die einzige Betriebsart, in
der das Portal ueberhaupt arbeitet.

Das oeffnet `http://127.0.0.1:8770` -- der Browser behandelt `localhost` als
sicheren Kontext, also ist die Verschluesselung da. Als Adresse traegt man
die volle Basis ein (`http://…/privat`).

Oeffnet sich der Browser nicht von selbst, sagt das Skript es und nennt die
Adresse -- dann von Hand einfuegen. (Pythons `webbrowser` findet unter Linux
nur dann einen grafischen Browser, wenn `DISPLAY` gesetzt ist; ueber SSH ist
es das nie.)

**Warum nicht einfach die Datei doppelklicken?** Zwei Browserregeln ziehen
gegeneinander: `crypto.subtle` gibt es nur im sicheren Kontext (dazu zaehlt
`file://`) -- aber eine Seite im sicheren Kontext darf keine unsicheren
Inhalte nachladen. Eine `file://`-Seite kann deshalb je nach Browser NICHT
mehr auf einen `http`-Webspace zugreifen. `http://localhost` loest beides:
sicherer Kontext, und weil die Seite selbst `http` ist, entsteht gar keine
Mischung. Am 03.09.2026 im Browser nachgemessen.

Der Gewinn ist in beiden Faellen derselbe, und er ist der eigentliche Grund:

| | Portal vom Webspace | Portal von der eigenen Maschine |
|---|---|---|
| Schutz gegen Fremde im Netz | ja | ja |
| Schutz gegen den **Hoster** | **nein** | **ja** |
| Braucht https beim Hoster | ja | nein |

Kaeme die Seite vom Webspace, koennte der Hoster sie austauschen — und mit
ihr den Schluessel, gegen den verschluesselt wird. Dann verschluesselte das
Portal brav gegen seinen Schluessel, und niemandem fiele etwas auf.
Verschluesselung, deren Schluessel vom Unvertrauten geliefert wird, ist
keine.

Damit das geht, setzt die `.htaccess` auf den statischen Antwortdateien eine
CORS-Kopfzeile. Das ist unbedenklich: Diese Dateien sind ohnehin ohne
Anmeldung abrufbar — sie muessen es sein, sonst gaebe es den Kostenvorteil
nicht — und sie enthalten nur Rauschen.

Die `.htaccess` im Portal-Ordner sichert die Oberflaeche mit einem Passwort.
**Das schuetzt die Dateien nicht** — die liegen verschluesselt nebenan und
sind statisch abrufbar. Das Passwort ist die Haustuer; die Verschluesselung
ist der Grund, warum im Vorgarten nichts Lesbares liegt.

---

## Was geprueft ist

```
relay.php, statisch                       14 Pruefungen
Noise IK in Python                        53 Pruefungen   gegen offizielle Testvektoren
Noise IK in JavaScript                    13 Pruefungen   gegen dieselben Vektoren
Durchstich mit Client, Portal, Angriffen  34 Pruefungen
Portal gegen den laufenden Betrieb         6 Pruefungen   ueber bplaced, echtes PHP
Portal im echten Browser                  gemessen      Auflisten, Hochladen, Rundlauf
```

Der letzte Punkt hat einen Fehler gefunden, den keine der anderen Pruefungen
finden konnte: **Ein 404 vom Hoster kommt ohne CORS-Kopfzeile.** Das Portal
fragte im Takt nach der Antwortdatei und bekam bis zu deren Eintreffen
lauter 404 -- die im Browser nicht als 404 ankommen, sondern als Netzfehler.
Node kennt keine CORS-Pruefung, die Attrappe lief gleiche Herkunft; nur ein
echter Browser gegen einen echten Hoster konnte es zeigen.

Behoben wurde es nicht mit einer Serverregel (weder `FilesMatch` noch ein
eigenes `ErrorDocument` liessen sich gegen bplaced durchsetzen), sondern im
Protokoll: Die Warteschlange nennt jetzt in `fertig` die Marken, deren
Antwort bereitliegt. Beide Clients warten darauf und fragen erst dann --
einmal, und mit Erfolg. Das spart nebenbei Abrufe: Ein Blick in die
Warteschlange beantwortet die Frage fuer alle laufenden Vorgaenge.

Die Krypto-Umsetzungen sind **nicht ausgedacht, sondern nachgerechnet**:
`tests/ik_vektoren.json` enthaelt die offiziellen Noise-Testvektoren aus
*snow*, und beide Umsetzungen treffen jeden Geheimtext Byte fuer Byte.

Ein Testvektor beweist allerdings nur, dass jede Seite die Spezifikation
trifft — dass sie **miteinander** reden koennen, zeigt erst
`tests/pruefe_portal.cjs`, das den Browser-Quelltext gegen den echten
Python-Agenten fuehrt.

Sechs absichtliche Verfaelschungen von `krypto.py` wurden alle erkannt. Eine
davon fiel **erst bei der zweiten Transportnachricht** auf — die
Byte-Reihenfolge der Nonce unterscheidet sich zwischen AES-GCM und
ChaCha20-Poly1305, und bis dahin ist der Zaehler null, was in beiden
Reihenfolgen dasselbe ist.

### Gemessene Zeiten (bplaced, 03.09.2026)

```
Auflisten                    1,1 s   ein voller Umlauf
180 KiB hochladen            3,9 s   7 Stuecke
180 KiB zurueckholen         2,7 s
```

Das ist die ungestueckelte Frage, gut fuer Dokumente und einzelne Fotos.
Groessere Dateien gehen ueber `lege_block`: Der Agent haengt sie
blockweise an eine Teildatei, prueft die Pruefsumme des Ganzen und legt
erst dann ab -- begrenzt nur durch `max_bytes` (0 = unbegrenzt je Datei)
und `TEIL_MAX_GESAMT` (4 GiB Zwischenspeicher ueber alle gleichzeitigen
Uebertragungen). Optional laesst sich vor dem endgueltigen Ablegen ein
Virenscanner einhaengen (`virenscan_befehl` in der Konfiguration) --
plattform- und produktunabhaengig, AHPT kennt nur die Kommandozeilen-
Konvention "Exitcode 0 heisst sauber".

---

## Was es nicht gibt, und warum

- **Kein Loeschen und kein Ueberschreiben.** Wer ueberschreiben kann, kann
  loeschen — und ein Loeschen, das als Hochladen daherkommt, faellt
  niemandem auf. Gibt es den Namen schon, zaehlt der Agent hoch:
  `bericht.pdf` wird zu `bericht (2).pdf`, und der Client sagt es.
- **Kein Streaming, kein VPN.** Der Weg traegt Frage und Antwort, keinen
  Paketstrom. Ein bis drei Sekunden Mindestverzoegerung sind die Bauart.
- **Kein `exec`-Handler.** Eine Zeile Konfiguration von einer Fernsteuerung
  entfernt.
- **Kein Mehrbenutzerbetrieb.** Ein Nutzer, ein Schluesselpaar.

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

Auf einem Hoster mit gueltigem https gehoert `https` in die Konfiguration.
Hat der Hoster ein selbstsigniertes Zertifikat, gibt es
`[relay] zertifikat_pin` — dann steht die Gegenstelle kryptografisch fest,
ohne Wurzelzertifikat.

---

## Was der Webspace trotzdem sieht

Verschluesselung verbirgt den Inhalt, nicht die Umstaende: **wann** etwas
abgerufen wird, **wie oft**, **wie gross** die Antwort war und **aus wie
vielen Stuecken** sie bestand. Wer daraus schliessen will, ob jemand zu
Hause ist, kann das.

---

## Ordner anlegen — und warum es keinen Abgleich gibt

Ganz normal per SSH, Dateimanager oder ueber das Portal. **Beides geht, und
es muss nichts synchronisiert werden.**

Das Portal fuehrt keine eigene Ordnerliste. Es zeigt, was der Agent im
Moment der Anfrage wirklich vorfindet — `os.listdir()` auf dem Ordner, den
`wurzel` in der `config.toml` festlegt. Es gibt keine zweite Fassung, die
auseinanderlaufen koennte; eine portalseitige Liste waere genau der
Fehlertyp, an dem in diesem Projekt schon mehrere Bugs gestorben sind.

Wenn ein Ordner leerer aussieht als er ist, sagt der Agent warum: `gekappt`
bei mehr als 500 Eintraegen, `endung_gesperrt` fuer Dateien, deren Endung
nicht freigegeben ist, `versteckt` fuer solche mit fuehrendem Punkt. Eine
unvollstaendige Liste, die wie eine vollstaendige aussieht, ist schlimmer
als eine Fehlermeldung.
