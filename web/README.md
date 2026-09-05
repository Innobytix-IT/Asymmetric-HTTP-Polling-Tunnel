# AHPT Web — noch nicht gebaut

Eine gewöhnliche Webseite vom Heimserver ausliefern, über denselben
Webspace-Umweg — ohne Portfreigabe, ohne DynDNS, ohne eigenen
öffentlich erreichbaren Webserver zu Hause.

## Der naheliegende Ansatz

Von den geplanten Nutzungsarten liegt diese vermutlich am nächsten am
[Kern](../kern/): `handler/kiwix.py` im Kern zeigt bereits das Muster
"ein Handler liefert Inhalt aus einem Archiv aus". Ein `handler/web.py`
bräuchte im Kern nur, statische Dateien aus einem freigegebenen
Ordner auszuliefern (HTML, CSS, JS, Bilder) — nah an
[`../cloud/`](../cloud/)s `handler/datei.py`, nur lesend und ohne
Ende-zu-Ende-Verschlüsselung, weil der Inhalt ja öffentlich sein soll.

Offene Fragen:

- **MIME-Typen** korrekt setzen, ohne dass der Vermittler dafür etwas
  wissen muss — der Handler müsste sie im Antwort-Umschlag mitschicken.
- **Wie viele gleichzeitige Besucher** ein einzelner Heimserver über
  diesen Umweg bedienen kann, bevor die Ein-bis-drei-Sekunden-Verzögerung
  je Abruf störend wird — vermutlich nur für wenig frequentierte Seiten
  geeignet, nicht für echten Web-Traffic.

Bis diese Fragen beantwortet sind, gibt es hier keinen Code.
