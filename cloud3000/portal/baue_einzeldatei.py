#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
baue_einzeldatei.py -- macht aus dem Portal EINE Datei zum Doppelklicken

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Das Portal auf dem Webspace laufen zu lassen hat einen Haken, der sich
nicht wegprogrammieren laesst: Der Hoster liefert die Seite aus und koennte
sie austauschen -- mitsamt dem Schluessel, gegen den verschluesselt wird.

Eine Seite auf der eigenen Festplatte kann er nicht anfassen. Dann traegt
die Verschluesselung auch gegen ihn, und nicht nur gegen Fremde im Netz.

Dazu kommt ein zweiter, ganz praktischer Grund: Browser geben `crypto.subtle`
nur im sicheren Zusammenhang frei -- ueber https, auf localhost, oder bei
einer lokal geoeffneten Datei. Ueber gewoehnliches http gibt es die
Verschluesselung schlicht nicht. Auf einem Hoster ohne brauchbares https ist
die lokale Datei damit nicht der Notnagel, sondern der einzige Weg.

Drei Dateien von Hand zu verwalten ist laestig, und was laestig ist, wird
falsch gemacht. Diese Datei baut daraus eine einzige.

Aufruf:
    python3 portal/baue_einzeldatei.py [zieldatei]
"""

import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))


def main():
    ziel = sys.argv[1] if len(sys.argv) > 1 \
        else os.path.join(HIER, 'ahpt-portal-lokal.html')

    with open(os.path.join(HIER, 'index.html'), encoding='utf-8') as f:
        html = f.read()

    for name in ('noise.js', 'ahpt.js'):
        with open(os.path.join(HIER, name), encoding='utf-8') as f:
            js = f.read()
        # Der Export-Block am Ende ist nur fuer die Pruefung in Node da. Im
        # Browser stoert er nicht, aber er gehoert auch nicht in eine Datei,
        # die jemand liest, um zu verstehen, was sie tut.
        js = re.sub(r"\nif \(typeof module !== 'undefined'.*?\n\}\n", '\n', js,
                    flags=re.S)
        marke = '<script src="%s"></script>' % name
        if marke not in html:
            print('ABBRUCH: %s wird in index.html nicht eingebunden.' % name)
            print('         Dann baut diese Datei etwas Unvollstaendiges --')
            print('         und das faellt erst im Browser auf.')
            return 2
        html = html.replace(marke, '<script>\n/* --- %s --- */\n%s\n</script>'
                            % (name, js), 1)

    # Ein Hinweis im Titel, damit man die beiden Fassungen nicht verwechselt.
    html = html.replace('<title>AHPT Cloud</title>',
                        '<title>AHPT Cloud (lokal)</title>', 1)
    # Die Vorgabe ".." stimmt nur, wenn die Seite NEBEN relay.php liegt.
    # Lokal muss die volle Adresse eingetragen werden -- das Feld sagt es
    # jetzt selbst, statt es den Nutzer raten zu lassen.
    html = html.replace('<input type="text" id="feld-basis" placeholder="..">',
                        '<input type="text" id="feld-basis" '
                        'placeholder="https://example.de/privat  '
                        '(volle Adresse, diese Seite liegt ja woanders)">', 1)

    with open(ziel, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)

    print('%s  (%d Bytes)' % (ziel, os.path.getsize(ziel)))
    print('')
    print('Eine einzige Datei, kein Ordner, keine Nachbardateien.')
    print('Doppelklick oeffnet sie; als Adresse die volle Basis eintragen.')
    print('')
    print('Der Hoster kann diese Datei nicht austauschen -- damit traegt die')
    print('Verschluesselung auch gegen ihn, nicht nur gegen Fremde im Netz.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
