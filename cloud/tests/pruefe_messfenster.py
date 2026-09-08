#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pruefe_messfenster.py -- Messung und laufender Agent gleichzeitig

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Der Rundlauf-Test legt eine Frage ab, die NIEMAND entschluesseln kann --
sie ist nur Fuellstoff, damit der Vermittler eine Marke oeffnet. Fuer den
laufenden Agenten sieht das aus wie ein Fremder, der seine Verschluesselung
nicht trifft: Er zaehlt `krypto_abgewiesen` hoch.

Und dieser Zaehler ist nach der ausdruecklichen Zusage im Kopf von
relay_agent.py im gesunden Betrieb NULL. Ein Diagnosewerkzeug, das den
Befund faelscht, den es liefern soll, ist schlimmer als keines.

Das Messfenster (~/.ahpt/messung_laeuft, genauer: neben der Konfiguration)
loest das. Ob es das WIRKLICH tut, laesst sich nur mit zwei echten
Prozessen zeigen -- ein Agent, der pollt, und eine Messung, die daneben
laeuft. Genau das tut diese Datei.

WAS SIE SCHON GEFUNDEN HAT
---------------------------
Der Agent suchte das Fenster stur unter `~/.ahpt/`, waehrend die Messung es
im Ordner der Konfiguration ablegt. In der ueblichen Anlage ist das
dasselbe -- aber eben nur dort. Wer den Agenten mit `--konfig
woanders/agent.toml` startet, hatte zwei Seiten, die auf verschiedene
Dateien schauen. Der Zaehler stand danach auf 2 statt auf 1.

WARUM DER RUNDLAUF ALLEIN DAS NICHT ZEIGT
------------------------------------------
Ueber Loopback ist er in Millisekunden fertig, und `action=antwort` nimmt
die Marke dabei aus der Warteschlange. Der Agent bekommt sie also meistens
gar nicht zu Gesicht, und dann bewiese sein Schweigen nichts. Auf einer
echten Strecke, wo ein Megabyte Sekunden braucht, sieht er sie sehr wohl --
und genau dafuer gibt es das Fenster. Deshalb wird hier eine Frage ABGELEGT
UND LIEGEN GELASSEN, statt sich auf die Laufzeit zu verlassen.

Aufruf:
    python3 tests/pruefe_messfenster.py
"""

import base64
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HIER = os.path.dirname(os.path.abspath(__file__))
QUELLE = os.path.dirname(HIER)
sys.path.insert(0, QUELLE)

PORT = 5055
fehler = []


def pruefe(b, t):
    print(('   OK   ' if b else '   FEHL ') + t)
    if not b:
        fehler.append(t)


def main():
    if shutil.which('php') is None:
        print('PHP fehlt -- ohne Vermittler gibt es nichts zu messen.')
        print('Debian/Ubuntu/Mint:  sudo apt install php-cli')
        return 77

    import einrichten
    import krypto
    import netz

    tmp = tempfile.mkdtemp(prefix='ahpt_mf_relay_')
    heim = tempfile.mkdtemp(prefix='ahpt_mf_heim_')
    frei = os.path.join(heim, 'freigabe')
    os.makedirs(frei, exist_ok=True)
    php = agent = None
    try:
        # ---- Wegwerf-Vermittler
        shutil.copy(os.path.join(QUELLE, 'relay.php'), tmp)
        geheim = os.urandom(32).hex()     # nur fuer diesen Test, nie ausgegeben
        with open(os.path.join(tmp, 'relay_token.php'), 'wb') as f:
            f.write(einrichten._token_datei(geheim))
        with open(os.path.join(tmp, 'relay_state.php'), 'wb') as f:
            f.write(einrichten._zustand_datei())
        os.makedirs(os.path.join(tmp, 'ahpt'), exist_ok=True)
        php = subprocess.Popen(
            ['php', '-S', '127.0.0.1:%d' % PORT, '-t', tmp],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # ---- Wegwerf-Agent
        gpfad = os.path.join(heim, 'geheimnis')
        with open(gpfad, 'w') as f:
            f.write(geheim)
        kpfad = os.path.join(heim, 'agent.key')
        priv, _pub = krypto.schluesselpaar()
        krypto.schreibe_privat(kpfad, priv)
        konf = os.path.join(heim, 'agent.toml')
        with open(konf, 'w') as f:
            f.write('[relay]\nbasis = "http://127.0.0.1:%d"\n'
                    'geheimnis_datei = "%s"\npoll_abstand = 0.5\n\n'
                    '[krypto]\nverfahren = "noise_ik"\n'
                    'schluessel = "%s"\nclients = ["%s"]\n\n'
                    '[[dienst]]\nname = "dateien"\nart = "datei"\n'
                    'wurzel = "%s"\naktionen = ["liste", "hole"]\n'
                    % (PORT, gpfad, kpfad, 'aa' * 32, frei))
        log = os.path.join(heim, 'agent.log')
        with open(log, 'w') as lf:
            agent = subprocess.Popen(
                [sys.executable, os.path.join(QUELLE, 'relay_agent.py'),
                 '--konfig', konf], stdout=lf, stderr=subprocess.STDOUT)
        time.sleep(3)
        if agent.poll() is not None:
            print('   Der Agent ist sofort gestorben. Sein Protokoll:')
            with open(log) as f:
                for z in f.read().splitlines()[-15:]:
                    print('      ' + z)
        pruefe(agent.poll() is None, 'Der Agent laeuft')

        einrichten.KONFIG_ORDNER = heim
        einrichten.MESSUNG_DATEI = os.path.join(heim, 'messungen.json')
        einrichten.MESS_FENSTER = os.path.join(heim, 'messung_laeuft')
        einrichten._geheimnis_lesen = lambda: geheim
        basis = 'http://127.0.0.1:%d' % PORT

        print('== 1. Der Rundlauf laeuft, waehrend der Agent arbeitet')
        e = einrichten.vermittler_messen(basis, groesse=128 * 1024)
        pruefe(not e.get('fehler'),
               'ohne Abbruch (%s)' % (e.get('fehler') or 'nichts'))

        def frage_ablegen():
            fuell = base64.b64encode(os.urandom(96)).decode('ascii')
            return netz.sende_json(basis + '/relay.php?action=frage',
                                   {'v': 1, 'krypto': 'noise_ik', 'teile': 1,
                                    'nutzlast': {'chiffre': fuell}}, geheim)

        print('== 2. Frage bleibt liegen, Fenster ist ZU -> er muss klagen')
        with open(log) as f:
            vorher = len(f.read())
        frage_ablegen()
        time.sleep(2.5)
        with open(log) as f:
            neu = f.read()[vorher:]
        pruefe('nicht entschluesselbar' in neu,
               'ohne Fenster meldet er die undurchsichtige Frage')

        print('== 3. Frage bleibt liegen, Fenster ist AUF -> er muss schweigen')
        einrichten._messfenster(30)
        frage_ablegen()
        time.sleep(2.5)
        einrichten._messfenster_zu()
        # SIGINT, nicht SIGTERM: Seine Zaehler gibt der Agent im
        # KeyboardInterrupt-Zweig aus, und nur dort. Und der Zaehler zaehlt
        # hier mehr als die Logzeile -- gemeldet wird jeder Grund nur EINMAL
        # (einmal()), gezaehlt aber jedes Mal.
        agent.send_signal(signal.SIGINT)
        agent.wait(timeout=10)
        with open(log) as f:
            ende = f.read()
        agent = None
        treffer = re.search(r'krypto_abgewiesen[^0-9]*(\d+)', ende)
        zahl = int(treffer.group(1)) if treffer else -1
        pruefe(zahl == 1,
               'genau EINE abgewiesene Frage gezaehlt, nicht zwei (%s)' % zahl)
    finally:
        for p in (agent, php):
            if p:
                try:
                    p.send_signal(signal.SIGTERM)
                    p.wait(timeout=5)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(heim, ignore_errors=True)

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
