#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
anhang_scan_attrappe.py -- ein Fake-Virenscanner fuer pruefe_bloecke.py

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
`_scan_virus()` in handler/datei.py kennt keinen bestimmten Virenscanner,
nur die Kommandozeilen-Konvention: Exitcode 0 heisst sauber, alles andere
heisst nicht sauber. Um das zu pruefen, braucht es kein echtes ClamAV --
nur etwas, das sich an dieselbe Konvention haelt.

Diese Attrappe erkennt die EICAR-Testzeichenkette -- denselben Text, den
auch echte Virenscanner als harmlosen, aber garantiert erkannten Testfall
behandeln (https://www.eicar.org/download-anti-malware-testfile/). Eine
Datei damit ist kein Schadcode, nur eine Vereinbarung, die jeder Scanner
kennt.

Aufruf:  python3 anhang_scan_attrappe.py <datei>
Exitcode 0 = sauber, 1 = "Fund", 2 = Datei nicht lesbar (Scanner-Fehler).
"""
import sys

EICAR = (r'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE'
         r'!$H+H*')

if len(sys.argv) != 2:
    print('Aufruf: anhang_scan_attrappe.py <datei>', file=sys.stderr)
    sys.exit(2)

try:
    with open(sys.argv[1], 'rb') as f:
        inhalt = f.read()
except OSError as e:
    print('nicht lesbar: %s' % e, file=sys.stderr)
    sys.exit(2)

if EICAR.encode('ascii') in inhalt:
    print('EICAR-Testsignatur gefunden')
    sys.exit(1)

sys.exit(0)
