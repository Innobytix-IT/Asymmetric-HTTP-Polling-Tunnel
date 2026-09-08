#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
starten.pyw -- dasselbe wie starten.py, nur ohne Konsolenfenster

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

Windows entscheidet an der ENDUNG, ob ein schwarzes Konsolenfenster
mitgeht: .py oeffnet eines, .pyw nicht. Fuer einen Doppelklick ist das der
ganze Unterschied -- ein Fenster, das niemand gelesen hat und das beim
Schliessen das Programm mitnimmt, ist kein guter erster Eindruck.

Deshalb liegt hier keine Kopie, sondern nur der Aufruf. Zwei Fassungen
derselben Oberflaeche wuerden auseinanderlaufen, sobald man eine davon
anfasst.

Unter Linux und Mac ist die Endung bedeutungslos; dort startet man
weiterhin starten.py.
"""

import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
runpy.run_module('starten', run_name='__main__')
