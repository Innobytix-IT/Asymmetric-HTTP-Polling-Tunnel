#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
attrappe_relay.py -- ein Vermittler aus Pappe, fuer den Durchstich ohne PHP

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT


  ####  DIES IST EINE ATTRAPPE. SIE BEWEIST NICHTS UEBER relay.php.  ####


WAS SIE PRUEFT UND WAS NICHT
-----------------------------
Sie prueft AGENT und CLIENT: Umschlag, Marken, Stueckelung,
Zusammensetzen, Weissliste, Abweisungen. Das sind die Teile, die sonst
reine Behauptung blieben.

Sie prueft NICHT relay.php. Kein PHP, kein Apache, kein mod_speling, keine
Prozessgrenze, keine 503, kein `flock`, keine Sperre gegen gleichzeitige
Zugriffe. Das README des Projekts sagt dazu das Richtige:

    "Alles gemessen gegen echtes PHP 8.1 und echtes Apache, nicht gegen
     Attrappen."

und

    "Was ein Testaufbau nicht hat, kann er nicht messen."

Der Live-Lauf vom 02.09.2026 hat `mod_speling` gefunden -- KEINE lokale
Pruefung haette das gekonnt. Diese Datei aendert daran nichts.

DIE GEFAHR EINER ATTRAPPE
-------------------------
Sie kann von der echten Fassung abdriften. Dann laeuft der Test gruen und
der Betrieb faellt um -- genau der Fehlertyp, gegen den dieses Projekt
sonst ueberall Vorkehrungen trifft.

Dagegen: `pruefe_gleichstand()` liest die Deckel AUS relay.php und
vergleicht sie mit den eigenen. Weichen sie ab, startet die Attrappe gar
nicht erst. Sie kann dann immer noch anders HANDELN als relay.php -- aber
sie kann nicht mehr stillschweigend mit anderen ZAHLEN arbeiten.

Aufruf (sonst wird sie von durchstich_lokal.py gestartet):
    python3 tests/attrappe_relay.py --ordner /tmp/x --geheimnis abc... --port 8099
"""

import argparse
import hashlib
import http.server
import ipaddress
import json
import os
import re
import secrets
import socketserver
import sys
import threading
import time

VERSION = 1

# Muessen mit relay.php uebereinstimmen -- pruefe_gleichstand() erzwingt das.
MARKE_TTL   = 120
ANTWORT_TTL = 120
MAX_OFFEN   = 40
MAX_JE_IP   = 20        # AHPT Cloud: ein Nutzer -- Begruendung in relay.php
MAX_FRAGE   = 4096
MAX_STUECK  = 49152
MAX_TEILE   = 256
MAX_FRAGE_TEILE = 160
MAX_RUMPF   = 65536

_BEZEICHNER = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
_MARKE      = re.compile(r'^[0-9a-f]{32}$')


def pruefe_gleichstand(php_pfad):
    """Liest die Deckel aus relay.php und vergleicht sie mit den eigenen.

    Eine Attrappe, die andere Zahlen benutzt als das Original, prueft ein
    System, das es nicht gibt.
    """
    with open(php_pfad, 'r', encoding='utf-8') as f:
        php = f.read()
    meine = {n: globals()[n] for n in (
        'MARKE_TTL', 'ANTWORT_TTL', 'MAX_OFFEN', 'MAX_JE_IP',
        'MAX_FRAGE', 'MAX_STUECK', 'MAX_TEILE', 'MAX_RUMPF')}
    abweichung = []
    for name, wert in sorted(meine.items()):
        m = re.search(r"define\s*\(\s*'%s'\s*,\s*(\d+)\s*\)" % name, php)
        if not m:
            abweichung.append('%s steht nicht in relay.php' % name)
        elif int(m.group(1)) != wert:
            abweichung.append('%s: relay.php sagt %s, Attrappe sagt %s'
                              % (name, m.group(1), wert))
    m = re.search(r"define\s*\(\s*'AHPT_VERSION'\s*,\s*(\d+)\s*\)", php)
    if not m or int(m.group(1)) != VERSION:
        abweichung.append('AHPT_VERSION weicht ab')
    # Die Attrappe bildet diese drei nach. Fehlt eine in relay.php, prueft
    # sie ein Verhalten, das es dort gar nicht gibt.
    for name in ('absender_kennung', 'sicherer_titel', 'raeume_marke'):
        if ('function ' + name) not in php:
            abweichung.append('relay.php hat kein %s()' % name)
    if 'array_key_first' not in php:
        abweichung.append('relay.php verdraengt nicht fair '
                          '(kein array_key_first)')
    return abweichung


def stueck_name(marke, teil):
    """Muss zeichengenau der Funktion in relay.php entsprechen."""
    d = hashlib.sha256(('%s|%d' % (marke, teil)).encode('ascii')).hexdigest()[:4]
    return 'antwort_%s_%d_%s.json' % (marke, teil, d)


def frage_stueck_name(marke, teil):
    """Muss zeichengenau der Funktion in relay.php entsprechen."""
    d = hashlib.sha256(('%s|f|%d' % (marke, teil)).encode('ascii')).hexdigest()[:4]
    return 'fstueck_%s_%d_%s.json' % (marke, teil, d)


def absender_kennung(ip):
    """Muss sich verhalten wie absender_kennung() in relay.php.

    IPv4 voll, IPv6 auf /64. Die echte Fassung wird von
    tests/pruefe_absender.php gegen PHP geprueft -- diese hier gibt es nur,
    damit die Attrappe dieselbe Einteilung vornimmt. Eine Attrappe, die
    Absender anders zaehlt als das Original, prueft das faire Verdraengen
    an einem System, das es nicht gibt.
    """
    if not ip:
        return '?'
    try:
        b = ipaddress.ip_address(ip).packed
    except ValueError:
        return 'roh:' + ip
    if len(b) == 4:
        return 'v4:' + b.hex()
    if len(b) == 16:
        if b[:12] == bytes(10) + b'\xff\xff':
            return 'v4:' + b[12:].hex()
        return 'v6:' + b[:8].hex()
    return 'roh:' + ip


def ist_chiffre(s, grenze):
    """Auch ein undurchsichtiger Block hat eine Form -- muss wie relay.php."""
    return (isinstance(s, str) and s != '' and len(s) <= grenze
            and re.fullmatch(r'[A-Za-z0-9+/]+={0,2}', s) is not None)


def sicherer_titel(t):
    """Muss sich verhalten wie sicherer_titel() in relay.php."""
    t = str(t)
    t = ''.join(c for c in t if c >= ' ' and c != '\x7f' and c not in '<>')
    return t[:200]


class Ablage:

    def __init__(self, ordner, geheimnis):
        self.ordner = ordner
        self.ahpt = os.path.join(ordner, 'ahpt')
        os.makedirs(self.ahpt, exist_ok=True)
        self.geheimnis = geheimnis
        self.offen = []
        self.fertig = []
        self.folge = 0
        self.verdraengt = 0
        self.salz = secrets.token_hex(16)
        self.sperre = threading.Lock()

    def _raeume(self, marke, stuecke, fstuecke=0):
        for n in ('frage_%s.json' % marke, 'antwort_%s.json' % marke):
            try:
                os.unlink(os.path.join(self.ahpt, n))
            except OSError:
                pass
        for i in range(min(stuecke, MAX_TEILE)):
            try:
                os.unlink(os.path.join(self.ahpt, stueck_name(marke, i)))
            except OSError:
                pass
        for i in range(min(fstuecke, MAX_FRAGE_TEILE)):
            try:
                os.unlink(os.path.join(self.ahpt, frage_stueck_name(marke, i)))
            except OSError:
                pass

    def _kehre(self):
        jetzt = time.time()
        behalten = []
        for e in self.offen:
            if jetzt - e['ts'] > MARKE_TTL:
                self._raeume(e['marke'], e.get('st', 0), e.get('fst', 0))
            else:
                behalten.append(e)
        self.offen = behalten
        behalten = []
        for e in self.fertig:
            if jetzt - e['ts'] > ANTWORT_TTL:
                self._raeume(e['marke'], e['teile'] if e['teile'] > 1 else 0)
            else:
                behalten.append(e)
        self.fertig = behalten

    def _schreibe(self, name, text):
        """Atomar ersetzen -- mit einer Wiederholung, die es nur auf Windows
        braucht.

        Unter POSIX ist `rename()` ueber eine geoeffnete Datei zulaessig:
        Der Leser behaelt seinen alten Inhalt, der neue Name zeigt sofort auf
        die neue Datei. Genau darauf beruht das atomare Schreiben in
        relay.php, und auf einem Linux-Webspace gilt es.

        Windows verweigert das (WinError 5), solange irgendjemand die
        Zieldatei offen hat -- und hier liest der Agent sie im Sekundentakt.
        Ohne diese Wiederholung bricht die Attrappe unter Last mit
        PermissionError ab, und der Test meldet einen Fehler im Protokoll,
        wo keiner ist.

        Das ist ausdruecklich ein Zugestaendnis DER ATTRAPPE an ihr
        Betriebssystem, keine Eigenschaft von AHPT. Wer relay.php je auf
        Windows betreibt, muss sich denselben Punkt eigens ansehen.
        """
        ziel = os.path.join(self.ahpt, name)
        tmp = ziel + '.' + secrets.token_hex(4) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
        for versuch in range(40):
            try:
                os.replace(tmp, ziel)
                return
            except PermissionError:
                if versuch == 39:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
                time.sleep(0.01)

    def _warteschlange(self):
        self.folge += 1
        self._schreibe('warteschlange.json', json.dumps(
            {'stand': int(time.time()), 'folge': self.folge,
             'offen': [{'marke': e['marke'], 'ts': e['ts']}
                       for e in self.offen if e.get('bereit', True)],
             'fertig': [e['marke'] for e in self.fertig]},
            ensure_ascii=False))

    def _umschlag(self, marke, teil, teile, nutzlast, krypto='keine'):
        return json.dumps({'v': VERSION, 'marke': marke, 'teil': teil,
                           'teile': teile, 'krypto': krypto,
                           'nutzlast': nutzlast}, ensure_ascii=False)

    # ------------------------------------------------------- Aktionen

    def frage(self, eingabe, absender):
        n = eingabe.get('nutzlast')
        if not isinstance(n, dict):
            return 400, {'ok': False, 'fehler': 'nutzlast fehlt'}
        k = eingabe.get('krypto', 'keine')

        # MARKE, wahlweise vom Absender vorgegeben -- Spiegelbild derselben
        # Ergaenzung in relay.php (dort ausfuehrlich begruendet: AHPT Cloud
        # 3000 braucht das, damit dieselbe Marke einen Transportwechsel
        # ueberlebt, und WebDAV kann ueberhaupt keine Marke selbst erzeugen).
        marke_vorgabe = str(eingabe.get('marke', '') or '')
        if marke_vorgabe and not _MARKE.match(marke_vorgabe):
            return 400, {'ok': False, 'fehler': 'Ungueltige Marke'}

        # Verschluesselt sieht der Vermittler weder Dienst noch Aktion. Muss
        # er auch nicht -- inhaltsblind war immer sein Auftrag.
        f_teile = eingabe.get('teile', 1)
        if not isinstance(f_teile, int) or not 1 <= f_teile <= MAX_FRAGE_TEILE:
            return 400, {'ok': False, 'fehler': 'teile unplausibel'}
        if f_teile > 1 and k == 'keine':
            return 400, {'ok': False,
                         'fehler': 'Gestueckelte Fragen nur verschluesselt'}

        if k != 'keine':
            if f_teile > 1:
                return self._annehmen({'chiffre': ''}, absender, k, f_teile,
                                       marke_vorgabe)
            c = n.get('chiffre')
            if not ist_chiffre(c, MAX_FRAGE):
                return 400, {'ok': False, 'fehler': 'chiffre: Base64 erwartet'}
            return self._annehmen({'chiffre': c}, absender, k,
                                   marke_vorgabe=marke_vorgabe)

        dienst, aktion, daten = n.get('dienst'), n.get('aktion'), n.get('daten')
        if not isinstance(dienst, str) or not _BEZEICHNER.match(dienst):
            return 400, {'ok': False, 'fehler': 'dienst: Bezeichner erwartet'}
        if not isinstance(aktion, str) or not _BEZEICHNER.match(aktion):
            return 400, {'ok': False, 'fehler': 'aktion: Bezeichner erwartet'}
        if not isinstance(daten, dict):
            return 400, {'ok': False, 'fehler': 'daten: Objekt erwartet'}
        nutz = {'dienst': dienst, 'aktion': aktion, 'daten': daten}
        if len(json.dumps(nutz, ensure_ascii=False).encode('utf-8')) > MAX_FRAGE:
            return 400, {'ok': False, 'fehler': 'Frage zu gross'}
        return self._annehmen(nutz, absender, k, marke_vorgabe=marke_vorgabe)

    def _annehmen(self, nutz, absender, k, f_teile=1, marke_vorgabe=''):
        """Aufnehmen, verdraengen, ablegen -- fuer beide Verfahren gleich."""
        with self.sperre:
            self._kehre()
            wer = hashlib.sha256(('%s|%s' % (self.salz, absender_kennung(absender)))
                                 .encode('utf-8')).hexdigest()[:16]
            if sum(1 for e in self.offen if e['wer'] == wer) >= MAX_JE_IP:
                return 429, {'ok': False, 'fehler': 'Zu viele offene Fragen'}

            # Faires Verdraengen -- muss der Logik in relay.php entsprechen.
            if len(self.offen) >= MAX_OFFEN:
                zaehlung = {}
                for e in self.offen:
                    zaehlung[e['wer']] = zaehlung.get(e['wer'], 0) + 1
                vielste = max(zaehlung, key=lambda k: zaehlung[k])
                if zaehlung[vielste] <= 1:
                    return 503, {'ok': False, 'fehler': 'Vermittler ausgelastet'}
                if vielste == wer:
                    return 429, {'ok': False, 'fehler': 'Zu viele offene Fragen'}
                opfer_i = min((i for i, e in enumerate(self.offen)
                               if e['wer'] == vielste),
                              key=lambda i: self.offen[i]['ts'])
                opfer = self.offen.pop(opfer_i)
                self._raeume(opfer['marke'], opfer.get('st', 0))
                self.verdraengt += 1

            if marke_vorgabe:
                if any(e['marke'] == marke_vorgabe for e in self.offen) \
                        or any(e['marke'] == marke_vorgabe for e in self.fertig):
                    return 409, {'ok': False, 'fehler': 'Marke bereits in Gebrauch'}
                marke = marke_vorgabe
            else:
                marke = secrets.token_hex(16)
            if f_teile > 1:
                nutz = dict(nutz)
                nutz['stuecke'] = [{'teil': i,
                                    'datei': frage_stueck_name(marke, i)}
                                   for i in range(f_teile)]
            self._schreibe('frage_%s.json' % marke,
                           self._umschlag(marke, 0, f_teile, nutz, k))
            self.offen.append({'marke': marke, 'ts': int(time.time()),
                               'wer': wer, 'st': 0, 'fst': 0,
                               'bereit': f_teile == 1})
            self._warteschlange()
        return 200, {'ok': True, 'marke': marke, 'ttl': MARKE_TTL,
                     'teile': f_teile,
                     'abholen': 'ahpt/antwort_%s.json' % marke}

    def frage_stueck(self, eingabe):
        """Ein Stueck einer gestueckelten Frage -- der Hochladeweg."""
        marke = str(eingabe.get('marke', ''))
        if not _MARKE.match(marke):
            return 400, {'ok': False, 'fehler': 'Ungueltige Marke'}
        teil, teile = eingabe.get('teil'), eingabe.get('teile')
        if not isinstance(teil, int) or not isinstance(teile, int)                 or not 2 <= teile <= MAX_FRAGE_TEILE                 or not 0 <= teil < teile:
            return 400, {'ok': False, 'fehler': 'teil/teile unplausibel'}
        inhalt = eingabe.get('nutzlast')
        if not ist_chiffre(inhalt, MAX_STUECK):
            return 400, {'ok': False, 'fehler': 'nutzlast: Base64 erwartet'}
        with self.sperre:
            self._kehre()
            for e in self.offen:
                if e['marke'] != marke:
                    continue
                if e.get('bereit', True):
                    return 404, {'ok': False, 'fehler': 'schon fertig'}
                e['fst'] = max(e.get('fst', 0), teil + 1)
                self._schreibe(frage_stueck_name(marke, teil),
                               self._umschlag(marke, teil, teile, inhalt,
                                              eingabe.get('krypto', 'keine')))
                return 200, {'ok': True,
                             'datei': frage_stueck_name(marke, teil)}
        return 404, {'ok': False, 'fehler': 'Marke unbekannt oder verfallen'}

    def frage_fertig(self, eingabe):
        """Alle Stuecke da -- erst jetzt wird die Marke sichtbar."""
        marke = str(eingabe.get('marke', ''))
        if not _MARKE.match(marke):
            return 400, {'ok': False, 'fehler': 'Ungueltige Marke'}
        teile = eingabe.get('teile')
        if not isinstance(teile, int) or not 2 <= teile <= MAX_FRAGE_TEILE:
            return 400, {'ok': False, 'fehler': 'teile unplausibel'}
        # NACHSEHEN, nicht glauben: eine Warteschlange, die auf Luecken
        # zeigt, ist schlimmer als eine leere.
        for i in range(teile):
            if not os.path.isfile(os.path.join(self.ahpt,
                                               frage_stueck_name(marke, i))):
                return 409, {'ok': False, 'fehler': 'Es fehlt ein Stueck',
                             'teil': i}
        with self.sperre:
            self._kehre()
            for e in self.offen:
                if e['marke'] != marke:
                    continue
                if e.get('bereit', True):
                    return 404, {'ok': False, 'fehler': 'schon fertig'}
                e['bereit'] = True
                e['ts'] = int(time.time())
                self._warteschlange()
                return 200, {'ok': True, 'marke': marke, 'ttl': MARKE_TTL}
        return 404, {'ok': False, 'fehler': 'Marke unbekannt oder verfallen'}

    def stueck(self, eingabe):
        marke = eingabe.get('marke', '')
        if not isinstance(marke, str) or not _MARKE.match(marke):
            return 400, {'ok': False, 'fehler': 'Ungueltige Marke'}
        teil, teile = eingabe.get('teil'), eingabe.get('teile')
        if not isinstance(teil, int) or not isinstance(teile, int) \
                or isinstance(teil, bool) or isinstance(teile, bool) \
                or not (2 <= teile <= MAX_TEILE) or not (0 <= teil < teile):
            return 400, {'ok': False, 'fehler': 'teil/teile unplausibel'}
        inhalt = eingabe.get('nutzlast')
        if not isinstance(inhalt, str):
            return 400, {'ok': False, 'fehler': 'nutzlast: Zeichenkette erwartet'}
        if len(inhalt.encode('utf-8')) > MAX_STUECK:
            return 413, {'ok': False, 'fehler': 'Stueck zu gross'}
        with self.sperre:
            self._kehre()
            e = next((x for x in self.offen if x['marke'] == marke), None)
            if e is None:
                return 404, {'ok': False, 'fehler': 'Marke unbekannt oder verfallen'}
            e['st'] = max(e.get('st', 0), teil + 1)
            self._schreibe(stueck_name(marke, teil),
                           self._umschlag(marke, teil, teile, inhalt,
                                          eingabe.get('krypto', 'keine')))
            self._warteschlange()
        return 200, {'ok': True, 'datei': stueck_name(marke, teil)}

    def antwort(self, eingabe):
        marke = eingabe.get('marke', '')
        if not isinstance(marke, str) or not _MARKE.match(marke):
            return 400, {'ok': False, 'fehler': 'Ungueltige Marke'}
        teile = eingabe.get('teile', 1)
        if not isinstance(teile, int) or isinstance(teile, bool) \
                or not (1 <= teile <= MAX_TEILE):
            return 400, {'ok': False, 'fehler': 'teile unplausibel'}
        n = eingabe.get('nutzlast')
        if not isinstance(n, dict):
            return 400, {'ok': False, 'fehler': 'nutzlast fehlt'}
        k = eingabe.get('krypto', 'keine')
        if k != 'keine':
            c = n.get('chiffre')
            if teile == 1 and not ist_chiffre(c, MAX_STUECK):
                return 400, {'ok': False, 'fehler': 'chiffre: Base64 erwartet'}
            nutz = {'chiffre': '' if teile > 1 else c}
            return self._ablegen(marke, teile, nutz, k)

        nutz = {'gefunden': bool(n.get('gefunden', True)),
                'titel': sicherer_titel(n.get('titel', '')),
                'quelle': sicherer_titel(n.get('quelle', '')),
                'inhalt_typ': str(n.get('inhalt_typ', 'text')),
                'inhalt': str(n.get('inhalt', ''))}
        if nutz['inhalt_typ'] not in ('text', 'base64'):
            return 400, {'ok': False, 'fehler': 'inhalt_typ: text oder base64'}
        if teile == 1 and len(nutz['inhalt'].encode('utf-8')) > MAX_STUECK:
            return 413, {'ok': False, 'fehler': 'Antwort zu gross -- stueckeln'}
        if teile > 1:
            nutz['inhalt'] = ''
        return self._ablegen(marke, teile, nutz, k)

    def _ablegen(self, marke, teile, nutz, k):
        if teile > 1:
            nutz['stuecke'] = [{'teil': i, 'datei': stueck_name(marke, i)}
                               for i in range(teile)]
        with self.sperre:
            self._kehre()
            if not any(x['marke'] == marke for x in self.offen):
                return 404, {'ok': False, 'fehler': 'Marke unbekannt oder verfallen'}
            if teile > 1:
                for i in range(teile):
                    if not os.path.isfile(os.path.join(self.ahpt,
                                                       stueck_name(marke, i))):
                        return 409, {'ok': False, 'fehler': 'Stueck fehlt', 'teil': i}
            self.offen = [x for x in self.offen if x['marke'] != marke]
            self._schreibe('antwort_%s.json' % marke,
                           self._umschlag(marke, 0, teile, nutz, k))
            try:
                os.unlink(os.path.join(self.ahpt, 'frage_%s.json' % marke))
            except OSError:
                pass
            self.fertig.append({'marke': marke, 'ts': int(time.time()),
                                'teile': teile})
            self._warteschlange()
        return 200, {'ok': True, 'teile': teile}


class Behandler(http.server.BaseHTTPRequestHandler):

    ablage = None
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass                        # still, sonst uebertoent es den Test

    def handle_one_request(self):
        # Ein Client, der die Verbindung abbricht (der Abbruch-Test tut das
        # absichtlich), erzeugt sonst einen Stapelauszug mitten im Bericht.
        # Das ist Rauschen der Attrappe, kein Befund -- und Rauschen sorgt
        # dafuer, dass echte Meldungen ueberlesen werden.
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def handle_error(self, *a):
        pass

    def _sende(self, code, daten):
        roh = json.dumps(daten, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(roh)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(roh)

    def do_POST(self):
        if not self.path.startswith('/relay.php'):
            return self._sende(404, {'ok': False, 'fehler': 'nicht gefunden'})
        aktion = ''
        if '?' in self.path:
            for p in self.path.split('?', 1)[1].split('&'):
                if p.startswith('action='):
                    aktion = p[7:]
        laenge = int(self.headers.get('Content-Length') or 0)
        if laenge > MAX_RUMPF:
            return self._sende(413, {'ok': False, 'fehler': 'Rumpf zu gross'})
        try:
            eingabe = json.loads(self.rfile.read(laenge).decode('utf-8'))
        except Exception:
            eingabe = {}
        if not isinstance(eingabe, dict):
            eingabe = {}

        if aktion != 'selbsttest':
            if eingabe.get('v') != VERSION:
                return self._sende(400, {'ok': False, 'fehler': 'Protokollfassung'})
            if eingabe.get('krypto', 'keine') not in ('keine', 'noise_ik', 'noise_ik_aes'):
                return self._sende(400, {'ok': False, 'fehler': 'Unbekanntes Verfahren'})

        a = self.ablage
        if aktion in ('frage_stueck', 'frage_fertig'):
            return self._sende(*(a.frage_stueck(eingabe)
                                 if aktion == 'frage_stueck'
                                 else a.frage_fertig(eingabe)))
        if aktion == 'frage':
            return self._sende(*a.frage(eingabe, self.client_address[0]))
        if aktion in ('stueck', 'antwort'):
            # Ausweis. Ohne ihn koennte jeder eine Antwort einschleusen.
            if self.headers.get('X-AHPT-Auth') != a.geheimnis:
                return self._sende(403, {'ok': False, 'fehler': 'Geheimnis noetig'})
            return self._sende(*(a.stueck(eingabe) if aktion == 'stueck'
                                 else a.antwort(eingabe)))
        return self._sende(400, {'ok': False, 'fehler': 'Unbekannte Aktion'})

    def do_GET(self):
        pfad = self.path.split('?', 1)[0]
        if not pfad.startswith('/ahpt/'):
            return self._sende(404, {'ok': False, 'fehler': 'nicht gefunden'})
        name = pfad[6:]
        # Keine Pfadwanderung, auch nicht in der Attrappe.
        if '/' in name or '\\' in name or '..' in name or not name:
            return self._sende(400, {'ok': False, 'fehler': 'Name'})
        voll = os.path.join(self.ablage.ahpt, name)
        if not os.path.isfile(voll):
            return self._sende(404, {'ok': False, 'fehler': 'noch nicht da'})
        with open(voll, 'rb') as f:
            roh = f.read()
        # ETag wie Apache: Groesse und Aenderungszeit. Ohne das gibt es kein
        # 304, und ohne 304 gibt es AHPT nicht.
        st = os.stat(voll)
        # ABSICHTLICH so grob wie Apaches Vorgabe `FileETag MTime Size`:
        # ganze Sekunden und Groesse. Wer hier die Inode-Nummer mit
        # hineinnimmt, macht die Attrappe besser als den schlechtesten
        # Fall -- und prueft dann nicht mehr, ob der Agent damit
        # zurechtkommt. Der unbedingte Abruf des Agenten MUSS hier
        # gebraucht werden, sonst beweist der Test nichts.
        etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)
        if self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(roh)))
        self.send_header('ETag', etag)
        self.end_headers()
        self.wfile.write(roh)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def starte(ordner, geheimnis, port=0):
    """Startet die Attrappe im Hintergrund. Gibt (server, port) zurueck."""
    hier = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    abweichung = pruefe_gleichstand(os.path.join(hier, 'relay.php'))
    if abweichung:
        raise SystemExit(
            'ABBRUCH: Attrappe und relay.php sind nicht mehr gleich:\n  '
            + '\n  '.join(abweichung)
            + '\n\nEine Attrappe mit anderen Zahlen prueft ein System, das es'
              ' nicht gibt.')
    klasse = type('B', (Behandler,), {'ablage': Ablage(ordner, geheimnis)})
    srv = Server(('127.0.0.1', port), klasse)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--ordner', required=True)
    ap.add_argument('--geheimnis', required=True)
    ap.add_argument('--port', type=int, default=8099)
    a = ap.parse_args()
    srv, port = starte(a.ordner, a.geheimnis, a.port)
    print('Attrappe laeuft auf http://127.0.0.1:%d  --  BEWEIST NICHTS UEBER '
          'relay.php' % port, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()
