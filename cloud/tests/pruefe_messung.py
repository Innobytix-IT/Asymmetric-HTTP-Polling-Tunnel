#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pruefe_messung.py -- den Rundlauf-Test gegen ein echtes PHP fahren

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
`vermittler_messen()` in einrichten.py laesst einen vollstaendigen
AHPT-Vorgang laufen: Frage ablegen, Stuecke ablegen, Antwort ablegen, alles
statisch wieder abholen. Das laesst sich nicht sinnvoll nachbilden -- die
Zeit steckt zu grossen Teilen genau in dem, was PHP und der Webserver mit
den Stuecken machen. Eine Attrappe wuerde all das richtig machen und den
Fehler verstecken.

Also ein echter PHP-Prozess (`php -S`) mit einem WEGWERF-Vermittler in einem
temporaeren Ordner. Die eingerichtete Anlage des Nutzers wird nicht
angefasst; das Geheimnis dieses Tests entsteht hier und stirbt hier.

WAS DIESER TEST SCHON GEFUNDEN HAT
-----------------------------------
Am 08.09.2026, in seiner ersten Fassung: Mit dem RICHTIGEN Geheimnis kam ein
403 zurueck. Die Ursache lag nicht in der Messung, sondern in einrichten.py
-- es schrieb relay_token.php als `<?php return "<geheimnis>";`, eine Datei
ohne Zeilenschaltung, aus der lies_geschuetzt() in relay.php immer eine
leere Zeichenkette macht. agent_erlaubt() war dauerhaft falsch: JEDE ueber
den Assistenten eingerichtete Anlage haette auf jede Frage nie eine Antwort
bekommen.

Deshalb baut dieser Test die beiden Dateien mit den ECHTEN Erzeugern aus
einrichten.py und nicht mit einer eigenen, gut gemeinten Nachbildung. Eine
Nachbildung haette hier das Richtige getan und den Fehler zugedeckt.

Aufruf:
    python3 tests/pruefe_messung.py
"""

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


def pruefe_ohne_php(einrichten):
    """Was sich ohne laufenden Webspace pruefen laesst.

    Der Fahrplan der Clients ist reine Rechnerei -- und gerade deshalb muss
    er stimmen: Er geht als "Warten (Client)" in das Ergebnis ein, ohne dass
    ihn irgendetwas nachmisst.
    """
    print('== 1. Der Vermittler ist wieder dumm')
    with open(os.path.join(QUELLE, 'relay.php'), encoding='utf-8') as f:
        relay = f.read()
    # Die erste Fassung dieses Werkzeugs hatte eine eigene Aktion im
    # Vermittler. Sie ist weg, und sie soll wegbleiben: Der Rundlauf
    # braucht keinen einzigen Aufruf, den es nicht ohnehin gaebe.
    pruefe('messung' not in relay,
           'relay.php kennt keine eigene Mess-Aktion')

    print('== 2. Der Fahrplan der Clients')
    # 350 ms, dann mal 1,3, gedeckelt bei 1500 -- so steht es in
    # portal/ahpt.js und in Protokoll.kt. Der erste Abruf faellt auf t = 0.
    w = einrichten._client_wartezeit
    pruefe(abs(w(0.0, 0.0)) < 1e-9,
           'Antwort sofort da -> gar kein Warten (%.3f s)' % w(0.0, 0.0))
    # Abrufe bei 0, 0.350, 0.805, 1.396, 2.164 ...
    pruefe(abs(w(0.2, 0.0) - 0.150) < 1e-6,
           'bereit nach 0.2 s -> Abruf bei 0.350, also 0.150 s Warten')
    pruefe(abs(w(0.9, 0.0) - 0.496) < 1e-3,
           'bereit nach 0.9 s -> Abruf bei 1.396, also 0.496 s Warten')
    pruefe(w(30.0, 0.0) <= 1.5 + 1e-6,
           'nach langem Lauf hoechstens der Deckel von 1.5 s (%.3f s)'
           % w(30.0, 0.0))

    print('== 3. Die Herkunft der Leitungsangabe bleibt erhalten')
    # miss_leitung.py schreibt "gemessen". Wenn das Messfenster danach
    # speichert, OHNE dass jemand die Felder angefasst hat, darf daraus
    # nicht "eingetragen" werden -- sonst steht dort eine Herkunft, die
    # nicht stimmt, und ein gemessener Wert verliert sein Gewicht.
    import json
    import tempfile
    import time as _t
    ordner = tempfile.mkdtemp(prefix='ahpt_leitung_')
    alt_datei = einrichten.LEITUNG_DATEI
    try:
        einrichten.LEITUNG_DATEI = os.path.join(ordner, 'leitung.json')
        with open(einrichten.LEITUNG_DATEI, 'w') as f:
            json.dump({'herunter_mbit': 54.5, 'hinauf_mbit': 20.4,
                       'quelle': 'gemessen', 'zeit': _t.time(),
                       'knoten': 'FRA'}, f)
        einrichten.leitung_schreiben(20.4, 54.5)
        pruefe(einrichten.leitung_lesen().get('quelle') == 'gemessen',
               'unveraendert gespeichert -> bleibt "gemessen"')
        einrichten.leitung_schreiben(20.4, 100)
        pruefe(einrichten.leitung_lesen().get('quelle') == 'eingetragen',
               'von Hand geaendert -> wird "eingetragen"')
        pruefe(einrichten.leitung_lesen().get('herunter_mbit') == 100,
               'und der neue Wert steht drin')
    finally:
        einrichten.LEITUNG_DATEI = alt_datei
        shutil.rmtree(ordner, ignore_errors=True)


def main():
    import einrichten

    pruefe_ohne_php(einrichten)

    if shutil.which('php') is None:
        print()
        print('PHP fehlt -- der Rundlauf braucht es und kann ohne nichts sagen.')
        print('Debian/Ubuntu/Mint:  sudo apt install php-cli')
        return 77 if not fehler else 1

    tmp = tempfile.mkdtemp(prefix='ahpt_messung_')
    heim = tempfile.mkdtemp(prefix='ahpt_heim_')
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

        # Eigenes Zuhause: Das Geheimnis dieses Tests statt des
        # eingerichteten, und der Verlauf soll nicht in den echten laufen.
        einrichten.KONFIG_ORDNER = heim
        einrichten.MESSUNG_DATEI = os.path.join(heim, 'messungen.json')
        einrichten.MESS_FENSTER = os.path.join(heim, 'messung_laeuft')
        einrichten._geheimnis_lesen = lambda: geheim
        basis = 'http://127.0.0.1:%d' % PORT

        print('== 4. Ein vollstaendiger Rundlauf')
        verlauf = []
        e = einrichten.vermittler_messen(basis, melde=verlauf.append,
                                         groesse=256 * 1024)
        pruefe(not e.get('fehler'),
               'ohne Abbruch (%s)' % (e.get('fehler') or 'nichts'))
        pruefe(e['verdikt'] in ('gut', 'lahm'), 'Verdikt: %s' % e['verdikt'])

        print('== 5. Die Zahlen sind plausibel')
        # Base64 blaeht um genau ein Drittel auf. Kommt etwas anderes
        # heraus, wurde nicht das gemessen, was der Agent wirklich schickt.
        soll = 256 * 1024 * 4 / 3
        pruefe(abs(e['leitung_bytes'] - soll) < 8,
               'Base64: %d Byte Datei -> %d Byte Leitung (erwartet ~%d)'
               % (e['datei_bytes'], e['leitung_bytes'], soll))
        pruefe(e['stuecke'] == 8,
               '%d Stuecke zu je 48 KiB' % e['stuecke'])
        # Was abgelegt wurde, muss auch zurueckkommen -- sonst misst der
        # Test einen halben Vorgang und meldet ihn als ganzen.
        pruefe(e['zurueck_bytes'] >= e['leitung_bytes'],
               'zurueckgeholt: %d Byte (abgelegt: %d)'
               % (e['zurueck_bytes'], e['leitung_bytes']))
        pruefe(e['arbeit_s'] > 0, 'Arbeit: %.2f s' % e['arbeit_s'])
        pruefe(e['rundlauf_s'] > e['arbeit_s'],
               'Rundlauf %.2f s > Arbeit %.2f s (Warten kommt dazu)'
               % (e['rundlauf_s'], e['arbeit_s']))
        pruefe(abs(e['rundlauf_s'] - (e['arbeit_s'] + e['warten_agent_s']
                                      + e['warten_client_s'])) < 1e-6,
               'Rundlauf = Arbeit + Warten (Agent %.2f + Client %.2f)'
               % (e['warten_agent_s'], e['warten_client_s']))
        pruefe(e.get('durchsatz_bps', 0) > 0,
               'Durchsatz: %s' % einrichten._tempo(e.get('durchsatz_bps')))
        pruefe(len(verlauf) >= 5,
               '%d Fortschrittsmeldungen' % len(verlauf))

        print('== 6. Die eigene Leitung als Vergleichsgroesse')
        # Dieselbe Messung, zwei Vertragsraten -- und zwei verschiedene
        # Befunde. Genau das ist der Zweck: Ein Vermittler, der die Leitung
        # ausschoepft, ist nicht lahm, sondern fertig.
        einrichten.LEITUNG_DATEI = os.path.join(heim, 'leitung.json')
        rate = (e.get('ablegen_bps') or 0) * 8 / 1e6
        einrichten.leitung_schreiben(round(rate * 1.1, 2), 1000)   # knapp drueber
        e_eng = einrichten.vermittler_messen(basis, groesse=256 * 1024)
        pruefe(e_eng.get('anteil_hinauf', 0) and e_eng['anteil_hinauf'] > 0.6,
               'knappe Leitung -> hoher Anteil (%.0f %%)'
               % ((e_eng.get('anteil_hinauf') or 0) * 100))
        pruefe(any('Am Vermittler liegt es jedenfalls nicht' in x
                   for x in e_eng['saetze']),
               'und der Satz sagt: nicht der Vermittler')

        einrichten.leitung_schreiben(rate * 20, 1000)              # weit drueber
        e_weit = einrichten.vermittler_messen(basis, groesse=256 * 1024)
        pruefe((e_weit.get('anteil_hinauf') or 1) < 0.25,
               'weite Leitung -> niedriger Anteil (%.0f %%)'
               % ((e_weit.get('anteil_hinauf') or 0) * 100))
        pruefe(any('NICHT dein' in x for x in e_weit['saetze']),
               'und der Satz sagt: nicht dein Anschluss')
        einrichten.leitung_schreiben(None, None)

        print('== 7. Das Messfenster wird wieder geschlossen')
        # Bleibt es stehen, zaehlt der Agent dauerhaft keine abgewiesenen
        # Fragen mehr -- und genau darauf soll man sich verlassen koennen.
        pruefe(not os.path.exists(einrichten.MESS_FENSTER),
               'messung_laeuft ist weg')

        print('== 8. Die Warteschlange bleibt aufgeraeumt')
        st = einrichten._relay_selbsttest(basis)
        pruefe(st is not None and st.get('offen') == 0,
               'keine offene Marke zurueckgelassen (offen=%s)'
               % (st or {}).get('offen'))

        print('== 9. Der Verlauf wurde fortgeschrieben')
        v = einrichten._messungen_lesen()
        pruefe(len(v) == 3 and all(x.get('arbeit_s') for x in v),
               '%d Eintraege im Verlauf' % len(v))

        print('== 10. Ist er weg, sagt die Messung das -- und raet nicht')
        php.send_signal(signal.SIGTERM)
        php.wait(timeout=10)
        php = None
        e2 = einrichten.vermittler_messen(basis)
        pruefe(e2['verdikt'] == 'weg',
               'Verdikt nach Abschaltung: %s' % e2['verdikt'])
        pruefe(bool(e2['saetze']), 'mit Begruendung: %s'
               % (e2['saetze'][0][:58] if e2['saetze'] else '(keine)'))
    finally:
        if php:
            try:
                php.kill()
            except OSError:
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
