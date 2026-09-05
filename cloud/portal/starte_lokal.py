#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
starte_lokal.py -- das Portal von der eigenen Maschine ausliefern

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU -- und warum nicht einfach die Datei doppelklicken
--------------------------------------------------------
Zwei Browserregeln stehen im Weg, und sie ziehen in verschiedene
Richtungen:

  1. `crypto.subtle` gibt es nur im SICHEREN KONTEXT: https, localhost,
     oder eine lokal geoeffnete Datei. Ueber gewoehnliches http gibt es die
     Verschluesselung schlicht nicht.

  2. Eine Seite in einem sicheren Kontext darf keine UNSICHEREN Inhalte
     nachladen (Mixed Content). Eine `file://`-Seite gilt als sicher --
     und darf dann je nach Browser NICHT mehr auf `http://` zugreifen.

Eine doppelgeklickte Datei erfuellt also 1, kann aber an 2 scheitern. Auf
einem Webspace ohne https ist sie damit unbrauchbar.

`http://localhost` loest beides auf einmal:

  * Es gilt als sicherer Kontext (Browser machen fuer localhost eine
    ausdrueckliche Ausnahme) -- WebCrypto ist da.
  * Die Seite selbst ist http, also entsteht beim Zugriff auf einen
    http-Webspace gar keine Mischung.

Und der eigentliche Gewinn bleibt derselbe wie bei der Datei: Die Seite
kommt von DEINER Maschine. Der Hoster kann sie nicht austauschen, also
traegt die Verschluesselung auch gegen ihn.

Der Server hoert NUR auf 127.0.0.1. Er ist aus dem Netz nicht erreichbar --
weder aus dem eigenen WLAN noch von aussen.

Aufruf:
    python3 portal/starte_lokal.py
    python3 portal/starte_lokal.py --port 8770 --kein-browser
"""

import argparse
import http.server
import os
import socketserver
import subprocess
import sys
import webbrowser

HIER = os.path.dirname(os.path.abspath(__file__))


class Still(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HIER, **k)

    def log_message(self, *a):
        pass                      # das Protokoll interessiert hier niemanden

    def end_headers(self):
        # Kein Zwischenspeicher: Wer die Portal-Datei aendert, soll die
        # Aenderung sehen und nicht raten, ob der Browser noch die alte hat.
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def oeffne(adresse):
    """Browser oeffnen -- und SAGEN, wenn es nicht geht.

    Der erste Entwurf schrieb schlicht `try: webbrowser.open(...) except:
    pass`. Damit blieb ein Fehlschlag stumm, und der Nutzer sass vor einem
    Terminal, in dem alles gut aussah, waehrend nichts passierte. Genau die
    Sorte stiller Fehlschlag, die dieses Projekt sonst ueberall vermeidet.

    Und er passiert leicht: Pythons `webbrowser` beruecksichtigt unter Linux
    nur dann einen grafischen Browser, wenn DISPLAY oder WAYLAND_DISPLAY
    gesetzt ist. In einer SSH-Sitzung ist das nicht so -- dann meldet es
    "could not locate runnable browser", obwohl Firefox danebenliegt.
    Am 03.09.2026 auf dem HomeServer genau so gemessen.
    """
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
            or sys.platform in ('win32', 'darwin')):
        print('  Kein Bildschirm in dieser Sitzung (DISPLAY ist leer) --')
        print('  vermutlich laeuft das ueber SSH. Die Adresse oben im')
        print('  Browser des Desktops oeffnen.')
        print('')
        return True          # kein Fehler, nur nichts zu oeffnen

    try:
        if webbrowser.open(adresse):
            return True
    except Exception:
        pass

    # Zweiter Versuch am Modul vorbei, direkt ueber den Desktop. `xdg-open`
    # kennt den eingestellten Standardbrowser auch dann, wenn Python ihn
    # nicht findet.
    for befehl in (['xdg-open', adresse], ['x-www-browser', adresse],
                   ['sensible-browser', adresse]):
        try:
            subprocess.Popen(befehl, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return False


def main():
    ap = argparse.ArgumentParser(
        description='Liefert das Portal auf 127.0.0.1 aus.')
    ap.add_argument('--port', type=int, default=8770)
    ap.add_argument('--kein-browser', action='store_true')
    a = ap.parse_args()

    if not os.path.isfile(os.path.join(HIER, 'index.html')):
        print('ABBRUCH: index.html liegt nicht neben dieser Datei.')
        return 2

    gewuenscht = a.port
    # SO_REUSEADDR NUR auf POSIX.
    #
    # Dort loest es ein echtes Problem: Das Betriebssystem haelt einen
    # freigegebenen Port noch in TIME_WAIT, und ein Neustart scheitert mit
    # "Address already in use", obwohl nichts mehr laeuft.
    #
    # Auf WINDOWS bedeutet dieselbe Einstellung etwas anderes -- dort heisst
    # sie sinngemaess "diesen Port notfalls einem anderen wegnehmen". Windows
    # verweigert das und meldet WinError 10013, "Zugriff unzulaessig". Die
    # Meldung fuehrt in die Irre: Sie klingt nach fehlenden Rechten, waehrend
    # in Wahrheit schlicht der Port belegt ist.
    #
    # Am 03.09.2026 nachgestellt, derselbe belegte Port:
    #     ohne SO_REUSEADDR -> 10048 "Adresse nur einmal verwendbar"  (klar)
    #     mit  SO_REUSEADDR -> 10013 "Zugriff unzulaessig"        (irrefuehrend)
    socketserver.TCPServer.allow_reuse_address = (os.name != 'nt')

    # Und wenn der Port belegt ist: den naechsten nehmen, nicht aufgeben.
    #
    # Ein Werkzeug, das wegen einer belegten Portnummer abbricht und den
    # Nutzer rechnen laesst, ist unnoetig unfreundlich -- zumal die Nummer
    # hier voellig gleichgueltig ist. Der Browser bekommt sie ohnehin
    # ausgedruckt.
    srv = None
    versucht = []
    for versuch in range(10):
        port = a.port + versuch
        try:
            # NUR 127.0.0.1, ausdruecklich nicht 0.0.0.0. Ein Portal, das den
            # eigenen Schluessel im Browser haelt, gehoert nicht ins WLAN.
            srv = socketserver.TCPServer(('127.0.0.1', port), Still)
            a.port = port
            break
        except OSError as e:
            versucht.append('%d (%s)' % (port, getattr(e, 'winerror', None)
                                         or e.errno))
    if srv is None:
        print('ABBRUCH: Kein freier Port zwischen %d und %d.'
              % (gewuenscht, gewuenscht + 9))
        print('         Versucht: %s' % ', '.join(versucht))
        print('')
        print('         Laeuft das Portal vielleicht schon in einem anderen')
        print('         Fenster? Nachsehen:')
        print('             Linux:   ss -tlnp | grep %d' % gewuenscht)
        print('             Windows: netstat -ano | findstr :%d' % gewuenscht)
        print('                      (die deutsche Ausgabe sagt ABHOEREN,')
        print('                       nicht LISTENING)')
        return 2
    if a.port != gewuenscht:
        print('')
        print('  HINWEIS: Port %d war belegt, es wurde %d genommen.'
              % (gewuenscht, a.port))
    adresse = 'http://127.0.0.1:%d/index.html' % a.port

    print('')
    print('  Portal laeuft auf   %s' % adresse)
    print('')
    print('  Diese Adresse gilt dem Browser als sicherer Kontext -- die')
    print('  Verschluesselung ist damit verfuegbar. Und weil die Seite von')
    print('  DEINER Maschine kommt, kann der Hoster sie nicht austauschen.')
    print('')
    print('  Nur ueber 127.0.0.1 erreichbar, nicht aus dem Netz.')
    print('  Beenden mit Strg+C.')
    print('')
    if not a.kein_browser and not oeffne(adresse):
        print('  Der Browser liess sich nicht selbst oeffnen.')
        print('  Bitte die Adresse oben von Hand einfuegen.')
        print('')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('  beendet.')
    finally:
        srv.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
