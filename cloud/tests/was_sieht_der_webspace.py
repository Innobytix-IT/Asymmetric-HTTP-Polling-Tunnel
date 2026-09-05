#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
was_sieht_der_webspace.py -- die Gegenprobe am LAUFENDEN System

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
`durchstich_privat.py` prueft dasselbe gegen eine Attrappe. Diese Datei
prueft es dort, wo es zaehlt: an dem Webspace, auf dem die Sachen wirklich
liegen.

Sie holt die oeffentliche Warteschlange, dazu jede Frage- und Antwortdatei,
die sie darin findet -- also genau das, was ein beliebiger Fremder auch
bekaeme -- und sucht darin nach Klartext.

Geprueft wird auf ABWESENHEIT. Damit "nicht gefunden" etwas bedeutet, gibt
es eine Gegenprobe: Etwas, das dort WIRKLICH steht, muss gefunden werden.
Sonst hiesse das Ergebnis nur, dass die Suche nicht funktioniert.

Die Nadeln tragen Anfuehrungszeichen. Das ist kein Zufall: Sie werden
dadurch laenger, UND das Anfuehrungszeichen kommt im Base64-Alphabet nicht
vor. Eine vier Zeichen kurze Nadel wie `hole` taucht in ein paar hundert
Kilobyte Rauschen irgendwann zufaellig auf -- am 03.09.2026 genau so
passiert, und ein Pruefer mit Fehlalarm wird beim zweiten Mal ignoriert.

Aufruf:
    python3 tests/was_sieht_der_webspace.py http://example.de/privat
"""

import json
import sys
import urllib.error
import urllib.request

NADELN = [
    ('"dienst"',      'das Feld "dienst"'),
    ('"dateien"',     'der Name des Dienstes'),
    ('"aktion"',      'das Feld "aktion"'),
    ('"liste"',       'die Aktion'),
    ('"pfad"',        'das Feld "pfad"'),
    ('"gefunden"',    'ob etwas gefunden wurde'),
    ('"titel"',       'der Anzeigename'),
    ('"inhalt_typ"',  'die Art des Inhalts'),
    ('"eintraege"',   'die Struktur einer Auflistung'),
]


def hol(url):
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            return r.read()
    except urllib.error.HTTPError:
        return b''
    except Exception:
        return b''


def main():
    if len(sys.argv) < 2:
        print('Aufruf: was_sieht_der_webspace.py <basis>')
        return 2
    basis = sys.argv[1].rstrip('/')

    roh = hol(basis + '/ahpt/warteschlange.json')
    if not roh:
        print('ABBRUCH: Warteschlange nicht abrufbar.')
        print('         Entweder gibt es sie noch nicht (dann erst eine Frage')
        print('         stellen) oder die Adresse stimmt nicht. So oder so')
        print('         wurde hier NICHTS geprueft.')
        return 2

    alles = roh
    dateien = 1
    try:
        d = json.loads(roh)
    except ValueError:
        d = {}
    for e in (d.get('offen') or []):
        m = e.get('marke', '')
        if not m:
            continue
        for name in ('frage_%s.json' % m, 'antwort_%s.json' % m):
            b = hol('%s/ahpt/%s' % (basis, name))
            if b:
                alles += b
                dateien += 1

    print('')
    print('WAS DER WEBSPACE HERGIBT   %s' % basis)
    print('')
    print('  %d Datei(en), %d Bytes -- so, wie sie jeder Fremde bekaeme.'
          % (dateien, len(alles)))
    print('')

    fehler = 0
    for nadel, was in NADELN:
        drin = nadel.encode('utf-8') in alles
        if drin:
            fehler += 1
        print('  %-34s %s' % (was, 'GEFUNDEN -- liegt offen!' if drin
                              else 'nicht auffindbar'))

    # Ohne diese Zeile hiesse "nicht auffindbar" womoeglich nur, dass die
    # Suche gar nichts findet.
    print('')
    gegen = b'noise_ik' in alles
    print('  %-34s %s' % ('Gegenprobe: findet die Suche etwas?',
                          'ja (noise_ik)' if gegen
                          else 'NEIN -- die Pruefung sagt nichts aus'))
    if not gegen:
        fehler += 1

    print('')
    if fehler == 0:
        print('ERGEBNIS: Der Webspace sieht Rauschen.')
        print('')
        print('  Was er weiterhin sieht: WANN gefragt wird, WIE OFT und WIE')
        print('  GROSS die Antwort war. Verschluesselung verbirgt den Inhalt,')
        print('  nicht die Umstaende.')
    else:
        print('ERGEBNIS: %d Beanstandung(en) -- NICHT in Betrieb nehmen.' % fehler)
    return 1 if fehler else 0


if __name__ == '__main__':
    sys.exit(main())
