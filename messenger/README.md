# AHPT Messenger — noch nicht gebaut

Nachrichten zwischen den eigenen Geräten austauschen, über denselben
Webspace-Umweg wie [`../cloud/`](../cloud/): kein eigener Server, kein
offener Port, Ende-zu-Ende verschlüsselt.

## Was sich von `cloud/` unterscheiden müsste

`cloud/` hat einen Agenten (Heimserver) und beliebig viele Clients, die
bei ihm anfragen. Ein Messenger bräuchte **mehrere gleichberechtigte
Geräte**, die sich gegenseitig Nachrichten hinterlassen — kein Gerät ist
mehr "der Agent", jedes ist gleichzeitig Absender und Empfänger.

Offene Fragen, die vor dem ersten Quelltext geklärt werden müssen:

- **Zustellung an ein Gerät, das gerade nicht online ist.** `cloud/`
  braucht das nicht — der Agent läuft dauerhaft. Ein Messenger müsste
  Nachrichten so lange auf dem Webspace vorhalten, bis das Zielgerät
  wieder pollt, ohne die `MARKE_TTL`-Kurzlebigkeit des Kerns zu verletzen.
- **Wer ist in wessen Weißliste?** Bei zwei gleichberechtigten Geräten
  bräuchte jedes die Schlüssel aller anderen — eine Weißliste pro Gerät,
  nicht eine zentrale.
- **Reihenfolge und Zustellbestätigung**, ohne dass der Vermittler mehr
  sieht als "irgendwann kam etwas an".

Bis diese Fragen beantwortet sind, gibt es hier keinen Code.
