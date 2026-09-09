#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pruefe_liste.py -- warum eine Liste kuerzer ist, als der Ordner Eintraege hat

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
`liste` laesst drei Sorten von Eintraegen weg und sagt zu jeder, wie viele
es waren: `gekappt`, `versteckt`, `endung_gesperrt`. Diese Zahlen sind die
einzige Moeglichkeit, "der Ordner ist leer" von "hier ist alles gesperrt"
zu unterscheiden.

Genau deshalb sind sie die Sorte Angabe, deren Ausfall NIEMANDEM AUFFAELLT.
Am 09.09.2026 zweimal belegt: Die Android-App las den dritten Zaehler unter
einem Namen, den der Agent nie schickt -- und bekam von `optInt` brav 0,
also "nichts gesperrt". Das Portal zeigte zwei der drei Gruende. Keiner der
beiden Fehler hat je eine Fehlermeldung erzeugt; beide fielen beim Lesen
auf, nicht im Betrieb.

Ein Test, der die Zahlen festnagelt, ist deshalb mehr wert als bei den
meisten anderen Feldern: Ein falscher Wert ist hier still.

Aufruf:
    python3 tests/pruefe_liste.py
"""

import json
import os
import shutil
import sys
import tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))

from handler.datei import DateiHandler, MAX_EINTRAEGE   # noqa: E402

GRUEN, ROT, GRAU, AUS = '\033[32m', '\033[31m', '\033[90m', '\033[0m'
if os.name == 'nt' or not sys.stdout.isatty():
    GRUEN = ROT = GRAU = AUS = ''

_zahl = [0, 0]


def pruef(was, bedingung, hinweis=''):
    _zahl[0] += 1
    if bedingung:
        print('  %-58s %sok%s' % (was, GRUEN, AUS))
    else:
        _zahl[1] += 1
        print('  %-58s %sFEHLGESCHLAGEN%s' % (was, ROT, AUS))
        if hinweis:
            print('      %s%s%s' % (GRAU, hinweis, AUS))


def abschnitt(t):
    print('\n%s\n' % t.upper())


def mach_handler(wurzel, **mehr):
    konfig = {'name': 'dateien', 'art': 'datei', 'wurzel': wurzel,
              'aktionen': ['liste', 'hole', 'lege', 'neuer_ordner'],
              'endungen': []}
    konfig.update(mehr)
    return DateiHandler(konfig)


def liste(h, pfad=''):
    """Die Antwort von `liste` als Objekt."""
    a = h.bearbeite('liste', {'pfad': pfad})
    return json.loads(a['inhalt'])


def schreibe(pfad, text='x'):
    with open(pfad, 'w', encoding='utf-8') as f:
        f.write(text)


def main():
    wurzel = tempfile.mkdtemp(prefix='ahpt_liste_')
    try:
        abschnitt('Die drei Gruende einzeln')

        schreibe(os.path.join(wurzel, 'sichtbar.txt'))
        schreibe(os.path.join(wurzel, '.geheim'))
        os.mkdir(os.path.join(wurzel, '.ahpt-teil'))

        h = mach_handler(wurzel)
        d = liste(h)
        namen = [e['name'] for e in d['eintraege']]

        pruef('sichtbare Datei erscheint', namen == ['sichtbar.txt'], repr(namen))
        pruef('versteckte Datei erscheint NICHT', '.geheim' not in namen)
        pruef('der Sammelordner erscheint NICHT', '.ahpt-teil' not in namen)

        # DAS ist der Punkt dieser Datei.
        #
        # `.ahpt-teil` legt der Handler selbst an, er liegt in jeder Wurzel
        # und verschwindet nie. Zaehlte er mit, stuende der Hinweis "1
        # versteckte" dauerhaft auf dem Schirm -- fuer etwas voellig
        # Normales. Eine Anzeige, die immer an ist, lernt man zu
        # uebersehen, und dann uebersieht man sie auch, wenn sie einmal
        # etwas Echtes meldet.
        pruef('versteckt zaehlt NUR die fremde (1, nicht 2)',
              d.get('versteckt') == 1, 'versteckt=%r' % d.get('versteckt'))

        abschnitt('Der Sammelordner allein ergibt gar keinen Hinweis')

        wurzel2 = tempfile.mkdtemp(prefix='ahpt_liste2_')
        try:
            os.mkdir(os.path.join(wurzel2, '.ahpt-teil'))
            schreibe(os.path.join(wurzel2, 'nur_die.txt'))
            d2 = liste(mach_handler(wurzel2))
            # Kein Schluessel, nicht etwa 0: Der Handler setzt das Feld nur,
            # wenn es etwas zu sagen gibt.
            pruef('kein `versteckt`-Feld, wenn nur der eigene Ordner da ist',
                  'versteckt' not in d2, repr(d2))
        finally:
            shutil.rmtree(wurzel2, ignore_errors=True)

        abschnitt('Tiefer im Baum gehoert der Name dem Nutzer')

        # Ein Ordner desselben Namens UNTERHALB der Wurzel ist keiner von
        # uns -- den hat jemand angelegt, und der zaehlt.
        unter = os.path.join(wurzel, 'unter')
        os.mkdir(unter)
        os.mkdir(os.path.join(unter, '.ahpt-teil'))
        d3 = liste(h, 'unter')
        pruef('gleichnamiger Ordner tiefer im Baum zaehlt mit',
              d3.get('versteckt') == 1, 'versteckt=%r' % d3.get('versteckt'))

        abschnitt('Gesperrte Endung')

        h2 = mach_handler(wurzel, endungen=['txt'])
        d4 = liste(h2)
        schreibe(os.path.join(wurzel, 'gesperrt.exe'))
        d4 = liste(h2)
        # Der Name des Feldes ist der Vertrag mit drei Oberflaechen
        # (Kommandozeile, Portal, App). Er steht hier woertlich.
        pruef('Feld heisst `endung_gesperrt`', 'endung_gesperrt' in d4, repr(d4))
        pruef('genau eine Datei gesperrt', d4.get('endung_gesperrt') == 1)
        pruef('die erlaubte ist noch da',
              [e['name'] for e in d4['eintraege']] == ['unter', 'sichtbar.txt']
              or 'sichtbar.txt' in [e['name'] for e in d4['eintraege']])

        abschnitt('Gekappt')

        wurzel3 = tempfile.mkdtemp(prefix='ahpt_liste3_')
        try:
            for i in range(MAX_EINTRAEGE + 5):
                schreibe(os.path.join(wurzel3, 'd%04d.txt' % i))
            d5 = liste(mach_handler(wurzel3))
            pruef('gekappt meldet die Obergrenze',
                  d5.get('gekappt') == MAX_EINTRAEGE, repr(d5.get('gekappt')))
            pruef('nicht mehr als MAX_EINTRAEGE geliefert',
                  len(d5['eintraege']) == MAX_EINTRAEGE)
        finally:
            shutil.rmtree(wurzel3, ignore_errors=True)

    finally:
        shutil.rmtree(wurzel, ignore_errors=True)

    print('\n%d Pruefungen, %d fehlgeschlagen.' % (_zahl[0], _zahl[1]))
    return 1 if _zahl[1] else 0


if __name__ == '__main__':
    sys.exit(main())
