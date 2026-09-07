#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ahpt_client.py -- die Besucherseite von AHPT Cloud, auf der Kommandozeile

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Das Gegenstueck zum Agenten. Er laeuft auf dem Geraet, mit dem du unterwegs
bist -- Laptop, zweiter Rechner --, und spricht durch den Webspace mit dem
Heimserver.

    ahpt_client.py liste
    ahpt_client.py liste unterordner
    ahpt_client.py hole bericht.pdf
    ahpt_client.py hole bilder/urlaub.jpg --nach ~/Downloads/urlaub.jpg

WARUM EIN EIGENES PROGRAMM UND KEINE WEBSEITE
----------------------------------------------
Das ist die tragende Entscheidung dieser ganzen Fassung.

Kaeme die Oberflaeche als HTML vom Webspace, koennte der Hoster sie
austauschen -- und mit ihr den eingebauten Schluessel des Agenten. Dann
verschluesselte der Client brav gegen den Schluessel des Angreifers, und
niemandem fiele etwas auf. Verschluesselung, deren Schluessel vom
Unvertrauten geliefert wird, ist keine.

Hier liegt der Schluessel des Agenten in DEINER Konfigurationsdatei, von
Hand uebertragen. Der Webspace ist nie im Vertrauenspfad. Genau deshalb ist
die private Nutzung leichter abzusichern als ein oeffentliches Portal --
und genau deshalb kommt das Portal spaeter und wird, wenn moeglich, lokal
liegen.

WAS DER WEBSPACE ZU SEHEN BEKOMMT
----------------------------------
Rauschen. Weder Dienst noch Aktion, weder Dateiname noch Inhalt, nicht
einmal, ob etwas gefunden wurde.

Was er weiterhin sieht: WANN gefragt wird, WIE OFT, und WIE GROSS die
Antwort war. Verschluesselung verbirgt den Inhalt, nicht die Umstaende.

HTTP ODER HTTPS
---------------
Ohne Verschluesselung besteht dieser Client auf https -- sonst laege alles
offen. MIT Noise IK ist http zulaessig: Der Transport muss dann nicht mehr
vertrauenswuerdig sein, das ist ja der Zweck. Ein Mitleser sieht Rauschen.

Das ist keine Testklappe. Es ist die Feststellung, dass zwei Schutzschichten
dasselbe Ziel haben und eine davon genuegt -- und der Client sagt beim
Start, welche gerade traegt.
"""

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)

import netz
import transport

VERSION = 1
PROLOG = b'AHPT-Privat/1'

# Groesster Ausschnitt, den ein Dienst als EINE Frage/Antwort vertraegt --
# Grenzen des PHP-Wegs (transport.PHP_MAX_FRAGE usw.) und des WebDAV-Wegs
# (transport.MAX_WEBDAV_NUTZLAST) stecken seit der Transport-Abstraktion in
# transport.py, weil sie je Weg verschieden sind und WebDAV die meisten
# davon gar nicht kennt.

# Wieviel Nutzdatei in EINE Frage passt (Bloecke bei `lege`).
#
# 160 Stuecke a 49152 Zeichen (transport.PHP_MAX_FRAGE_TEILE/PHP_MAX_STUECK)
# sind 7,5 MiB Base64-Geheimtext, also 5,6 MiB Geheimtext, also nach Abzug
# von Siegel und JSON-Huelle rund 4,2 MiB Datei. 3 MiB laesst Luft und ist
# eine Zahl, die man im Kopf behaelt.
#
# Diese Grenze ist die des PHP-VERMITTLERS und bleibt als Vorgabe fuer die
# Bloeckelung beim Hochladen: Fragestuecke darf jeder ablegen, der die
# Adresse kennt. Sie begrenzt nicht mehr die Dateigroesse, denn eine Datei
# geht ueber beliebig viele Fragen.
SCHREIB_BLOCK   = 3 * 1024 * 1024

# Groesster Ausschnitt, den der Agent je Antwort liefert (siehe
# handler/datei.py, LESE_BLOCK). Muss dazu passen, sonst weist er ab.
LESE_BLOCK      = 4 * 1024 * 1024

# Wie oft ein GANZER Vorgang (neue Marke, neue Frage) versucht wird, bevor
# aufgegeben wird -- fuer den Fall, dass der Agent gar nicht erst antwortet,
# nicht nur ein einzelnes Stueck ablehnt. Zaehlt jetzt auch als "wie oft den
# Transportweg wechseln": jeder Versuch waehlt per Rundlauf neu (siehe
# Client._naechster_frageweg).
FRAGE_WIEDERHOLUNGEN = 3


class ClientFehler(Exception):
    pass


# ------------------------------------------------------------------- Netz
#
# Rohe, ausweislose Anfragen an relay.php -- NICHT mehr der normale Weg
# einer Frage (der laeuft seit der Transport-Abstraktion ueber `transport.py`
# und damit ueber `netz.py`, siehe Client.__init__/_frage_einmal). Diese
# beiden Funktionen bleiben oeffentlich, weil `tests/durchstich_privat.py`
# sie braucht, um absichtlich PROTOKOLLWIDRIGE Anfragen zu bauen (eine
# Wiederholung, ein veraendertes Chiffrat, ein Rueckfall auf Klartext) --
# genau die Faelle, die die hoehere Ebene (`Client.frage`) gar nicht erst
# zulassen wuerde.

class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen sind AUS.

    Am 02.09.2026 auf IONOS gemessen: `mod_speling` leitete die Abfrage nach
    der ANTWORT stillschweigend auf die FRAGE um. Wer folgt, liest eine
    Auskunft, die es nie gab.
    """

    def redirect_request(self, *a, **k):
        return None


_OEFFNER = urllib.request.build_opener(_KeineWeiterleitung)


def _hole(url, timeout=15):
    # EINE Kennung fuer alles, was dieses Programm hinausschickt -- die
    # aus netz.py, dieselbe, die auch `transport` benutzt. Frueher hatte
    # dieses Modul eine eigene ("AHPT-Privat-Client/1"), und damit trugen
    # zwei Anfragen desselben Vorgangs zwei verschiedene Namen: Wer die
    # Kennung umstellt, um nicht aufzufallen, faellt dann GERADE DADURCH
    # auf. Umgestellt wird sie ueber `kennung` in der Konfiguration.
    req = urllib.request.Request(url, method='GET')
    req.add_header('User-Agent', netz.KENNUNG)
    try:
        with _OEFFNER.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b''
    except Exception as e:
        raise ClientFehler('Abruf fehlgeschlagen (Umleitung? Netz?): %s' % e)


def _sende(url, nutzlast, timeout=15):
    daten = json.dumps(nutzlast, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=daten, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('User-Agent', netz.KENNUNG)
    try:
        with _OEFFNER.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8', 'replace'))
        except Exception:
            return e.code, {}
    except Exception as e:
        raise ClientFehler('Absenden fehlgeschlagen: %s' % e)


# ---------------------------------------------------------------- Aufbau

class Aufbau:
    def __init__(self, roh, konfig_pfad='client.toml'):
        r = roh.get('relay') or {}
        self.basis = str(r.get('basis', '')).rstrip('/')
        if not self.basis:
            raise ClientFehler('[relay] basis fehlt.')
        self.frist = float(r.get('frist', 60))
        self.abstand = float(r.get('abstand', 0.4))
        # Wie oft ein ganzer Vorgang (neue Marke, neue Frage) versucht wird,
        # bevor aufgegeben wird. Einstellbar, weil ein Test, der absichtlich
        # eine Ablehnung ohne Antwort auf die Probe stellt, sonst bei jeder
        # Wiederholung erneut die volle Frist abwarten muesste.
        self.wiederholungen = int(r.get('wiederholungen', FRAGE_WIEDERHOLUNGEN))

        # Kennung (User-Agent). Vorgabe siehe netz.KENNUNG; hier gesetzt,
        # SOBALD sie gelesen ist -- die ersten Anfragen entstehen schon
        # beim Aufbau der Transportwege, nicht erst beim ersten Befehl.
        try:
            netz.setze_kennung(r.get('kennung'))
        except ValueError as e:
            raise ClientFehler('[relay] kennung: %s' % e)

        k = roh.get('krypto') or {}
        self.verfahren = str(k.get('verfahren', 'keine'))
        if self.verfahren not in ('keine', 'noise_ik'):
            raise ClientFehler('[krypto] verfahren: "keine" oder "noise_ik"')

        schema = urllib.parse.urlsplit(self.basis).scheme
        if schema != 'https' and self.verfahren != 'noise_ik':
            raise ClientFehler(
                'Ohne Verschluesselung ist nur https zulaessig.\n'
                '  Entweder eine https-Basis eintragen, oder\n'
                '  [krypto] verfahren = "noise_ik" setzen. Ueber http und ohne\n'
                '  Verschluesselung laege jede Frage und jede Antwort offen --\n'
                '  fuer den Hoster und fuer jeden Zwischenknoten.')

        self.privat = None
        self.agent = None
        if self.verfahren == 'noise_ik':
            try:
                import krypto
            except ImportError:
                raise ClientFehler('`cryptography` fehlt: pip install cryptography')
            sd = k.get('schluessel')
            if not sd:
                raise ClientFehler('[krypto] schluessel fehlt (dein eigener).')
            self.privat = krypto.lies_privat(os.path.expanduser(str(sd)))
            ag = k.get('agent')
            if not ag:
                raise ClientFehler(
                    '[krypto] agent fehlt -- der oeffentliche Schluessel des\n'
                    '  Agenten. Er steht in dessen Startausgabe und wird VON\n'
                    '  HAND uebertragen, nie ueber den Webspace geholt: was\n'
                    '  dort liegt, kann der Hoster austauschen.')
            try:
                self.agent = bytes.fromhex(str(ag))
            except ValueError:
                raise ClientFehler('[krypto] agent ist kein Hexwert.')
            if len(self.agent) != 32:
                raise ClientFehler('[krypto] agent hat %d Bytes statt 32'
                                   % len(self.agent))

        self._lies_transporte(roh)

        # ------------------------------------- Gesundheits-Gedaechtnis
        #
        # Anders als der Agent (ein Prozess, der Tage laeuft) ist dieses
        # Programm nach jedem Aufruf vorbei -- ohne eine Datei waere jeder
        # Aufruf amnesisch und muesste einen toten Weg jedesmal neu
        # entdecken. Vorgabe: neben der Konfigurationsdatei, nicht im
        # Arbeitsverzeichnis -- sonst haengt der Ort vom Zufall ab, WOHER
        # das Programm gerade aufgerufen wird.
        gd = r.get('gesundheit_datei')
        if gd:
            self.gesundheit_datei = os.path.expanduser(str(gd))
        else:
            ordner = os.path.dirname(os.path.abspath(konfig_pfad))
            self.gesundheit_datei = os.path.join(
                ordner, '.ahpt-client-gesundheit.json')

    # ------------------------------------------------- Transportwege
    #
    # Spiegelbild von Aufbau._lies_transporte in relay_agent.py -- dieselbe
    # Idee (der urspruengliche Weg aus [relay] bleibt immer der erste
    # Eintrag, [[transport]] ergaenzt weitere), aber ohne `geheimnis_datei`
    # (der CLIENT braucht kein Ausweis-Geheimnis -- er stellt Fragen, dafuer
    # verlangt relay.php keinen; siehe transport.PhpTransport-Doku) und ohne
    # `unbedingt_nach`/ETag-Belange (die betreffen nur das Abklopfen einer
    # Warteschlange, und das tut nur der Agent).
    def _lies_transporte(self, roh):
        rollen = ('frage', 'antwort', 'beide')
        r = roh.get('relay') or {}
        rolle_php = str(r.get('rolle', 'beide'))
        if rolle_php not in rollen:
            raise ClientFehler(
                '[relay] rolle muss "frage", "antwort" oder "beide" sein, '
                'nicht %r.' % rolle_php)
        self.transporte = [{'art': 'php', 'name': 'php', 'rolle': rolle_php,
                             'basis': self.basis}]
        namen = {'php'}

        zusaetzlich = roh.get('transport') or []
        if not isinstance(zusaetzlich, list):
            raise ClientFehler('[[transport]] ist keine Liste von Abschnitten.')

        for t in zusaetzlich:
            if not isinstance(t, dict):
                raise ClientFehler('[[transport]] ist kein Abschnitt.')
            name = t.get('name')
            if not isinstance(name, str) \
                    or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', name):
                raise ClientFehler(
                    '[[transport]] name %r passt nicht zu '
                    '^[a-z][a-z0-9_-]{0,31}$' % (name,))
            if name in namen:
                raise ClientFehler(
                    'Transportweg "%s" ist zweimal angegeben (der '
                    'urspruengliche Weg aus [relay] heisst intern "php").'
                    % name)
            namen.add(name)

            rolle = str(t.get('rolle', 'beide'))
            if rolle not in rollen:
                raise ClientFehler(
                    'Transportweg "%s": rolle muss "frage", "antwort" oder '
                    '"beide" sein, nicht %r.' % (name, rolle))

            art = t.get('art')
            if art == 'php':
                basis = str(t.get('basis', '')).rstrip('/')
                if not basis:
                    raise ClientFehler('Transportweg "%s": basis fehlt.' % name)
                schema = urllib.parse.urlsplit(basis).scheme
                if schema != 'https' and self.verfahren != 'noise_ik':
                    raise ClientFehler(
                        'Transportweg "%s": basis muss https sein (oder '
                        '[krypto] verfahren = "noise_ik" setzen).' % name)
                self.transporte.append({'art': 'php', 'name': name,
                                        'rolle': rolle, 'basis': basis})
            elif art == 'webdav':
                basis = str(t.get('basis', '')).rstrip('/')
                if not basis:
                    raise ClientFehler('Transportweg "%s": basis fehlt.' % name)
                benutzer = t.get('benutzer')
                if not benutzer:
                    raise ClientFehler(
                        'Transportweg "%s": benutzer fehlt.' % name)
                pd = t.get('passwort_datei')
                if not pd:
                    raise ClientFehler(
                        'Transportweg "%s": passwort_datei fehlt.' % name)
                pd = os.path.expanduser(str(pd))
                try:
                    with open(pd, 'r', encoding='utf-8') as f:
                        if not f.read().strip():
                            raise ClientFehler(
                                'Transportweg "%s": passwort_datei ist leer: '
                                '%s' % (name, pd))
                except OSError as e:
                    raise ClientFehler(
                        'Transportweg "%s": passwort_datei nicht lesbar: %s'
                        % (name, e.strerror or e))
                self.transporte.append({
                    'art': 'webdav', 'name': name, 'rolle': rolle,
                    'basis': basis, 'benutzer': str(benutzer),
                    'passwort_datei': pd,
                    'timeout': float(t.get('timeout', 20)),
                })
            else:
                raise ClientFehler(
                    'Transportweg "%s": art muss "php" oder "webdav" sein, '
                    'nicht %r.' % (name, art))

        if not any(x['rolle'] in ('frage', 'beide') for x in self.transporte):
            raise ClientFehler(
                'Kein Transportweg mit rolle "frage" oder "beide" -- '
                'der Client koennte nie eine Frage stellen.')
        if not any(x['rolle'] in ('antwort', 'beide') for x in self.transporte):
            raise ClientFehler(
                'Kein Transportweg mit rolle "antwort" oder "beide" -- '
                'der Client koennte nie eine Antwort abholen.')


def lies_konfig(pfad):
    if not os.path.isfile(pfad):
        raise ClientFehler('Konfiguration nicht gefunden: %s' % pfad)
    if pfad.endswith('.toml'):
        import tomllib
        with open(pfad, 'rb') as f:
            return tomllib.load(f)
    with open(pfad, encoding='utf-8') as f:
        return json.load(f)


# --------------------------------------------------------------- Vorgang

class Client:
    def __init__(self, aufbau):
        self.a = aufbau
        # Transportwege bauen -- Spiegelbild von Agent.__init__ in
        # relay_agent.py. `geheimnis=None`: der Client weist sich nicht
        # aus, das braucht er fuer `frage`/`frage_stueck`/`frage_fertig`
        # auch nicht (siehe transport.PhpTransport-Doku).
        self.transporte = []
        for t in aufbau.transporte:
            if t['art'] == 'php':
                obj = transport.PhpTransport(t['name'], t['basis'], None,
                                             VERSION)
            else:                                            # 'webdav'
                obj = transport.WebDavTransport(
                    t['name'], t['basis'], t['benutzer'],
                    t['passwort_datei'], timeout=t['timeout'])
            self.transporte.append(
                {'name': t['name'], 'rolle': t['rolle'], 'obj': obj})

        # Gesundheits-Gedaechtnis -- PERSISTENT (JSON-Datei), anders als
        # beim Agenten: Dieses Programm ist nach jedem Aufruf vorbei, der
        # Agent laeuft dauerhaft. Ohne Datei waere jeder Aufruf amnesisch.
        self.gesundheit = transport.lies_gesundheit(aufbau.gesundheit_datei)

    def _sichere_gesundheit(self):
        transport.schreibe_gesundheit(self.a.gesundheit_datei, self.gesundheit)

    def _naechster_frageweg(self):
        """Waehlt den Transportweg fuer den NAECHSTEN Versuch -- im Rundlauf
        unter den Wegen mit Rolle "frage"/"beide", die gerade nicht gesperrt
        sind. Der Zeiger steckt (wie die Gesundheit) im selben JSON, ist
        also PERSISTENT: Die Verteilung gilt ueber viele Aufrufe dieses
        Programms hinweg, nicht nur innerhalb eines einzigen.

        Damit rotiert auch eine WIEDERHOLUNG automatisch auf einen anderen
        Weg, wenn es Alternativen gibt -- ohne dass `frage()` das eigens
        verwalten muesste. Gibt es nur einen zulaessigen Weg (das
        urspruengliche Einzel-PHP-Setup), bleibt es exakt beim alten
        Verhalten: derselbe Weg, jedesmal.
        """
        kandidaten = [t for t in self.transporte
                      if t['rolle'] in ('frage', 'beide')
                      and self.gesundheit.verfuegbar(t['name'])]
        if not kandidaten:
            return None
        rundlauf = self.gesundheit.zustand.setdefault('_rundlauf', {})
        zeiger = int(rundlauf.get('wert', 0))
        rundlauf['wert'] = zeiger + 1
        return kandidaten[zeiger % len(kandidaten)]

    def frage(self, dienst, aktion, daten):
        """Ein vollstaendiger Vorgang, mit Wiederholung bei Ueberlastung UND
        Wechsel des Transportwegs zwischen den Versuchen.

        Ein einzelner Versuch kann scheitern, ohne dass etwas falsch waere:
        der Agent hat gerade nicht abgeholt, der gewaehlte Weg antwortete
        kurz nicht, ein Stueck kam trotz eigener Wiederholung nicht durch.
        Deshalb wird der GANZE Vorgang -- neue Frage, ggf. anderer Weg --
        mehrfach versucht, bevor aufgegeben wird. Das ist die letzte, grobe
        Schranke; die feinere liegt schon naeher am Fehler, im Transportweg
        selbst (siehe transport.py).

        Die MARKE entsteht HIER, einmal, und bleibt ueber alle Versuche
        gleich -- sie muss einen Transportwechsel ueberleben (siehe
        transport.PhpTransport.lege_frage).
        """
        letzter = None
        n = max(1, self.a.wiederholungen)
        marke = os.urandom(16).hex()
        for versuch in range(1, n + 1):
            weg = self._naechster_frageweg()
            self._sichere_gesundheit()
            if weg is None:
                letzter = ClientFehler(
                    'Kein Transportweg verfuegbar (alle gerade gesperrt).')
                if versuch < n:
                    time.sleep(3.0)
                continue
            try:
                return self._frage_einmal(weg, marke, dienst, aktion, daten)
            except ClientFehler as e:
                letzter = e
                if versuch < n:
                    time.sleep(3.0)
        if n == 1:
            raise letzter
        raise ClientFehler(
            'Fehlercode 1202. Die Aufgabe konnte nicht aufgrund einer '
            'Ueberlastung abgeschlossen werden. Bitte versuchen Sie es zu '
            'einem spaeteren Zeitpunkt erneut.\n'
            '  (Letzter Grund nach %d Versuchen: %s)' % (n, letzter))

    def _frage_einmal(self, weg, marke, dienst, aktion, daten):
        """Ein einzelner Versuch, ueber EINEN bestimmten Weg: fragen,
        warten, Antwort auspacken."""
        sitzung = None
        if self.a.verfahren == 'noise_ik':
            import krypto
            sitzung = krypto.HandshakeIK(True, PROLOG, self.a.privat,
                                         rs=self.a.agent)
            klartext = json.dumps({'dienst': dienst, 'aktion': aktion,
                                   'daten': daten},
                                  ensure_ascii=False).encode('utf-8')
            m1 = sitzung.schreibe_nachricht1(klartext)
            nutz = {'chiffre': base64.b64encode(m1).decode('ascii')}
        else:
            nutz = {'dienst': dienst, 'aktion': aktion, 'daten': daten}

        # Stueckelung (falls die Frage nicht in eine Nachricht passt) ist
        # Sache des Transportwegs selbst -- der PHP-Weg braucht sie
        # (transport.PhpTransport.lege_frage), WebDAV nicht (bis 12 MiB in
        # einem Rutsch gemessen, README.md).
        umschlag = {'v': VERSION, 'krypto': self.a.verfahren, 'marke': marke,
                    'teile': 1, 'nutzlast': nutz}
        ok, fehler = weg['obj'].lege_frage(marke, umschlag)
        if not ok:
            self.gesundheit.fehlschlag(weg['name'])
            self._sichere_gesundheit()
            raise ClientFehler('Frage abgewiesen ueber "%s": %s'
                               % (weg['name'], fehler))
        self.gesundheit.erfolg(weg['name'])
        self._sichere_gesundheit()

        umschlag, antwortweg = self._warte(marke)
        ergebnis = self._auspacken(marke, umschlag, sitzung, antwortweg)
        # Aufraeumen, sobald die Antwort erfolgreich ausgepackt ist --
        # siehe Kommentar bei Agent.bearbeite_marke in relay_agent.py
        # (dasselbe Problem, nur auf der Abholseite): beim PHP-Weg ein
        # No-Op, beim WebDAV-Weg noetig, sonst bleibt die Antwort fuer
        # immer liegen.
        antwortweg['obj'].loesche_antwort(marke)
        return ergebnis

    def _warte(self, marke):
        """Statisch abholen. Kein PHP, kein Kontingent -- der ganze Sinn.

        Klopft direkt nach `antwort_<marke>.json`, bei JEDEM Transportweg
        mit Rolle "antwort"/"beide" -- der Agent koennte auf einem anderen
        Weg geantwortet haben als dem, ueber den die Frage ging (siehe
        Agent._waehle_antwortweg in relay_agent.py). "Noch nicht da" ist
        dabei KEIN Fehler; nur ein echter Fehlschlag zaehlt gegen die
        Gesundheit des jeweiligen Wegs.

        (Der urspruengliche Client fragte stattdessen erst die
        Warteschlange, dann die Antwortdatei -- einzig wegen CORS im
        Browser-Portal, siehe transport.PhpTransport.hole_antwort. Das
        betrifft diesen Python-Client nicht.)
        """
        bis = time.time() + self.a.frist
        abstand = self.a.abstand
        kandidaten = [t for t in self.transporte
                      if t['rolle'] in ('antwort', 'beide')]
        while time.time() < bis:
            for t in kandidaten:
                if not self.gesundheit.verfuegbar(t['name']):
                    continue
                gefunden, umschlag, fehler = t['obj'].hole_antwort(marke)
                if gefunden:
                    self.gesundheit.erfolg(t['name'])
                    self._sichere_gesundheit()
                    return umschlag, t
                if fehler:
                    self.gesundheit.fehlschlag(t['name'])
                    self._sichere_gesundheit()
            time.sleep(abstand)
            abstand = min(1.5, abstand * 1.3)
        raise ClientFehler('Zeit abgelaufen -- keine Antwort binnen %.0f s'
                           % self.a.frist)

    def _pruefe_umschlag(self, u, marke, teil=None):
        if not isinstance(u, dict):
            raise ClientFehler('Umschlag ist kein Objekt')
        if u.get('v') != VERSION:
            raise ClientFehler('Protokollfassung %r, erwartet %d'
                               % (u.get('v'), VERSION))
        # DIE Pruefung gegen eine stille Umleitung.
        if u.get('marke') != marke:
            raise ClientFehler(
                'Marke weicht ab (%r statt %r) -- deutet auf eine Umleitung '
                'hin. CheckSpelling Off gesetzt?' % (u.get('marke'), marke))
        if teil is not None and u.get('teil') != teil:
            raise ClientFehler('Stuecknummer weicht ab (%r statt %d)'
                               % (u.get('teil'), teil))

    def _auspacken(self, marke, u, sitzung, antwortweg):
        self._pruefe_umschlag(u, marke)

        # Ein Rueckfall auf Klartext waere ein Angriff, kein Zufall: Wer die
        # Verschluesselung abschalten kann, indem er sie weglaesst, hat keine.
        if u.get('krypto') != self.a.verfahren:
            raise ClientFehler(
                'Antwort kam mit Verfahren %r, erwartet %r.\n'
                '  Das ist kein Rueckfall auf Klartext, den wir hinnehmen --\n'
                '  entweder stimmt die Konfiguration nicht, oder jemand hat\n'
                '  die Antwort ersetzt.' % (u.get('krypto'), self.a.verfahren))

        n = u.get('nutzlast') or {}
        teile = u.get('teile', 1)
        if teile > 1:
            inhalt = self._stuecke(antwortweg, marke, teile, n.get('stuecke'))
        elif self.a.verfahren == 'noise_ik':
            inhalt = n.get('chiffre', '')
        else:
            inhalt = n.get('inhalt', '')

        if self.a.verfahren != 'noise_ik':
            n = dict(n)
            n['inhalt'] = inhalt
            return n

        try:
            m2 = base64.b64decode(inhalt, validate=True)
        except (binascii.Error, ValueError):
            raise ClientFehler('Antwort ist kein gueltiges Base64')
        import krypto
        try:
            klartext = sitzung.lies_nachricht2(m2)
        except krypto.KryptoFehler:
            raise ClientFehler(
                'Antwort nicht entschluesselbar.\n'
                '  Sie stammt nicht von dem Agenten, dessen Schluessel in der\n'
                '  Konfiguration steht -- oder sie wurde unterwegs veraendert.')
        try:
            return json.loads(klartext.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise ClientFehler('Entschluesselte Antwort ist kein JSON')

    def _stuecke(self, antwortweg, marke, teile, liste):
        if not hasattr(antwortweg['obj'], 'hole_antwort_stueck'):
            # Stueckelung ist eine PHP-Eigenheit -- ueber WebDAV kann eine
            # gestueckelte Antwort gar nicht erst entstanden sein.
            raise ClientFehler(
                'Gestueckelte Antwort ueber "%s" -- dieser Weg stueckelt '
                'nicht.' % antwortweg['name'])
        if not isinstance(liste, list) or len(liste) != teile:
            raise ClientFehler('Verzeichnis nennt %s Stuecke, angekuendigt %d'
                               % (len(liste) if isinstance(liste, list) else '?',
                                  teile))
        teil = [None] * teile
        for e in liste:
            # Der Dateiname wird GELESEN, nie gebaut. Er traegt vier
            # abgeleitete Zeichen, damit benachbarte Stuecke nicht eine
            # Zeichenaenderung auseinanderliegen -- sonst haelt mod_speling
            # sie fuer Tippfehler.
            datei = e.get('datei', '') if isinstance(e, dict) else ''
            nr = e.get('teil') if isinstance(e, dict) else None
            if not isinstance(datei, str) or '/' in datei or '\\' in datei \
                    or not datei.startswith('antwort_'):
                raise ClientFehler('Stueck mit unbrauchbarem Dateinamen')
            ok, roh, grund = antwortweg['obj'].hole_antwort_stueck(datei)
            if not ok:
                raise ClientFehler('Stueck %s: %s' % (nr, grund))
            try:
                s = json.loads(roh.decode('utf-8'))
            except ValueError:
                raise ClientFehler('Stueck %s ist kein JSON' % nr)
            self._pruefe_umschlag(s, marke, teil=nr)
            if s.get('teile') != teile:
                raise ClientFehler('Stueck %s nennt %r Stuecke statt %d'
                                   % (nr, s.get('teile'), teile))
            if not isinstance(nr, int) or not 0 <= nr < teile:
                raise ClientFehler('Stueck mit unbrauchbarer Nummer %r' % (nr,))
            teil[nr] = s.get('nutzlast', '')
        if any(t is None for t in teil):
            raise ClientFehler('Es fehlt ein Stueck')
        return ''.join(teil)


# ------------------------------------------------------------------ main

def _menschlich(b):
    if b < 1024:
        return '%d B' % b
    if b < 1048576:
        return '%.1f KiB' % (b / 1024.0)
    return '%.1f MiB' % (b / 1048576.0)


def _summe(pfad):
    """SHA-256 der ganzen Datei, ohne sie in den Speicher zu nehmen."""
    h = hashlib.sha256()
    with open(pfad, 'rb') as f:
        for s in iter(lambda: f.read(1 << 20), b''):
            h.update(s)
    return h.hexdigest()


def lege_in_bloecken(klient, dienst, quelle, ziel, laut=True):
    """Eine Datei jeder Groesse hinauflegen.

    Eine Datei geht ueber beliebig viele Fragen. Der Agent haengt die
    Bloecke an eine Teildatei und legt sie erst ab, wenn die Pruefsumme
    des GANZEN stimmt -- sonst waere eine abgebrochene Uebertragung von
    einer vollstaendigen nicht zu unterscheiden.

    Die Pruefsumme wird VORHER berechnet, in einem eigenen Durchlauf.
    Zweimal lesen ist billiger, als die ganze Datei im Speicher zu halten;
    bei einer 4-GiB-Datei ist es der Unterschied zwischen laeuft und
    laeuft nicht.
    """
    gesamt = os.path.getsize(quelle)
    bloecke = max(1, (gesamt + SCHREIB_BLOCK - 1) // SCHREIB_BLOCK)
    marke = os.urandom(16).hex()
    summe = _summe(quelle)

    with open(quelle, 'rb') as f:
        for i in range(bloecke):
            teil = f.read(SCHREIB_BLOCK)
            daten = {
                'uebertragung': marke, 'block': i, 'bloecke': bloecke,
                'inhalt_typ': 'base64',
                'inhalt': base64.b64encode(teil).decode('ascii'),
            }
            # Der Pfad nur beim ersten Block. Danach steht er beim Agenten
            # fest -- ihn erneut mitzuschicken waere eine zweite Wahrheit.
            if i == 0:
                daten['pfad'] = ziel
            if i == bloecke - 1:
                daten['sha256'] = summe
            antw = klient.frage(dienst, 'lege_block', daten)
            if not antw.get('gefunden'):
                raise ClientFehler('Block %d/%d abgewiesen: %s'
                                   % (i + 1, bloecke,
                                      antw.get('grund', '')))
            if laut and bloecke > 1:
                sys.stderr.write('\r  Block %d/%d  (%s)          '
                                 % (i + 1, bloecke, _menschlich(
                                     min((i + 1) * SCHREIB_BLOCK, gesamt))))
                sys.stderr.flush()
    if laut and bloecke > 1:
        sys.stderr.write('\r' + ' ' * 46 + '\r')
        sys.stderr.flush()
    return json.loads(antw.get('inhalt', '{}'))


def hole_in_bloecken(klient, dienst, pfad, ziel, laut=True):
    """Eine Datei jeder Groesse herunterholen.

    Der erste Umlauf fragt gleich Daten UND Pruefsumme. Bei einer kleinen
    Datei ist er damit der einzige -- ein getrennter Vorablauf nur fuer die
    Groesse waere bei jeder Notiz ein zweiter Umlauf durch den Tunnel, und
    ein Umlauf kostet hier zwei Sekunden.
    """
    tmp = ziel + '.' + os.urandom(4).hex() + '.teil'
    gesamt = None
    stand = None
    summe = None
    von = 0
    try:
        with open(tmp, 'wb') as aus:
            while gesamt is None or von < gesamt:
                rest = None if gesamt is None else gesamt - von
                laenge = LESE_BLOCK if rest is None \
                    else min(LESE_BLOCK, rest)
                d = {'pfad': pfad, 'von': von, 'laenge': laenge}
                # Pruefsumme beim ERSTEN Zug mitnehmen: dann ist eine
                # kleine Datei nach einem Umlauf fertig und geprueft.
                if gesamt is None or rest <= laenge:
                    d['pruefsumme'] = True
                antw = klient.frage(dienst, 'hole', d)
                if not antw.get('gefunden'):
                    raise ClientFehler(antw.get('grund', 'nichts gefunden'))
                a = json.loads(antw.get('inhalt', '{}'))

                if gesamt is None:
                    gesamt = int(a.get('gesamt', 0))
                    stand = a.get('stand')
                elif a.get('stand') != stand:
                    # Die Datei hat sich waehrend des Holens geaendert.
                    # Weitermachen hiesse, Stuecke aus zwei Fassungen
                    # zusammenzusetzen -- jedes fuer sich gueltig, das
                    # Ganze falsch, und niemandem faellt es auf.
                    raise ClientFehler(
                        'Die Datei hat sich waehrend des Holens geaendert. '
                        'Abgebrochen -- nichts geschrieben.')
                if a.get('sha256'):
                    summe = a['sha256']

                stueck = base64.b64decode(a.get('inhalt', ''))
                if not stueck and von < gesamt:
                    raise ClientFehler('leerer Block bei %d von %d'
                                       % (von, gesamt))
                aus.write(stueck)
                von += len(stueck)
                if laut and gesamt > LESE_BLOCK:
                    sys.stderr.write('\r  %s von %s          '
                                     % (_menschlich(von),
                                        _menschlich(gesamt)))
                    sys.stderr.flush()
        if laut and gesamt and gesamt > LESE_BLOCK:
            sys.stderr.write('\r' + ' ' * 40 + '\r')
            sys.stderr.flush()

        if summe and _summe(tmp) != summe:
            raise ClientFehler('Pruefsumme stimmt nicht -- nichts behalten.')
        os.replace(tmp, ziel)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return gesamt or 0


def _zeige_liste(a):
    d = json.loads(a.get('inhalt', '{}'))
    for e in d.get('eintraege', []):
        if e.get('art') == 'ordner':
            print('  %-50s  <Ordner>' % e.get('name', ''))
        else:
            print('  %-50s  %10d Bytes' % (e.get('name', ''), e.get('bytes', 0)))
    # Warum die Liste kuerzer sein kann, als der Ordner Eintraege hat. Eine
    # unvollstaendige Liste, die wie eine vollstaendige aussieht, ist
    # schlimmer als eine Fehlermeldung.
    if d.get('gekappt'):
        print('')
        print('  ACHTUNG: nur die ersten %d Eintraege. Der Ordner enthaelt mehr.'
              % d['gekappt'])
    if d.get('endung_gesperrt'):
        print('  %d Datei(en) nicht gezeigt -- Endung nicht freigegeben.'
              % d['endung_gesperrt'])
    if d.get('versteckt'):
        print('  %d versteckte Eintraege ausgelassen.' % d['versteckt'])


def main():
    ap = argparse.ArgumentParser(description='AHPT Cloud -- Client')
    ap.add_argument('--konfig', default='client.toml')
    ap.add_argument('--dienst', default='dateien')
    unter = ap.add_subparsers(dest='befehl', required=True)
    p = unter.add_parser('liste', help='Ordner auflisten')
    p.add_argument('pfad', nargs='?', default='')
    p = unter.add_parser('hole', help='Datei holen')
    p.add_argument('pfad')
    p.add_argument('--nach', help='Zieldatei (sonst nach stdout bzw. Basisname)')
    p = unter.add_parser('lege', help='Datei auf den Heimserver legen')
    p.add_argument('datei', help='oertliche Datei')
    p.add_argument('--nach', help='Zielpfad auf dem Server (sonst Basisname)')
    p = unter.add_parser('ordner', help='Ordner auf dem Heimserver anlegen')
    p.add_argument('pfad')
    a = ap.parse_args()

    try:
        klient = Client(Aufbau(lies_konfig(a.konfig), a.konfig))
    except ClientFehler as e:
        print('ABBRUCH: %s' % e, file=sys.stderr)
        return 2

    if klient.a.verfahren != 'noise_ik':
        print('HINWEIS: unverschluesselt. Alles, was jetzt durch den Kanal',
              file=sys.stderr)
        print('         geht, liegt fuer jeden lesbar auf dem Webspace.',
              file=sys.stderr)

    try:
        if a.befehl == 'liste':
            antw = klient.frage(a.dienst, 'liste', {'pfad': a.pfad})
            if not antw.get('gefunden'):
                print('nichts gefunden: %s' % antw.get('grund', ''), file=sys.stderr)
                return 1
            _zeige_liste(antw)
            return 0

        if a.befehl == 'ordner':
            antw = klient.frage(a.dienst, 'neuer_ordner', {'pfad': a.pfad})
            if not antw.get('gefunden'):
                print('nicht angelegt: %s' % antw.get('grund', ''),
                      file=sys.stderr)
                return 1
            print('angelegt: %s' % antw.get('titel', a.pfad))
            return 0

        if a.befehl == 'lege':
            if not os.path.isfile(a.datei):
                print('ABBRUCH: %s gibt es nicht.' % a.datei, file=sys.stderr)
                return 2
            gesamt = os.path.getsize(a.datei)
            ziel = a.nach or os.path.basename(a.datei)
            bloecke = max(1, (gesamt + SCHREIB_BLOCK - 1) // SCHREIB_BLOCK)
            print('%s  ->  %s   (%s%s)'
                  % (a.datei, ziel, _menschlich(gesamt),
                     '' if bloecke == 1 else ', %d Bloecke' % bloecke))
            d = lege_in_bloecken(klient, a.dienst, a.datei, ziel)
            # Der Server nennt den Namen, unter dem die Datei WIRKLICH liegt.
            # Er kann abweichen: ueberschrieben wird nie, stattdessen zaehlt
            # der Agent hoch. Wer das verschweigt, laesst den Nutzer glauben,
            # er habe eine aeltere Fassung ersetzt.
            print('abgelegt als: %s  (%s)'
                  % (d.get('abgelegt', '?'),
                     _menschlich(int(d.get('bytes', 0)))))
            if d.get('abgelegt') and d['abgelegt'] != ziel:
                print('  HINWEIS: umbenannt -- unter %s lag schon etwas.' % ziel)
            return 0

        ziel = a.nach or os.path.basename(a.pfad) or 'ahpt-datei'
        if os.path.exists(ziel):
            # Nicht ueberschreiben. Ein Client, der ungefragt ersetzt, ist
            # einmal zu oft ein Datenverlust.
            print('ABBRUCH: %s gibt es schon.' % ziel, file=sys.stderr)
            return 2
        n = hole_in_bloecken(klient, a.dienst, a.pfad, ziel)
        print('%s  (%s)' % (ziel, _menschlich(n)))
        return 0
    except ClientFehler as e:
        print('FEHLER: %s' % e, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
