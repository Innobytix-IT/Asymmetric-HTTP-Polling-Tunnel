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
(Portfreigaben).**

---

## 2. Der Impuls: Das theoretische Limit der künstlichen Intelligenz

Die Konzeption von AHPT (Asymmetric HTTP Polling Tunnel) begann mit einer
systematischen Befragung der künstlichen Intelligenz **Claude** durch den
Entwickler Manuel Person. Auf die Frage nach unkonventionellen Wegen,
hinter einer DS-Lite-Barriere ohne VPS, ohne Portfreigaben und ohne
Drittanbieter-Tunnel eine Erreichbarkeit herzustellen, lautete das
sinngemäße Urteil der KI: technisch nicht auf konventionellem Weg lösbar.

Die KI war in der klassischen Lehrmeinung persistenter, synchroner
Socket-Verbindungen gefangen. Erst ein radikaler Wechsel der Perspektive
brach die Blockade. Person stellte die fundamentale Systemfrage:

> *„Kann ein einfaches PHP-Skript auf einem gewöhnlichen Webspace in eine
> Textdatei schreiben?“*

Die Bestätigung dieser Funktion durch die KI war der logische Katalysator.
Wenn ein minimales Skript im Web Daten persistieren kann, fungiert der
Webspace als universeller, passiver **Zustands- und Speicher-Briefkasten**.
Wenn der Heimserver von innen heraus das Internet erreicht und diese
Zustände periodisch abruft (Polling), ist die Richtung der
Verbindungsinitiierung umgekehrt. Das DS-Lite-Problem war auf logischer
Ebene neutralisiert.

Da digitale Informationen — ob Texte, Dateien oder verschlüsselte
Handshakes — auf binäre Datenströme reduzierbar sind, existierte kein
grundsätzliches Hindernis für die Transportfähigkeit dieses asynchronen
Kanals.

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
