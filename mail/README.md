# AHPT Mail — noch nicht gebaut

E-Mail-artiger Austausch ohne eigenen Mailserver, ohne Port 25/587, ohne
SPF/DKIM/DMARC-Sorgen — über denselben Webspace-Umweg wie
[`../cloud/`](../cloud/) und [`../messenger/`](../messenger/).

## Was sich von `messenger/` unterscheiden müsste

Eine Nachricht soll ankommen, auch wenn der Empfänger sein Gerät erst in
drei Tagen wieder einschaltet — anders als bei `messenger/`, wo eine
kurze Offline-Zeit reicht. Das verträgt sich schlecht mit `MARKE_TTL`
(120 Sekunden im Kern): Eine Frage, die drei Tage auf dem Webspace liegen
bleiben soll, ist kein "Frage-Antwort"-Vorgang mehr, sondern eine
**Ablage mit Verfallsdatum in Tagen, nicht Sekunden** — ein eigener
Mechanismus, kein Wiederverwenden der bestehenden Warteschlange.

Offene Fragen:

- **Absenderadressen**, die nicht wie bei `cloud/` eine feste, von Hand
  gepflegte Weißliste sind, sondern öffentlich adressierbar sein müssten
  — was dem Grundsatz "nur wer in der Weißliste steht, bekommt eine
  Antwort" widerspricht und getrennt gelöst werden muss.
- **Anhänge**, vermutlich über denselben Blockübertragungsweg wie in
  `cloud/` (`lege_block`).
- **Wie lange darf eine unzugestellte Nachricht den Webspace belegen**,
  bevor sie verworfen wird — ein kostenloser oder billiger Webspace ist
  kein Postfach für Wochen.

Bis diese Fragen beantwortet sind, gibt es hier keinen Code.
