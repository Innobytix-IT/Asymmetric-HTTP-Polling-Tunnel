#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pruefe_transport.py -- prueft transport.py ohne Netz und ohne Konto

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
`transport.py` ist das Neue an AHPT Cloud 3000: mehrere Wege zum
Vermittler statt einem. Alles, was `relay.php` beim PHP-Weg
serverseitig erledigt, steckt beim WebDAV-Weg im Transport selbst --
und damit in Code, den keine Gegenseite mehr fuer uns prueft.

Zwei Dinge sind hier nur mit einem Test zu halten:

  * Die Verzeichnisliste. WebDAV antwortet auf PROPFIND mit XML, und das
    NAMENSRAUM-KUERZEL vor "href" waehlt jeder Server frei -- GMX
    schreibt "D:href", freenet "x1:href", beides gueltig. Am 07.09.2026
    kostete genau das einen halben Abend: identische Antwort, anderes
    Kuerzel, `hole_offene_marken` fand nichts, obwohl die Datei
    nachweislich dalag. Ein Regex auf ein festes Kuerzel waere bei jedem
    neuen Anbieter erneut zerbrochen. Diese Pruefung nagelt fest, dass
    ueber den Namensraum aufgeloest wird und nicht ueber das Kuerzel.

  * Der Kreislauf-Unterbrecher. Ein dauerhaft toter Weg darf nicht bei
    JEDER Nachricht erneut seine volle Frist verstreichen lassen. Diese
    Pruefung sagt, ab wann gesperrt wird, wie lange, und dass ein Erfolg
    die Zaehlung wirklich zuruecksetzt -- nicht nur die Sperre aufhebt.

OHNE NETZ, OHNE KONTO
---------------------
`netz.webdav` wird fuer die Dauer der Pruefung durch eine Attrappe
ersetzt, die vorgegebene Antworten zurueckgibt. Getestet wird damit
nicht, ob GMX antwortet -- das sagt `gmx_webdav_test.py` gegen ein
echtes Konto -- sondern, ob wir eine Antwort richtig verstehen. Das ist
der Teil, der bei einem neuen Anbieter bricht.

Aufruf:
    python3 tests/pruefe_transport.py
"""

import json
import os
import sys
import tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))

import netz                                              # noqa: E402
import transport                                         # noqa: E402

ERGEBNIS = []


def pruefe(beschreibung, bedingung, hinweis=''):
    ok = bool(bedingung)
    ERGEBNIS.append(ok)
    print('  %-58s %s%s' % (beschreibung, 'ok' if ok else 'FEHLSCHLAG',
                            ('  -- ' + hinweis) if hinweis and not ok else ''))
    return ok


# --------------------------------------------------------------- Attrappe

class Attrappe:
    """Ersetzt `netz.webdav` und merkt sich, was gefragt wurde.

    `antworten` ist eine Liste von (code, koerper) -- eine je Aufruf, in
    der Reihenfolge. Geht sie aus, kommt 404 (nichts da), damit ein Test
    nicht am Ende der Liste stolpert statt an seiner Behauptung.
    """

    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe = []

    def __call__(self, methode, url, benutzer, passwort, daten=None,
                 kopfzeilen=None, timeout=15):
        self.aufrufe.append({'methode': methode, 'url': url, 'daten': daten,
                             'benutzer': benutzer, 'passwort': passwort,
                             'kopfzeilen': kopfzeilen or {}})
        if not self.antworten:
            return 404, b''
        return self.antworten.pop(0)


def mit_attrappe(antworten):
    """Baut einen WebDavTransport, dessen Netzzugriff die Attrappe ist."""
    ordner = tempfile.mkdtemp()
    pw = os.path.join(ordner, 'pw')
    with open(pw, 'w', encoding='utf-8') as f:
        f.write('geheim\n')
    t = transport.WebDavTransport('probe', 'https://dav.example.net/',
                                  'konto@example.net', pw)
    a = Attrappe(antworten)
    netz.webdav = a
    return t, a


# ------------------------------------------------------ Verzeichnisliste

# Zwei ECHTE Antwortformen, nur gekuerzt: dasselbe Ergebnis, anderes
# Namensraum-Kuerzel. Genau daran ist es am 07.09.2026 gescheitert.
XML_GMX = b'''<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response><D:href>/ahpt/</D:href></D:response>
  <D:response><D:href>/ahpt/frage_00112233445566778899aabbccddeeff.json</D:href></D:response>
  <D:response><D:href>/ahpt/antwort_00112233445566778899aabbccddeeff.json</D:href></D:response>
</D:multistatus>'''

XML_FREENET = b'''<?xml version="1.0" encoding="utf-8"?>
<x1:multistatus xmlns:x1="DAV:">
  <x1:response><x1:href>/ahpt/</x1:href></x1:response>
  <x1:response><x1:href>/ahpt/frage_00112233445566778899aabbccddeeff.json</x1:href></x1:response>
</x1:multistatus>'''

# Ein Name mit Prozent-Kodierung -- WebDAV-Server duerfen kodieren, und
# ein nicht dekodierter Name passt auf kein Muster.
XML_KODIERT = b'''<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response><D:href>/ahpt%2Fx/frage_ffeeddccbbaa99887766554433221100.json</D:href></D:response>
</D:multistatus>'''


def verzeichnis_pruefen():
    print('')
    print('VERZEICHNISLISTE (PROPFIND)')
    print('')

    marke = '00112233445566778899aabbccddeeff'

    t, a = mit_attrappe([(207, XML_GMX)])
    marken, fehler = t.hole_offene_marken(set())
    pruefe('GMX-Form ("D:href") wird gelesen',
           fehler is None and marken == [marke], repr(marken))
    pruefe('PROPFIND fragt mit Depth 1',
           a.aufrufe and a.aufrufe[0]['kopfzeilen'].get('Depth') == '1')
    pruefe('Antwortdatei zaehlt nicht als offene Frage',
           marken == [marke])

    t, a = mit_attrappe([(207, XML_FREENET)])
    marken, fehler = t.hole_offene_marken(set())
    pruefe('freenet-Form ("x1:href") wird ebenso gelesen',
           fehler is None and marken == [marke], repr(marken))

    t, a = mit_attrappe([(207, XML_KODIERT)])
    marken, fehler = t.hole_offene_marken(set())
    pruefe('prozentkodierter Pfad wird dekodiert',
           marken == ['ffeeddccbbaa99887766554433221100'], repr(marken))

    t, a = mit_attrappe([(207, XML_GMX)])
    marken, fehler = t.hole_offene_marken({marke})
    pruefe('schon bearbeitete Marke kommt nicht noch einmal',
           marken == [], repr(marken))

    # Ein Server, der etwas anderes schickt als XML, darf keinen
    # Absturz ausloesen -- der Agent laeuft Tage, ein Aufschlag hier
    # beendet ihn.
    t, a = mit_attrappe([(207, b'<multistatus><nicht geschlossen')])
    marken, fehler = t.hole_offene_marken(set())
    pruefe('unlesbares XML ergibt Fehler statt Absturz',
           marken is None and fehler, repr(fehler))

    # Wohlgeformtes XML ohne ein einziges href ist KEINE leere
    # Verzeichnisliste -- eine echte nennt immer mindestens die
    # Sammlung selbst. Als "nichts offen" gelesen, pollte der Agent
    # ewig geduldig daran vorbei, ohne dass je eine Sperre griffe.
    t, a = mit_attrappe([(207, b'<html>Wartungsarbeiten</html>')])
    marken, fehler = t.hole_offene_marken(set())
    pruefe('207 ganz ohne href gilt als Fehler, nicht als "leer"',
           marken is None and fehler, repr(fehler))

    t, a = mit_attrappe([(401, b'nope')])
    marken, fehler = t.hole_offene_marken(set())
    pruefe('abgelehnt (401) ergibt Fehler, nicht "nichts offen"',
           marken is None and '401' in (fehler or ''), repr(fehler))

    # 0 heisst bei netz.py "gar keine Antwort", nicht "abgelehnt". Wer
    # das verwechselt, sperrt einen Weg wegen eines Wackelkontakts.
    t, a = mit_attrappe([(0, b'Name oder Dienst nicht bekannt')])
    marken, fehler = t.hole_offene_marken(set())
    pruefe('Netzfehler (0) wird als Grund durchgereicht',
           marken is None and 'nicht bekannt' in (fehler or ''), repr(fehler))


# --------------------------------------------------------- Ablegen/Holen

def ablegen_pruefen():
    print('')
    print('ABLEGEN UND HOLEN')
    print('')

    marke = '00112233445566778899aabbccddeeff'

    t, a = mit_attrappe([(201, b'')])
    ok, grund = t.lege_frage(marke, {'v': 1, 'nutzlast': {'chiffre': 'abc'}})
    pruefe('PUT mit 201 gilt als abgelegt', ok and grund == '')
    pruefe('Pfad enthaelt die Marke',
           a.aufrufe and a.aufrufe[0]['url'].endswith(
               '/frage_%s.json' % marke), a.aufrufe[0]['url'] if a.aufrufe else '')
    pruefe('Basis behaelt keinen doppelten Schraegstrich',
           '//frage' not in a.aufrufe[0]['url'].split('://', 1)[1])

    t, a = mit_attrappe([(204, b'')])
    ok, _ = t.lege_frage(marke, {'v': 1})
    pruefe('PUT mit 204 gilt ebenso als abgelegt', ok)

    # Der RUMPF muss mit in die Meldung: Bei 4xx steht die eigentliche
    # Ursache fast immer nur dort, nie im Statuscode allein.
    t, a = mit_attrappe([(400, b'Quota exceeded')])
    ok, grund = t.lege_frage(marke, {'v': 1})
    pruefe('abgelehntes PUT nennt den Rumpf, nicht nur den Code',
           not ok and 'Quota exceeded' in grund, repr(grund))

    t, a = mit_attrappe([(0, b'Zeitueberschreitung')])
    ok, grund = t.lege_frage(marke, {'v': 1})
    pruefe('nicht erreichbar wird von abgelehnt unterschieden',
           not ok and 'nicht erreichbar' in grund, repr(grund))

    gross = {'v': 1, 'nutzlast': {'chiffre':
             'x' * (transport.MAX_WEBDAV_NUTZLAST + 1)}}
    t, a = mit_attrappe([(201, b'')])
    ok, grund = t.lege_frage(marke, gross)
    pruefe('ueber dem Deckel wird gar nicht erst gesendet',
           not ok and 'zu gross' in grund and not a.aufrufe, repr(grund))

    t, a = mit_attrappe([(200, json.dumps({'v': 1, 'ok': True}).encode())])
    da, umschlag, grund = t.hole_antwort(marke)
    pruefe('Antwort wird als JSON zurueckgegeben',
           da and umschlag == {'v': 1, 'ok': True}, repr(umschlag))

    # 404 heisst "noch nicht da" -- der Normalfall beim Warten, kein
    # Fehler. Wer das als Fehler zaehlt, sperrt den Weg beim Warten.
    t, a = mit_attrappe([(404, b'')])
    da, umschlag, grund = t.hole_antwort(marke)
    pruefe('404 ist "noch nicht da", kein Fehler',
           not da and umschlag is None and grund == '', repr(grund))

    t, a = mit_attrappe([(200, b'{kein json')])
    da, umschlag, grund = t.hole_antwort(marke)
    pruefe('unlesbare Antwort ergibt Fehler statt Absturz',
           not da and grund, repr(grund))

    t, a = mit_attrappe([(204, b'')])
    t.loesche_antwort(marke)
    pruefe('Loeschen benutzt DELETE',
           a.aufrufe and a.aufrufe[0]['methode'] == 'DELETE')

    # Das Passwort reist in der Kopfzeile dieser einen Anfrage -- es darf
    # in keinem Pfad und keiner Meldung auftauchen.
    pruefe('Passwort steht in keiner URL',
           all('geheim' not in x['url'] for x in a.aufrufe))


# ------------------------------------------------------------ Gesundheit

def gesundheit_pruefen():
    print('')
    print('KREISLAUF-UNTERBRECHER')
    print('')

    g = transport.Gesundheit()
    pruefe('unbekannter Weg gilt als verfuegbar', g.verfuegbar('neu', 1000))

    g.fehlschlag('w', 1000)
    pruefe('ein Fehlschlag sperrt noch nicht', g.verfuegbar('w', 1000))

    bis = g.fehlschlag('w', 1000)
    pruefe('der zweite sperrt (SCHWELLE=2)',
           bis == 1000 + transport.Gesundheit.SPERRZEIT, repr(bis))
    pruefe('waehrend der Sperre nicht verfuegbar', not g.verfuegbar('w', 1100))
    pruefe('nach der Sperre wieder verfuegbar',
           g.verfuegbar('w', 1000 + transport.Gesundheit.SPERRZEIT))

    bis2 = g.fehlschlag('w', 2000)
    pruefe('jeder weitere Fehlschlag verlaengert',
           bis2 == 2000 + transport.Gesundheit.SPERRZEIT * 2, repr(bis2))

    for i in range(20):
        letzte = g.fehlschlag('w', 3000)
    pruefe('die Sperre ist gedeckelt',
           letzte == 3000 + transport.Gesundheit.SPERRZEIT_DECKEL, repr(letzte))

    # Erfolg muss die ZAEHLUNG zuruecksetzen, nicht nur die Sperre --
    # sonst springt der naechste einzelne Fehlschlag sofort auf den
    # gedeckelten Wert, und ein kurzer Aussetzer sperrt eine Stunde.
    g.erfolg('w')
    pruefe('Erfolg macht sofort wieder verfuegbar', g.verfuegbar('w', 3000))
    pruefe('Erfolg setzt die Zaehlung zurueck, nicht nur die Sperre',
           g.fehlschlag('w', 4000) is None)

    pruefe('stand() nennt einen gesunden Weg verfuegbar',
           transport.Gesundheit().stand('x', 1000) == 'verfuegbar')
    g2 = transport.Gesundheit()
    g2.fehlschlag('y', 1000)
    g2.fehlschlag('y', 1000)
    pruefe('stand() nennt die Restzeit', 'gesperrt' in g2.stand('y', 1010))
    pruefe('stand() kuendigt den Testversuch an',
           g2.stand('y', 9999) == 'wird erneut geprueft')


def gedaechtnis_pruefen():
    print('')
    print('GESUNDHEITS-GEDAECHTNIS AUF PLATTE')
    print('')

    ordner = tempfile.mkdtemp()
    pfad = os.path.join(ordner, 'gesundheit.json')

    pruefe('fehlende Datei ergibt ein leeres Gedaechtnis',
           transport.lies_gesundheit(pfad).zustand == {})

    g = transport.Gesundheit()
    g.fehlschlag('w', 1000)
    g.fehlschlag('w', 1000)
    transport.schreibe_gesundheit(pfad, g)
    zurueck = transport.lies_gesundheit(pfad)
    pruefe('geschrieben und wieder gelesen ist derselbe Zustand',
           zurueck.zustand == g.zustand, repr(zurueck.zustand))
    pruefe('die Sperre ueberlebt den Programmlauf',
           not zurueck.verfuegbar('w', 1100))

    pruefe('kein .tmp bleibt liegen',
           not os.path.exists(pfad + '.tmp'))

    # Eine halb geschriebene Datei darf den naechsten Aufruf nicht
    # lahmlegen -- lieber ohne Gedaechtnis anlaufen als gar nicht.
    with open(pfad, 'w', encoding='utf-8') as f:
        f.write('{"w": {"fehler": 2, "gespe')
    pruefe('abgeschnittene Datei ergibt ein leeres Gedaechtnis',
           transport.lies_gesundheit(pfad).zustand == {})


# --------------------------------------------------------------- Kennung

def kennung_pruefen():
    print('')
    print('KENNUNG')
    print('')

    vorher = netz.KENNUNG
    try:
        netz.setze_kennung('')
        pruefe('leer laesst die Vorgabe stehen', netz.KENNUNG == vorher)
        netz.setze_kennung(None)
        pruefe('None laesst die Vorgabe stehen', netz.KENNUNG == vorher)

        netz.setze_kennung('AHPT-Agent/1')
        pruefe('ein eigener Wert wird uebernommen',
               netz.KENNUNG == 'AHPT-Agent/1', netz.KENNUNG)

        # Steuerzeichen wuerden die Kopfzeile zerlegen. Das faellt sonst
        # erst im Betrieb bei der ersten Anfrage auf, nicht beim Start.
        fehler = False
        try:
            netz.setze_kennung('boes\r\nX-Andere: 1')
        except ValueError:
            fehler = True
        pruefe('Steuerzeichen werden abgewiesen', fehler)
        pruefe('nach der Abweisung bleibt der alte Wert',
               netz.KENNUNG == 'AHPT-Agent/1', netz.KENNUNG)
    finally:
        netz.KENNUNG = vorher


def main():
    echt = netz.webdav
    try:
        verzeichnis_pruefen()
        ablegen_pruefen()
    finally:
        netz.webdav = echt
    gesundheit_pruefen()
    gedaechtnis_pruefen()
    kennung_pruefen()

    fehler = sum(1 for ok in ERGEBNIS if not ok)
    print('')
    print('ERGEBNIS: %d Pruefungen, %s' % (
        len(ERGEBNIS),
        'alle bestanden.' if not fehler else '%d FEHLSCHLAG(E).' % fehler))
    if not fehler:
        print('')
        print('  Das prueft, ob wir eine Antwort richtig VERSTEHEN, nicht ob')
        print('  ein Anbieter antwortet -- dafuer gibt es tests/gmx_webdav_')
        print('  test.py gegen ein echtes Konto.')
    return 1 if fehler else 0


if __name__ == '__main__':
    sys.exit(main())
