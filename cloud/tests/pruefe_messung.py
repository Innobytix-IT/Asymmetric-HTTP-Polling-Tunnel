#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pruefe_messung.py -- die Vermittler-Messung gegen ein echtes PHP fahren

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Die Messung (relay.php, action=messung) laesst sich nicht sinnvoll
nachbilden: Sie ist zu grossen Teilen genau das, was PHP und der Webserver
mit den Bytes machen -- Ausgabepuffer, Komprimierung, Rumpfgrenzen. Eine
Attrappe wuerde alles davon richtig machen und den Fehler verstecken.

Also ein echter PHP-Prozess (`php -S`) mit einem WEGWERF-Vermittler in einem
temporaeren Ordner. Die eingerichtete Anlage des Nutzers wird nicht
angefasst; das Geheimnis dieses Tests entsteht hier und stirbt hier.

WAS DIESER TEST GEFUNDEN HAT
-----------------------------
Beim ersten Durchlauf am 08.09.2026 kam mit dem RICHTIGEN Geheimnis ein 403
zurueck. Die Ursache lag nicht in der Messung, sondern in einrichten.py: Es
schrieb relay_token.php als `<?php return "<geheimnis>";` -- eine Datei ohne
Zeilenschaltung, aus der lies_geschuetzt() in relay.php immer eine leere
Zeichenkette macht. Damit war agent_erlaubt() dauerhaft falsch und der Agent
durfte auf dem Vermittler nichts ablegen: JEDE ueber den Assistenten
eingerichtete Anlage haette auf jede Frage nie eine Antwort bekommen.

Deshalb baut dieser Test die beiden Dateien mit den ECHTEN Erzeugern aus
einrichten.py und nicht mit einer eigenen, gut gemeinten Nachbildung. Eine
Nachbildung haette hier das Richtige getan und den Fehler zugedeckt.

Aufruf:
    python3 tests/pruefe_messung.py
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HIER = os.path.dirname(os.path.abspath(__file__))
QUELLE = os.path.dirname(HIER)
sys.path.insert(0, QUELLE)

PORT = 8899
fehler = []


def pruefe(bedingung, text):
    print(('   OK   ' if bedingung else '   FEHL ') + text)
    if not bedingung:
        fehler.append(text)


def main():
    if shutil.which('php') is None:
        print('PHP fehlt -- dieser Test braucht es und kann ohne nichts sagen.')
        print('Debian/Ubuntu/Mint:  sudo apt install php-cli')
        return 77          # wie bei automake: uebersprungen, nicht bestanden

    import einrichten

    tmp = tempfile.mkdtemp(prefix='ahpt_messung_')
    php = None
    try:
        shutil.copy(os.path.join(QUELLE, 'relay.php'), tmp)
        geheim = os.urandom(32).hex()      # nur fuer diesen Test, nie ausgegeben
        with open(os.path.join(tmp, 'relay_token.php'), 'wb') as f:
            f.write(einrichten._token_datei(geheim))
        with open(os.path.join(tmp, 'relay_state.php'), 'wb') as f:
            f.write(einrichten._zustand_datei())
        os.makedirs(os.path.join(tmp, 'ahpt'), exist_ok=True)

        php = subprocess.Popen(
            ['php', '-S', '127.0.0.1:%d' % PORT, '-t', tmp],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)

        # Das Geheimnis dieses Tests statt des eingerichteten -- sonst wuerde
        # der Test die Anlage des Nutzers voraussetzen und ohne sie scheitern.
        einrichten._geheimnis_lesen = lambda: geheim
        basis = 'http://127.0.0.1:%d' % PORT

        print('== 1. Der Selbsttest verraet, dass es die Messung gibt')
        st = einrichten._relay_selbsttest(basis)
        pruefe(st is not None and st.get('ok'), 'relay.php antwortet')
        pruefe(bool(st and st.get('messung_max')),
               'messung_max steht im Selbsttest (%s)'
               % (st or {}).get('messung_max'))

        print('== 2. Ohne das Geheimnis geht nichts')
        v = einrichten._Messverbindung(basis)
        _, _, kode = v.herunter('falsch' * 10, 65536)
        pruefe(kode == 403, 'falsches Geheimnis -> 403 (war %s)' % kode)
        v.zu()

        print('== 3. Herunter liefert genau so viele Bytes wie verlangt')
        v = einrichten._Messverbindung(basis)
        for wunsch in (1024, 300000, 1048576):
            n, _, kode = v.herunter(geheim, wunsch)
            pruefe(kode == 200 and n == wunsch,
                   '%d verlangt, %d bekommen (HTTP %s)' % (wunsch, n, kode))

        print('== 4. Der Deckel greift')
        n, _, kode = v.herunter(geheim, 99 * 1024 * 1024)
        pruefe(kode == 200 and n == einrichten.MESSUNG_MAX,
               'ueber dem Deckel -> genau MESSUNG_MAX (%d bekommen)' % n)

        print('== 5. Hinauf zaehlt richtig')
        for wunsch in (65536, 700000):
            n, _, kode = v.hinauf(geheim, wunsch)
            pruefe(kode == 200 and n == wunsch,
                   '%d gesendet, %d bestaetigt (HTTP %s)' % (wunsch, n, kode))
        v.zu()

        print('== 6. Die Messung hinterlaesst nichts in der Ablage')
        # Sonst wuerde sie das Aufraeumen mitmessen und der Warteschlange
        # Plaetze wegnehmen -- eine Diagnose, die den Patienten belastet.
        da = os.listdir(os.path.join(tmp, 'ahpt'))
        pruefe(da == [], 'Ablage leer geblieben (%r)' % (da,))

        print('== 7. Ein ganzer Durchlauf')
        verlauf = []
        e = einrichten.vermittler_messen(basis, melde=verlauf.append)
        pruefe(e['verdikt'] in ('gut', 'lahm'), 'Verdikt: %s' % e['verdikt'])
        pruefe(e.get('herunter_bps', 0) > 0,
               'Herunter: %s' % einrichten._tempo(e.get('herunter_bps')))
        pruefe(e.get('hinauf_bps', 0) > 0,
               'Hinauf:   %s' % einrichten._tempo(e.get('hinauf_bps')))
        pruefe(e.get('tcp_ms') is not None,
               'TCP:      %.1f ms' % (e.get('tcp_ms') or -1))
        pruefe('umlauf_ms' in e, 'Umlauf:   %.1f ms, davon PHP %.1f ms'
               % (e.get('umlauf_ms', -1), e.get('php_ms', -1)))
        pruefe(e.get('gesamt_s', 0) > 0,
               'Gesamt:   %.2f s' % e.get('gesamt_s', 0))
        pruefe(len(verlauf) >= 4,
               'vier Fortschrittsmeldungen (%d)' % len(verlauf))
        pruefe(not e['hinweise'],
               'keine Beanstandung: %r' % (e['hinweise'],))

        print('== 8. Ist er weg, sagt die Messung das -- und raet nicht')
        php.send_signal(signal.SIGTERM)
        php.wait(timeout=10)
        php = None
        e2 = einrichten.vermittler_messen(basis)
        pruefe(e2['verdikt'] == 'weg',
               'Verdikt nach Abschaltung: %s' % e2['verdikt'])
        pruefe(bool(e2['saetze']), 'mit Begruendung: %s'
               % (e2['saetze'][0][:60] if e2['saetze'] else '(keine)'))
    finally:
        if php:
            try:
                php.kill()
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fehler:
        print('%d FEHLER:' % len(fehler))
        for f in fehler:
            print('  - ' + f)
        return 1
    print('Alles bestanden.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
