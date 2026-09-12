#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ahpt_start.py -- Einstiegspunkt der gebuendelten Windows-.exe (PyInstaller).

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Als .exe liegt kein `python3` mehr daneben. `starten.py` startet den
Assistenten, den Agenten und das Messwerkzeug aber als EIGENE Prozesse --
ueber `[sys.executable, <skript>.py, ...]`. Eingefroren ist `sys.executable`
diese .exe selbst; der Aufruf `AHPT-Cloud.exe einrichten.py --port 8771`
wuerde ohne Vermittlung wieder nur die Oberflaeche oeffnen.

Dieser Einstieg ist genau diese Vermittlung. Er erkennt an `--rolle` ODER am
Dateinamen des ersten Arguments, welches Modul gemeint ist, und fuehrt es
statt der Oberflaeche aus. So bleibt `starten.py` fast unveraendert: Es ruft
weiterhin `[sys.executable, <skript>.py, ...]` auf, und hier landet der Ruf
beim richtigen Modul. Nur der Autostart nennt `--rolle agent` ausdruecklich,
weil ein `_MEIPASS`-Pfad einen Neustart nicht ueberlebt.

Im Quelltext-Betrieb (nicht eingefroren) wird diese Datei nicht gebraucht --
dort startet man `starten.py` wie bisher.
"""

import os
import runpy
import sys

# Welches Modul steckt hinter einem --rolle-Wert bzw. einem Skriptnamen.
_MODULE = {
    'agent':          'relay_agent',
    'relay_agent.py': 'relay_agent',
    'assistent':      'einrichten',
    'einrichten.py':  'einrichten',
    'messung':        'miss_leitung',
    'miss_leitung.py': 'miss_leitung',
}


def _ziel_und_argv(argv):
    """(Modulname oder None, bereinigtes argv) aus dem Aufruf bestimmen."""
    if len(argv) >= 3 and argv[1] == '--rolle':
        return _MODULE.get(argv[2]), [argv[2]] + argv[3:]
    if len(argv) >= 2:
        modul = _MODULE.get(os.path.basename(argv[1]).lower())
        if modul:
            return modul, argv[1:]
    return None, argv


def _stdio_absichern():
    """Fensterbau (--windowed) laesst sys.stdout/err None sein. print() darf
    nirgends daran zerbrechen. Wo ein Elternprozess die Ausgabe mitliest, ist
    sie bereits umgelenkt (dann NICHT None) -- nur den echten Leerfall fangen,
    damit das Mitlesen der Assistenten-Adresse heil bleibt."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    ziel = None
    try:
        ordner = os.path.expanduser('~/.ahpt')
        os.makedirs(ordner, exist_ok=True)
        ziel = open(os.path.join(ordner, 'exe.log'), 'a',
                    encoding='utf-8', buffering=1)
    except OSError:
        try:
            ziel = open(os.devnull, 'w')
        except OSError:
            return
    if sys.stdout is None:
        sys.stdout = ziel
    if sys.stderr is None:
        sys.stderr = ziel


def main():
    _stdio_absichern()
    modul, argv = _ziel_und_argv(sys.argv)
    sys.argv = argv
    if modul:
        runpy.run_module(modul, run_name='__main__')
    else:
        runpy.run_module('starten', run_name='__main__')


if __name__ == '__main__':
    main()
