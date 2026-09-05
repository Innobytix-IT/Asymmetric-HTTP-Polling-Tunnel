#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
relay_agent.py -- AHPT/1, die Heimseite. Transport, sonst nichts.

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Der Heimserver steht hinter DS-Lite, CGNAT oder einer strengen Firewall und
ist von aussen nicht erreichbar. Dieser Agent dreht die Richtung um: Er baut
jede Verbindung selbst auf, nach draussen, und holt sich Arbeit ab.

    Warteschlange holen  ->  statisch, If-None-Match, meist HTTP 304
    Frage holen          ->  statisch
    Handler fragen       ->  bleibt im Haus
    Antwort ablegen      ->  PHP (der einzige teure Schritt)

Kein offener Port, kein DynDNS, kein Zertifikat, kein VPS.

WAS DIESE DATEI NICHT MEHR KENNT
---------------------------------
kiwix. Archive. Suchtreffer. Artikeltexte. In `tunnel_agent.py` stand das
alles hier drin -- richtig, solange es genau einen Dienst gab. Jetzt steht
es in `handler/kiwix.py`, und diese Datei koennte nicht sagen, was ein
Archiv ist.

Was sie dafuer kennt und woanders nicht steht: Protokollfassung, Marke,
Deckel, Stueckelung, 503-Wiederholung, bedingte Abrufe.

DIE GRENZE, DIE HIER VERLAEUFT
-------------------------------
Der Kern ist INHALTSBLIND. Der Handler ist NICHT UEBERREDBAR. Nur das erste
wurde beim Verallgemeinern aufgegeben.

Konkret heisst das: Diese Datei prueft Fassung, Marke, Form und Deckel und
schaut nach, ob der genannte Dienst in der `config.toml` steht. Was ein
gueltiger Suchbegriff oder ein gueltiger Dateipfad ist, entscheidet
ausschliesslich der Handler -- der Kern koennte es nicht wissen, und genau
das soll er auch nicht.

Von aussen kommt nie eine Adresse, nie ein Befehl, nie eine Faehigkeit.
Immer nur ein NAME aus einer Liste, die zu Hause steht.

KEIN STILLER FEHLSCHLAG
-----------------------
Jede Fehlerart wird gezaehlt und beim ersten Mal je Grund einmal genannt.
Im gesunden Betrieb sind alle Fehlerzaehler 0. Ein Werkzeug, das im
Normalbetrieb Fehler meldet, wird nach dem zweiten Mal ignoriert -- und
findet danach auch die echten nicht mehr.

Aufruf:
    python3 relay_agent.py --konfig config.toml
    python3 relay_agent.py --konfig config.toml --selbsttest   (ohne Netz)
"""

import argparse
import json
import os
import re
import sys
import time

import handler as handler_paket
import netz

VERSION = 1

# Muessen zu den Konstanten in relay.php passen. Weichen sie ab, weist der
# Vermittler mit 413 ab -- was der Agent zwar meldet, aber erst im Betrieb.
MAX_STUECK      = 49152     # Bytes je Stueck, dekodiert
MAX_JSON        = 60000     # Bytes je POST-Rumpf, damit MAX_RUMPF (65536) haelt
MAX_TEILE       = 256
FRAGE_MAX_ALTER = 110       # s -- knapp unter MARKE_TTL (120) in relay.php
GEDAECHTNIS     = 600       # s -- so lange erinnern wir uns an erledigte Marken
POLL_VORGABE    = 1.0

# Spaetestens nach so vielen Sekunden wird die Warteschlange UNBEDINGT
# geholt, ohne If-None-Match.
#
# Der Grund ist gemessen, nicht vorsorglich. Apache bildet den ETag
# standardmaessig aus Aenderungszeit in ganzen SEKUNDEN und Groesse. Zwei
# Warteschlangen mit je EINEM Eintrag sind exakt gleich lang -- Marke und
# Zeitstempel haben feste Breite. Wird eine Frage beantwortet und trifft in
# derselben Sekunde die naechste ein, ohne dass der Agent den leeren
# Zwischenstand gesehen hat, traegt die neue Datei denselben ETag wie die
# alte. Der Agent bekommt 304 und uebersieht die Frage -- und weil die Datei
# danach nicht mehr angefasst wird, bekommt er bei jedem weiteren Abruf
# wieder 304. Die Frage bliebe bis zum Verfall unbeantwortet, waehrend der
# Besucher wartet.
#
# Der unbedingte Abruf traegt OHNE jede Serverkonfiguration. Er kostet alle
# 30 Sekunden eine statische Datei von wenigen hundert Bytes -- gemessen an
# 30 kostenlosen 304ern ist das nichts, und es ist der Preis dafuer, dass
# kein Fehler von einer .htaccess abhaengt.
UNBEDINGT_NACH  = 30

ZAEHLER = {}
_GENANNT = set()


def log(*t):
    print(time.strftime('[%H:%M:%S]'), *t, flush=True)


def zaehle(name):
    ZAEHLER[name] = ZAEHLER.get(name, 0) + 1


def einmal(grund, *t):
    """Jeden Grund genau einmal melden, aber jeden mindestens einmal."""
    if grund not in _GENANNT:
        _GENANNT.add(grund)
        log(*t)


class KonfigFehler(handler_paket.KonfigFehler):
    pass


# ------------------------------------------------------------- Konfiguration

def lies_konfig(pfad):
    """Liest config.toml (bevorzugt) oder config.json.

    TOML statt YAML, weil `tomllib` seit Python 3.11 in der
    Standardbibliothek liegt. YAML braeuchte PyYAML -- eine Abhaengigkeit
    ausgerechnet fuer die Datei, die jeder Nutzer als erstes anfasst. Und
    YAML ist an den Raendern ueberraschend: Einrueckung, `no` als
    Wahrheitswert, mehrdeutige Zeichenketten. Eine Konfigurationsdatei, die
    sich anders liest als sie aussieht, erzeugt genau die stillen
    Fehlschlaege, gegen die hier sonst ueberall Vorkehrungen stehen.

    Fuer Python 3.8 bis 3.10 gibt es dieselbe Struktur als JSON. Der Agent
    sagt beim Start, welchen Weg er genommen hat -- offenlassen waere
    schlechter als beides.
    """
    if not os.path.isfile(pfad):
        raise KonfigFehler('Konfiguration nicht gefunden: %s' % pfad)

    if pfad.endswith('.toml'):
        try:
            import tomllib
        except ImportError:
            raise KonfigFehler(
                'Dieses Python (%d.%d) bringt kein tomllib mit -- das gibt es\n'
                '         erst ab 3.11. Zwei Wege:\n'
                '           1. dieselbe Struktur als config.json ablegen und\n'
                '              --konfig config.json angeben (kein Nachinstallieren)\n'
                '           2. auf Python 3.11 oder neuer wechseln'
                % (sys.version_info[0], sys.version_info[1]))
        with open(pfad, 'rb') as f:
            try:
                return tomllib.load(f), 'tomllib'
            except Exception as e:
                raise KonfigFehler('config.toml ist nicht lesbar: %s' % e)

    if pfad.endswith('.json'):
        with open(pfad, 'r', encoding='utf-8') as f:
            try:
                return json.load(f), 'json'
            except Exception as e:
                raise KonfigFehler('config.json ist nicht lesbar: %s' % e)

    raise KonfigFehler('Endung nicht erkannt: %s (erwartet .toml oder .json)' % pfad)


class Aufbau:
    """Die geprueften Angaben aus der Konfiguration, samt fertiger Handler.

    ALLES wird hier geprueft, beim Start. Ein Agent, der mit halber
    Konfiguration anlaeuft, antwortet auf jede Frage "nichts gefunden" --
    und das sieht von aussen genauso aus wie ein leerer Dienst.
    """

    def __init__(self, roh, herkunft):
        self.herkunft = herkunft

        r = roh.get('relay')
        if not isinstance(r, dict):
            raise KonfigFehler('Abschnitt [relay] fehlt.')

        self.basis = str(r.get('basis', '')).rstrip('/')
        if not self.basis:
            raise KonfigFehler('[relay] basis fehlt.')
        if not netz.basis_erlaubt(self.basis):
            raise KonfigFehler(
                '[relay] basis muss https sein: %r\n'
                '         Ueber http reist das Geheimnis im Klartext mit, und\n'
                '         jeder Zwischenknoten liest es. Ausnahme ist allein\n'
                '         Loopback (127.0.0.1, localhost, ::1) -- dort verlaesst\n'
                '         nichts den Rechner. Das ist keine Testklappe: ein\n'
                '         echter Webspace ist nie Loopback, die Regel laesst sich\n'
                '         also nicht versehentlich in den Betrieb tragen.'
                % self.basis)

        gd = r.get('geheimnis_datei')
        if not gd:
            raise KonfigFehler('[relay] geheimnis_datei fehlt.')
        self.geheimnis_datei = os.path.expanduser(str(gd))

        self.poll_abstand = float(r.get('poll_abstand', POLL_VORGABE))
        if not 0.2 <= self.poll_abstand <= 60:
            raise KonfigFehler('[relay] poll_abstand muss zwischen 0.2 und 60 '
                               'liegen (ist %s).' % self.poll_abstand)

        # Einstellbar, damit die Pruefungen das Netz auch wirklich spannen
        # koennen. Im Betrieb bleibt es bei 30 s -- siehe UNBEDINGT_NACH.
        self.unbedingt_nach = float(r.get('unbedingt_nach', UNBEDINGT_NACH))
        if not 1 <= self.unbedingt_nach <= 3600:
            raise KonfigFehler('[relay] unbedingt_nach muss zwischen 1 und 3600 '
                               'liegen (ist %s).' % self.unbedingt_nach)

        dienste = roh.get('dienst')
        if not isinstance(dienste, list) or not dienste:
            raise KonfigFehler(
                'Kein [[dienst]] in der Konfiguration.\n'
                '         Ein Agent ohne Dienst antwortet auf jede Frage\n'
                '         "nichts gefunden" -- das ist schlechter als gar keiner,\n'
                '         weil es wie ein leerer Dienst aussieht.')

        self.dienste = {}
        for d in dienste:
            if not isinstance(d, dict):
                raise KonfigFehler('[[dienst]] ist kein Abschnitt.')
            name = d.get('name')
            # Dieselbe Form wie in relay.php. Der Name reist ueber die
            # Leitung; er darf unter keinen Umstaenden in einen Dateinamen
            # oder Pfad ausbrechen koennen.
            if not isinstance(name, str) \
                    or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', name):
                raise KonfigFehler(
                    '[[dienst]] name %r passt nicht zu ^[a-z][a-z0-9_]{0,31}$'
                    % (name,))
            if name in self.dienste:
                raise KonfigFehler(
                    'Dienst "%s" ist zweimal angegeben. Welcher gemeint ist,\n'
                    '         soll nicht von der Reihenfolge in einer Textdatei\n'
                    '         abhaengen.' % name)

            art = d.get('art')
            klasse = handler_paket.lade(art)      # wirft, wenn etwas fehlt
            h = klasse(d)                         # prueft die eigene Konfig

            erlaubt = d.get('aktionen')
            if erlaubt is None:
                erlaubt = sorted(klasse.AKTIONEN)
            if not isinstance(erlaubt, list) or not erlaubt:
                raise KonfigFehler('Dienst "%s": `aktionen` ist leer.' % name)
            unbekannt = set(erlaubt) - set(klasse.AKTIONEN)
            if unbekannt:
                raise KonfigFehler(
                    'Dienst "%s": Aktion(en) %s kennt der Handler "%s" nicht.\n'
                    '         Er kennt: %s'
                    % (name, ', '.join(sorted(unbekannt)), art,
                       ', '.join(sorted(klasse.AKTIONEN))))

            # Die Weissliste ist der Schnitt aus dem, was der Handler kann,
            # und dem, was die Konfiguration freigibt. Nie die Vereinigung.
            self.dienste[name] = (h, frozenset(erlaubt))

    def geheimnis(self):
        with open(self.geheimnis_datei, 'r', encoding='utf-8') as f:
            g = f.read().strip()
        if len(g) < 16:
            raise KonfigFehler('Geheimnis zu kurz (%d Zeichen, mindestens 16).'
                               % len(g))
        return g


# ------------------------------------------------------------- Stueckelung

def zerlege(text, max_bytes=MAX_STUECK, max_json=MAX_JSON):
    """Teilt eine Zeichenkette in uebertragbare Stuecke.

    ZWEI Grenzen, nicht eine, und das ist kein Uebereifer:

      max_bytes   misst der Vermittler am DEKODIERTEN Inhalt (MAX_STUECK).
      max_json    ist der ganze POST-Rumpf (MAX_RUMPF).

    Die beiden laufen auseinander, sobald Text Anfuehrungszeichen,
    Rueckwaertsschraegstriche oder Steuerzeichen enthaelt: JSON verdoppelt
    sie, Steuerzeichen werden sechsfach lang. Ein Stueck, das die erste
    Grenze haelt, kann die zweite reissen -- und dann kommt HTTP 413 zurueck,
    im Betrieb und nicht im Test.

    Geschnitten wird an Zeichengrenzen, nie an Byte-Grenzen: Eine in der
    Mitte zerschnittene UTF-8-Folge waere in beiden Haelften unlesbar.
    """
    if not text:
        return ['']
    stuecke = []
    i, n = 0, len(text)
    while i < n:
        j = min(n, i + max_bytes)
        while j > i + 1:
            teil = text[i:j]
            b  = len(teil.encode('utf-8'))
            jb = len(json.dumps(teil, ensure_ascii=False).encode('utf-8'))
            if b <= max_bytes and jb <= max_json:
                break
            # Verhaeltnismaessig verkleinern statt Zeichen fuer Zeichen --
            # das trifft fast immer im zweiten Anlauf.
            faktor = min(max_bytes / b, max_json / jb)
            neu = i + max(1, int((j - i) * faktor * 0.97))
            j = neu if neu < j else j - 1
        stuecke.append(text[i:j])
        i = j
    return stuecke


# ------------------------------------------------------------------ Agent

class Agent:

    def __init__(self, aufbau, geheimnis):
        self.a = aufbau
        self.geheimnis = geheimnis
        self.schlange_url = aufbau.basis + '/ahpt/warteschlange.json'
        self.relay_url    = aufbau.basis + '/relay.php'
        self.etag = None
        self.erledigt = {}
        self.letzter_bericht = time.time()
        self.letzte_volle = 0.0      # wann zuletzt unbedingt geholt wurde
        self.letzte_folge = None     # Nummer der zuletzt gesehenen Schlange
        self.nur_304 = 0             # 304er seit dem letzten 200

    # ------------------------------------------------------- Verteiler

    def verteile(self, nutzlast):
        """Prueft die Form und gibt an den Handler weiter.

        Was hier geprueft wird, ist alles, was OHNE Kenntnis des Dienstes
        pruefbar ist -- und keinen Schritt mehr.
        """
        if not isinstance(nutzlast, dict):
            zaehle('form_abgewiesen')
            return handler_paket.nichts('nutzlast: Objekt erwartet')

        dienst = nutzlast.get('dienst')
        aktion = nutzlast.get('aktion')
        daten  = nutzlast.get('daten')

        # Zweite Formpruefung. relay.php hat schon geprueft -- aber dieser
        # Agent muss auch dann sicher sein, wenn dort etwas nachgibt oder
        # jemand einen zweiten Vermittler betreibt. Eine Schranke, die nur an
        # einer Stelle steht, ist eine Schranke auf Zuruf.
        if not isinstance(dienst, str) \
                or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', dienst):
            zaehle('form_abgewiesen')
            return handler_paket.nichts('dienst: Bezeichner erwartet')
        if not isinstance(aktion, str) \
                or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', aktion):
            zaehle('form_abgewiesen')
            return handler_paket.nichts('aktion: Bezeichner erwartet')
        if not isinstance(daten, dict):
            zaehle('form_abgewiesen')
            return handler_paket.nichts('daten: Objekt erwartet')

        eintrag = self.a.dienste.get(dienst)
        if eintrag is None:
            # Kein Hinweis darauf, welche Dienste es gibt. Die Liste steht zu
            # Hause und geht die Oeffentlichkeit nichts an.
            zaehle('dienst_unbekannt')
            return handler_paket.nichts('dienst unbekannt')
        h, erlaubte = eintrag
        if aktion not in erlaubte:
            zaehle('aktion_gesperrt')
            return handler_paket.nichts('aktion nicht freigegeben')

        try:
            antwort = h.bearbeite(aktion, daten)
        except Exception as e:
            # Ein Handler, der stuerzt, darf den Agenten nicht mitnehmen --
            # aber er darf auch nicht unbemerkt bleiben. Die Ausnahme wird
            # genannt, ihr Text geht NICHT nach draussen: er koennte Pfade
            # oder Namen aus dem Haus enthalten.
            zaehle('handler_absturz')
            log('  Handler "%s" gestuerzt bei %s: %s: %s'
                % (dienst, aktion, type(e).__name__, e))
            return handler_paket.nichts('handler-fehler')

        if not isinstance(antwort, dict) or 'inhalt' not in antwort:
            zaehle('handler_absturz')
            log('  Handler "%s" gab nichts Brauchbares zurueck.' % dienst)
            return handler_paket.nichts('handler-fehler')

        antwort['quelle'] = dienst      # eine Stelle, an der der Name entsteht
        return antwort

    # --------------------------------------------------------- Ablegen

    def lege_ab(self, marke, antwort):
        """Legt die Antwort ab -- gestueckelt, wenn noetig.

        REIHENFOLGE IST VERBINDLICH: erst alle Stuecke, dann das Verzeichnis.
        Andersherum verwiese ein Verzeichnis auf Dateien, die es noch nicht
        gibt, und der Besucher setzte eine halbe Antwort zusammen, ohne dass
        ein Fehler entstuende.
        """
        inhalt = antwort.get('inhalt', '')
        stuecke = zerlege(inhalt) if len(inhalt.encode('utf-8')) > MAX_STUECK \
            else [inhalt]

        if len(stuecke) > MAX_TEILE:
            zaehle('antwort_zu_gross')
            log('  %s  zu gross: %d Stuecke, erlaubt sind %d'
                % (marke[:8], len(stuecke), MAX_TEILE))
            antwort = handler_paket.nichts('antwort zu gross')
            antwort['quelle'] = ''
            stuecke = ['']

        teile = len(stuecke)

        if teile > 1:
            for i, s in enumerate(stuecke):
                code, daten = netz.sende_json(
                    self.relay_url + '?action=stueck',
                    {'v': VERSION, 'krypto': 'keine', 'marke': marke,
                     'teil': i, 'teile': teile, 'nutzlast': s},
                    self.geheimnis, zaehler=ZAEHLER)
                if code != 200 or not daten.get('ok'):
                    # Aufgeben, aber KEIN Verzeichnis ablegen. Lieber gar
                    # keine Antwort als eine, die auf Luecken zeigt.
                    zaehle('stueck_fehler')
                    log('  %s  Stueck %d/%d nicht abgelegt: HTTP %s %s'
                        % (marke[:8], i + 1, teile, code,
                           daten.get('fehler', '')))
                    return False

        nutz = {k: antwort.get(k, '') for k in
                ('gefunden', 'titel', 'quelle', 'inhalt_typ')}
        nutz['gefunden'] = bool(antwort.get('gefunden', False))
        nutz['inhalt_typ'] = antwort.get('inhalt_typ', 'text')
        nutz['inhalt'] = '' if teile > 1 else stuecke[0]

        code, daten = netz.sende_json(
            self.relay_url + '?action=antwort',
            {'v': VERSION, 'krypto': 'keine', 'marke': marke,
             'teile': teile, 'nutzlast': nutz},
            self.geheimnis, zaehler=ZAEHLER)

        if code == 200 and daten.get('ok'):
            zaehle('beantwortet')
            return True
        if code == 404:
            zaehle('marke_verfallen')
            log('  %s  zu spaet -- Marke war schon verfallen' % marke[:8])
            return False
        zaehle('ablage_fehler')
        log('  %s  ANTWORT NICHT ABGELEGT: HTTP %s %s'
            % (marke[:8], code, daten.get('fehler', '')))
        return False

    # ------------------------------------------------------ Ein Durchgang

    def durchgang(self):
        jetzt = time.time()
        for m, t in list(self.erledigt.items()):
            if jetzt - t > GEDAECHTNIS:
                del self.erledigt[m]

        # In Abstaenden unbedingt holen, damit ein uebersehener ETag den
        # Agenten nicht dauerhaft blind macht (siehe UNBEDINGT_NACH).
        unbedingt = (jetzt - self.letzte_volle) >= self.a.unbedingt_nach
        code, koerper, neuer_etag = netz.hole(
            self.schlange_url, None if unbedingt else self.etag)

        if code == 304:
            zaehle('poll_304')
            self.nur_304 += 1
            return
        if code == 404:
            # KEIN Fehler: Solange nie jemand gefragt hat, gibt es die Datei
            # nicht. relay.php legt sie mit der ersten Frage an.
            zaehle('schlange_leer')
            einmal('leer', '  Noch keine Warteschlange -- normal, bis die '
                           'erste Frage kommt.')
            return
        if code != 200:
            zaehle('poll_fehler')
            einmal('poll', '  Warteschlange nicht erreichbar (HTTP %s)' % code)
            return

        zaehle('poll_ok')
        if unbedingt:
            self.letzte_volle = jetzt
        if neuer_etag:
            self.etag = neuer_etag
        try:
            schlange = json.loads(koerper.decode('utf-8', 'replace'))
            offen = schlange.get('offen', [])
        except Exception:
            # Halb geschriebene Datei: relay.php benennt atomar um, das sollte
            # nicht vorkommen. Wenn doch, muss es auffallen.
            zaehle('poll_fehler')
            einmal('schlange-kaputt', '  Warteschlange nicht lesbar -- '
                   'schreibt die Gegenseite nicht atomar?')
            return

        # Fortlaufende Nummer der Warteschlange. Springt sie weiter, waehrend
        # wir nur 304er bekommen haben, ist uns eine Aenderung entgangen --
        # der ETag hat sie nicht angezeigt.
        #
        # Das ist der Punkt: Ohne diese Zaehlung waere der Fehlschlag
        # unsichtbar. Der Besucher wartete, der Agent meldete "keine Fehler",
        # und niemand haette einen Anhaltspunkt. Jetzt steht er in der
        # Fehlerzeile und im Fuenfminutenbericht.
        folge = schlange.get('folge')
        if isinstance(folge, int):
            if self.letzte_folge is not None and self.nur_304 > 0                     and folge > self.letzte_folge + 1:
                zaehle('schlange_verpasst')
                einmal('verpasst',
                       '  UEBERSEHENE AENDERUNG: Warteschlange sprang von %d '
                       'auf %d, dazwischen nur 304er.' % (self.letzte_folge, folge))
                einmal('verpasst2',
                       '  Ursache ist fast immer der ETag: Apache bildet ihn aus '
                       'Sekunde und Groesse,')
                einmal('verpasst3',
                       '  und zwei gleich lange Warteschlangen in derselben '
                       'Sekunde sind dann nicht zu unterscheiden.')
                einmal('verpasst4',
                       '  Abhilfe: `FileETag INode MTime Size` in die .htaccess '
                       '(siehe htaccess-beispiel).')
            self.letzte_folge = folge
        self.nur_304 = 0

        for eintrag in offen:
            if not isinstance(eintrag, dict):
                continue
            marke = eintrag.get('marke', '')
            if not isinstance(marke, str) or not re.fullmatch(r'[0-9a-f]{32}', marke):
                continue
            if marke in self.erledigt:
                continue
            if jetzt - eintrag.get('ts', 0) > FRAGE_MAX_ALTER:
                zaehle('frage_zu_alt')
                self.erledigt[marke] = jetzt
                continue

            self.erledigt[marke] = jetzt
            self.bearbeite_marke(marke, jetzt)

    def bearbeite_marke(self, marke, jetzt):
        # `frage_` und `antwort_` statt `f_`/`a_`: Am 02.09.2026 auf IONOS
        # gemessen -- mod_speling haelt zwei Namen, die sich um EIN Zeichen
        # unterscheiden, fuer einen Tippfehler und leitet per HTTP 301 um.
        fc, fk, _ = netz.hole('%s/ahpt/frage_%s.json' % (self.a.basis, marke))
        if fc != 200:
            zaehle('frage_unlesbar')
            einmal('frage-weg', '  Fragedatei nicht abrufbar (HTTP %s)' % fc)
            return
        try:
            umschlag = json.loads(fk.decode('utf-8', 'replace'))
        except Exception:
            zaehle('frage_unlesbar')
            return
        if not isinstance(umschlag, dict):
            zaehle('frage_unlesbar')
            return

        # Umschlag pruefen. Eine unbekannte Fassung wird ABGEWIESEN, nicht
        # gedeutet: Ein Agent, der raet, tut irgendwann etwas Falsches und
        # meldet es nicht.
        if umschlag.get('v') != VERSION:
            zaehle('fassung_falsch')
            einmal('fassung', '  Frage mit Protokollfassung %r -- erwartet %d. '
                              'Abgewiesen, nicht gedeutet.'
                   % (umschlag.get('v'), VERSION))
            return
        if umschlag.get('krypto', 'keine') != 'keine':
            zaehle('krypto_unbekannt')
            einmal('krypto', '  Frage mit Verfahren %r -- nicht gebaut, '
                             'abgewiesen. Siehe ARCHITEKTUR.md Abschnitt 8.'
                   % umschlag.get('krypto'))
            return
        # Die Marke IM Umschlag muss die sein, die abgerufen wurde. Ohne
        # diese Pruefung faellt eine Umleitung auf eine fremde Datei nicht
        # auf -- genau das, was mod_speling am 02.09. getan hat.
        if umschlag.get('marke') != marke:
            zaehle('marke_falsch')
            log('  %s  Marke im Umschlag weicht ab (%r) -- Umleitung im Spiel?'
                % (marke[:8], umschlag.get('marke')))
            return

        zaehle('fragen_geholt')
        nutzlast = umschlag.get('nutzlast')

        t0 = time.time()
        antwort = self.verteile(nutzlast)
        dauer = time.time() - t0

        if self.lege_ab(marke, antwort):
            n = nutzlast if isinstance(nutzlast, dict) else {}
            log('  %s  %-10s %-8s %-30s %6d Z.  %.1fs' % (
                marke[:8], str(n.get('dienst', '?'))[:10],
                str(n.get('aktion', '?'))[:8],
                str(antwort.get('titel', ''))[:30],
                len(antwort.get('inhalt', '')), dauer))

    # -------------------------------------------------------- Hauptlauf

    def lauf(self):
        log('Warteschlange: %s' % self.schlange_url)
        log('Ablage:        %s' % self.relay_url)
        log('Bereit. Der Agent baut jede Verbindung selbst auf -- kein offener Port.')

        while True:
            self.durchgang()

            if time.time() - self.letzter_bericht > 300:
                self.letzter_bericht = time.time()
                fehler = {k: v for k, v in ZAEHLER.items()
                          if v and ('fehler' in k or k in (
                              'frage_zu_alt', 'marke_verfallen', 'form_abgewiesen',
                              'dienst_unbekannt', 'aktion_gesperrt',
                              'handler_absturz', 'fassung_falsch',
                              'krypto_unbekannt', 'marke_falsch',
                              'antwort_zu_gross', 'schlange_verpasst'))}
                abrufe = ZAEHLER.get('poll_ok', 0) + ZAEHLER.get('poll_304', 0)
                log('Stand: %d beantwortet, %d Abrufe (%d davon 304). %s' % (
                    ZAEHLER.get('beantwortet', 0), abrufe,
                    ZAEHLER.get('poll_304', 0),
                    ('FEHLER: ' + str(fehler)) if fehler else 'keine Fehler.'))

            time.sleep(self.a.poll_abstand)


# --------------------------------------------------------------- Selbsttest

def selbsttest(aufbau):
    """Faehrt die Selbsttests aller Handler -- ohne Netz, ohne die Dienste.

    Dazu die Stueckelung, weil sie die einzige Stelle im Kern ist, die
    rechnet statt nur weiterzureichen.
    """
    fehler = 0
    print('')
    print('KERN -- Stueckelung')
    print('')

    faelle = []
    # Kurz genug: ein Stueck, unveraendert.
    faelle.append(('kurzer Text bleibt ein Stueck',
                   lambda: zerlege('hallo') == ['hallo']))
    faelle.append(('leerer Text ergibt ein leeres Stueck',
                   lambda: zerlege('') == ['']))
    # Zusammensetzen muss das Original ergeben -- sonst ist die Stueckelung
    # eine Datenverfaelschung mit Zusatzschritten.
    for name, text in (
            ('reines ASCII',       'A' * 200000),
            ('Umlaute',            'aeoeue' * 40000),
            ('Zeichen ausserhalb der BMP', '\U0001F600' * 30000),
            ('lauter Anfuehrungszeichen',  '"' * 100000),
            ('lauter Rueckstriche', chr(92) * 100000),
            ('Steuerzeichen',      '\x01' * 40000),
            ('gemischt',           ('a"' + chr(92) + '\x02\U0001F600') * 20000)):
        def pruef(t=text):
            st = zerlege(t)
            if ''.join(st) != t:
                return False
            for s in st:
                if len(s.encode('utf-8')) > MAX_STUECK:
                    return False
                if len(json.dumps(s, ensure_ascii=False).encode('utf-8')) > MAX_JSON:
                    return False
            return True
        faelle.append(('zusammengesetzt wieder gleich: ' + name, pruef))

    for beschreibung, f in faelle:
        try:
            ok = bool(f())
        except Exception as e:
            ok = False
            beschreibung += '  (%s: %s)' % (type(e).__name__, e)
        print('  %-58s %s' % (beschreibung, 'ok' if ok else 'FEHLSCHLAG'))
        fehler += 0 if ok else 1

    print('')
    print('KERN -- Anzeigenamen (titel)')
    print('')

    # `titel` ist von aussen bestimmt und wird zurueckgespiegelt: Bei einer
    # Suche IST er der Suchbegriff. Ein Entwickler, der `innerHTML = a.titel`
    # schreibt, haette sonst Stored XSS mit frei gewaehltem Inhalt -- ohne
    # dass ein Angreifer dafuer eine Datei oder ein Archiv braucht.
    st = handler_paket.sicherer_titel
    titel_faelle = [
        ('Tag laesst sich nicht oeffnen',
         st('<script>alert(1)</script>') == 'scriptalert(1)/script'),
        ('spitze Klammern einzeln',      '<' not in st('a<b') and '>' not in st('a>b')),
        ('Steuerzeichen raus',           st('a\x00b\x01c') == 'abc'),
        ('Zeilenumbruch raus',           st('a\nb') == 'ab'),
        ('Loeschzeichen raus',           st('a\x7fb') == 'ab'),
        ('harmloser Text bleibt',        st('Wasser (H2O) -- 20 %') == 'Wasser (H2O) -- 20 %'),
        ('Umlaute bleiben',              st('Fuesse, Groesse, äöü') ==
                                         'Fuesse, Groesse, äöü'),
        ('gekuerzt auf 200 Zeichen',     len(st('a' * 5000)) == 200),
        ('Zahl wird zu Text',            st(12345) == '12345'),
        ('None wird zu Text',            st(None) == 'None'),
        ('leer bleibt leer',             st('') == ''),
    ]
    for beschreibung, ok in titel_faelle:
        print('  %-58s %s' % (beschreibung, 'ok' if ok else 'FEHLSCHLAG'))
        fehler += 0 if ok else 1

    # Und die Gegenprobe: Der INHALT wird NICHT angetastet. Wer die Nutzlast
    # saeubert, liefert nicht mehr aus, sondern verfaelscht -- eine Datei mit
    # entfernten Zeichen ist keine Datei mehr.
    unberuehrt = handler_paket.text_antwort('<script>x</script>')['inhalt']
    print('  %-58s %s' % ('inhalt bleibt unangetastet',
                          'ok' if unberuehrt == '<script>x</script>' else 'FEHLSCHLAG'))
    fehler += 0 if unberuehrt == '<script>x</script>' else 1

    for name, (h, erlaubte) in sorted(aufbau.dienste.items()):
        print('')
        print('DIENST "%s"  (Handler %s, Aktionen: %s)'
              % (name, h.ART, ', '.join(sorted(erlaubte))))
        print('')
        for beschreibung, ok, hinweis in h.selbsttest():
            print('  %-58s %s%s' % (beschreibung, 'ok' if ok else 'FEHLSCHLAG',
                                    ('  -- ' + hinweis) if hinweis else ''))
            fehler += 0 if ok else 1

    print('')
    print('ERGEBNIS: %s' % ('alle Schranken halten.' if not fehler
                            else '%d FEHLSCHLAG(E).' % fehler))
    print('')
    print('  Das prueft die Schranken, nicht den Durchstich. Ob der ganze Weg')
    print('  traegt, sagt allein tests/durchstich.sh gegen einen echten')
    print('  Vermittler -- was ein Testaufbau nicht hat, kann er nicht messen.')
    return fehler


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description='AHPT-Agent: die Heimseite. Transport, sonst nichts.')
    ap.add_argument('--konfig', default='config.toml',
                    help='Konfigurationsdatei (.toml oder .json)')
    ap.add_argument('--selbsttest', action='store_true',
                    help='Schranken ohne Netz pruefen')
    ap.add_argument('--einmal', action='store_true',
                    help='nur einen Durchgang, dann beenden (fuer Pruefungen)')
    a = ap.parse_args()

    try:
        roh, herkunft = lies_konfig(a.konfig)
        aufbau = Aufbau(roh, herkunft)
    except handler_paket.KonfigFehler as e:
        log('ABBRUCH: %s' % e)
        return 1

    log('AHPT-Agent, Protokollfassung %d' % VERSION)
    log('Konfiguration: %s (gelesen mit %s)' % (a.konfig, aufbau.herkunft))

    if a.selbsttest:
        return 1 if selbsttest(aufbau) else 0

    try:
        geheimnis = aufbau.geheimnis()
    except handler_paket.KonfigFehler as e:
        log('ABBRUCH: %s' % e)
        return 1
    except OSError as e:
        log('ABBRUCH: Geheimnis nicht lesbar (%s): %s'
            % (aufbau.geheimnis_datei, e.strerror))
        return 1

    log('Dienste:')
    bereit = 0
    for name, (h, erlaubte) in sorted(aufbau.dienste.items()):
        ok, hinweis = h.bereit()
        log('  %-12s %-8s %-24s %s' % (
            name, h.ART, ','.join(sorted(erlaubte)),
            hinweis if ok else 'NICHT BEREIT: ' + hinweis))
        bereit += 1 if ok else 0
        if ok and getattr(h, 'endungen', None) == set() and h.ART == 'datei':
            log('               ACHTUNG: keine Endungs-Weissliste -- es geht '
                'ALLES aus diesem Ordner hinaus.')
    if not bereit:
        log('ABBRUCH: kein einziger Dienst ist bereit. Ein Agent, der auf')
        log('         jede Frage "nichts gefunden" antwortet, ist schlechter')
        log('         als keiner -- er sieht aus wie ein leerer Dienst.')
        return 1

    agent = Agent(aufbau, geheimnis)
    try:
        if a.einmal:
            agent.durchgang()
            log('Ein Durchgang beendet. %s' % dict(sorted(ZAEHLER.items())))
        else:
            agent.lauf()
    except KeyboardInterrupt:
        log('Beendet. %s' % dict(sorted(ZAEHLER.items())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
