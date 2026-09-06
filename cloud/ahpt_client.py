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
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)

VERSION = 1
PROLOG = b'AHPT-Privat/1'
KENNUNG = 'AHPT-Privat-Client/1'

# Muessen zu relay.php passen. Weichen sie ab, weist der Vermittler ab -- was
# der Client zwar meldet, aber erst nach dem halben Hochladen.
MAX_FRAGE       = 4096
MAX_STUECK      = 49152
MAX_FRAGE_TEILE = 160

# Wieviel Nutzdatei in EINE Frage passt.
#
# 160 Stuecke a 49152 Zeichen sind 7,5 MiB Base64-Geheimtext, also 5,6 MiB
# Geheimtext, also nach Abzug von Siegel und JSON-Huelle rund 4,2 MiB Datei.
# 3 MiB laesst Luft und ist eine Zahl, die man im Kopf behaelt.
#
# Diese Grenze ist die des VERMITTLERS und bleibt: Fragestuecke darf jeder
# ablegen, der die Adresse kennt. Sie begrenzt nicht mehr die Dateigroesse,
# denn eine Datei geht ueber beliebig viele Fragen.
SCHREIB_BLOCK   = 3 * 1024 * 1024

# Groesster Ausschnitt, den der Agent je Antwort liefert (siehe
# handler/datei.py, LESE_BLOCK). Muss dazu passen, sonst weist er ab.
LESE_BLOCK      = 4 * 1024 * 1024

# Gemessen 05./06.09.2026 gegen bplaced: Unter Last weist das PHP-Kontingent
# ein einzelnes Stueck gelegentlich ab, ohne dass Absender oder Inhalt falsch
# waeren -- dieselbe Gleichzeitigkeitsgrenze wie bei IONOS. Ein Stueck
# deshalb sofort aufzugeben, wirft die ganze Uebertragung wegen eines
# einzelnen Ausrutschers weg.
STUECK_WIEDERHOLUNGEN = 5

# Wie oft ein GANZER Vorgang (neue Marke, neue Frage) versucht wird, bevor
# aufgegeben wird -- fuer den Fall, dass der Agent gar nicht erst antwortet,
# nicht nur ein einzelnes Stueck ablehnt.
FRAGE_WIEDERHOLUNGEN = 3


class ClientFehler(Exception):
    pass


# ------------------------------------------------------------------- Netz

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
    req = urllib.request.Request(url, method='GET')
    req.add_header('User-Agent', KENNUNG)
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
    req.add_header('User-Agent', KENNUNG)
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
    def __init__(self, roh):
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

    def frage(self, dienst, aktion, daten):
        """Ein vollstaendiger Vorgang, mit Wiederholung bei Ueberlastung.

        Ein einzelner Versuch kann scheitern, ohne dass etwas falsch waere:
        der Agent hat gerade nicht abgeholt, die Warteschlange antwortete
        kurz nicht, ein Stueck kam trotz eigener Wiederholung nicht durch.
        Deshalb wird der GANZE Vorgang -- neue Marke, neue Frage -- mehrfach
        versucht, bevor aufgegeben wird. Das ist die letzte, grobe Schranke;
        die feinere liegt schon naeher am Fehler, in `_hochladen()`.
        """
        letzter = None
        n = max(1, self.a.wiederholungen)
        for versuch in range(1, n + 1):
            try:
                return self._frage_einmal(dienst, aktion, daten)
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

    def _frage_einmal(self, dienst, aktion, daten):
        """Ein einzelner Versuch: fragen, warten, Antwort auspacken."""
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

        # Passt die Frage in eine Nachricht? Beim Hochladen tut sie das
        # nicht -- dann geht zuerst nur das Verzeichnis hinaus, danach die
        # Stuecke, und erst zum Schluss wird die Marke sichtbar. Dieselbe
        # Reihenfolge wie bei der Antwort, aus demselben Grund: Eine
        # Warteschlange, die auf Luecken zeigt, ist schlimmer als eine leere.
        gross = (self.a.verfahren == 'noise_ik'
                 and len(nutz.get('chiffre', '')) > MAX_FRAGE)
        if not gross:
            code, d = _sende(self.a.basis + '/relay.php?action=frage',
                             {'v': VERSION, 'krypto': self.a.verfahren,
                              'nutzlast': nutz})
            if code != 200 or not d.get('ok'):
                raise ClientFehler('Frage abgewiesen (HTTP %s): %s'
                                   % (code, d.get('fehler', '')))
            marke = d.get('marke', '')
        else:
            marke = self._hochladen(nutz['chiffre'])

        if not isinstance(marke, str) or len(marke) != 32:
            raise ClientFehler('Vermittler gab keine gueltige Marke')

        umschlag = self._warte(marke)
        return self._auspacken(marke, umschlag, sitzung)

    def _hochladen(self, chiffre, fortschritt=None):
        """Eine grosse Frage in Stuecken hinaufbringen.

        Verschluesselt wird VORHER, als ein Stueck -- geteilt wird erst der
        fertige Geheimtext. Andersherum waere jedes Stueck fuer sich
        gueltig, und ein Angreifer koennte sie umsortieren oder eines
        weglassen, ohne dass etwas auffiele. So macht jede Aenderung das
        Ganze unbrauchbar.
        """
        # Mindestens 2 Stuecke -- nicht nur "mind. 1". Der Vermittler
        # akzeptiert die leere Ankuendigungs-Nutzlast unten nur bei
        # `teile > 1`; bei genau 1 Stueck landet die leere Nutzlast in der
        # normalen Pruefung und scheitert dort, weil leer kein gueltiges
        # Base64 ist. Trifft jede Chiffre zwischen MAX_FRAGE (4096 B) und
        # MAX_STUECK (49152 B). Am 05.09.2026 im Portal (ahpt.js) live
        # gefunden und hier gleich mitgezogen -- derselbe Fehler war
        # identisch auch hier.
        teile = max(2, (len(chiffre) + MAX_STUECK - 1) // MAX_STUECK)
        if teile > MAX_FRAGE_TEILE:
            # Das ist jetzt ein FEHLER IM CLIENT, keine Auskunft an den
            # Nutzer: Wer Dateien ablegt, teilt sie vorher in Bloecke von
            # SCHREIB_BLOCK. Kommt hier trotzdem etwas zu Grosses an, hat
            # ein Aufrufer das Teilen vergessen -- und dann soll die Meldung
            # das sagen, statt dem Nutzer seine Datei vorzuwerfen.
            raise ClientFehler(
                'Frage zu gross: %d Stuecke, der Vermittler nimmt %d.\n'
                '  Das ist kein Problem der Datei -- eine Frage wurde nicht\n'
                '  in Bloecke geteilt. Dateien gehen ueber `lege_block`.'
                % (teile, MAX_FRAGE_TEILE))

        code, d = _sende(self.a.basis + '/relay.php?action=frage',
                         {'v': VERSION, 'krypto': self.a.verfahren,
                          'teile': teile, 'nutzlast': {'chiffre': ''}},
                         timeout=30)
        if code != 200 or not d.get('ok'):
            raise ClientFehler('Hochladen abgewiesen (HTTP %s): %s'
                               % (code, d.get('fehler', '')))
        marke = d.get('marke', '')
        if not isinstance(marke, str) or len(marke) != 32:
            raise ClientFehler('Vermittler gab keine gueltige Marke')

        # Schnittgroesse aus der (ggf. angehobenen) Stueckzahl ableiten,
        # NICHT umgekehrt in feste MAX_STUECK-Bloecke schneiden -- sonst
        # waere bei einer kurzen Chiffre und teile=2 das zweite Stueck
        # leer, und leer scheitert bei `frage_stueck` an derselben
        # Pruefung, nur eine Ebene tiefer.
        stueckgroesse = -(-len(chiffre) // teile)  # Ganzzahl-Aufrundung
        for i in range(teile):
            stueck = chiffre[i * stueckgroesse:(i + 1) * stueckgroesse]
            for versuch in range(1, STUECK_WIEDERHOLUNGEN + 1):
                code, d = _sende(self.a.basis + '/relay.php?action=frage_stueck',
                                 {'v': VERSION, 'krypto': self.a.verfahren,
                                  'marke': marke, 'teil': i, 'teile': teile,
                                  'nutzlast': stueck}, timeout=30)
                if code == 200 and d.get('ok'):
                    break
                if versuch < STUECK_WIEDERHOLUNGEN:
                    time.sleep(min(5.0, 0.5 * (2 ** (versuch - 1))))
            else:
                raise ClientFehler(
                    'Stueck %d/%d abgewiesen nach %d Versuchen (HTTP %s): %s'
                    % (i + 1, teile, STUECK_WIEDERHOLUNGEN, code,
                       d.get('fehler', '')))
            if fortschritt:
                fortschritt(i + 1, teile)

        # Erst jetzt sichtbar machen. Der Vermittler sieht dabei selbst nach,
        # ob wirklich alle Stuecke daliegen.
        code, d = _sende(self.a.basis + '/relay.php?action=frage_fertig',
                         {'v': VERSION, 'krypto': self.a.verfahren,
                          'marke': marke, 'teile': teile}, timeout=30)
        if code != 200 or not d.get('ok'):
            raise ClientFehler('Abschluss abgewiesen (HTTP %s): %s'
                               % (code, d.get('fehler', '')))
        return marke

    def _warte(self, marke):
        """Statisch abholen. Kein PHP, kein Kontingent -- der ganze Sinn.

        Gewartet wird auf die WARTESCHLANGE, nicht durch wiederholtes Fragen
        nach der Antwortdatei. Sie nennt in `fertig` die Marken, deren
        Antwort bereitliegt; der Vermittler schreibt beides unter derselben
        Sperre.

        Der Grund steht ausfuehrlich im Portal (`portal/ahpt.js`): Dort
        scheiterte das direkte Fragen an CORS, weil ein 404 vom Hoster ohne
        die noetige Kopfzeile kommt. Hier waere das gleichgueltig -- Python
        kennt keine CORS-Pruefung -- aber ZWEI Wartelogiken fuer dasselbe
        waeren die Sorte Doppelung, an der in diesem Projekt schon mehrere
        Fehler gestorben sind.
        """
        bis = time.time() + self.a.frist
        abstand = self.a.abstand
        while time.time() < bis:
            code, roh = _hole('%s/ahpt/warteschlange.json' % self.a.basis)
            if code == 200:
                try:
                    q = json.loads(roh.decode('utf-8'))
                except ValueError:
                    q = {}
                if marke in (q.get('fertig') or []):
                    code, roh = _hole('%s/ahpt/antwort_%s.json'
                                      % (self.a.basis, marke))
                    if code != 200:
                        raise ClientFehler(
                            'Die Warteschlange meldet die Antwort als fertig, '
                            'aber der Abruf ergab HTTP %s.' % code)
                    try:
                        return json.loads(roh.decode('utf-8'))
                    except ValueError:
                        raise ClientFehler('Antwort ist kein JSON')
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

    def _auspacken(self, marke, u, sitzung):
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
            inhalt = self._stuecke(marke, teile, n.get('stuecke'))
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

    def _stuecke(self, marke, teile, liste):
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
            code, roh = _hole('%s/ahpt/%s' % (self.a.basis, datei))
            if code != 200:
                raise ClientFehler('Stueck %s: HTTP %s' % (nr, code))
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
        klient = Client(Aufbau(lies_konfig(a.konfig)))
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
