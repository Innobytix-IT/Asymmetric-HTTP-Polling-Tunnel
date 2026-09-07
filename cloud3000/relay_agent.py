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
import base64
import binascii
import json
import os
import random
import re
import sys
import time

import handler as handler_paket
import netz
import transport

VERSION = 1

# Der Prologue bindet den Handshake an DIESES Protokoll. Beide Seiten muessen
# denselben Wert nehmen; weicht er ab, scheitert der Handshake, statt dass
# eine Nachricht aus einem anderen Zusammenhang hier durchginge.
PROLOG = b'AHPT-Privat/1'

# MAX_STUECK/MAX_JSON/MAX_TEILE/STUECK_WIEDERHOLUNGEN (Grenzen aus
# relay.php, Stueckelung bei Last -- gemessen 05./06.09.2026 gegen
# bplaced/IONOS) stecken seit der Transport-Abstraktion in transport.py
# (PHP_*), weil sie PHP-spezifisch sind und WebDAV sie nicht braucht.
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


def lies_geheimnis(pfad):
    """Liest und prueft ein Transport-Geheimnis (X-AHPT-Auth beim PHP-Weg).

    Eigene Funktion statt nur `Aufbau.geheimnis()`, weil jeder zusaetzliche
    PHP-Transportweg (siehe `Aufbau._lies_transporte`) SEIN EIGENES
    Geheimnis braucht -- ein Webspace soll nicht das Geheimnis eines
    anderen mitbenutzen koennen.
    """
    with open(pfad, 'r', encoding='utf-8') as f:
        g = f.read().strip()
    if len(g) < 16:
        raise KonfigFehler('Geheimnis zu kurz (%d Zeichen, mindestens 16): %s'
                            % (len(g), pfad))
    return g


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
        # http ist zulaessig, WENN Noise laeuft -- aber erst nach Abschnitt
        # [krypto], den es hier noch nicht gelesen hat. Deshalb wird die
        # Pruefung zurueckgestellt und weiter unten nachgeholt.
        # Die Pruefung der Basis steht WEITER UNTEN, nicht hier.
        #
        # Sie haengt davon ab, ob verschluesselt wird -- und der Abschnitt
        # [krypto] ist an dieser Stelle noch nicht gelesen. Sie hier mit
        # einem `if False` stillzulegen waere schlimmer als sie zu
        # verschieben: Toter Code an einer Sicherheitsschranke sieht aus wie
        # eine Schranke und ist keine.

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
        # Selbstsigniertes Zertifikat beim Hoster? Dann den oeffentlichen
        # Schluessel des Servers festnageln -- Begruendung in netz.py.
        self.zert_pin = str(r.get('zertifikat_pin', '') or '')
        if self.zert_pin:
            try:
                netz.setze_pin(self.zert_pin)
            except ValueError as e:
                raise KonfigFehler('[relay] zertifikat_pin: %s' % e)

        # Kennung (User-Agent) fuer alles, was hinausgeht. Vorgabe und
        # Begruendung stehen in netz.py, die Abwaegung in SICHERHEIT.md.
        self.kennung = str(r.get('kennung', '') or '')
        try:
            netz.setze_kennung(self.kennung)
        except ValueError as e:
            raise KonfigFehler('[relay] kennung: %s' % e)

        # ------------------------------------------------ Verschluesselung
        #
        # Wahlweise, und zwar aus einem Grund: `krypto.py` braucht
        # `cryptography`. Wer das nicht hat, soll den Agenten trotzdem
        # unverschluesselt starten koennen -- und wer es hat, soll nicht
        # versehentlich unverschluesselt laufen. Deshalb wird das Verfahren
        # ausdruecklich in der Konfiguration genannt, nie erraten.
        kk = roh.get('krypto') or {}
        if not isinstance(kk, dict):
            raise KonfigFehler('Abschnitt [krypto] ist kein Abschnitt.')
        self.verfahren = str(kk.get('verfahren', 'keine'))
        if self.verfahren not in ('keine', 'noise_ik'):
            raise KonfigFehler('[krypto] verfahren: "keine" oder "noise_ik", '
                               'nicht %r' % self.verfahren)
        self.privat = None
        self.clients = set()
        if self.verfahren == 'noise_ik':
            try:
                import krypto
            except ImportError:
                raise KonfigFehler(
                    '[krypto] verfahren = "noise_ik", aber `cryptography`\n'
                    '         fehlt. Entweder installieren:\n'
                    '             pip install cryptography\n'
                    '         oder verfahren = "keine" setzen -- dann liegt\n'
                    '         aber alles offen, was durch den Kanal geht.')
            sd = kk.get('schluessel')
            if not sd:
                raise KonfigFehler('[krypto] schluessel fehlt (Datei mit dem '
                                   'privaten Schluessel des Agenten).')
            try:
                self.privat = krypto.lies_privat(os.path.expanduser(str(sd)))
            except OSError as e:
                raise KonfigFehler('[krypto] schluessel nicht lesbar: %s'
                                   % e.strerror)
            # Wer fragen darf. Eine Weissliste, keine Ausschlussliste -- und
            # eine LEERE waere keine Weissliste, sondern ein offenes Tor:
            # Jeder, der den oeffentlichen Schluessel des Agenten kennt,
            # koennte ihn dann bedienen.
            liste = kk.get('clients')
            if not isinstance(liste, list) or not liste:
                raise KonfigFehler(
                    '[krypto] clients ist leer.\n'
                    '         Ohne Weissliste duerfte jeder fragen, der den\n'
                    '         oeffentlichen Schluessel des Agenten kennt --\n'
                    '         und der ist kein Geheimnis.')
            for c in liste:
                try:
                    b = bytes.fromhex(str(c))
                except ValueError:
                    raise KonfigFehler('[krypto] clients: %r ist kein Hexwert'
                                       % (c,))
                if len(b) != 32:
                    raise KonfigFehler('[krypto] clients: %r hat %d Bytes '
                                       'statt 32' % (c, len(b)))
                self.clients.add(b)

        # SCHREIBENDE AKTIONEN NUR VERSCHLUESSELT.
        #
        # `lege` und `neuer_ordner` legen Bytes auf dem Heimserver ab. Ohne
        # Verschluesselung koennte JEDER, der die Adresse des Webspace kennt,
        # eine solche Frage einstellen -- der Vermittler kann Freund und Feind
        # nicht unterscheiden, und ohne Noise gibt es keinen Absender, den man
        # pruefen koennte.
        #
        # Das wird hier BEIM START abgewiesen, nicht im Betrieb: Ein Agent,
        # der monatelang mit offener Schreibfreigabe laeuft, faellt niemandem
        # auf, bevor es zu spaet ist.
        SCHREIBT = {'lege', 'neuer_ordner'}
        if self.verfahren == 'keine':
            for name, (h, erlaubte) in self.dienste.items():
                schlimm = SCHREIBT & set(erlaubte)
                if schlimm:
                    raise KonfigFehler(
                        'Dienst "%s" gibt %s frei, aber [krypto] verfahren ist '
                        '"keine".'
                        '         Schreibende Aktionen ohne Verschluesselung '
                        'heissen: jeder, der die Adresse kennt, darf Dateien '
                        'auf deinem Heimserver ablegen.'
                        '         Entweder verfahren = "noise_ik" setzen oder '
                        'die Aktion streichen.'
                        % (name, ', '.join(sorted(schlimm))))

        # DIE ZURUECKGESTELLTE PRUEFUNG DER BASIS.
        #
        # Ohne Verschluesselung gilt die alte Regel unveraendert: nur https,
        # sonst reist alles im Klartext -- Frage, Antwort UND das Geheimnis
        # des Agenten.
        #
        # MIT Noise IK aendert sich die Lage grundlegend, und das ist keine
        # Aufweichung, sondern eine andere Rechnung:
        #
        #   * Frage und Antwort sind verschluesselt. Ein Mitleser sieht
        #     Rauschen, egal ob http oder https.
        #   * Was ueber http noch offen liegt, ist allein die Kopfzeile
        #     X-AHPT-Auth -- das Geheimnis, mit dem der Agent beim VERMITTLER
        #     schreiben darf.
        #   * Wer es stiehlt, kann gefaelschte Antworten ablegen. Die scheitern
        #     beim Client an der Noise-Pruefung. Er kann also stoeren, aber
        #     NICHTS MITLESEN und nichts unterschieben.
        #
        # Am 03.09.2026 gemessen: bplaced-frei liefert ueber https ueberhaupt
        # nicht den eigenen Webspace aus -- Port 443 zeigt eine fremde
        # Standardseite, /privat/relay.php gibt es dort nicht. Ohne diese
        # Regel waere der Dienst dort schlicht nicht betreibbar.
        if not netz.basis_erlaubt(self.basis):
            if self.verfahren == 'keine':
                raise KonfigFehler(
                    '[relay] basis muss https sein: %r'
                    '         Ueber http reist das Geheimnis im Klartext mit,'
                    ' und ohne Verschluesselung auch jede Frage und jede'
                    ' Antwort. Entweder eine https-Basis eintragen oder'
                    ' [krypto] verfahren = "noise_ik" setzen.' % self.basis)
            self.basis_ohne_tls = True
        else:
            self.basis_ohne_tls = False

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

        self._lies_transporte(roh)

    def geheimnis(self):
        with open(self.geheimnis_datei, 'r', encoding='utf-8') as f:
            g = f.read().strip()
        if len(g) < 16:
            raise KonfigFehler('Geheimnis zu kurz (%d Zeichen, mindestens 16).'
                               % len(g))
        return g

    # ------------------------------------------------- Transportwege
    #
    # Aufgeteilt in eine eigene Methode, weil sie NACH allem anderen laeuft
    # (braucht self.verfahren, self.basis, ...) und weil sie sonst
    # __init__ noch weiter aufblaehen wuerde.
    def _lies_transporte(self, roh):
        # Der urspruengliche Weg (Abschnitt [relay]) bleibt IMMER der erste
        # Eintrag, intern "php" genannt -- ein bestehendes config.toml mit
        # nur [relay] soll unveraendert weiterlaufen, ohne dass irgendwer
        # [[transport]] ergaenzen muesste. Rolle "beide" ist die Vorgabe
        # (genau das Verhalten von vor der Transport-Abstraktion) --
        # ueberschreibbar mit [relay] rolle, fuer den Fall, dass gerade
        # DIESER (der urspruengliche) Weg auf nur eine Richtung
        # eingeschraenkt werden soll.
        r = roh.get('relay') or {}
        rolle_php = str(r.get('rolle', 'beide'))
        if rolle_php not in ('frage', 'antwort', 'beide'):
            raise KonfigFehler(
                '[relay] rolle muss "frage", "antwort" oder "beide" sein, '
                'nicht %r.' % rolle_php)
        self.transporte = [{
            'art': 'php', 'name': 'php', 'rolle': rolle_php,
            'basis': self.basis, 'geheimnis_datei': self.geheimnis_datei,
            'unbedingt_nach': self.unbedingt_nach,
            'zertifikat_pin': self.zert_pin,
        }]
        namen = {'php'}
        rollen = ('frage', 'antwort', 'beide')

        zusaetzlich = roh.get('transport') or []
        if not isinstance(zusaetzlich, list):
            raise KonfigFehler('[[transport]] ist keine Liste von Abschnitten.')

        for t in zusaetzlich:
            if not isinstance(t, dict):
                raise KonfigFehler('[[transport]] ist kein Abschnitt.')
            name = t.get('name')
            if not isinstance(name, str) \
                    or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', name):
                raise KonfigFehler(
                    '[[transport]] name %r passt nicht zu '
                    '^[a-z][a-z0-9_-]{0,31}$' % (name,))
            if name in namen:
                raise KonfigFehler(
                    'Transportweg "%s" ist zweimal angegeben (der '
                    'urspruengliche Weg aus [relay] heisst intern "php").'
                    % name)
            namen.add(name)

            rolle = str(t.get('rolle', 'beide'))
            if rolle not in rollen:
                raise KonfigFehler(
                    'Transportweg "%s": rolle muss "frage", "antwort" oder '
                    '"beide" sein, nicht %r.' % (name, rolle))

            art = t.get('art')
            if art == 'php':
                basis = str(t.get('basis', '')).rstrip('/')
                if not basis:
                    raise KonfigFehler('Transportweg "%s": basis fehlt.' % name)
                if not netz.basis_erlaubt(basis) and self.verfahren == 'keine':
                    raise KonfigFehler(
                        'Transportweg "%s": basis muss https sein (oder '
                        '[krypto] verfahren = "noise_ik" setzen).' % name)
                gd = t.get('geheimnis_datei')
                if not gd:
                    raise KonfigFehler(
                        'Transportweg "%s": geheimnis_datei fehlt.' % name)
                gd = os.path.expanduser(str(gd))
                # ALLES wird beim Start geprueft (siehe Klassendoku) -- anders
                # als beim urspruenglichen [relay]-Geheimnis (aus historischen
                # Gruenden weiterhin erst spaeter in main() gelesen) wird das
                # hier sofort gelesen: ein zusaetzlicher Transportweg mit
                # kaputtem Geheimnis soll nicht erst beim ersten Gebrauch
                # auffallen.
                try:
                    geh = lies_geheimnis(gd)
                except OSError as e:
                    raise KonfigFehler(
                        'Transportweg "%s": geheimnis_datei nicht lesbar: %s'
                        % (name, e.strerror or e))
                un = float(t.get('unbedingt_nach', UNBEDINGT_NACH))
                if not 1 <= un <= 3600:
                    raise KonfigFehler(
                        'Transportweg "%s": unbedingt_nach muss zwischen 1 '
                        'und 3600 liegen.' % name)
                pin = str(t.get('zertifikat_pin', '') or '')
                if pin:
                    # netz.py verwendet EINEN globalen gepinnten Opener --
                    # ZWEI verschiedene Pins gleichzeitig kann es (noch)
                    # nicht. Lieber klar abbrechen als den zweiten Pin
                    # stillschweigend zu verlieren.
                    if self.zert_pin and pin != self.zert_pin:
                        raise KonfigFehler(
                            'Transportweg "%s": eigener zertifikat_pin -- '
                            'netz.py kennt aber nur EINEN Pin gleichzeitig '
                            '(siehe [relay] zertifikat_pin). Bitte densel'
                            'ben Pin eintragen oder auf einen der beiden '
                            'verzichten.' % name)
                    try:
                        netz.setze_pin(pin)
                    except ValueError as e:
                        raise KonfigFehler(
                            'Transportweg "%s": zertifikat_pin: %s'
                            % (name, e))
                self.transporte.append({
                    'art': 'php', 'name': name, 'rolle': rolle,
                    'basis': basis, 'geheimnis_datei': gd, 'geheimnis': geh,
                    'unbedingt_nach': un, 'zertifikat_pin': pin,
                })
            elif art == 'webdav':
                basis = str(t.get('basis', '')).rstrip('/')
                if not basis:
                    raise KonfigFehler('Transportweg "%s": basis fehlt.' % name)
                benutzer = t.get('benutzer')
                if not benutzer:
                    raise KonfigFehler(
                        'Transportweg "%s": benutzer fehlt.' % name)
                pd = t.get('passwort_datei')
                if not pd:
                    raise KonfigFehler(
                        'Transportweg "%s": passwort_datei fehlt.' % name)
                pd = os.path.expanduser(str(pd))
                # Nur die Lesbarkeit pruefen -- WebDavTransport liest die
                # Datei beim Aufbau selbst nochmal (siehe transport.py).
                # Doppelte Arbeit, aber so bleibt die schon getestete
                # WebDavTransport-Klasse unangetastet.
                try:
                    with open(pd, 'r', encoding='utf-8') as f:
                        if not f.read().strip():
                            raise KonfigFehler(
                                'Transportweg "%s": passwort_datei ist leer: %s'
                                % (name, pd))
                except OSError as e:
                    raise KonfigFehler(
                        'Transportweg "%s": passwort_datei nicht lesbar: %s'
                        % (name, e.strerror or e))
                self.transporte.append({
                    'art': 'webdav', 'name': name, 'rolle': rolle,
                    'basis': basis, 'benutzer': str(benutzer),
                    'passwort_datei': pd,
                    'timeout': float(t.get('timeout', 20)),
                })
            else:
                raise KonfigFehler(
                    'Transportweg "%s": art muss "php" oder "webdav" sein, '
                    'nicht %r.' % (name, art))

        # Mindestens EIN Weg je Richtung -- sonst waere die halbe
        # Konfiguration ein Weg ins Leere, der erst im Betrieb auffiele.
        if not any(x['rolle'] in ('frage', 'beide') for x in self.transporte):
            raise KonfigFehler(
                'Kein Transportweg mit rolle "frage" oder "beide" -- der '
                'Agent koennte nie eine Frage entgegennehmen.')
        if not any(x['rolle'] in ('antwort', 'beide') for x in self.transporte):
            raise KonfigFehler(
                'Kein Transportweg mit rolle "antwort" oder "beide" -- der '
                'Agent koennte nie eine Antwort ablegen.')


# Die Stueckelung (`zerlege`) ist PHP-spezifisch und steckt seit der
# Transport-Abstraktion in transport.py -- `selbsttest()` unten prueft sie
# ueber `transport.zerlege`, ohne sie hier zu duplizieren.


# ------------------------------------------------------------------ Agent

class Agent:

    def __init__(self, aufbau, geheimnis):
        self.a = aufbau
        self.geheimnis = geheimnis

        # Die Transportwege -- ETag/Folge-Zustand, Stueckelung und
        # Wiederholung stecken jetzt DORT (transport.PhpTransport bzw.
        # transport.WebDavTransport), nicht mehr hier. `zaehle`/`log`/
        # `einmal`/`ZAEHLER` werden injiziert statt importiert, damit
        # transport.py nichts von diesen Namen wissen muss -- aber der
        # Agent sieht danach GENAU dieselben Zaehler und Meldungen wie vor
        # der Abspaltung (fuer den PHP-Weg; WebDAV zaehlt eigenstaendig,
        # siehe transport.WebDavTransport).
        #
        # `aufbau.transporte` ist eine gepruefte Liste von rohen Angaben
        # (siehe Aufbau._lies_transporte); hier werden daraus die
        # tatsaechlichen Objekte gebaut. Der ERSTE Eintrag ("php", aus
        # [relay]) bekommt das explizit uebergebene `geheimnis` -- alle
        # weiteren tragen ihr eigenes schon vorgelesenes (siehe dort).
        self.transporte = []
        for i, t in enumerate(aufbau.transporte):
            if t['art'] == 'php':
                obj = transport.PhpTransport(
                    t['name'], t['basis'],
                    geheimnis if i == 0 else t['geheimnis'], VERSION,
                    unbedingt_nach=t['unbedingt_nach'],
                    frage_max_alter=FRAGE_MAX_ALTER, gedaechtnis=GEDAECHTNIS,
                    zaehle_fn=zaehle, log_fn=log, einmal_fn=einmal,
                    zaehler_dict=ZAEHLER)
            else:                                            # 'webdav'
                obj = transport.WebDavTransport(
                    t['name'], t['basis'], t['benutzer'],
                    t['passwort_datei'], timeout=t['timeout'])
            self.transporte.append(
                {'name': t['name'], 'rolle': t['rolle'], 'obj': obj})

        # Kreislauf-Unterbrecher je Transportweg -- IM SPEICHER, nicht auf
        # Platte: Der Agent laeuft dauerhaft (anders als der CLI-Client,
        # der nach jedem Aufruf endet und deshalb eine Datei braucht), sein
        # Prozessspeicher UEBERLEBT also einen Ausfall lang genug.
        self.gesundheit = transport.Gesundheit()
        # Rundlauf-Zeiger fuer die Wahl des Ablageweges bei mehreren
        # gleichermassen zulaessigen Antwortwegen -- siehe _waehle_antwortweg.
        self._antwort_zeiger = 0

        # Ueber alle Transportwege HINWEG gemeinsam: Eine Marke, die ueber
        # einen Weg schon beantwortet wurde, soll nicht ueber einen anderen
        # Weg noch einmal auftauchen und ein zweites Mal bearbeitet werden.
        self.erledigt = {}
        # Marken, deren Antwort schon FERTIG VERSCHLUESSELT ist, aber (noch)
        # nicht abgelegt werden konnte -- Marke -> {herkunft, paket, seit},
        # wobei `paket` das in sich abgeschlossene Buendel aus
        # `_verschluessele_antwort` ist (NIE die rohe `sitzung`, siehe dort
        # -- ein zweiter Verschluesselungsversuch auf derselben Sitzung
        # waere selbst der Fehler, nicht die Behebung). Getrennt von
        # `erledigt`, aus gutem Grund: Eine Marke muss sofort als erledigt
        # gelten, sobald sie entschluesselt wurde (der Wiederholungsschutz
        # wuerde einen zweiten Entschluesselungsversuch ohnehin abweisen)
        # -- aber "entschluesselt" ist nicht dasselbe wie "die Antwort ist
        # beim Besucher angekommen". Schlaegt das Ablegen fehl, ginge die
        # schon fertige Antwort ohne dieses Gedaechtnis fuer immer verloren:
        # Kein spaeterer Durchgang wuerde es je wieder versuchen, auch nicht
        # ueber einen inzwischen wieder gesunden Weg. Im Mischbetrieb-
        # Nachttest vom 07.09.2026 genau so gefunden -- ein Teil der
        # damaligen Fehlschlaege bei grossen Dateien geht darauf zurueck.
        self.wartend = {}
        self.letzter_bericht = time.time()

        # Gedaechtnis gegen wiederholte erste Handshake-Nachrichten. Es
        # gehoert hierher und nicht in krypto.py: Kryptografie kann eine
        # Wiederholung nicht erkennen -- die Nachricht ist ja echt.
        self.schutz = None
        if aufbau.verfahren == 'noise_ik':
            import krypto
            self.schutz = krypto.Wiederholungsschutz(fenster=FRAGE_MAX_ALTER)

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
        # Blockversionen einer Aktion sind KEINE eigene Freigabe. Wer
        # eine Datei in einem Zug legen darf, darf sie auch in Bloecken
        # legen -- die Blockversion ist nur die Anpassung an den Weg, nicht
        # eine andere Faehigkeit. Sie hier eigens einzutragen zu verlangen,
        # waere die Sorte kleiner Stolperdraht, ueber den der Nutzer beim
        # ersten grossen Bild stolpert.
        #
        # Umgekehrt gilt es nicht: `hole` freizugeben, gibt NICHT `lege`
        # oder `lege_block` frei -- Schreiben braucht die eigene Freigabe.
        erlaubt = aktion in erlaubte or (
            aktion.endswith('_block') and aktion[:-6] in erlaubte
        )
        if not erlaubt:
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

    def _verschluessele_antwort(self, marke, antwort, sitzung):
        """Verschluesselt (falls noetig) die Antwort GENAU EINMAL.

        Das entstehende Paket ist danach in sich abgeschlossen und wird
        unveraendert weiterverwendet -- sowohl beim ersten Ablageversuch
        als auch bei jedem spaeteren Nachholversuch aus `self.wartend`.
        Ein zweiter Aufruf von `sitzung.schreibe_nachricht2` auf DERSELBEN
        Sitzung waere kein Fehler, sondern ein eigener, gueltiger, aber
        ANDERER Geheimtext (der Nachrichtenzaehler der Sitzung laeuft
        weiter) -- der Client erwartet aber genau EINE Antwortnachricht je
        Sitzung und koennte einen zweiten, spaeter erzeugten Geheimtext
        nicht mehr entschluesseln ("Antwort nicht entschluesselbar").
        Deshalb ist das Verschluesseln strikt von der Ablage getrennt:
        Verschluesselt wird HIER, ein einziges Mal; abgelegt (und bei
        Bedarf wiederholt) wird in `_lege_ab_versuch`, das nur noch das
        fertige Paket entgegennimmt.

        Rueckgabe `(ok, fehler, paket)` -- `paket` ist bei Erfolg das
        Buendel fuer `_lege_ab_versuch`, sonst `None`.
        """
        inhalt = antwort.get('inhalt', '')
        meta = None

        if sitzung is not None:
            # `gefunden`, `titel`, `quelle` wandern MIT hinein. Stuenden sie
            # aussen, verriete der Titel den Dateinamen -- und wer den kennt,
            # braucht den Inhalt oft gar nicht mehr.
            klartext = json.dumps({
                'gefunden':   bool(antwort.get('gefunden', False)),
                'titel':      str(antwort.get('titel', '')),
                'quelle':     str(antwort.get('quelle', '')),
                'inhalt_typ': str(antwort.get('inhalt_typ', 'text')),
                'inhalt':     inhalt,
                'grund':      str(antwort.get('grund', '')),
            }, ensure_ascii=False).encode('utf-8')
            try:
                m2 = sitzung.schreibe_nachricht2(klartext)
            except Exception as e:
                zaehle('krypto_fehler')
                log('  %s  Antwort nicht verschluesselbar: %s'
                    % (marke[:8], type(e).__name__))
                return False, 'krypto_fehler', None
            inhalt = base64.b64encode(m2).decode('ascii')
        else:
            meta = {k: antwort.get(k, '') for k in
                    ('gefunden', 'titel', 'quelle', 'inhalt_typ')}
            meta['gefunden'] = bool(antwort.get('gefunden', False))
            meta['inhalt_typ'] = antwort.get('inhalt_typ', 'text')

        verf = 'keine' if sitzung is None else (
            'noise_ik_aes' if sitzung.ss.cs.aead == 'AESGCM' else 'noise_ik')
        return True, '', {'inhalt': inhalt, 'verf': verf, 'meta': meta,
                           'verschluesselt': sitzung is not None}

    @staticmethod
    def _leere_metadaten(grund):
        """Baut ein `meta`-Buendel fuer eine ERSATZ-Antwort (z.B. "zu
        gross") -- nur fuer den unverschluesselten Weg gebraucht, siehe
        `_lege_ab_versuch`."""
        ersatz = handler_paket.nichts(grund)
        meta = {k: ersatz.get(k, '') for k in
                ('gefunden', 'titel', 'quelle', 'inhalt_typ')}
        meta['gefunden'] = bool(ersatz.get('gefunden', False))
        meta['inhalt_typ'] = ersatz.get('inhalt_typ', 'text')
        return meta

    def _lege_ab_versuch(self, herkunft, marke, paket):
        """Ein einzelner Ablageversuch mit einem BEREITS fertigen Paket
        (siehe `_verschluessele_antwort`) -- hier wird nichts mehr
        verschluesselt, nur noch der Weg gewaehlt, gestueckelt/verpackt und
        hochgeladen. Beliebig oft wiederholbar (genau dafuer gibt es
        `self.wartend`), weil hier nichts mehr verbraucht wird, das nur
        einmal gilt.

        REIHENFOLGE IST VERBINDLICH: erst alle Stuecke, dann das Verzeichnis.
        Andersherum verwiese ein Verzeichnis auf Dateien, die es noch nicht
        gibt, und der Besucher setzte eine halbe Antwort zusammen, ohne dass
        ein Fehler entstuende.

        `herkunft` ist der Weg, ueber den die FRAGE hereinkam -- die Antwort
        bleibt darauf, WENN er das darf (rolle "antwort"/"beide") und gerade
        gesund ist. Sonst waehlt `_waehle_antwortweg` einen anderen -- auch
        von Versuch zu Versuch verschieden, das ist der ganze Sinn von
        `self.wartend`.

        Rueckgabe `(ok, fehler)`: `fehler` ist `''` bei Erfolg, sonst ein
        kurzes Schlagwort. Der Aufrufer unterscheidet danach, ob sich ein
        spaeterer Versuch lohnt -- bei `'verfallen'` (die Marke selbst ist
        serverseitig abgelaufen) nicht, bei jedem anderen Grund
        (Transportweg gerade nicht erreichbar, zu gross fuer DIESEN Weg,
        kein zulaessiger Weg frei) schon, weil sich das bis zum naechsten
        Durchgang aendern kann.
        """
        inhalt = paket['inhalt']
        verf = paket['verf']
        meta = paket['meta']
        verschluesselt = paket['verschluesselt']

        gewaehlt = self._waehle_antwortweg(herkunft)
        if gewaehlt is None:
            zaehle('kein_antwortweg')
            log('  %s  KEIN Transportweg fuer die Antwort verfuegbar (alle '
                'gesperrt oder nicht zulaessig).' % marke[:8])
            return False, 'kein_antwortweg'

        if gewaehlt['obj'].art == 'php':
            # Die Stueckelung selbst ist PHP-spezifisch (transport.zerlege)
            # -- OB eine zu grosse Antwort durch eine leere Fehlerantwort
            # ERSETZT wird, ist aber eine Protokollentscheidung und bleibt
            # deshalb HIER, nicht im Transportweg (siehe Kommentar in
            # transport.PhpTransport.lege_antwort).
            stuecke = transport.zerlege(inhalt) \
                if len(inhalt.encode('utf-8')) > transport.PHP_MAX_STUECK \
                else [inhalt]
            if len(stuecke) > transport.PHP_MAX_TEILE:
                zaehle('antwort_zu_gross')
                log('  %s  zu gross: %d Stuecke, erlaubt sind %d'
                    % (marke[:8], len(stuecke), transport.PHP_MAX_TEILE))
                stuecke = ['']
                if not verschluesselt:
                    meta = self._leere_metadaten('antwort zu gross')
            if verschluesselt:
                # Nach aussen bleibt genau ein Feld uebrig. Bei Ueberlaenge
                # wird HIER bewusst NICHTS Lesbares nachgereicht (`stuecke`
                # ist dann schon auf [''] gesetzt).
                ok, fehler = gewaehlt['obj'].lege_antwort(
                    marke, stuecke, {}, 'chiffre', verf)
            else:
                ok, fehler = gewaehlt['obj'].lege_antwort(
                    marke, stuecke, meta, 'inhalt', verf)
            # Zaehlung/Meldung (stueck_fehler/marke_verfallen/ablage_fehler/
            # beantwortet) geschehen bereits IM Transportweg, mit denselben
            # Namen wie vor der Abspaltung.
        else:                                                # 'webdav'
            # Kein Stueck-Limit wie bei PHP -- WebDAV braucht keine
            # Stueckelung (README.md, bis 12 MB in einem Rutsch gemessen).
            # Der einzige Deckel ist MAX_WEBDAV_NUTZLAST (grosszuegig
            # darueber, siehe transport.py).
            if len(inhalt.encode('utf-8')) > transport.MAX_WEBDAV_NUTZLAST:
                zaehle('antwort_zu_gross')
                log('  %s  zu gross fuer "%s": %d Bytes, Deckel %d'
                    % (marke[:8], gewaehlt['name'],
                       len(inhalt.encode('utf-8')),
                       transport.MAX_WEBDAV_NUTZLAST))
                inhalt = ''
                if not verschluesselt:
                    meta = self._leere_metadaten('antwort zu gross')
            if verschluesselt:
                nutz = {'chiffre': inhalt}
            else:
                nutz = dict(meta)
                nutz['inhalt'] = inhalt
            umschlag = {'v': VERSION, 'krypto': verf, 'marke': marke,
                        'teile': 1, 'nutzlast': nutz}
            ok, fehler = gewaehlt['obj'].lege_antwort(marke, umschlag)
            if ok:
                zaehle('beantwortet')
            else:
                zaehle('ablage_fehler')
                log('  %s  ANTWORT NICHT ABGELEGT ("%s"): %s'
                    % (marke[:8], gewaehlt['name'], fehler))

        if ok:
            self.gesundheit.erfolg(gewaehlt['name'])
        elif fehler != 'verfallen':
            # 'verfallen' (Marke war schon verfallen) ist eine Antwort DES
            # SERVERS -- der Weg selbst ist erreichbar, kein Anzeichen fuer
            # einen kranken Transportweg.
            self.gesundheit.fehlschlag(gewaehlt['name'])

        return ok, fehler

    def lege_ab(self, herkunft, marke, antwort, sitzung=None):
        """Verschluesselt und legt in EINEM Aufwasch ab -- der Normalfall
        beim ERSTEN Versuch. Siehe `_verschluessele_antwort` (warum
        Verschluesseln und Ablegen getrennte Schritte sind) und
        `_lege_ab_versuch` (was ein Ablageversuch macht).

        Rueckgabe `(ok, fehler, paket)`. Schlaegt schon das Verschluesseln
        fehl, ist `paket` `None` und ein spaeterer Nachholversuch (der ja
        neu verschluesseln muesste) hat keine Grundlage -- dieser Fall wird
        nicht in `self.wartend` gemerkt. Schlaegt nur die ABLAGE fehl, ist
        `paket` das fertige Buendel, das ein Nachholversuch unveraendert an
        `_lege_ab_versuch` weiterreichen kann.
        """
        ok, fehler, paket = self._verschluessele_antwort(marke, antwort, sitzung)
        if not ok:
            return False, fehler, None
        ok, fehler = self._lege_ab_versuch(herkunft, marke, paket)
        return ok, fehler, paket

    # ------------------------------------------------------ Ein Durchgang

    def durchgang(self):
        jetzt = time.time()
        for m, t in list(self.erledigt.items()):
            if jetzt - t > GEDAECHTNIS:
                del self.erledigt[m]

        # Zuerst die noch offenen Ablagen aus fruehren Durchgaengen
        # nachholen -- VOR dem Abklopfen neuer Fragen, damit eine schon
        # fertige Antwort nicht hinter frischer Arbeit zurueckbleibt.
        # Dieselbe GEDAECHTNIS-Frist wie bei `erledigt`: Wartet ein Client
        # laengst nicht mehr auf eine Antwort, lohnt sich auch das
        # Nachholen nicht mehr (siehe Kommentar in `__init__` zu `wartend`).
        for m, w in list(self.wartend.items()):
            if jetzt - w['seit'] > GEDAECHTNIS:
                del self.wartend[m]
                continue
            # NUR die Ablage wird wiederholt, nicht die Verschluesselung --
            # das fertige Paket aus dem ersten Versuch bleibt unveraendert.
            # Ein erneuter `lege_ab`-Aufruf (mit `sitzung`) wuerde die
            # Sitzung ein zweites Mal verbrauchen und einen Geheimtext
            # erzeugen, den der Client nicht mehr zuordnen kann -- siehe
            # Kommentar in `_verschluessele_antwort`.
            ok, fehler = self._lege_ab_versuch(w['herkunft'], m, w['paket'])
            if ok:
                zaehle('nachgeholt')
                log('  %s  NACHGEHOLT (zuvor nicht abgelegt)' % m[:8])
                del self.wartend[m]
                w['herkunft']['obj'].loesche_frage(m)
            elif fehler == 'verfallen':
                # Erst jetzt, beim Ablegen, als verfallen erkannt -- auch
                # dann lohnt kein weiterer Versuch mehr.
                del self.wartend[m]

        # JEDEN Weg mit Rolle "frage"/"beide" abklopfen -- der Agent weiss
        # ja nicht im Voraus, welchen Weg ein Client fuer die naechste Marke
        # waehlt (siehe Gespraech ueber Lastverteilung). Ein Weg, der gerade
        # ausfaellt, blockt dabei NICHT die anderen: Genau dafuer gibt es den
        # Kreislauf-Unterbrecher.
        for herkunft in self.transporte:
            if herkunft['rolle'] not in ('frage', 'beide'):
                continue
            if not self.gesundheit.verfuegbar(herkunft['name'], jetzt):
                continue

            marken, fehler = herkunft['obj'].hole_offene_marken(self.erledigt)
            if marken is None:
                # Zaehlung/Meldung geschah schon im Transportweg selbst
                # (PHP) bzw. bleibt dort namenlos (WebDAV) -- hier zaehlt
                # nur die Gesundheit, damit ein dauerhaft toter Weg nicht
                # bei jedem Durchgang erneut seine volle Frist abwartet.
                self.gesundheit.fehlschlag(herkunft['name'], jetzt)
                continue
            self.gesundheit.erfolg(herkunft['name'])

            for marke in marken:
                if marke in self.erledigt:
                    continue    # ueber einen anderen Weg schon aufgetaucht
                self.erledigt[marke] = jetzt
                self.bearbeite_marke(herkunft, marke, jetzt)

    def _waehle_antwortweg(self, herkunft):
        """Welcher Transportweg bekommt die Antwort?

        Erlaubt der Weg, ueber den die Frage hereinkam, auch Antworten
        (Rolle "antwort"/"beide") UND ist er gerade gesund, bleibt die
        ganze Marke auf einem Weg -- der einfachste Fall.

        Sonst (reiner Frage-Weg, oder der Herkunftsweg ist gerade gesperrt)
        wird unter den brauchbaren Antwortwegen im Rundlauf gewaehlt, nicht
        immer derselbe zuerst -- das verteilt die Last, statt sie auf einen
        einzigen "ersten" Weg zu haeufen (siehe Lastverteilungs-Gespraech).
        Gibt keinen brauchbaren Weg zurueck (None), wenn keiner gesund und
        zulaessig ist.
        """
        jetzt = time.time()
        if herkunft['rolle'] in ('antwort', 'beide') \
                and self.gesundheit.verfuegbar(herkunft['name'], jetzt):
            return herkunft

        kandidaten = [t for t in self.transporte
                      if t['rolle'] in ('antwort', 'beide')
                      and self.gesundheit.verfuegbar(t['name'], jetzt)]
        if not kandidaten:
            return None
        gewaehlt = kandidaten[self._antwort_zeiger % len(kandidaten)]
        self._antwort_zeiger += 1
        return gewaehlt

    def hole_fragestuecke(self, herkunft, marke, umschlag):
        """Setzt eine gestueckelte Frage zusammen (Hochladen).

        Spiegelbild der Antwortstueckelung, nur in die andere Richtung. Die
        Pruefungen sind dieselben und aus demselben Grund: Am 02.09.2026 hat
        `mod_speling` eine Abfrage stillschweigend auf eine fremde Datei
        umgeleitet. Wer Marke und Stuecknummer im Inhalt nicht nachprueft,
        setzt eine verfaelschte Datei zusammen, ohne dass ein Fehler
        entsteht.

        Der Dateiname wird GELESEN, nie gebaut -- er traegt vier abgeleitete
        Zeichen, die der Agent nicht erraten soll.
        """
        if not hasattr(herkunft['obj'], 'hole_frage_stueck'):
            # Stueckelung ist eine PHP-Eigenheit (siehe MAX_STUECK-Kommentar
            # in transport.py) -- ueber WebDAV kann eine gestueckelte Frage
            # gar nicht erst entstanden sein. Kommt sie trotzdem, ist das
            # kein Programmfehler, sondern ein Client, der sich nicht an
            # das Protokoll haelt.
            zaehle('frage_stueck_fehler')
            log('  %s  Gestueckelte Frage ueber "%s" -- dieser Weg stueckelt '
                'nicht.' % (marke[:8], herkunft['name']))
            return None
        n = umschlag.get('nutzlast') or {}
        teile = umschlag.get('teile', 1)
        liste = n.get('stuecke')
        if not isinstance(liste, list) or len(liste) != teile:
            zaehle('frage_stueck_fehler')
            log('  %s  Verzeichnis nennt %s Stuecke, angekuendigt %r'
                % (marke[:8],
                   len(liste) if isinstance(liste, list) else '?', teile))
            return None

        teil = [None] * teile
        for e in liste:
            if not isinstance(e, dict):
                zaehle('frage_stueck_fehler')
                return None
            datei = e.get('datei', '')
            nr = e.get('teil')
            if not isinstance(datei, str) or not datei.startswith('fstueck_') \
                    or '/' in datei or '\\' in datei:
                zaehle('frage_stueck_fehler')
                log('  %s  Stueck mit unbrauchbarem Dateinamen' % marke[:8])
                return None
            ok, roh, grund = herkunft['obj'].hole_frage_stueck(datei)
            if not ok:
                zaehle('frage_stueck_fehler')
                log('  %s  Fragestueck %r: %s' % (marke[:8], nr, grund))
                return None
            try:
                st = json.loads(roh.decode('utf-8'))
            except ValueError:
                zaehle('frage_stueck_fehler')
                return None
            if not isinstance(st, dict) or st.get('marke') != marke \
                    or st.get('teil') != nr or st.get('teile') != teile:
                zaehle('frage_stueck_fehler')
                log('  %s  Fragestueck %r passt nicht (Marke/Nummer) -- '
                    'Umleitung im Spiel?' % (marke[:8], nr))
                return None
            if not isinstance(nr, int) or not 0 <= nr < teile:
                zaehle('frage_stueck_fehler')
                return None
            teil[nr] = st.get('nutzlast', '')

        if any(t is None for t in teil):
            zaehle('frage_stueck_fehler')
            log('  %s  Es fehlt ein Fragestueck' % marke[:8])
            return None
        return ''.join(teil)

    def entschluessele(self, marke, nutzlast, verfahren='noise_ik'):
        """Macht aus einem undurchsichtigen Block eine Frage.

        Rueckgabe: (sitzung, nutzlast) oder (None, None), wenn etwas nicht
        stimmte. Der Grund wird gezaehlt und genannt -- aber NICHT nach
        aussen beantwortet.

        WARUM KEINE FEHLERANTWORT: Wir haben in diesem Fall gar keinen
        Sitzungsschluessel, koennten also nur unverschluesselt antworten.
        Das waere eine Auskunft an jemanden, der sich nicht ausweisen konnte
        -- und der Betreiber erfaehrt es ohnehin aus dem Protokoll, wo es
        hingehoert. Der Client laeuft in seinen Zeitablauf, und das ist die
        richtige Auskunft: es kam nichts zurueck.
        """
        import krypto

        chiffre = nutzlast.get('chiffre') if isinstance(nutzlast, dict) else None
        if not isinstance(chiffre, str) or not chiffre:
            zaehle('krypto_form')
            einmal('krypto-form', '  Verschluesselte Frage ohne `chiffre`.')
            return None, None
        try:
            m1 = base64.b64decode(chiffre, validate=True)
        except (binascii.Error, ValueError):
            zaehle('krypto_form')
            einmal('krypto-b64', '  `chiffre` ist kein gueltiges Base64.')
            return None, None
        if len(m1) < 32:
            zaehle('krypto_form')
            return None, None

        # ZUERST die Wiederholung pruefen, DANN rechnen. Der fluechtige
        # Schluessel steht unverschluesselt am Anfang und ist je Vorgang neu
        # -- also die natuerliche Kennung. Wer erst entschluesselt und dann
        # prueft, laesst sich die Arbeit doppelt aufhalsen, und genau darauf
        # zielt eine Wiedereinspielung.
        if not self.schutz.neu(m1[:32]):
            zaehle('wiederholung')
            log('  %s  WIEDERHOLUNG abgewiesen -- dieselbe Frage schon gesehen'
                % marke[:8])
            return None, None

        try:
            aead = 'AESGCM' if verfahren == 'noise_ik_aes' else 'ChaChaPoly'
            hs = krypto.HandshakeIK(False, PROLOG, self.a.privat, aead=aead)
            klartext = hs.lies_nachricht1(m1)
        except krypto.KryptoFehler:
            zaehle('krypto_abgewiesen')
            einmal('krypto-ab',
                   '  Frage nicht entschluesselbar. Entweder war sie nicht '
                   'fuer diesen Agenten bestimmt,')
            einmal('krypto-ab2',
                   '  oder Client und Agent haben verschiedene Schluessel.')
            return None, None

        # Der Absender steht erst JETZT fest -- vorher war er nur behauptet.
        if hs.rs not in self.a.clients:
            zaehle('client_unbekannt')
            # DEN GANZEN SCHLUESSEL nennen, nicht die ersten sechzehn Zeichen.
            #
            # Genau hier steht der Betreiber, wenn er ein neues Geraet
            # einrichtet -- und ein abgeschnittener Schluessel ist dann
            # wertlos: Man kann ihn nicht eintragen. Die Meldung soll die
            # Zeile liefern, die gebraucht wird, nicht ein Fragment davon.
            #
            # Er ist OEFFENTLICH; ihn zu protokollieren verraet nichts.
            #
            # Je Schluessel nur einmal, sonst fuellt ein hartnaeckiger
            # Fremder das Protokoll.
            einmal('fremd-' + hs.rs.hex(),
                   '  %s  ABSENDER NICHT ZUGELASSEN.' % marke[:8])
            einmal('fremd2-' + hs.rs.hex(),
                   '    Wenn das ein eigenes Geraet ist, diesen Wert in die '
                   'clients-Liste')
            einmal('fremd3-' + hs.rs.hex(),
                   '    der config.toml eintragen und den Agenten neu starten:')
            einmal('fremd4-' + hs.rs.hex(), '      %s' % hs.rs.hex())
            return None, None

        try:
            frage = json.loads(klartext.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            zaehle('krypto_form')
            einmal('krypto-json', '  Entschluesselte Frage ist kein JSON.')
            return None, None
        return hs, frage

    def bearbeite_marke(self, herkunft, marke, jetzt):
        # `frage_` und `antwort_` statt `f_`/`a_`: Am 02.09.2026 auf IONOS
        # gemessen -- mod_speling haelt zwei Namen, die sich um EIN Zeichen
        # unterscheiden, fuer einen Tippfehler und leitet per HTTP 301 um.
        # (Jeder Transportweg kennt diesen Namen selbst -- siehe
        # transport.PhpTransport.hole_frage/WebDavTransport.hole_frage. Der
        # PHP-Weg zaehlt/meldet 'frage_unlesbar' bei Fehlschlag bereits
        # selbst; beim WebDAV-Weg genuegt ein stiller Rueckzug, es gibt
        # kein Gegenstueck zu "Umschlag falsch benannt".)
        gefunden, umschlag, grund = herkunft['obj'].hole_frage(marke)
        if not gefunden:
            if herkunft['obj'].art != 'php':
                zaehle('frage_unlesbar')     # PHP zaehlt das selbst, siehe oben
            self.gesundheit.fehlschlag(herkunft['name'], jetzt)
            return
        self.gesundheit.erfolg(herkunft['name'])

        # Umschlag pruefen. Eine unbekannte Fassung wird ABGEWIESEN, nicht
        # gedeutet: Ein Agent, der raet, tut irgendwann etwas Falsches und
        # meldet es nicht.
        if umschlag.get('v') != VERSION:
            zaehle('fassung_falsch')
            einmal('fassung', '  Frage mit Protokollfassung %r -- erwartet %d. '
                              'Abgewiesen, nicht gedeutet.'
                   % (umschlag.get('v'), VERSION))
            return
        uk = umschlag.get('krypto', 'keine')
        # Die Konfiguration sagt OB verschluesselt wird, der Umschlag sagt
        # WOMIT. Zwei Suiten sind zugelassen, weil der Browser kein
        # ChaCha20-Poly1305 kann -- inhaltlich sind sie gleichwertig.
        erwartet = (('noise_ik', 'noise_ik_aes') if self.a.verfahren == 'noise_ik'
                    else ('keine',))
        if uk not in erwartet:
            # Auch der GEGENFALL wird abgewiesen: Steht die Konfiguration auf
            # "noise_ik" und kommt eine unverschluesselte Frage, ist das kein
            # Rueckfall auf Klartext, sondern ein Fehler. Wer hier nachgibt,
            # hat eine Verschluesselung, die sich abschalten laesst, indem man
            # sie weglaesst.
            zaehle('krypto_unbekannt')
            einmal('krypto', '  Frage mit Verfahren %r -- erwartet %r. '
                             'Abgewiesen, nicht gedeutet.'
                   % (uk, ' oder '.join(erwartet)))
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
        sitzung = None

        if uk != 'keine':
            # Gestueckelte Frage: erst zusammensetzen, dann entschluesseln.
            # Andersherum ginge nicht -- ein halbes Chiffrat ist kein
            # Chiffrat, und genau das ist der Sinn: Wer ein Stueck weglaesst
            # oder vertauscht, macht das Ganze unbrauchbar, statt einen Teil
            # davon zu veraendern.
            if umschlag.get('teile', 1) > 1:
                zusammen = self.hole_fragestuecke(herkunft, marke, umschlag)
                if zusammen is None:
                    return
                nutzlast = {'chiffre': zusammen}
            sitzung, nutzlast = self.entschluessele(marke, nutzlast, uk)
            if sitzung is None:
                return          # Grund wurde dort schon gezaehlt und genannt

        t0 = time.time()
        antwort = self.verteile(nutzlast)
        dauer = time.time() - t0

        ok, fehler, paket = self.lege_ab(herkunft, marke, antwort, sitzung)
        if ok:
            n = nutzlast if isinstance(nutzlast, dict) else {}
            log('  %s  %-10s %-8s %-30s %6d Z.  %.1fs' % (
                marke[:8], str(n.get('dienst', '?'))[:10],
                str(n.get('aktion', '?'))[:8],
                str(antwort.get('titel', ''))[:30],
                len(antwort.get('inhalt', '')), dauer))
            # Aufraeumen, sobald die Antwort sicher abgelegt ist. Beim
            # PHP-Weg ein No-Op (relay.php raeumt selbst ueber MARKE_TTL
            # weg) -- beim WebDAV-Weg dagegen noetig: dort gibt es KEIN
            # serverseitiges Verfallsdatum, eine liegengelassene Frage
            # bliebe fuer immer stehen und wuerde bei jedem Neustart des
            # Gedaechtnisses (`erledigt`, alle 600s) ERNEUT bearbeitet.
            # Am 07.09.2026 im Mischbetrieb-Test genau so gefunden: eine
            # WebDAV-Frage aus einem laengst erledigten Vorgang tauchte
            # Minuten spaeter wieder auf, weil niemand sie je geloescht
            # hatte.
            herkunft['obj'].loesche_frage(marke)
        elif fehler == 'verfallen' or paket is None:
            # 'verfallen': die Marke selbst ist abgelaufen -- ein
            # spaeterer Versuch wuerde nur denselben Grund erneut liefern.
            # `paket is None`: schon das VERSCHLUESSELN ist gescheitert
            # (siehe `_verschluessele_antwort`) -- ohne fertiges Paket gibt
            # es nichts, das ein Nachholversuch ablegen koennte, ohne die
            # Sitzung ein zweites Mal zu verbrauchen. In beiden Faellen:
            # nichts zu merken.
            pass
        else:
            # Die Antwort ist fertig VERSCHLUESSELT (das `paket` ist in
            # sich abgeschlossen), konnte aber (noch) nicht abgelegt werden
            # (Transportweg gerade unerreichbar, zu gross fuer DIESEN Weg,
            # kein zulaessiger Weg frei). Ohne dieses Gedaechtnis waere sie
            # fuer immer verloren -- kein spaeterer Durchgang wuerde es je
            # wieder versuchen. `durchgang()` holt das am Anfang jedes
            # weiteren Umlaufs nach, indem es GENAU dieses Paket erneut an
            # `_lege_ab_versuch` gibt (nie an `lege_ab` -- das wuerde neu
            # verschluesseln und die Sitzung ein zweites Mal verbrauchen).
            zaehle('antwort_zurueckgestellt')
            log('  %s  Ablage fehlgeschlagen ("%s") -- fuer spaeteren '
                'Versuch vorgemerkt.' % (marke[:8], fehler))
            self.wartend[marke] = {'herkunft': herkunft, 'paket': paket,
                                    'seit': time.time()}

    # -------------------------------------------------------- Hauptlauf

    def lauf(self):
        for t in self.transporte:
            ort = (t['obj'].schlange_url if t['obj'].art == 'php'
                   else t['obj'].basis)
            log('Transportweg "%s" (%s, Rolle %s): %s'
                % (t['name'], t['obj'].art, t['rolle'], ort))
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
                              'antwort_zu_gross', 'schlange_verpasst',
                              'krypto_form', 'krypto_abgewiesen',
                              'client_unbekannt', 'wiederholung',
                              'krypto_fehler', 'antwort_zurueckgestellt',
                              'kein_antwortweg'))}
                abrufe = ZAEHLER.get('poll_ok', 0) + ZAEHLER.get('poll_304', 0)
                log('Stand: %d beantwortet, %d Abrufe (%d davon 304). %s' % (
                    ZAEHLER.get('beantwortet', 0), abrufe,
                    ZAEHLER.get('poll_304', 0),
                    ('FEHLER: ' + str(fehler)) if fehler else 'keine Fehler.'))

            time.sleep(self.a.poll_abstand * random.uniform(0.8, 1.3))


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
                   lambda: transport.zerlege('hallo') == ['hallo']))
    faelle.append(('leerer Text ergibt ein leeres Stueck',
                   lambda: transport.zerlege('') == ['']))
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
            st = transport.zerlege(t)
            if ''.join(st) != t:
                return False
            for s in st:
                if len(s.encode('utf-8')) > transport.PHP_MAX_STUECK:
                    return False
                if len(json.dumps(s, ensure_ascii=False).encode('utf-8')) \
                        > transport.PHP_MAX_JSON:
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

    if getattr(aufbau, 'basis_ohne_tls', False):
        log('ACHTUNG: Die Basis ist http, nicht https.')
        log('  Frage und Antwort sind trotzdem verschluesselt -- ein Mitleser')
        log('  sieht Rauschen. Offen liegt allein das Geheimnis, mit dem')
        log('  dieser Agent beim Vermittler schreiben darf. Wer es abfaengt,')
        log('  kann stoeren, aber nichts mitlesen: gefaelschte Antworten')
        log('  scheitern beim Client an der Noise-Pruefung.')

    # Die Kennung im Klartext beim Start ausgeben, nicht nur in der
    # Konfiguration lassen: Sie ist das Einzige an diesem Agenten, das
    # gegenueber dem Anbieter etwas ANDERES behauptet, als er ist. Wer
    # das nicht will, soll es sehen, ohne danach suchen zu muessen.
    log('Kennung: %s' % netz.KENNUNG)
    if not aufbau.kennung:
        log('  Vorgabe -- gibt sich als Browser aus. Umzustellen mit')
        log('  [relay] kennung, Abwaegung in SICHERHEIT.md.')

    if aufbau.zert_pin:
        log('TLS: Schluessel des Servers festgenagelt (%s...)'
            % aufbau.zert_pin[:26])
        log('  Kein Wurzelzertifikat noetig, dafuer genau EIN erlaubter')
        log('  Gegenueber. Wechselt der Hoster ihn, bricht der Agent ab,')
        log('  statt weiterzumachen.')

    if aufbau.verfahren == 'noise_ik':
        import krypto
        log('Verschluesselung: Noise IK  (%d zugelassene Client-Schluessel)'
            % len(aufbau.clients))
        log('  oeffentlicher Schluessel dieses Agenten -- gehoert in die')
        log('  Konfiguration des Clients, von Hand zu uebertragen:')
        log('    %s' % krypto._oeffentlich(aufbau.privat).hex())
    else:
        log('Verschluesselung: KEINE. Alles, was durch diesen Kanal geht,')
        log('  liegt fuer jeden lesbar auf dem Webspace.')

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
        if ok and getattr(h, 'virenscan_befehl', None) == [] and h.ART == 'datei':
            log('               ACHTUNG: kein Virenscan konfiguriert -- '
                'hochgeladene Dateien werden ungeprueft abgelegt.')
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
