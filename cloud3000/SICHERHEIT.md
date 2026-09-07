# AHPT Cloud 3000 — Sicherheit

Stand 02.09.2026; Abschnitte 3.6 bis 3.8 zu den Transportwegen ergaenzt
am 07.09.2026.

Dieses Dokument sagt, **was haelt, was wackelt und was ausdruecklich nicht
geschuetzt ist.** Es ist kein Werbetext. Wer AHPT betreibt, soll hier
erfahren, wogegen er geschuetzt ist — und wogegen nicht, bevor es ihn
trifft.

Die Angriffsanalyse in Abschnitt 3 stammt aus `../Zukunftsmusik.txt` und
wurde gegen den Quelltext nachgeprueft. Wo die Pruefung etwas anderes ergab
als die Analyse, steht das dabei.

---

## 1. Das Bedrohungsmodell

Drei Beteiligte, und sie haben sehr verschiedene Rechte:

| Wer | Kann | Muss man ihm glauben? |
|---|---|---|
| **Besucher** | Fragen stellen, statische Dateien lesen | Nein. Jeder im Internet ist ein Besucher. |
| **Vermittler** (Webspace) | Fragen und Antworten sehen und veraendern | Teilweise. Er sieht alles, was durchgeht. |
| **Agent** (zu Hause) | Antworten ablegen, lokale Dienste bedienen | Ja — er weist sich aus. |

Der Angreifer, gegen den hier gebaut wird, ist ein **beliebiger Fremder im
Internet**, der die oeffentliche Adresse kennt. Er darf alles tun, was ein
Besucher tun kann, beliebig oft und beliebig boesartig.

### Der eine Satz, an dem alles haengt

> **Was geschehen kann, wird ausschliesslich zu Hause festgelegt.
> Von aussen kommt nur die Auswahl daraus.**

Kein Feld im Protokoll traegt eine Adresse, einen Befehl, einen Pfad
ausserhalb einer Wurzel oder eine Faehigkeit. Immer nur einen **Namen aus
einer Liste, die in der `config.toml` des Agenten steht**. Wer dem Protokoll
ein Feld hinzufuegt, in das eine Zieladresse passt, hat AHPT in einen
offenen Proxy ins Heimnetz verwandelt — Drucker, Router, NAS, bedienbar von
der oeffentlichen Seite aus. Das ist der eine Fehler, der alles kaputtmacht.

### Und die eine Sache, die strukturell nicht geht

**Der Weg ist oeffentlich, und zwar zwangslaeufig.** Der Agent muss die
Frage ohne PHP lesen koennen — sonst gibt es den Kostenvorteil nicht, und
ohne den gibt es keinen Grund fuer AHPT. Also liegt sie in einer statischen
Datei. Also kann jeder sie lesen, der die Marke aus der Warteschlange nimmt.
Dasselbe gilt fuer die Antwort.

Das ist keine Luecke, die man schliessen koennte, ohne den Entwurf
aufzugeben. Es ist der Preis. Siehe 3.1.

---

## 2. Was haelt

Jeder Punkt hier ist gemessen, nicht behauptet. Die Pruefung steht dabei.

### 2.1 SSRF ins Heimnetz — abgewehrt

Der gefaehrlichste denkbare Fehler: ein Agent, der eine uebergebene Adresse
abruft. Dann ist er ein offener Proxy ins Heimnetz.

Drei Schranken, keine genuegt allein:

1. **Es gibt kein Adressfeld.** Eine Frage ist `{dienst, aktion, daten}`.
   `dienst` waehlt aus einer Zuordnung, die in der `config.toml` steht.
2. **`netz.ziel_erlaubt()`** laesst als Handler-Ziel nur `127.0.0.1`,
   `localhost` und `::1` zu, und nur als blosse Basis ohne Pfad. Ein
   Tippfehler in der Konfiguration wird beim Start abgewiesen, nicht im
   Betrieb.
3. **Keine Weiterleitungen.** Ein Redirect koennte aus `127.0.0.1` etwas
   anderes machen. `netz.py` schaltet sie ab, auf beiden Seiten.

*Geprueft:* Handler-Selbsttest, 6 Zielfaelle je kiwix-Dienst
(`relay_agent.py --selbsttest`).

### 2.2 Pfadwanderung — abgewehrt

`handler/datei.py` ist die gefaehrlichste Stelle des Projekts. Drei
voneinander unabhaengige Schranken:

1. **Form** — geprueft, bevor das Dateisystem beruehrt wird: kein
   fuehrender Schraegstrich, kein Rueckwaertsschraegstrich, kein `.` oder
   `..` als Bestandteil, keine versteckten Namen, kein Doppelpunkt, keine
   Steuerzeichen, begrenzte Laenge.
2. **Lage** — der aufgeloeste Pfad (`realpath`, also mit verfolgten
   Verknuepfungen) muss innerhalb der aufgeloesten Wurzel liegen. Das faengt
   ab, was die Form nicht sieht: eine symbolische Verknuepfung nach draussen.
3. **Art** — nur gewoehnliche Dateien, und wenn konfiguriert, nur erlaubte
   Endungen.

Zusaetzlich lehnt der Handler beim Start eine Wurzel ab, die auf `/` oder
das Benutzerverzeichnis zeigt.

*Geprueft:* 19 Pfadfaelle plus Verknuepfungs- und Endungsfaelle im
Handler-Selbsttest; 4 Angriffe im Durchstich gegen echtes PHP.

**Anmerkung:** Der Verknuepfungs-Fall wird auf Windows **uebersprungen** —
dort lassen sich ohne Entwicklermodus keine symbolischen Verknuepfungen
anlegen. Der Selbsttest sagt das ausdruecklich, statt „ok" zu melden.

### 2.3 Gefaelschte Antworten — abgewehrt, solange das Geheimnis geheim ist

Ohne Ausweis koennte jeder eine Antwort einschleusen, und sie erschiene beim
Besucher als echter Inhalt — schlimmer als gar keine Antwort, weil sie
geglaubt wird.

Geteiltes Geheimnis, mindestens 16 Zeichen, Vergleich mit `hash_equals`
(konstante Zeit). Es reist **nur** in der Kopfzeile `X-AHPT-Auth`, **nur**
ueber `https` (Ausnahme allein Loopback), und es erscheint in keiner
Fehlermeldung und keiner Diagnoseausgabe.

Die Geheimnisdatei heisst `.php` und beginnt mit einer Zeile, die PHP sofort
beendet — der Server *fuehrt sie aus* und gibt nichts aus. **Der Schutz
steckt in der Datei, nicht in der Konfiguration.** Am 02.09.2026 meldete ein
Uploader eine neue `.htaccess` zweimal mit gruenem Haken, waehrend auf dem
Server die alte lag. Ein Schutz, der davon abhaengt, dass eine
Konfigurationsdatei ankommt, ist besonders tueckisch: ein ungeschuetztes
Geheimnis funktioniert genauso gut wie ein geschuetztes.

*Geprueft:* Durchstich gegen echtes PHP — beide empfindlichen Dateien
liefern 0 Bytes, Ablage ohne Geheimnis wird mit 403 abgewiesen, der
Selbsttest gibt das Geheimnis nicht heraus.

Zum Bruch dieser Schranke siehe 3.3.

### 2.4 Stille Verfaelschung durch `mod_speling` — abgewehrt

Apache haelt zwei Dateinamen, die sich um **ein** Zeichen unterscheiden,
fuer einen Tippfehler und leitet per HTTP 301 um. Am 02.09.2026 gemessen:
die Abfrage nach der ANTWORT landete bei der FRAGE, und `fetch` folgte
stillschweigend.

Bei gestueckelten Antworten waere die Lage dieselbe — fehlt Stueck 3, weil
der Agent es gerade ablegt, kaeme statt 404 eine Umleitung auf Stueck 2, und
der Browser setzte eine Datei zusammen, in der Stueck 2 zweimal steht. Keine
Fehlermeldung, nur eine **verfaelschte Datei**.

Fuenf Schranken:

1. Getrennte Namensstaemme `frage_` / `antwort_`.
2. Stueck-Dateinamen tragen vier abgeleitete Hexzeichen, damit benachbarte
   Stuecke nie eine Zeichenaenderung auseinanderliegen.
3. Jede Datei traegt ihre Marke im Inhalt; der Client prueft sie.
4. Jedes Stueck traegt seine Nummer; der Client prueft sie.
5. `redirect: 'error'` im SDK und keine Weiterleitungen im Agenten.

`CheckSpelling Off` in der `.htaccess` ist die **sechste**, nicht die erste
— sie muss ankommen, und das tut sie nachweislich nicht immer.

*Geprueft:* Durchstich lokal misst, dass benachbarte Stuecknamen mehr als
ein Zeichen auseinanderliegen; 300 KiB ueber neun Stuecke kommen Byte fuer
Byte gleich an.

### 2.5 Uebersehene Aenderung durch den ETag — abgewehrt

Kein Angriff, sondern ein Ausfall — aber einer, der wie Stille aussieht.

Apache bildet den ETag standardmaessig aus **Aenderungszeit in ganzen
Sekunden** und **Groesse**. Zwei Warteschlangen mit je einem Eintrag sind
exakt gleich lang. Gemessen:

```
Warteschlange mit Marke A       97 Bytes   ETag "6a9825a5-61"
... beantwortet, Schlange leer  34 Bytes   ETag "6a9825a5-22"
Warteschlange mit Marke B       97 Bytes   ETag "6a9825a5-61"   <-- gleich
```

Hat der Agent den leeren Zwischenstand nicht gesehen, bekommt er `304` und
uebersieht die Frage — dauerhaft, weil die Datei danach nicht mehr angefasst
wird. Der Besucher wartet, der Agent meldet „keine Fehler".

Drei Schranken: unbedingter Abruf alle 30 s (`unbedingt_nach`), eine
fortlaufende Nummer `folge` in der Warteschlange, an der der Agent eine
uebersehene Aenderung **erkennt und meldet**, und `FileETag INode MTime
Size` in der `.htaccess`.

*Geprueft:* Der Durchstich fuehrt die Falle **gezielt** herbei und stellt
fest, ob sie zugeschnappt ist, bevor er die Gegenmassnahme prueft.

---

## 3. Was wackelt

### 3.1 Vertraulichkeit — offen, und zwar bauartbedingt

**Jeder im Internet kann `ahpt/warteschlange.json` abrufen, die Marke
nehmen und damit Frage und Antwort mitlesen.**

Wer AHPT einsetzt, muss das wissen: Ueber diesen Weg reist nichts, was nicht
oeffentlich sein darf. Keine Direktnachricht, kein Schluessel, nichts
Persoenliches, nichts aus einem Notfallzusammenhang.

**Eine Praezisierung zur Analyse:** Sie schreibt, ein Angreifer sehe „in
Echtzeit, **wer** wann nach welchen Begriffen sucht". Das *Was* stimmt. Das
*Wer* nicht: Der Absender steht **gesalzen** in `relay_state.php` und
gerade nicht in der oeffentlichen Warteschlange — die traegt nur Marke und
Zeit, und die Marke ist 128 Bit Zufall. Gesalzen, **weil** ein SHA-256 ueber
eine IPv4 eine Adresse in Verkleidung waere: 2^32 Moeglichkeiten sind in
Sekunden durch.

Der Verlust ist also **Inhaltsvertraulichkeit, nicht Anonymitaet**. Diese
Trennung ist die eine Sache, die sich hier billig schuetzen liess, und sie
haelt.

**Warum keine Verschluesselung eingebaut ist:** Der Umschlag traegt das Feld
`krypto` von Anfang an, mit genau einem erlaubten Wert: `keine`. Jeder
andere wird **abgewiesen**, nicht ignoriert. Ohne Fremdbibliothek gibt es in
Python kein X25519 und kein AES-GCM; die drei Auswege waeren eine
Abhaengigkeit (bricht die 0-Abhaengigkeits-Zusage), selbstgeschriebene
Kryptografie, oder etwas, das nach Verschluesselung *aussieht*. Der dritte
ist der gefaehrlichste: **Eine Antwort, der man glaubt, ist schlimmer als
keine.** Wer seinen Kanal fuer vertraulich haelt, schickt Dinge hindurch,
die er sonst nicht schicken wuerde.

Der Entwurf steht in `ARCHITEKTUR.md` Abschnitt 8. Gebaut wird er als
eigener, gemessener Schritt — nicht nebenbei.

### 3.2 Queue-Jamming — verteuert, nicht geloest

Der Angriff: Die Warteschlange fassst `MAX_OFFEN = 40` Fragen. Wer sie
fuellt und gefuellt haelt, sperrt alle anderen aus.

**Was am 02.09.2026 geaendert wurde:**

*Erstens*, der Absender wird als **Netz** gezaehlt, nicht als Adresse
(`absender_kennung()`): IPv4 voll, IPv6 auf das /64. Vorher ging
`MAX_JE_IP = 5` ueber IPv6 vollstaendig ins Leere — ein einzelner Anschluss
bekommt regelmaessig ein ganzes /64, also 2^64 „verschiedene Absender". Es
brauchte kein Botnetz und keine Proxys.

Dieselbe Zeile hatte die umgekehrte Schlagseite: Hinter CGNAT teilen sich
**echte** Besucher eine IPv4 und bekamen zusammen fuenf Plaetze. Also zu
lasch gegen Angreifer und zu streng gegen genau die Zielgruppe, die AHPT
bedienen soll.

*Zweitens*, bei voller Schlange wird **verdraengt statt abgewiesen**: Dem
Absender mit den meisten Plaetzen wird sein aeltester genommen. Wer genau
einen Platz haelt, wird nie verdraengt, solange irgendjemand zwei haelt.

**Was das NICHT loest — bitte nicht schoenreden:**

Vorher genuegten acht IP-Adressen. Jetzt braucht ein Angreifer **vierzig
verschiedene /64-Netze**, die je genau einen Platz halten. Dann ist die
Schlange „ehrlich voll", niemand wird verdraengt, und alle bekommen 503.
Wer ueber ein /48 verfuegt, hat 65536 solcher Netze.

**Die billige Variante ist zu, die teure nicht.**

**Am 04.09.2026 geprueft und bewusst zurueckgestellt:** eine zweite,
groebere Bucket-Stufe (`/32` statt `/64`) mit eigenem Kontingent und
eigenem fairen Verdraengen, gefaltet in dieselbe Schleife ueber `offen` --
also ohne Geschwindigkeitsnachteil. Dagegen sprach nicht die Umsetzung,
sondern die Abwaegung:

* Mehr Zustand in genau der Closure, in der `$k` bereits einmal
  ueberschrieben wurde -- zwei Bucket-Ebenen statt einer sind zwei
  Gelegenheiten fuer denselben Fehlertyp.
* Der Grenzwert fuer die `/32`-Stufe hat keine sauberere Herleitung als
  „irgendeine Zahl" -- anders als `MAX_JE_IP = 20`, das aus dem
  Blaetterverhalten des Portals folgt.
* Es schliesst die Luecke nicht, es verschiebt sie nur -- ein `/29` oder
  groesser haebelt eine `/32`-Schranke genauso aus.
* Die Adresse ist nirgends beworben. Der Angriff braucht sowohl ein
  geroutetes `/48`-Netz als auch das Wissen um genau diese private URL --
  beides zusammen ist unwahrscheinlich genug, dass der
  Komplexitaetszuwachs den Nutzen aktuell nicht aufwiegt.

Kein Fall von „nie geprueft" -- eine Neubewertung lohnt sich, sobald sich
etwas an dieser Einschaetzung aendert (z. B. die Adresse wird doch einmal
sichtbar, oder ein tatsaechlicher Verdraengungs-Vorfall wird im
`selbsttest` gezaehlt).

Ein verdraengter Platz kostet ausserdem einen echten Besucher seine Antwort
— er wartet bis zum Zeitablauf. Deshalb wird jedes Verdraengen gezaehlt und
im `selbsttest` ausgewiesen. Steht dort etwas anderes als 0, versucht
jemand, die Warteschlange zu besetzen.

**Warum kein Proof-of-Work:** Der Vorschlag aus der Analyse wurde geprueft
und verworfen. PoW verteuert die **Rate**; dieser Angriff hat keine hohe
Rate, er **haelt** Plaetze. Vierzig Plaetze alle zwei Minuten kosten bei
100 ms Rechenzeit ganze vier Sekunden — das bremst niemanden, waehrend ein
altes Handy die 100 ms bei jeder Frage bezahlt. Die Begruendung steht
ausfuehrlich im Quelltext bei der Verdraengungslogik.

### 3.3 Der boese Nachbar auf Shared Hosting — offen

Auf billigem Shared Hosting teilen sich oft hunderte Kunden einen Server.
Wenn der Anbieter `open_basedir` oder die Dateirechte nicht wasserdicht
isoliert, kann ein anderer Kunde per PHP-Skript `relay_token.php` **vom
Dateisystem** lesen — die `<?php exit;`-Zeile schuetzt nur gegen Auslieferung
ueber HTTP, nicht gegen einen Leser auf demselben Rechner.

Wer das Geheimnis hat, kann beliebige Antworten einschleusen, und sie
erscheinen beim Besucher als echter Inhalt.

**Es gibt dagegen keine Massnahme im Quelltext.** Was hilft, sind
Betriebsentscheidungen — siehe 6.

Wichtig: Betroffen ist nicht nur das Geheimnis. Ein Nachbar, der Dateien
lesen kann, liest auch `relay_state.php` (die gesalzenen Absender) und jede
Frage- und Antwortdatei.

### 3.4 Ressourcenhunger am Heimknoten — offen

Der Vermittler begrenzt die Zahl **gleichzeitig offener** Fragen. **Eine
Begrenzung pro Zeit gibt es nirgends** — weder im Vermittler noch im
Agenten.

Ein Angreifer kann also formal einwandfreie, aber teure Anfragen stellen:
Suchen nach sehr haeufigen Woertern in einem 48-GiB-Archiv, oder wiederholt
Dateien in Maximalgroesse. Ein Raspberry Pi laeuft dann auf 100 % Last, und
der Upstream einer DS-Lite-Leitung ist mit dem Hochladen der Stuecke dicht.

**Nicht behoben.** Die naheliegende Massnahme waere ein Token-Bucket je
Absender und global im Agenten, dazu ein Deckel auf gleichzeitig laufende
teure Anfragen. Bis dahin gilt: `max_bytes` klein halten und, wenn moeglich,
teure Aktionen in der `config.toml` gar nicht erst freigeben — `aktionen`
ist der Schnitt aus dem, was der Handler kann, und dem, was freigegeben ist.

### 3.5 XSS beim Web-Entwickler — entschaerft, nicht ausgeschlossen

Das SDK liefert reinen Text oder Bytes, nie HTML zum Einbetten. Aber es
kann nicht verhindern, dass ein Entwickler schreibt:

```js
document.getElementById('ergebnis').innerHTML = a.text;   // <-- XSS
```

Da die Warteschlange oeffentlich ist, kann ein Angreifer eine Frage
einstellen, deren Antwort sein Nutzlast enthaelt.

**Eine Praezisierung zur Analyse:** Sie beschreibt den Umweg ueber
Dateiinhalte. Der kuerzere Weg ist `titel`: Bei einer Suche **ist** der
Titel der Suchbegriff (`handler/kiwix.py`), bei einer Datei der angefragte
Pfad (`handler/datei.py`). Ein Angreifer braucht also weder eine Datei noch
ein Archiv — nur eine Frage.

**Was geaendert wurde:** `titel` und `quelle` werden entschaerft — an einer
Stelle im Agenten (`handler/__init__.py`, wo jede Antwort entsteht) und als
zweite Schranke im Vermittler, weil ein Agent mit gestohlenem Geheimnis die
erste nicht bedienen wuerde. Steuerzeichen und spitze Klammern fallen weg,
Laenge auf 200 Zeichen begrenzt. Ohne spitze Klammern laesst sich kein Tag
oeffnen.

**`inhalt` bleibt unangetastet, und das ist Absicht.** Wer die Nutzlast
saeubert, liefert nicht mehr aus, sondern verfaelscht — eine Datei mit
entfernten Zeichen ist keine Datei mehr.

**Das macht `innerHTML` also NICHT sicher.** Es nimmt der schaerfsten Kante
die Spitze. Der richtige Weg steht in 7.

---

### 3.6 Der WebDAV-Vermittler ist ein Konto, kein anonymer Webspace — offen

Das ist der Punkt, an dem sich AHPT Cloud 3000 sicherheitstechnisch vom
PHP-Weg unterscheidet, und er ist nicht klein.

Ein PHP-Webspace ist ein gemieteter Briefkasten. Ein WebDAV-Speicher bei
einem E-Mail-Anbieter ist **dieselbe Anmeldung wie das Postfach**. Daraus
folgt dreierlei:

1. **Wer das Passwort erbeutet, hat mehr als den Vermittler.** Beim
   PHP-Weg ist das gestohlene Geheimnis genau eine Vollmacht: Antworten
   ablegen. Mitlesen kann der Dieb nicht (Noise), und mehr als stoeren
   auch nicht. Beim WebDAV-Weg haengt am selben Zugang in aller Regel
   das E-Mail-Postfach — und damit die Passwort-vergessen-Funktion jedes
   anderen Dienstes.

   **Gegenmassnahme, und sie ist nicht wahlfrei:** ein **eigenes Konto**
   nur fuer diesen Zweck, nicht das private, und darin ein
   **anwendungsspezifisches Passwort** (bei aktivierter
   Zwei-Faktor-Anmeldung), nie das Hauptpasswort. Ein solches Passwort
   laesst sich einzeln widerrufen und oeffnet keine Weboberflaeche.

2. **Basic-Auth traegt das Passwort in JEDER Anfrage mit.** Deshalb ist
   ein WebDAV-Weg ohne `https` nicht vertretbar — anders als beim
   PHP-Weg, wo `http` mit Noise noch eine verteidigbare Rechnung hat
   (siehe README). Der Agent laesst `http` bei WebDAV nicht zu.

3. **Der Anbieter kennt einen Namen.** Beim Webspace sieht der Betreiber
   Verkehr; beim WebDAV-Konto sieht er Verkehr **eines identifizierten
   Kontoinhabers**, mit Anmeldedaten, Zahlungsweg und Bestandsdaten. Am
   Inhalt aendert das nichts — Noise bleibt Noise —, an den Umstaenden
   sehr wohl. Wer das nicht will, nimmt den PHP-Weg.

Das Passwort steht in einer eigenen Datei, eine Zeile, sonst nichts, wie
das Geheimnis beim PHP-Weg. Es taucht in keiner Meldung, keinem Pfad und
keinem Protokoll auf — `tests/pruefe_transport.py` prueft das.

### 3.7 Die Nutzungsbedingungen — Graubereich, kein gruenes Licht

Fuer GMX nachgelesen am 06.09.2026:

- **§2.5.3.1** verbietet automatisierte Massen-*Registrierung, -Anmeldung
  und -Einwilligung* (netID). Betrifft diesen Fall nicht — hier werden
  bestehende Zugangsdaten benutzt, es wird nichts angelegt.
- **§4.2** ist die einschlaegige Klausel: keine Daten senden, die „den
  Bestand oder Betrieb des Rechenzentrums oder Datennetzes von GMX
  gefaehrden". Der gemessene Takt liegt weit darunter.
- **§17.10**: Funktionen duerfen jederzeit aus Stabilitaetsgruenden
  geaendert oder abgeschaltet werden. Keine Zusage auf Verfuegbarkeit.
- **§4.4**: Verstoesse gegen die allgemeinen Regeln koennen zur
  **sofortigen Sperrung** fuehren.

Ein ausdrueckliches Verbot automatisierten Zugriffs auf die *eigene*
Cloud liess sich nicht finden. Eine ausdrueckliche Erlaubnis aber auch
nicht: Die Bedingungen sind auf Privatnutzer zugeschnitten, nicht auf
Programme. Das ist ein Graubereich, und er ist als solcher zu behandeln —
**ein WebDAV-Weg kann jederzeit wegbrechen, samt Konto**. Genau dafuer
gibt es mehrere Wege und den Kreislauf-Unterbrecher; ein Betrieb, der auf
einem einzelnen Gratiskonto ruht, ruht auf nichts.

Quellen: [AGB GMX](https://agb-server.gmx.net/gmxagb-de),
[Anwendungsspezifisches Passwort](https://hilfe.gmx.net/sicherheit/2fa/anwendungsspezifisches-passwort.html),
[Netzlaufwerk unter Windows](https://hilfe.gmx.net/cloud/netzlaufwerk/windows-10.html).

### 3.8 Die Kennung — eine bewusste Taeuschung, und umstellbar

**Die Vorgabe gibt sich als Browser aus.** `netz.KENNUNG` traegt eine
gewoehnliche Chrome-Kennung statt eines selbstnennenden Werts wie
`AHPT-Agent/1`. Das ist kein Versehen und keine Nebensache, deshalb steht
es hier und nicht nur im Quelltext.

**Was es bewirkt:** Ein selbstnennender Wert steht im Klartext in jedem
einzelnen Zugriffs-Log jedes Anbieters und ist die einfachste Art,
diesen Verkehr wiederzuerkennen, auszuzaehlen und zu drosseln. Die
Browser-Kennung taeuscht eine solche einfache Auswertung.

**Was es nicht bewirkt:** Alles, was tiefer greift — TLS-Fingerabdruck,
fehlende browsertypische Zusatz-Kopfzeilen, das Zugriffsmuster selbst
(ein Browser pollt keine Datei im Sekundentakt ueber Stunden) — bleibt
unberuehrt. Wer ernsthaft sucht, findet. Eine Kopfzeile ist Tarnung
gegen die Statistik, nicht gegen einen Menschen, der hinsieht.

**Die Abwaegung, ehrlich:** Das ist der eine Punkt, an dem dieses
Programm dem Anbieter gegenueber etwas anderes behauptet, als es ist.
Wer im Graubereich aus 3.7 arbeitet, sollte wissen, dass er das tut. Es
gibt gute Gruende dagegen: Ein Anbieter, der die eigenen Regeln
durchsetzen will, hat ein legitimes Interesse daran, seinen Verkehr zu
kennen; und eine Sperrung nach §4.4 wiegt schwerer, wenn die Tarnung
dokumentiert ist. Es gibt auch einen dafuer: Ein Kennzeichen, das nur
dieses eine Programm trifft, laedt zu einer Sperre ein, die mit Last
nichts zu tun hat.

**Die Entscheidung liegt beim Betreiber**, nicht im Auslieferungszustand
festgenagelt:

```toml
[relay]
kennung = "AHPT-Agent/1"
```

Der Agent gibt die gerade gueltige Kennung **beim Start im Klartext
aus** und sagt dazu, wenn die Vorgabe gilt. Wer sie nicht will, soll sie
sehen, ohne im Quelltext danach suchen zu muessen.

---

## 4. Die Tabelle

| Angriff | Stand | Warum |
|---|---|---|
| SSRF ins Heimnetz (Drucker, Router, NAS) | **abgewehrt** | Kein Adressfeld, harte Weissliste, nur Loopback, keine Weiterleitungen |
| Pfadwanderung (`/etc/passwd`) | **abgewehrt** | Drei Schranken: Form, `realpath`-Eingrenzung, Dateiart |
| Fremde Antworten faelschen | **abgewehrt** | `X-AHPT-Auth` mit `hash_equals`, solange das Geheimnis geheim bleibt |
| Stille Verfaelschung (`mod_speling`) | **abgewehrt** | Fuenf Schranken, Marken- und Stueckpruefung im Client |
| Uebersehene Aenderung (ETag) | **abgewehrt** | Unbedingter Abruf, `folge`-Zaehler, `FileETag INode` |
| Lauschen auf Fragen und Antworten | **offen** | Bauartbedingt. Nichts Vertrauliches durch diesen Weg. |
| Queue-Jamming (Denial of Service) | **verteuert** | Statt 8 Adressen jetzt 40 verschiedene /64 noetig |
| Boeser Nachbar auf Shared Hosting | **offen** | Keine Massnahme im Quelltext moeglich, nur im Betrieb |
| Ressourcenhunger am Heimknoten | **offen** | Keine Begrenzung pro Zeit |
| XSS beim Web-Entwickler | **entschaerft** | `titel` ohne spitze Klammern; `inhalt` bleibt beliebig |
| Absender-Deanonymisierung | **abgewehrt** | Gesalzener Hash, nie in der oeffentlichen Warteschlange |
| Gestohlenes WebDAV-Passwort | **offen** | Haengt am Postfach. Nur eigenes Konto + anwendungsspezifisches Passwort begrenzen den Schaden |
| Sperrung des WebDAV-Kontos | **offen** | AGB-Graubereich. Mehrere Wege begrenzen den Ausfall, verhindern ihn nicht |
| Wiedererkennung durch den Anbieter | **erschwert** | Browser-Kennung als Vorgabe; gegen tiefere Erkennung wirkungslos, umstellbar |

---

## 5. Fuer wen AHPT betreibt

1. **Geheimnis und Zustand ausserhalb des Dokumentenstamms ablegen.** Die
   Pfade stehen als Konstanten am Kopf von `relay.php`. Das ist die einzige
   wirksame Massnahme gegen 3.3, und sie kostet nichts.
2. **Ein eigenes Geheimnis je Installation**, mindestens 32 Zeichen aus
   einem kryptografischen Zufallsquell. Nach jedem Verdacht wechseln — auf
   beiden Seiten, Webspace zuerst.
3. **`.htaccess` mit ausliefern**, aber sich nicht auf sie verlassen. Nach
   dem Hochladen nachmessen:
   ```bash
   curl -s https://example.de/ahpt/relay_token.php | wc -c   # muss 0 sein
   curl -s 'https://example.de/ahpt/relay.php?action=selbsttest'
   ```
4. **`verdraengt` im Selbsttest beobachten.** Alles ausser 0 heisst, dass
   jemand die Warteschlange zu besetzen versucht.
5. **`endungen` in der `config.toml` setzen.** Eine leere Liste heisst:
   alles aus diesem Ordner geht hinaus, was die drei Pfadschranken passiert.
   Der Agent sagt das beim Start laut — aber besser, es steht gar nicht
   erst so da.
6. **`aktionen` so eng wie moeglich.** Wer nur ausliefern und nichts
   auflisten will, nimmt nur `hole`.
7. **Nichts Vertrauliches durch diesen Weg.** Siehe 3.1.
8. **Fuer jeden WebDAV-Weg ein eigenes Konto und ein
   anwendungsspezifisches Passwort.** Nicht das private Postfach, nie das
   Hauptpasswort. Siehe 3.6 — das ist die einzige Massnahme, die den
   Schaden eines gestohlenen Passworts begrenzt.
9. **Jeder PHP-Weg bekommt sein eigenes Geheimnis.** Ein gemeinsames
   waere ein gemeinsamer Schaden: Wer es auf dem schwaechsten Hoster
   findet, hat es fuer alle.
10. **Zwei Wege bei zwei unabhaengigen Anbietern**, wenn Verfuegbarkeit
    zaehlt — zwei Marken desselben Konzerns sind ein Anbieter. Sonst
    ueberlebt die Redundanz genau die Ausfaelle nicht, gegen die sie
    gedacht war.
11. **Entscheiden, was in `kennung` steht.** Die Vorgabe taeuscht. Siehe
    3.8; der Agent sagt es beim Start.

---

## 6. Fuer wen das SDK benutzt

**Nie `innerHTML`.** Das SDK bringt den kuerzeren richtigen Weg mit:

```js
const a = await relay.frage('wiki', 'suche', { begriff: eingabe });
AhptClient.zeige(document.getElementById('ergebnis'), a.text);
```

`zeige()` schreibt immer nach `textContent`. Genauso kurz wie `innerHTML`,
und richtig.

Wer HTML braucht, muss den Inhalt selbst saeubern — und zwar in dem Wissen,
dass er aus einer oeffentlich beschreibbaren Warteschlange stammt.

`a.bytes` ist ein `Uint8Array`. Wer daraus eine Blob-URL baut und in ein
`<iframe>` haengt, hat dasselbe Problem mit anderen Mitteln.

---

## 7. Was ausdruecklich nicht geprueft ist

Ehrlichkeit ueber die Reichweite der Messungen gehoert in ein
Sicherheitsdokument, sonst ist es eines nur dem Namen nach.

| Nicht geprueft | Warum |
|---|---|
| **Betrieb gegen echtes Apache** | Bisher nur gegen `php -S`. Damit fehlen ETag/304, `mod_speling` und die Prozessgrenze — genau die drei, die im Betrieb zugeschlagen haben. |
| **Gleichzeitige Zugriffe** | `flock` ist gesetzt, aber nie unter Last gemessen. |
| **Verhalten unter echtem DoS** | Die Verdraengungslogik ist gegen eine Attrappe geprueft, nicht gegen einen echten Ansturm. |
| **Andere Webspace-Sorten** | Gemessen wurde gegen IONOS. Strato, Netcup und Hetzner duerften dieselbe Asymmetrie zeigen — gemessen ist das nicht. |
| **Betrieb durch jemand anderen** | Alle Messungen stammen von einem Aufbau. |
| **Symbolische Verknuepfungen auf Windows** | Nicht anlegbar, deshalb uebersprungen — und als uebersprungen ausgewiesen. |

**Der eine Fehler, der den ersten Live-Lauf gekostet hat, war
`mod_speling` — und keine lokale Pruefung haette ihn gefunden.**

Was ein Testaufbau nicht hat, kann er nicht messen.

---

## 8. Wie geprueft wird

```bash
python3 tests/pruefe_relay_php.py                       # 14 statische Pruefungen
python3 relay_agent.py --konfig config.toml --selbsttest # Schranken, ohne Netz
python3 tests/durchstich_lokal.py                        # Agent + Client (Attrappe)
bash    tests/durchstich.sh                              # gegen echtes PHP
bash    tests/durchstich.sh https://example.de/ahpt      # vollstaendig
```

Zwei Regeln, die dabei gelten:

**Ein Handler ohne Selbsttest wird nicht geladen.** Er ist die Stelle, an
der die Weissliste steht — und eine Weissliste, deren Wirkung niemand
nachprueft, ist eine Behauptung.

**Ein Test, der nicht messen kann, was er messen soll, muss das sagen.** Der
Verknuepfungs-Fall meldet „UEBERSPRUNGEN", nicht „ok". Die Pruefung von
`relay_state.php` meldet „nichts gemessen", wenn es die Datei noch nicht
gibt. Und `tests/durchstich_lokal.py` stellt erst fest, ob die ETag-Falle
ueberhaupt zugeschnappt ist, bevor es die Gegenmassnahme prueft.
