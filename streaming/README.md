# AHPT Streaming — noch nicht gebaut, und mit einer echten Grenze

Audio/Video vom Heimserver holen, blockweise statt als eine große
Antwort — im Prinzip existiert der Baustein dafür schon:
[`../cloud/`](../cloud/)s bereichsweises `hole` liest eine Datei in
Blöcken von `LESE_BLOCK` (4 MiB) und kann so schon heute einen Player
bedienen, der selbst nachlädt.

## Die Grenze, die ehrlich benannt gehört

Der [Kern](../kern/) sagt ausdrücklich: **kein Streaming, kein VPN** —
der Weg trägt Frage und Antwort, keinen Paketstrom. Jeder Block ist ein
eigener Frage-Antwort-Umlauf über den Webspace, mit ein bis drei
Sekunden Mindestverzögerung durch die Bauart, nicht durch eine
Einstellung. Das reicht für "eine Datei laden, während schon
wiedergegeben wird", nicht für Live-Streaming oder verzögerungsarme
Wiedergabe.

Was hier also entstehen könnte, ist kein Ersatz für RTMP/HLS, sondern
ein **Abspielen bereits vorhandener Dateien vom eigenen Heimserver ohne
Portfreigabe** — mit der Verzögerung, die die Bauart mitbringt, klar
benannt statt verschwiegen.

Offen: ob sich das lohnt, oder ob `cloud/`s `hole` mit Bereichsangabe
für diesen Zweck schon ausreicht, ohne einen eigenen Unterordner zu
brauchen.
