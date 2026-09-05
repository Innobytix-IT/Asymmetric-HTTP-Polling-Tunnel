# AHPT — Asymmetric HTTP Polling Tunnel

**Einen Server ohne eingehende Erreichbarkeit ins Netz stellen — mit einem
gewöhnlichen Webspace als Treffpunkt. Ohne DynDNS, ohne Portfreigabe, ohne
VPS, ohne Zertifikatsverfahren.**

Ein Heimserver hinter DS-Lite, CGNAT oder einer strengen Firewall hat keine
eigene öffentliche IPv4-Adresse und keinen Weg, eingehende Verbindungen
anzunehmen. AHPT braucht das auch nicht: Beide Seiten — der Client und der
Heimserver — bauen jede Verbindung selbst auf, nach außen, zu einem fest
bekannten Webspace. Keine Seite wartet je auf eine eingehende Verbindung,
also greift keine der üblichen Sperren.

Der Webspace selbst ist ein Briefkasten, kein Beteiligter: Er nimmt
Anfragen entgegen, legt sie ab, und wer sie abholt, holt sie ab. Das
Verfahren nutzt eine Eigenschaft, die auf nahezu jedem günstigen
Webhosting gilt — Lesen (statische Dateien) ist praktisch unbegrenzt,
Ausführen (PHP-Aufrufe) ist scharf gedeckelt. Die Herleitung dazu steht in
[`kern/ARCHITEKTUR.md`](kern/ARCHITEKTUR.md).

Idee, Namensgebung und Referenzumsetzung: Manuel Person, InnoBytix-IT.

---

## Aufbau dieses Repositoriums

AHPT ist als **ein Protokoll, viele Nutzungsarten** gedacht. Der
Vermittler bleibt in jeder Nutzungsart inhaltsblind, der Agent bleibt
nicht überredbar — was sich unterscheidet, ist nur, welcher Dienst am
Ende des Kanals steht.

| Ordner | Nutzungsart | Stand |
|---|---|---|
| [`kern/`](kern/) | Das generische Protokoll selbst: Vermittler, Agent, Handler-Vertrag. Öffentlich, lesend, ohne eigene Konfiguration eines Nutzers. | fertig |
| [`cloud/`](cloud/) | Persönliche Cloud: ein einzelner Nutzer, Ende-zu-Ende-Verschlüsselung (Noise IK), Lesen **und** Schreiben, beliebig große Dateien. | fertig |
| `messenger/` | Nachrichten zwischen eigenen Geräten über denselben Kanal. | folgt |
| `mail/` | E-Mail-artiger Austausch ohne eigenen Mailserver. | folgt |
| `streaming/` | Audio/Video vom Heimserver, blockweise statt als eine große Antwort. | folgt |
| `web/` | Eine gewöhnliche Webseite vom Heimserver ausliefern, über denselben Webspace-Umweg. | folgt |

Jeder Unterordner ist für sich lauffähig und dokumentiert sein eigenes
Bedrohungsmodell — `cloud/` etwa dreht das Modell von `kern/` bewusst um
(siehe [`cloud/README.md`](cloud/README.md)). Gemeinsamer Code wird nicht
zwischen den Ordnern importiert; jeder Ordner ist eine eigenständige
Kopie, die sich unabhängig weiterentwickeln darf.

## Womit anfangen

- **Nachbauen oder verstehen, wie das Protokoll grundsätzlich funktioniert:**
  [`kern/README.md`](kern/README.md), dann `kern/ARCHITEKTUR.md` und
  `kern/PROTOKOLL.md`.
- **Eigene Dateien unterwegs erreichbar machen, verschlüsselt:**
  [`cloud/README.md`](cloud/README.md).
- **Vor dem ersten produktiven Einsatz, in jedem Ordner:** die jeweilige
  `SICHERHEIT.md` — was hält, was wackelt, was ausdrücklich nicht
  geschützt ist.

## Lizenz

[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-or-later).
Wer eine geänderte Fassung über ein Netzwerk anbietet, muss den
Quelltext auch dieser geänderten Fassung offenlegen — das gilt gerade für
einen Vermittlungsdienst wie diesen ausdrücklich.
