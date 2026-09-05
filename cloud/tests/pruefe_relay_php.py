#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pruefe_relay_php.py -- statische Pruefung von relay.php ohne PHP

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
`php -l` ist die richtige Pruefung, aber sie setzt PHP voraus. Auf einem
Entwicklungsrechner ohne PHP fiele die Datei sonst durch JEDE Kontrolle
hindurch bis auf den Webspace -- und dort ist der erste Leser ein Besucher.

Wichtiger noch: `php -l` findet den einen Fehler NICHT, der dieses Projekt am
02.09.2026 siebzehn Pruefungen gekostet hat. Er ist syntaktisch vollkommen
gueltig.

DER FEHLER
----------
Die Zeichenfolge Fragezeichen-Groesserzeichen beendet den PHP-Modus AUCH in
einem Doppelstrich-Kommentar. Alles danach geht als HTML hinaus. Damit sind
die Kopfzeilen gesendet, `http_response_code()` bleibt wirkungslos, und JEDE
Antwort kommt mit HTTP 200 zurueck -- auch jede Ablehnung. Ein Tunnel, der
Ablehnungen als Erfolg meldet, ist schlimmer als einer, der gar nicht laeuft.

In Blockkommentaren ist dieselbe Zeichenfolge harmlos. Genau deshalb faellt
sie beim Lesen nicht auf: sie steht in diesem Projekt an vielen Stellen
voellig zu Recht.

Aufruf:
    python3 tests/pruefe_relay_php.py [pfad/zu/relay.php]
"""

import os
import re
import sys

# Die Zeichenfolge wird hier zusammengesetzt statt hingeschrieben -- diese
# Datei ist Python, aber sie wandert womoeglich in ein Werkzeug, das sie in
# PHP einbettet. Dann waere die Pruefung selbst der Fehler, den sie sucht.
ENDE_PHP = '?' + '>'
START_PHP = '<' + '?php'


def zerlege(quelltext):
    """Grobe Zerlegung in PHP-Code, Zeichenketten und Kommentare.

    Kein vollstaendiger Tokenizer -- er muss nur gut genug sein, um zu
    wissen, WO man gerade ist. Rueckgabe: Liste von (art, zeile, text) mit
    art aus code, zeile_kommentar, block_kommentar, zeichenkette.
    """
    stuecke = []
    i, n = 0, len(quelltext)
    zeile = 1
    art = 'html'                      # vor dem ersten Start-Tag
    start = 0

    def schiebe(bis, welche):
        if bis > start:
            stuecke.append((welche, zeile, quelltext[start:bis]))

    while i < n:
        c = quelltext[i]

        if art == 'html':
            j = quelltext.find(START_PHP, i)
            if j < 0:
                schiebe(n, 'html')
                break
            schiebe(j, 'html')
            zeile += quelltext.count('\n', start, j)
            i = j + len(START_PHP)
            start = i
            art = 'code'
            continue

        if art == 'code':
            if quelltext.startswith('//', i) or c == '#':
                schiebe(i, 'code')
                zeile += quelltext.count('\n', start, i)
                start = i
                art = 'zeile_kommentar'
                i += 2 if c == '/' else 1
                continue
            if quelltext.startswith('/*', i):
                schiebe(i, 'code')
                zeile += quelltext.count('\n', start, i)
                start = i
                art = 'block_kommentar'
                i += 2
                continue
            if c in ('"', "'"):
                schiebe(i, 'code')
                zeile += quelltext.count('\n', start, i)
                start = i
                art = 'zeichenkette'
                quote = c
                i += 1
                continue
            if quelltext.startswith(ENDE_PHP, i):
                schiebe(i, 'code')
                zeile += quelltext.count('\n', start, i)
                i += len(ENDE_PHP)
                start = i
                art = 'html'
                continue
            i += 1
            continue

        if art == 'zeile_kommentar':
            j = quelltext.find('\n', i)
            if j < 0:
                j = n
            schiebe(j, 'zeile_kommentar')
            zeile += quelltext.count('\n', start, j)
            i = start = j
            art = 'code'
            continue

        if art == 'block_kommentar':
            j = quelltext.find('*/', i)
            if j < 0:
                j = n
            else:
                j += 2
            schiebe(j, 'block_kommentar')
            zeile += quelltext.count('\n', start, j)
            i = start = j
            art = 'code'
            continue

        if art == 'zeichenkette':
            if c == '\\':
                i += 2
                continue
            if c == quote:
                i += 1
                schiebe(i, 'zeichenkette')
                zeile += quelltext.count('\n', start, i)
                start = i
                art = 'code'
                continue
            i += 1
            continue

    # Rest abgeben. Ohne das fehlt der Schwanz der Datei -- und die
    # Klammerzaehlung meldet genau eine fehlende schliessende Klammer, was
    # aussieht wie ein Fehler in der geprueften Datei statt in dieser.
    if start < n:
        stuecke.append((art if art != 'html' else 'html', zeile, quelltext[start:n]))

    return stuecke


def pruefe(pfad):
    with open(pfad, 'r', encoding='utf-8') as f:
        quelltext = f.read()

    stuecke = zerlege(quelltext)
    befunde = []

    def fehler(zeile, text):
        befunde.append((zeile, text))

    # 1 -- DER Fehler vom 02.09.2026.
    for art, zeile, text in stuecke:
        if art == 'zeile_kommentar' and ENDE_PHP in text:
            fehler(zeile, 'Zeilenkommentar enthaelt das PHP-Endezeichen. '
                          'Es beendet den PHP-Modus AUCH hier -- alles danach '
                          'geht als HTML hinaus und jede Antwort kommt mit '
                          'HTTP 200 zurueck.')

    # 2 -- Ausgabe vor den Kopfzeilen. Ein einziges Byte HTML vor dem ersten
    #      header() macht http_response_code() wirkungslos. Fuehrende
    #      Leerzeichen vor dem Start-Tag zaehlen mit.
    for art, zeile, text in stuecke:
        if art == 'html' and text.strip():
            fehler(zeile, 'Ausgabe ausserhalb von PHP: %r. Damit sind die '
                          'Kopfzeilen gesendet.' % text[:40])

    # 3 -- Byte-Order-Mark. Unsichtbar, und dieselbe Wirkung wie 2.
    if quelltext.startswith('﻿'):
        fehler(1, 'Datei beginnt mit einem Byte-Order-Mark. Der geht als '
                  'Ausgabe hinaus, bevor eine Kopfzeile gesetzt ist.')

    # ZWEI SICHTEN auf die Datei, und die Unterscheidung ist wesentlich:
    #
    #   code       nur Quelltext, OHNE Zeichenketten. Zum Klammernzaehlen --
    #              eine geschweifte Klammer in einem Text ist keine Klammer.
    #   quelle     Quelltext MIT Zeichenketten, ohne Kommentare. Fuer alles,
    #              was Literale braucht: `case 'frage':` ist beides.
    #
    # Der erste Entwurf dieser Datei hatte nur `code` und meldete daraufhin,
    # in relay.php fehlten saemtliche Aktionen und Konstanten. Ein Pruefer,
    # der falschen Alarm schlaegt, wird nach dem zweiten Mal nicht mehr
    # gelesen -- und findet danach auch die echten Fehler nicht mehr.
    code   = ''.join(t for a, _, t in stuecke if a == 'code')
    quelle = ''.join(t for a, _, t in stuecke if a in ('code', 'zeichenkette'))
    for auf, zu, name in (('{', '}', 'geschweifte'), ('(', ')', 'runde'),
                          ('[', ']', 'eckige')):
        if code.count(auf) != code.count(zu):
            fehler(0, '%s Klammern unausgeglichen: %d mal %s, %d mal %s'
                      % (name, code.count(auf), auf, code.count(zu), zu))

    # 5 -- declare(strict_types=1) muss da sein. Ohne strict_types wird aus
    #      einer Zeichenkette klaglos eine Zahl -- und aus "0" ein gueltiges
    #      `teil`.
    if not re.search(r'declare\s*\(\s*strict_types\s*=\s*1\s*\)', code):
        fehler(0, 'declare(strict_types=1) fehlt.')

    # 6 -- Es darf KEINE Abhol-Aktion geben. Das ist der ganze Entwurf: Wer
    #      hier lesen laesst, verlegt das Warten auf den teuren Weg.
    faelle = set(re.findall(r"case\s+'([a-z_]+)'\s*:", quelle))
    # AHPT PRIVAT hat zwei Aktionen mehr als die oeffentliche Fassung:
    # `frage_stueck` und `frage_fertig`. Beide SCHREIBEN, keine liest.
    #
    # Die Regel, die diese Liste bewacht, lautet nicht "es duerfen nie neue
    # Aktionen dazukommen", sondern: ES DARF KEINE ABHOL-AKTION GEBEN. Wer
    # das Abholen durch PHP leitet, verlegt das Warten auf den teuren Weg
    # und hebt den ganzen Entwurf auf. Ein Name, der nach Lesen klingt --
    # hole, lies, get, abholen, download --, gehoert hier nie hinein.
    erlaubt = {'frage', 'frage_stueck', 'frage_fertig',
               'stueck', 'antwort', 'selbsttest'}
    for verboten in ('hole', 'lies', 'get', 'abholen', 'download', 'lesen'):
        if verboten in faelle:
            fehler(0, 'Aktion "%s" klingt nach ABHOLEN. Es darf keine geben: '
                      'das Warten muss statisch bleiben, sonst faellt das '
                      'Kostenmodell.' % verboten)
    for f in sorted(faelle - erlaubt):
        fehler(0, 'Unerwartete Aktion "%s". Erlaubt sind nur %s -- '
                  'insbesondere gibt es KEINE Abhol-Aktion.'
                  % (f, ', '.join(sorted(erlaubt))))
    for f in sorted(erlaubt - faelle):
        fehler(0, 'Aktion "%s" fehlt.' % f)

    # 7 -- Die beiden empfindlichen Dateien muessen auf .php enden. Eine
    #      .htaccess kann beim Hochladen verlorengehen; die Endung nicht.
    for konst in ('ZUSTAND', 'TOKEN_DATEI'):
        m = re.search(r"define\s*\(\s*'%s'\s*,\s*[^;]*?'([^']+)'" % konst, quelle)
        if not m:
            fehler(0, 'Konstante %s nicht gefunden.' % konst)
        elif not m.group(1).endswith('.php'):
            fehler(0, '%s zeigt auf %r -- muss auf .php enden, sonst liefert '
                      'der Server die Datei aus statt sie auszufuehren.'
                      % (konst, m.group(1)))

    # 8 -- Die Schutzzeile braucht den schliessenden Tag. Ohne ihn waere der
    #      angehaengte JSON PHP-Quelltext, die Datei liesse sich nicht
    #      uebersetzen, und ein Abruf erzeugte eine Fehlermeldung -- die
    #      womoeglich Dateiinhalt zeigt.
    m = re.search(r"define\s*\(\s*'PHP_SCHUTZ'\s*,\s*\"([^\"]*)\"", quelle)
    if not m:
        fehler(0, 'PHP_SCHUTZ nicht gefunden.')
    else:
        if ENDE_PHP not in m.group(1):
            fehler(0, 'PHP_SCHUTZ enthaelt kein PHP-Endezeichen. Der '
                      'angehaengte JSON waere dann Quelltext.')
        if 'exit' not in m.group(1):
            fehler(0, 'PHP_SCHUTZ enthaelt kein exit.')

    # 9 -- Das Geheimnis darf in keiner Ausgabe landen. Gesucht wird nach
    #      einer Ausgabe, die die Variable des Sollwerts nennt.
    for zeile_nr, zeile_txt in enumerate(quelltext.split('\n'), 1):
        if re.search(r'antwort\s*\(.*\$soll\b', zeile_txt) \
                and 'hash(' not in zeile_txt and 'strlen' not in zeile_txt:
            fehler(zeile_nr, 'Moegliche Ausgabe des Geheimnisses ($soll).')

    # 10 -- Marken duerfen nie ungeprueft in einen Dateinamen. Jede Stelle,
    #       die einen Dateinamen baut, muss vorher ist_marke() gesehen haben.
    if 'function ist_marke' not in quelle:
        fehler(0, 'ist_marke() fehlt -- ohne Formpruefung ist jeder '
                  'Dateiname eine Pfadwanderung.')
    if not re.search(r"\^\[0-9a-f\]\{32\}\$", quelle):
        fehler(0, 'Kein Muster ^[0-9a-f]{32}$ gefunden.')

    # 11 -- Der Absender muss als NETZ gezaehlt werden, nicht als Adresse.
    #       Bei IPv6 bekommt ein Anschluss ein ganzes /64; wer die volle
    #       Adresse nimmt, hat 2^64 "verschiedene" Absender und damit kein
    #       MAX_JE_IP mehr.
    if 'function absender_kennung' not in quelle:
        fehler(0, 'absender_kennung() fehlt -- dann zaehlt REMOTE_ADDR direkt, '
                  'und ein einzelner IPv6-Anschluss gilt als 2^64 Absender.')
    else:
        if 'inet_pton' not in quelle:
            fehler(0, 'absender_kennung() ohne inet_pton -- eine Adresse als '
                      'Text zu kuerzen geht schief (::1 vs 0:0:...:1).')
        # Die IPv4-im-IPv6-Kleid-Ausnahme ist tragend: Ohne sie landen ALLE
        # IPv4-Besucher in einem Topf, und der erste Angreifer sperrt alle aus.
        #
        # Gesucht wird nach der OPERATION, nicht nach dem Wort "ffff": Die
        # Praefix-Bytes stehen als Escape-Folgen im Quelltext. Der erste
        # Entwurf dieser Zeile suchte den Text und schlug prompt falschen
        # Alarm -- ein Pruefer, der das tut, wird beim zweiten Mal ignoriert.
        if not ('strncmp($bin' in quelle and 'substr($bin, 12)' in quelle):
            fehler(0, 'absender_kennung() behandelt ::ffff: nicht gesondert -- '
                      'dann faellt jede IPv4 im IPv6-Kleid in dasselbe /64.')
        if re.search(r"REMOTE_ADDR.{0,400}?hash\('sha256'", quelle, re.S) \
                and 'absender_kennung($roh_ip)' not in quelle:
            fehler(0, 'REMOTE_ADDR geht offenbar ungekuerzt in den Hash.')

    # 12 -- Bei voller Schlange wird verdraengt, nicht abgewiesen. Ein
    #       globaler Deckel allein ist von dem erschoepfbar, der zuerst da
    #       ist -- vierzig Anfragen alle zwei Minuten genuegten.
    if 'array_key_first' not in code:
        fehler(0, 'Kein faires Verdraengen erkennbar (array_key_first fehlt). '
                  'Ein blosses 503 bei voller Schlange ist eine Einladung zum '
                  'Queue-Jamming.')

    # 13 -- `titel` wird zurueckgespiegelt und ist von aussen bestimmt.
    if 'function sicherer_titel' not in quelle:
        fehler(0, 'sicherer_titel() fehlt -- `titel` ist bei einer Suche der '
                  'Suchbegriff und geht unveraendert an den Browser zurueck.')

    # 14 -- json_encode darf nicht stillschweigend false liefern. Aus false
    #       wird beim Schreiben eine leere Datei, und die sieht aus wie eine
    #       Antwort.
    if 'JSON_INVALID_UTF8_SUBSTITUTE' not in quelle:
        fehler(0, 'umschlag() ohne JSON_INVALID_UTF8_SUBSTITUTE -- bei '
                  'ungueltigem UTF-8 entstuende eine leere Antwortdatei.')

    return befunde


def main():
    pfad = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'relay.php')

    if not os.path.isfile(pfad):
        print('NICHT GEFUNDEN: %s' % pfad)
        return 2

    print('Pruefe %s' % pfad)
    print('')
    befunde = pruefe(pfad)

    if not befunde:
        print('  14 Pruefungen bestanden.')
        print('')
        print('ERGEBNIS: keine Beanstandung.')
        print('')
        print('  Das ersetzt `php -l` NICHT. Es prueft, was `php -l` nicht')
        print('  prueft -- und `php -l` prueft, was hier fehlt. Vor dem')
        print('  Ausliefern beides.')
        return 0

    for zeile, text in befunde:
        wo = ('Zeile %d' % zeile) if zeile else 'Datei'
        print('  FEHLER (%s): %s' % (wo, text))
    print('')
    print('ERGEBNIS: %d Beanstandung(en).' % len(befunde))
    return 1


if __name__ == '__main__':
    sys.exit(main())
