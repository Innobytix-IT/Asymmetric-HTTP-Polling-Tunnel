# Die Entstehung von AHPT: Protokoll-Genese und modulare Architektur

*Stand: September 2026 / Urheber: InnoBytix-IT (Manuel Person)*

---

## 1. Der Ausgangspunkt: Die Restriktion des Consumer-Internets

Seit Jahren stellen Netzbetreiber private Internetanschlüsse wegen des
flächendeckenden Mangels an IPv4-Adressen standardmäßig auf **DS-Lite
(Dual-Stack Lite) und CG-NAT (Carrier-Grade NAT)** um — eine seit langem
etablierte, nicht erst 2026 entstandene Realität. Im Sommer 2026 erreichte
diese Einschränkung für die Self-Hosting- und Open-Source-Community einen
Punkt, an dem sie nicht länger hingenommen wurde: Eigene Server,
Smart-Home-Zentralen oder lokale Datenarchive waren aus dem globalen
IPv4-Internet von außen nicht mehr direkt erreichbar.

Das etablierte Paradigma der Netzwerktechnik bot hierfür feste, aber
unbefriedigende Lösungswege:

* Den Aufbau permanenter, synchroner Tunnel (Reverse Proxies) über eine
  extern gemietete und zu wartende Gegenstelle mit öffentlicher IP
  (vServer/VPS).
* Die vollständige Übergabe des Datenverkehrs an kommerzielle,
  mitlesende Cloud-Anbieter, die als intermediäre Proxies agieren.

Das Ziel von InnoBytix-IT war die Konstruktion einer Alternative:
**wartungsfrei im Betrieb (serverlos auf Betreiberseite), unabhängig von
Infrastruktur-Konzernen und ohne Modifikation von Router-Firewalls
(Portfreigaben).** Wie im Folgenden nachgezeichnet, war das kein
vorgefasster Plan, sondern das Ergebnis eines Tages, an dem jeder dieser
drei Wege einzeln geprüft und aus konkretem, nachvollziehbarem Grund
verworfen wurde.

---

## 2. Die Herleitung: Wie die Idee tatsächlich entstand

Anders als eine nachträgliche Erzählung es nahelegen könnte, entstand der
zentrale Gedanke von AHPT nicht in einem einzelnen Moment, sondern über
einen vollen Tag verteilt — in einer fortlaufenden, oft mühsamen
Befragung der künstlichen Intelligenz **Claude** durch den Entwickler
Manuel Person. Der Weg dahin enthält mehrere echte Sackgassen, eine
eigene sicherheitsrelevante Entdeckung und ein Prinzip, das lange vor der
eigentlichen Datei-Idee bereits feststand.

### 2.1 Die Standardfrage (01.09.2026, nachts)

Der Auftakt war unspektakulär: „ich habe einen DS Lite." Die KI
antwortete mit dem erwartbaren Repertoire — eine vorhandene IPv6-Adresse
nutzen, beim Anbieter eine öffentliche IPv4 erfragen, oder einen
kommerziellen Tunnel-Dienst wie *Cloudflare Tunnel* einsetzen, verbunden
mit dem ehrlichen Hinweis, dass dessen Betreiber dabei den Klartext
öffentlicher Kanäle mitläse. Das Gespräch mündete zunächst in einem
konkreten, konventionellen Plan: IPv6 aktivieren, per MyFRITZ! einen
Namen vergeben, Port 443 in der Firewall freigeben.

### 2.2 Der Plan zerbricht — und liefert das erste Prinzip (01.09.2026, morgens)

Wenige Stunden später widersprach Person seinem eigenen nächtlichen Plan:
„das alle meine Geräte dann via IPv6 im internet stehen ist nicht gerade
gut und beruhigend." Die Prüfung bestätigte dieses Unbehagen nicht nur,
sie deckte ein reales, bis dahin unbemerktes Sicherheitsproblem auf: Die
**selbstständige Portfreigabe** war am Router aktiv — jedes Gerät im
Heimnetz hätte sich eigenständig eine Öffnung in der Firewall bestellen
können.

Aus diesem Rückschlag entstand die erste tragende Unterscheidung der
späteren Architektur: **ein Knoten, der nur nach außen wählt, braucht
keine einzige eingehende Verbindung** — im Unterschied zu einem
Vermittler, der von außen erreichbar sein muss. Für Letzteren wurde noch
am selben Vormittag ein ausgehender Tunnel zu einem gemieteten
Kleinstserver als sauberster Weg vorgeschlagen, gerade weil er das
Heimnetz vollständig unangetastet lässt. Zusätzlich bestätigte sich
technisch, dass DS-Lite jede eingehende Verbindung ohnehin grundsätzlich
verhindert, unabhängig vom gewählten Port. Das Prinzip *„ausgehend
genügt, eingehend ist nicht nötig"* stand damit bereits Stunden vor dem
eigentlichen AHPT-Gespräch fest.

### 2.3 Ein anderes Problem, dieselbe Handschrift (01.09.2026, abends)

Der eigentliche Anstoß zu AHPT kam abends aus einer ganz anderen
Richtung: nicht „wie werde ich erreichbar", sondern eine nüchterne
Bestandsaufnahme des Bestehenden — „welchen Sinn erfüllt der [bereits
laufende OWLP-]Knoten?" Die ehrliche Antwort: kaum einen, und er belastet
zusätzlich die knappe PHP-Gleichzeitigkeitsgrenze des Webhosters. Daraus
entwickelte Person die Idee, Heimserver und gehosteten Webauftritt für
einen Besucher zu **einem** Server verschmelzen zu lassen, damit ein
privates Archiv für Fremde erreichbar wird.

Die Antwort der KI verband in einem Zug eine Absage und eine Lösung: Der
klassische Rücktunnel scheitert an der Bauart von PHP auf Shared Hosting,
das keinen dauerhaften Prozess kennt — **aber die funktionierende
Bauform existierte bereits** im eigenen Mesh-Netzwerk OWLP, das genau
nach diesem Prinzip arbeitet: Postfach statt Verbindung, Polling statt
Push. Zwei in der Folge vorgeschlagene Umwege — eine zweite Domain mit
Weiterleitung, ein eigener JavaScript-/WebSocket-Server — wurden nicht
behauptet, sondern **gemessen** verworfen: Zwölf gleichzeitige Anfragen
an ein PHP-Skript scheiterten mehrheitlich, zwölf gleichzeitige Anfragen
an eine statische Datei liefen ausnahmslos durch. Lesen ist auf Shared
Hosting umsonst; nur die Ausführung ist begrenzt.

### 2.4 Der Moment (01.09.2026, kurz vor Mitternacht)

Person stellte anschließend gezielt die Frage, ob der Prozess auf dem
Webspace deshalb scheitere, weil er sterbe, wenn er nicht angefragt
werde — eine Frage, die bewusst auf die Antwort zusteuerte, die er selbst
schon im Kopf hatte, während er die KI erst einmal antworten ließ. Die KI
korrigierte die Prämisse noch genauer (zwischen zwei Anfragen existiert
gar kein Prozess, kein schlafender) und lieferte innerhalb derselben
Antwort die entscheidende Beobachtung: Der Zustand überlebt in Dateien,
auch wenn kein Prozess überlebt — exakt das Prinzip, nach dem die
Signalisierung des eigenen Mesh-Netzwerks schon immer arbeitete.

Wenige Minuten später formulierte Person daraus die konkrete
Bauanleitung:

> *„die idee ist, dass der prozess bei jeder anfrage in eine txt schreibt
> die auf dem webspace liegt und auch aus dieser lesen kann. dann bauen
> wir einen anfrage cronjob auf dem Homeserver, der alle paar Sekunden
> eine Anfrage schickt."*

Die KI bestätigte darauf keine neue Erkenntnis, sondern eine bereits
vorhandene: **„Du hast ihn schon gebaut."** Dass Person unabhängig zu
demselben Prinzip fand, das die eigene OWLP-Architektur längst trug, war
kein Zufall, sondern die zwingende Konsequenz derselben physikalischen
Grundtatsache, die schon dem Funk- und Morselicht-Hintergrund von OWLP
zugrunde lag: Ein Zustand kann in einer Datei überdauern, auch wenn kein
Prozess ihn hält — und jede Information, ob Text, Bild oder
verschlüsselter Handshake, lässt sich letztlich auf genau diese Weise
transportieren, weil sie sich auf binäre Datenströme reduziert.

### 2.5 Von der Idee zur Architektur (02.09.2026, nach Mitternacht)

Eine letzte Messung gegen den echten Webserver bestätigte das Prinzip in
Zahlen: **264 von 270 Abrufen liefen als HTTP 304 durch, ohne ein
einziges Mal PHP auszulösen.** Aus einer Idee war eine geprüfte
Kostenasymmetrie geworden — der eigentliche Kern von AHPT: seltenes,
teures Schreiben gegen häufiges, kostenloses Lesen.

---

## 3. Die Einflüsse: Vom Krisenfunk zum HTTP-Protokoll

Die Architektur von AHPT fiel nicht vom Himmel, sondern zog ihre
kompromisslose Resilienz aus einem parallel laufenden Projekt von
InnoBytix-IT: **OWLP (Das Eulennetzwerk)**. OWLP wurde als
transportagnostisches, dezentrales Kommunikationsnetz für den zivilen
Katastrophenfall entwickelt. Im Zuge der OWLP-Entwicklung wurde aktiv mit
realer Hardware experimentiert — darunter LoRa-Funkstrecken über
Heltec-Boards mit Meshtastic-Firmware —, während die Spezifikationen
bereits optische Freiraumübertragungen (FSO-Laser und Morselicht-Signale)
als Schmalband-Transportwege definierten.

Diese Schule der *Low-Bandwidth, High-Latency-Kommunikation* prägte AHPT
tiefgreifend:

* **Asynchrones Denken:** Netzwerkverkehr wurde nicht als permanenter
  Live-Stream verstanden, sondern analog zum Paket-Radio oder taktischen
  Funk als isoliertes, in sich geschlossenes Datenpaket, das über ein
  Relais gesendet und quittiert wird.
* **Bauliche Inhaltsblindheit:** Der Vermittler (`relay.php`) auf dem
  Webspace wurde nach dem Vorbild dezentraler Mesh-Knoten absolut
  inhaltsblind konstruiert. Er benötigt keine Root-Rechte, versteht keine
  Dienste und führt keine Befehle aus. Er verwaltet lediglich die
  Dateiwarteschlange.

---

## 4. Die Architektur: Sicherheit durch reglementierte Dummheit

Das tragende Axiom der AHPT-Spezifikation lautet: *„Was geschehen kann,
wird ausschließlich zu Hause festgelegt. Von außen kommt nur die Auswahl
daraus.“*

Um die fatale Gefahr eines offenen Proxies im Heimnetzwerk baulich
auszuschließen, wurde dem Protokoll eine strikte funktionale Reduzierung
auferlegt. Das JSON-Paket transportiert niemals IP-Adressen, Pfade oder
ausführbare Befehle. Der lokale Agent (`relay_agent.py`) akzeptiert von
außen ausschließlich eine standardisierte Kennung für `dienst` und
`aktion`. Diese wird lokal gegen eine unveränderliche Whitelist in der
heimischen `config.toml` abgeglichen. Ein Überreden des Agenten von außen
ist architektonisch unmöglich.

### Die Härtung gegen Webspace-Anomalien

Im Zuge der Entwicklung stieß InnoBytix-IT auf subtile Eigenheiten von
Apache-Webservern, die im Produktiveinsatz zu stillen Fehlschlägen führten
und systematisch abgefangen werden mussten:

* **Das *mod_speling*-Problem:** Bei der Stückelung großer Nutzdaten
  unterschieden sich aufeinanderfolgende Fragmente oft nur um ein Zeichen
  (`_1.json`, `_2.json`). War ein Fragment noch im Upload, leitete das
  Apache-Modul `mod_speling` Anfragen fälschlicherweise per HTTP 301 auf
  ein existierendes Fragment um. **Die Lösung:** Jedes Fragment erhielt
  einen kryptografisch abgeleiteten Hex-Namenszusatz und eine interne
  Validierungsnummer.
* **Die ETag-Blockade:** Da Apache ETags standardmäßig aus Dateigröße und
  Modifikationszeit in ganzen Sekunden generiert, erzeugten gleich große
  Anfragen innerhalb derselben Sekunde identische ETags. Der Agent
  verblieb in einer `304 Not Modified`-Schleife. **Die Lösung:** Ein
  dreifacher Schutzmechanismus aus einer fortlaufenden `folge`-Nummer,
  erzwungenen atomaren Inode-Wechseln über `rename()` und einem
  unbedingten Abruf alle 5 Sekunden (`unbedingt_nach`), der jede
  zwischengespeicherte Antwort ignoriert.

---

## 5. Das Release und die modulare Zukunft

Anfang September 2026 wurde AHPT unter dem Account von **InnoBytix-IT**
offiziell auf GitHub veröffentlicht.

### Der modulare Schichtenaufbau

* **`kern/` (Die Basis):** Realisiert das reine, generische Protokoll über
  die Standardbibliothek von Python (bzw. `tomllib` ab Version 3.11).
  Dieser Kern folgt der strikten **0-Abhängigkeiten-Zusage** und ist ohne
  Drittanbieter-Bibliotheken sofort lauffähig.
* **`cloud/` (Die Vertraulichkeits-Erweiterung):** Für den Transport
  sensibler Daten sieht diese Ausbaustufe eine Ende-zu-Ende-Verschlüsselung
  auf Basis des **Noise-IK-Protokolls** vor. Hier wird die
  0-Abhängigkeiten-Zusage des Kerns bewusst zugunsten maximaler
  Vertraulichkeit aufgegeben, unter Verwendung einer etablierten
  Krypto-Bibliothek (`cryptography`), um auf dem Webspace ausschließlich
  unlesbares Rauschen zu hinterlegen.

### Die rechtliche Absicherung: AGPL-3.0

Um das Protokoll dauerhaft als dezentrales Gemeingut zu schützen, steht
AHPT unter der **GNU Affero General Public License v3 (AGPL-3.0)**. Diese
Lizenz schließt die Cloud-Lücke: Wer den Vermittlungsdienst (`relay.php`)
modifiziert oder als kommerziellen Netzwerkdienst anbietet, ist rechtlich
verpflichtet, den modifizierten Quellcode offenzulegen.

Für die Weiterentwicklung ist eine native, hochperformante Go-Variante
vorgesehen, sowie eine installationsfreie `.exe` für Windows-Heimserver —
beides bislang eigene Vorhaben, noch ohne veröffentlichten Quelltext.
Damit steht ein getestetes, dokumentiertes Protokoll bereit, das genau
das leistet, wofür es gebaut wurde: einen Heimserver hinter DS-Lite und
CGNAT erreichbar machen, ohne Portfreigabe, DynDNS oder gemieteten Server.
