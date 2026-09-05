# AHPT/1 — die generische Fassung

**Einen Heimserver ohne eingehende Erreichbarkeit ins Netz stellen — mit
einem gewoehnlichen Webspace als Treffpunkt. Ohne DynDNS, ohne
Portfreigabe, ohne VPS, ohne Zertifikat.**

Idee, Namensgebung und Referenzumsetzung: Manuel Person, InnoBytix-IT.

Dieser Ordner ist der generische Kern von AHPT — verallgemeinert aus einer
ersten, dienstspezifischen Referenzumsetzung (fest verdrahtet gegen einen
einzelnen Dienst). Was hier liegt, kennt keinen bestimmten Dienst mehr,
nur noch Handler, die sich darueber anmelden.

Wer wissen will, *warum* das Ganze funktioniert — die Messung der
Asymmetrie zwischen Lesen und Ausfuehren auf Webspace, die dem Entwurf
zugrunde liegt —, findet die Herleitung in `ARCHITEKTUR.md`.

---

## Der Unterschied in einem Satz

`tunnel.php` kennt kiwix. `relay.php` kennt gar nichts.

| | Referenzumsetzung | hier |
|---|---|---|
| Nachricht | `{typ, archiv, begriff}` | `{dienst, aktion, daten}` |
| wer kennt die Ziele | fest im Quelltext beider Seiten | `config.toml` des Agenten |
| Dienste | kiwix | beliebig, ueber Handler |
| Antwortgroesse | 64 KiB, danach gekuerzt | gestueckelt, bis ~12 MiB |
| Aufraeumen | nur unbeantwortete Fragen | auch beantwortete |

**Und die Regel, die dabei nicht aufgegeben wird:**

> Was geschehen kann, wird ausschliesslich zu Hause festgelegt.
> Von aussen kommt nur die Auswahl daraus.

Es gibt zwei Sorten Dummheit, und nur eine wird aufgegeben. Der
**Vermittler** wird inhaltsblind — das durfte er, er hat den Inhalt nie
gebraucht. Der **Agent** bleibt nicht ueberredbar — das darf er nie
verlieren. Kein Feld im Protokoll traegt eine Adresse, einen Befehl oder
eine Faehigkeit. Immer nur einen Namen aus einer Liste, die im Haus steht.

Die ausfuehrliche Begruendung: `ARCHITEKTUR.md`.
Der Vertrag fuer einen Nachbau in Go oder Rust: `PROTOKOLL.md`.
**Was haelt, was wackelt und was ausdruecklich nicht geschuetzt ist:
`SICHERHEIT.md` — vor dem ersten Einsatz lesen.**

---

## Dateien

| Datei | Seite | Zweck |
|---|---|---|
| `relay.php` | Webspace | nimmt Fragen, Stuecke und Antworten an. Sonst nichts. |
| `htaccess-beispiel` | Webspace | zweite Schranke, `CheckSpelling Off`, `FileETag INode` |
| `relay_agent.py` | Heimserver | Transport: Warteschlange, Marken, Stueckelung |
| `netz.py` | Heimserver | HTTP ohne Weiterleitungen, 503-Wiederholung |
| `handler/kiwix.py` | Heimserver | die entkernte OWLP-Logik |
| `handler/datei.py` | Heimserver | Dateien aus einem festgelegten Ordner |
| `config-beispiel.toml` | Heimserver | Vorlage |
| `relay-client.js` | Browser | fuehlt sich an wie `fetch`, ohne Abhaengigkeiten |

Nur Standardbibliothek, auf allen drei Seiten. Kein Bauschritt, kein
`npm install`, kein `pip install`.

---

## Einrichten

**1. Webspace.** `relay.php` und `htaccess-beispiel` (als `.htaccess`)
hochladen. Dazu ein Geheimnis erzeugen:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

und als `relay_token.php` ablegen — **mit der Schutzzeile davor**:

```
<?php exit; ?>
<hier das Geheimnis>
```

Die Endung `.php` ist der Schutz, nicht die `.htaccess`: Der Server
*fuehrt* die Datei *aus* und gibt nichts aus. Eine `.htaccess` kann beim
Hochladen verlorengehen — am 02.09.2026 zweimal passiert, jeweils mit
gruenem Haken im Uploader. Danach pruefen:

```bash
curl -s 'https://example.de/ahpt/relay.php?action=selbsttest'
```

Das sagt, **ob** das Geheimnis lesbar ist, nie **welches**.

**2. Heimserver.**

```bash
cp config-beispiel.toml config.toml   # und anpassen
python3 relay_agent.py --konfig config.toml --selbsttest
python3 relay_agent.py --konfig config.toml
```

**3. Browser.**

```html
<script src="relay-client.js"></script>
<script>
  const relay = new AhptClient('https://example.de/ahpt');
  const a = await relay.frage('wiki', 'suche', { begriff: 'Wasser' });
  if (a.gefunden) console.log(a.text);
</script>
```

`a.text` ist reiner Text, `a.bytes` ein `Uint8Array`. **Nie als `innerHTML`
einhaengen** — der Weg ist oeffentlich, und jeder kann in die Warteschlange
schreiben.

---

## Pruefen

```bash
python3 tests/pruefe_relay_php.py         # relay.php ohne PHP
python3 relay_agent.py --konfig config.toml --selbsttest
python3 tests/durchstich_lokal.py         # Agent + Client, gegen eine Attrappe
bash    tests/durchstich.sh https://…     # der echte Durchstich
```

**Was wo geprueft wird — und was nicht:**

- `pruefe_relay_php.py` findet den Fehler, den `php -l` **nicht** findet:
  das PHP-Endezeichen in einem `//`-Kommentar. Es ersetzt `php -l` nicht.
  Vor dem Ausliefern beides.
- `--selbsttest` prueft die Schranken der Handler, ohne Netz und ohne die
  Dienste. Ein Handler ohne Selbsttest wird gar nicht erst geladen.
- `durchstich_lokal.py` laeuft gegen eine **Attrappe** und beweist nichts
  ueber `relay.php`. Es prueft Agent und Client — vor allem die
  Stueckelung, die es in der Referenzumsetzung noch nicht gab.
- `durchstich.sh` ist der einzige Test, der etwas ueber den Betrieb sagt.

Der eine Fehler, der den ersten Live-Lauf gekostet hat, war `mod_speling` —
und keine lokale Pruefung haette ihn gefunden. **Was ein Testaufbau nicht
hat, kann er nicht messen.**

---

## Stand

Alle lokalen Pruefungen bestanden (02.09.2026, gegen Python 3.11 und
Node 22):

```
relay.php, 10 statische Pruefungen         bestanden
Kern und Handler, 84 Pruefungen            bestanden
Durchstich gegen Attrappe, 32 Pruefungen   bestanden
  300-KiB-Datei ueber 9 Stuecke              Byte fuer Byte gleich
  Text, der JSON verdoppelt                  vollstaendig
  Pfadwanderung, absoluter Pfad, Symlink     alle abgewiesen
relay-client.js, 15 Pruefungen             bestanden
```

**Noch nicht gegen echtes PHP und echtes Apache gelaufen.** Das ist der
naechste Schritt und der einzige, der zaehlt.

Zwei Funde aus dem Bestand, die in dieser Fassung behoben sind — beide
betreffen auch die laufende Referenzumsetzung:

1. **Antwortdateien wurden nie geraeumt.** In `tunnel.php` verlaesst eine
   Marke beim Beantworten die Liste `offen` und steht danach in keiner
   Liste mehr — der Sammler sieht sie nie wieder. Jeder *erfolgreiche*
   Vorgang hinterlaesst dauerhaft eine Datei. Hier gibt es dafuer die
   zweite Liste `fertig`.
2. **Der ETag kann eine Aenderung verbergen.** Apache bildet ihn aus ganzen
   Sekunden und Groesse; zwei Warteschlangen mit je einem Eintrag sind
   gleich lang. Der Agent bekommt dann `304` und uebersieht die Frage —
   dauerhaft, waehrend der Besucher wartet. Dagegen: unbedingter Abruf alle
   30 s, eine fortlaufende Nummer in der Warteschlange, und
   `FileETag INode MTime Size`.

---

## Offen

1. **Vertraulichkeit.** Weiterhin der groesste offene Punkt. Der Umschlag
   traegt `krypto` von Anfang an, mit genau einem erlaubten Wert: `keine`.
   Halb gebaute Verschluesselung waere schlimmer als gar keine, weil man ihr
   glaubt. **Ueber diesen Weg reist nichts, was nicht oeffentlich sein
   darf.** Entwurf in `ARCHITEKTUR.md` Abschnitt 8.
2. **Noch nie von jemand anderem betrieben.**
3. **Nur eine Webspace-Sorte gemessen** (IONOS).
4. **Kein Streaming.** Der Weg traegt Anfrage und Antwort, nicht eine
   Verbindung. Ein bis drei Sekunden Mindestverzoegerung sind die Bauart,
   keine Einstellung.
5. **Warteschlange ist eine Datei unter einer Sperre.** Fuer viele
   gleichzeitige Nutzer muesste sie geteilt werden.
6. **Go-Port.** `PROTOKOLL.md` ist dafuer geschrieben. Ein Go-Agent ist
   fertig, wenn er `tests/durchstich.sh` besteht.

---

## Lizenz

AGPL-3.0-or-later, wie die Referenzumsetzung.
