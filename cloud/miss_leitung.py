#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
miss_leitung.py -- die eigene Internetleitung messen

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Der Vermittler-Test in `starten.py` sagt, wie lange ein Rundlauf dauert. Er
sagt nicht, WORAN es liegt: Ein Anschluss mit 20 Mbit/s hinauf kann nicht
mehr hergeben, und dann ist ein langsamer Rundlauf kein Mangel des Webspace,
sondern die Wahrheit ueber die eigene Leitung.

Dafuer braucht es eine Vergleichsgroesse. Eintragen kann man sie von Hand --
aber die Vertragsrate stimmt oft nicht: 2 km zum DSLAM, ein ueberbuchtes
Kabelsegment, ein muedes Modem. Dann rechnet der Vermittler-Test eine zu
niedrige Ausschoepfung aus und BESCHULDIGT DEN HOSTER FUER ETWAS, DAS DIE
LEITUNG IST. Ein gemessener Wert raeumt genau diesen Irrtum weg.

WARUM DAS EIN EIGENES PROGRAMM IST
-----------------------------------
Weil es das Einzige in AHPT Cloud ist, das mit einem DRITTEN redet. Der
Agent spricht mit dem eigenen Webspace, der Assistent mit localhost, das
Portal mit dem Vermittler -- und dieses Programm mit einem fremden Rechner,
der dabei die oeffentliche IP zu sehen bekommt.

Das gehoert nicht heimlich in ein Diagnosewerkzeug hinein. Es gehoert in ein
Programm, das man ABSICHTLICH startet, das vorher sagt, wen es anruft und
was das kostet, und das man auch einfach loeschen kann. Die Verbindung zum
Rest ist eine Datei, sonst nichts:

    miss_leitung.py  --schreibt-->  ~/.ahpt/leitung.json  <--liest--  starten.py

Wer es nie benutzt, hat ein AHPT, das ausschliesslich mit dem eigenen
Webspace redet -- und das Feld im Messfenster fuellt er von Hand.

WAS GEMESSEN WIRD UND WIE
--------------------------
Gegen `speed.cloudflare.com`, weil das ohne Schluessel und ohne Bibliothek
geht und weil Anycast den naechstgelegenen Knoten von selbst waehlt -- je
nach Land und Region, ohne dass man eine Serverliste pflegen muesste. Der
Knoten wird angezeigt, damit man sieht, wo gemessen wurde.

MIT MEHREREN STROEMEN GLEICHZEITIG, und ueber ein ZEITFENSTER. Beides ist
kein Zierrat, sondern am 08.09.2026 gegen einen unabhaengigen Speedtest
(Google/M-Lab, Server Zuerich) geeicht worden:

    ein Strom, feste Groesse         50,0 Mbit/s
    vier Stroeme, feste Groesse      39,3 Mbit/s     <- schlechter!
    vier Stroeme, Zeitfenster        54,5 Mbit/s
    unabhaengige Messung             53,4 / 53,6 Mbit/s

Die mittlere Zeile ist die Lehre: Bei fester Groesse je Strom bestimmt der
LANGSAMSTE die Wanduhr, waehrend die anderen schon fertig danebenstehen und
nichts mehr uebertragen. Vier Stroeme machten es dadurch SCHLECHTER als
einer. Mit einem Zeitfenster -- alle senden, solange die Uhr laeuft, und die
Anlaufphase zaehlt nicht mit -- stimmt es auf zwei Prozent.

Warum das wichtig ist: Ein zu niedriger Vergleichswert laesst den Vermittler
BESSER aussehen als er ist, also genau der Fehler, den dieses Programm
verhindern soll. Hinauf ebenso: 20,4 gegen 18,2 bis 20,3 der unabhaengigen
Messung, die selbst um zehn Prozent schwankt.

Aufruf:
    python3 miss_leitung.py              fragt vorher nach
    python3 miss_leitung.py --ja         ohne Rueckfrage
    python3 miss_leitung.py --nur-zeigen misst, schreibt aber nichts
"""

import argparse
import http.client
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request

DIENST = 'https://speed.cloudflare.com'
ZIEL_S = 4.0                # so lange soll ein Durchgang dauern
RAMPE = 1.0                 # Anlauf, der nicht mitzaehlt (slow start)
STROEME = 4                 # gleichzeitige Verbindungen
BLOCK = 256 * 1024          # Bytes je Sendestueck beim Hinaufladen
# Obergrenze JE STROM. Mal vier Stroeme mal zwei Richtungen ist das der
# schlimmste Fall an Verkehr, und der muss vorher nennbar sein -- hier
# standen erst 96 MB, also bis zu 768 MB je Durchgang. Fuer eine
# DSL-Leitung wird der Deckel ohnehin nie erreicht (50 Mbit/s in vier
# Sekunden sind 26 MB); er greift nur bei sehr schnellen Anschluessen, und
# dort ist ein etwas kuerzerer Durchgang das kleinere Uebel.
DECKEL = 24 * 1024 * 1024   # Bytes je Strom, Obergrenze
# Eine eigene Kennung, im Stil von netz.py (KENNUNG = 'AHPT-Agent/1').
#
# NICHT NUR HOEFLICHKEIT: Ohne sie kommt HTTP 403 zurueck. Der Dienst weist
# `Python-urllib/3.12` ab -- am 08.09.2026 nachgemessen, waehrend derselbe
# Abruf mit curl durchging. Eine ehrliche Kennung genuegt; als Browser
# ausgeben muss man sich nicht, und das waere auch nicht in Ordnung.
#
# Zugleich ist das die Erinnerung daran, worauf man sich hier einlaesst:
# ein fremder Dienst mit unveroeffentlichter Schnittstelle, der jederzeit
# anders entscheiden kann. Deshalb ist dieses Programm eigenstaendig und
# sein Ausfall folgenlos -- das Feld laesst sich immer von Hand fuellen.
KENNUNG = ('AHPT-Leitungsmessung/1 '
           '(+https://github.com/Innobytix-IT/Asymmetric-HTTP-Polling-Tunnel)')
KONFIG_ORDNER = os.path.expanduser('~/.ahpt')
LEITUNG_DATEI = os.path.join(KONFIG_ORDNER, 'leitung.json')


def _oeffner():
    # Voreinstellung, keine Sonderbehandlung: Ein oeffentlicher Dienst mit
    # gueltigem Zertifikat -- wenn das nicht mehr stimmt, soll es auffallen
    # und nicht stillschweigend uebergangen werden.
    return urllib.request.build_opener()


def _herunter(zaehler, i, ende, fehler):
    """Laedt, bis die Zeit um ist -- und zaehlt laufend mit.

    NICHT eine feste Byte-Zahl je Strom, und das ist der Unterschied
    zwischen einer richtigen und einer falschen Messung: Bei fester Groesse
    bestimmt der LANGSAMSTE Strom die Wanduhr, waehrend die anderen schon
    fertig danebenstehen und nichts mehr uebertragen. Am 08.09.2026 gegen
    einen unabhaengigen Speedtest gehalten: 39 statt 53 Mbit/s, also ein
    Viertel zu wenig. Ein zu niedriger Vergleichswert laesst den Vermittler
    besser aussehen als er ist -- genau der Fehler, den dieses Programm
    verhindern soll.

    DECKEL ist deshalb nur noch eine Obergrenze, die nie erreicht wird.
    """
    try:
        req = urllib.request.Request(
            '%s/__down?bytes=%d' % (DIENST, DECKEL),
            headers={'Accept-Encoding': 'identity', 'User-Agent': KENNUNG})
        with _oeffner().open(req, timeout=30) as r:
            while time.perf_counter() < ende:
                s = r.read(65536)
                if not s:
                    break
                zaehler[i] += len(s)
    except Exception as e:
        fehler.append(str(e))


def _hinauf(zaehler, i, ende, fehler):
    """Sendet, bis die Zeit um ist -- gestueckelt, und zaehlt laufend mit.

    Dieselbe Ueberlegung wie beim Herunterladen: eine feste Groesse je
    Strom laesst den langsamsten die Zeit bestimmen, und der Anlauf
    (slow start) laesst sich nicht herausrechnen. Mit `Transfer-Encoding:
    chunked` laeuft der Strom stattdessen, solange das Fenster offen ist.
    Am 08.09.2026 geprueft: Der Dienst nimmt beides an.

    os.urandom, nicht Nullen -- presst ein Zwischenknoten die Daten
    zusammen, misst man seine Rechenleistung statt der Leitung. EINMAL
    erzeugt und wiederholt gesendet: Vier Faeden, die dauernd Zufall
    anfordern, messen sonst den Zufallsgenerator mit.
    """
    block = os.urandom(BLOCK)
    # Der Kopf eines Stuecks: Laenge in Hexadezimal, dann CRLF. So schreibt
    # es die HTTP-Norm vor, und bei `send()` nimmt http.client es uns nicht
    # ab -- der Strom wird hier von Hand gebaut.
    kopf = ('%x\r\n' % len(block)).encode('ascii')
    u = urllib.parse.urlparse(DIENST)
    v = None
    try:
        v = http.client.HTTPSConnection(u.netloc, timeout=30)
        v.putrequest('POST', '/__up', skip_accept_encoding=True)
        v.putheader('Host', u.netloc)
        v.putheader('Content-Type', 'application/octet-stream')
        v.putheader('User-Agent', KENNUNG)
        v.putheader('Transfer-Encoding', 'chunked')
        v.endheaders()
        while time.perf_counter() < ende:
            v.send(kopf + block + b'\r\n')
            zaehler[i] += len(block)
        # Ein Stueck der Laenge null beendet die Uebertragung ordentlich.
        # Ohne das bliebe eine halbe Anfrage stehen, und der Dienst muesste
        # auf einen Zeitablauf warten.
        v.send(b'0\r\n\r\n')
        v.getresponse().read()
    except Exception as e:
        fehler.append(str(e))
    finally:
        if v:
            try:
                v.close()
            except Exception:
                pass


def _fenster(funktion, dauer_s):
    """Misst ueber ein Zeitfenster. Zurueck: (Bytes/s, Fehler).

    Die ersten RAMPE Sekunden zaehlen NICHT mit: TCP faengt langsam an
    (slow start), und vier frische TLS-Handschlaege kosten auch etwas.
    Gemessen wird der eingeschwungene Zustand.
    """
    zaehler = [0] * STROEME          # jeder Faden schreibt nur sein Fach
    fehler = []
    ende = time.perf_counter() + RAMPE + dauer_s
    faeden = [threading.Thread(target=funktion,
                               args=(zaehler, i, ende, fehler), daemon=True)
              for i in range(STROEME)]
    for f in faeden:
        f.start()
    time.sleep(RAMPE)
    t0, n0 = time.perf_counter(), sum(zaehler)
    time.sleep(dauer_s)
    t1, n1 = time.perf_counter(), sum(zaehler)
    for f in faeden:
        f.join(timeout=5)
    if t1 <= t0 or n1 <= n0:
        return None, fehler
    return (n1 - n0) / (t1 - t0), fehler


def knoten():
    """Wo hat Anycast uns hingeschickt? Nur der Ort, nie die IP.

    Aus `CF-RAY`, dessen letztes Stueck hinter dem Bindestrich den
    Knotenpunkt nennt (z.B. `a37da6e2aaa37457-FRA` fuer Frankfurt).

    NICHT aus `cf-meta-colo`: Der Name steht zwar in
    `access-control-expose-headers`, mitgeschickt wird die Kopfzeile bei
    `__down` aber nicht. Am 08.09.2026 stand deshalb "Gemessen am 08.09. in
    ?" auf dem Bildschirm -- ein Fragezeichen als Ortsangabe ist schlechter
    als gar keine.

    Fehlt der Wert, kommt NICHTS zurueck statt eines Platzhalters. Wer
    nichts weiss, soll nichts behaupten.
    """
    try:
        req = urllib.request.Request('%s/__down?bytes=0' % DIENST,
                                     headers={'User-Agent': KENNUNG})
        with _oeffner().open(req, timeout=10) as r:
            strahl = r.headers.get('CF-RAY') or ''
            ort = strahl.rsplit('-', 1)[-1] if '-' in strahl else ''
            return {'knoten': ort} if ort.isalpha() else {}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(
        description='Misst die eigene Internetleitung und traegt das '
                    'Ergebnis fuer den AHPT-Vermittlertest ein.')
    ap.add_argument('--ja', action='store_true',
                    help='ohne Rueckfrage messen')
    ap.add_argument('--nur-zeigen', action='store_true',
                    help='messen, aber nichts schreiben')
    ap.add_argument('--sparsam', action='store_true',
                    help='kuerzer messen, etwa ein Drittel des Verkehrs')
    a = ap.parse_args()
    if a.sparsam:
        global ZIEL_S
        ZIEL_S = 1.5

    print()
    print('Leitung messen')
    print('=' * 58)
    print()
    print('DIESES PROGRAMM REDET MIT EINEM FREMDEN RECHNER -- als einziges')
    print('in AHPT Cloud. Damit du weisst, worauf du dich einlaesst:')
    print()
    print('   Angerufen wird   %s' % DIENST)
    print('   Der erfaehrt     deine oeffentliche IP-Adresse und dass hier')
    print('                    gemessen wird. Sonst nichts -- kein Name,')
    print('                    keine Adresse deines Webspace, kein Inhalt.')
    print('   Es kostet        je nach Leitung etwa 10 MB (langsam) bis')
    print('                    %d MB (sehr schnell). Am Handy-Tethering ist'
          % (DECKEL * STROEME * 2 // 1048576))
    print('                    das Geld -- dann besser --sparsam.')
    print('   Geschrieben wird %s' % LEITUNG_DATEI)
    print('                    Nur zwei Zahlen und der Knoten, keine IP.')
    print()
    print('Wenn dir das zu viel ist: Die Zahlen lassen sich im Messfenster')
    print('auch von Hand eintragen. Dann redet AHPT weiterhin ausschliesslich')
    print('mit deinem eigenen Webspace.')
    print()
    if not a.ja:
        try:
            if input('Messen? [j/N] ').strip().lower() not in ('j', 'ja'):
                print('Abgebrochen. Nichts gesendet, nichts geschrieben.')
                return 1
        except (EOFError, KeyboardInterrupt):
            print('\nAbgebrochen.')
            return 1
    print()

    def sag(t):
        print(t, flush=True)

    ort = knoten()
    if ort.get('knoten'):
        sag('   Naechster Knoten: %s' % ort['knoten'])

    sag('   herunter: %g s messen (nach %g s Anlauf) ...' % (ZIEL_S, RAMPE))
    herunter, f1 = _fenster(_herunter, ZIEL_S)
    sag('   hinauf:   %g s messen (nach %g s Anlauf) ...' % (ZIEL_S, RAMPE))
    hinauf, f2 = _fenster(_hinauf, ZIEL_S)

    print()
    if not herunter and not hinauf:
        print('FEHLGESCHLAGEN. Nichts gemessen.')
        for g in (f1 or []) + (f2 or []):
            print('   %s' % g)
        print()
        print('Moegliche Gruende: kein Internet, eine Firewall dazwischen,')
        print('oder der Dienst antwortet nicht mehr wie erwartet. Die Zahlen')
        print('lassen sich im Messfenster von Hand eintragen.')
        return 2

    def zeig(name, bps):
        if not bps:
            print('   %-10s -- nicht gemessen' % name)
            return
        print('   %-10s %6.1f Mbit/s   (%.2f MB/s)'
              % (name, bps * 8 / 1e6, bps / 1048576.0))

    print('Ergebnis:')
    zeig('herunter', herunter)
    zeig('hinauf', hinauf)
    print()
    print('   Gemessen mit %d gleichzeitigen Stroemen. Mit einem einzigen'
          % STROEME)
    print('   kaeme weniger heraus -- ein TCP-Strom fuellt eine Leitung')
    print('   nicht aus. Das ist keine Schoenrechnerei, sondern der Grund,')
    print('   warum jeder Speedtest es so macht.')
    print()

    if a.nur_zeigen:
        print('--nur-zeigen: nichts geschrieben.')
        return 0

    d = {'quelle': 'gemessen', 'zeit': time.time()}
    if herunter:
        d['herunter_mbit'] = round(herunter * 8 / 1e6, 1)
    if hinauf:
        d['hinauf_mbit'] = round(hinauf * 8 / 1e6, 1)
    if ort.get('knoten'):
        d['knoten'] = ort['knoten']
    try:
        os.makedirs(KONFIG_ORDNER, exist_ok=True)
        tmp = LEITUNG_DATEI + '.neu'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, LEITUNG_DATEI)
    except OSError as e:
        print('Konnte %s nicht schreiben: %s' % (LEITUNG_DATEI, e))
        print('Die Zahlen oben lassen sich im Messfenster von Hand eintragen.')
        return 2

    print('Eingetragen in %s.' % LEITUNG_DATEI)
    print('Das Messfenster ("Vermittler pruefen") benutzt die Werte ab jetzt.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
