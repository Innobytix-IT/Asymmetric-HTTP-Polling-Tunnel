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
import re
import sys
import time

import handler as handler_paket
import netz

VERSION = 1

# Der Prologue bindet den Handshake an DIESES Protokoll. Beide Seiten muessen
# denselben Wert nehmen; weicht er ab, scheitert der Handshake, statt dass
# eine Nachricht aus einem anderen Zusammenhang hier durchginge.
PROLOG = b'AHPT-Privat/1'

# Muessen zu den Konstanten in relay.php passen. Weichen sie ab, weist der
# Vermittler mit 413 ab -- was der Agent zwar meldet, aber erst im Betrieb.
MAX_STUECK      = 49152     # Bytes je Stueck, dekodiert
MAX_JSON        = 60000     # Bytes je POST-Rumpf, damit MAX_RUMPF (65536) haelt
MAX_TEILE       = 256

# Gemessen 05./06.09.2026 gegen bplaced: Bei Last auf dem Webspace weist
# das PHP-Kontingent ein einzelnes Stueck gelegentlich ab, obwohl Absender
# und Inhalt in Ordnung sind -- dieselbe Gleichzeitigkeitsgrenze wie bei
# IONOS, nur unregelmaessig statt zuverlaessig. Ein Stueck deshalb sofort
# aufzugeben, wirft eine ganze Uebertragung wegen eines einzelnen
# Ausrutschers weg. STUECK_WIEDERHOLUNGEN wiederholt NUR das eine Stueck,
# nicht die ganze Antwort -- bei 87 Stuecken je 4-MiB-Block waere ein
# Neuanfang bei jedem Ausrutscher praktisch aussichtslos.
STUECK_WIEDERHOLUNGEN = 5
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


# ----------------------------------------------------------- Messfenster
#
# WOZU
# ----
# Der Rundlauf-Test (einrichten.py) legt eine Frage ab, die NIEMAND
# entschluesseln kann -- sie ist nur Fuellstoff, damit der Vermittler eine
# Marke oeffnet, unter der sich Stuecke ablegen und wieder abholen lassen.
#
# Ohne diese Datei sieht der laufende Agent genau das, was er sehen soll,
# wenn ihn jemand angreift: eine undurchsichtige Frage, die er nicht
# aufbekommt. Er zaehlt `krypto_abgewiesen` hoch -- und dieser Zaehler ist
# nach der eigenen Zusage im Kopf dieser Datei im gesunden Betrieb NULL.
# Ein Diagnosewerkzeug, das den Befund faelscht, den es liefern soll, ist
# schlimmer als keines.
#
# WARUM EIN ZEITFENSTER UND NICHT DIE MARKE
# ------------------------------------------
# Weil die Marke der VERMITTLER vergibt, nicht der Fragende: Sie steht erst
# fest, wenn die Frage schon in der Warteschlange liegt. Zwischen dem
# Ablegen und dem Aufschreiben laege ein Rennen von wenigen Millisekunden
# gegen einen Abfragetakt von einer Sekunde -- selten verloren, aber eben
# nicht nie. Das Fenster wird VORHER gesetzt, damit gibt es kein Rennen.
#
# WAS DAS FENSTER NICHT TUT
# --------------------------
# Es unterdrueckt keine Bearbeitung. Echte Fragen laufen waehrenddessen
# voellig normal durch -- nur das ZAEHLEN und MELDEN einer nicht
# entschluesselbaren Frage unterbleibt. Der schlimmste denkbare Preis ist,
# dass in diesen wenigen Sekunden auch ein echter Fremdversuch ungezaehlt
# bliebe.

# Der Ort steht NEBEN DER KONFIGURATION, nicht stur unter ~/.ahpt. In der
# Regel ist das dasselbe -- aber eben nur in der Regel: Wer den Agenten mit
# `--konfig woanders/agent.toml` startet, haette sonst zwei Seiten, die auf
# verschiedene Dateien schauen und sich nie treffen. Genau so ist es beim
# Erproben am 08.09.2026 passiert, und der Zaehler stand danach auf 2 statt
# auf 1. main() setzt den Wert; die Vorgabe hier gilt nur, falls jemand
# dieses Modul einbindet, ohne es zu starten.
MESSFENSTER = os.path.expanduser('~/.ahpt/messung_laeuft')


def messung_laeuft():
    """Laeuft gerade ein Rundlauf-Test dieses Rechners?

    In der Datei steht, bis wann. Ein Ablaufzeitpunkt statt eines blossen
    Vorhandenseins, weil ein abgestuerztes Messwerkzeug seine Datei sonst
    liegen laesst -- und dann waere der Zaehler dauerhaft blind.
    """
    try:
        with open(MESSFENSTER) as f:
            return time.time() < float(f.read().strip())
    except (OSError, ValueError):
        return False


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

        # SCHREIBENDE AKTIONEN NUR VERSCHLUESSELT.
        #
        # `lege` und `neuer_ordner` legen Bytes auf dem Heimserver ab. Ohne
        # Verschluesselung koennte JEDER, der die Adresse des Webspace kennt,
        # eine solche Frage einstellen -- der Vermittler kann Freund und Feind
        # nicht unterscheiden, und ohne Noise gibt es keinen Absender, den man
        # pruefen koennte.
        #
        # Das wird BEIM START abgewiesen, nicht im Betrieb: Ein Agent, der
        # monatelang mit offener Schreibfreigabe laeuft, faellt niemandem auf,
        # bevor es zu spaet ist.
        #
        # HIER UNTEN, NICHT WEITER OBEN. Bis zum 10.09.2026 stand diese
        # Pruefung VOR der Schleife, die `self.dienste` ueberhaupt erst
        # anlegt. Sie lief damit in ein AttributeError -- und zwar bei JEDER
        # Konfiguration ohne [krypto]-Abschnitt, denn die Vorgabe fuer
        # `verfahren` ist "keine". Wer die Anleitung befolgt und den
        # Abschnitt weglaesst, bekam einen Python-Auszug statt der Erklaerung,
        # die hier unten steht. Gefunden hat es `durchstich_lokal.py`, das
        # genau so eine Konfiguration schreibt -- die Pruefung war rot, nur
        # hat sie niemand laufen lassen.
        #
        # `lege_block` gehoert dazu. Es legt genauso Bytes ab wie `lege`,
        # nur ueber mehrere Fragen verteilt; es zu vergessen hiesse, die
        # Schranke ueber den Blockweg umgehen zu koennen.
        SCHREIBT = {'lege', 'lege_block', 'neuer_ordner'}
        if self.verfahren == 'keine':
            for name, (h, erlaubte) in self.dienste.items():
                schlimm = SCHREIBT & set(erlaubte)
                if schlimm:
                    raise KonfigFehler(
                        'Dienst "%s" gibt %s frei, aber [krypto] verfahren ist '
                        '"keine".\n'
                        '         Schreibende Aktionen ohne Verschluesselung '
                        'heissen: jeder, der die Adresse kennt, darf Dateien '
                        'auf deinem Heimserver ablegen.\n'
                        '         Entweder verfahren = "noise_ik" setzen oder '
                        'die Aktion streichen.'
                        % (name, ', '.join(sorted(schlimm))))

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

    def lege_ab(self, marke, antwort, sitzung=None):
        """Legt die Antwort ab -- verschluesselt und gestueckelt, wenn noetig.

        REIHENFOLGE IST VERBINDLICH: erst alle Stuecke, dann das Verzeichnis.
        Andersherum verwiese ein Verzeichnis auf Dateien, die es noch nicht
        gibt, und der Besucher setzte eine halbe Antwort zusammen, ohne dass
        ein Fehler entstuende.

        BEI VERSCHLUESSELUNG wird ZUERST verschluesselt und DANN gestueckelt.
        Andersherum -- Stuecke einzeln verschluesseln -- waere jedes Stueck
        fuer sich angreifbar: Ein Angreifer koennte sie umsortieren oder
        einzelne weglassen, und jedes fuer sich bliebe gueltig. So gibt es
        genau einen Block, und wer daran etwas aendert, macht ihn unbrauchbar.
        """
        inhalt = antwort.get('inhalt', '')

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
                return False
            inhalt = base64.b64encode(m2).decode('ascii')

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

        verf = 'keine' if sitzung is None else (
            'noise_ik_aes' if sitzung.ss.cs.aead == 'AESGCM' else 'noise_ik')

        if teile > 1:
            for i, s in enumerate(stuecke):
                for versuch in range(1, STUECK_WIEDERHOLUNGEN + 1):
                    code, daten = netz.sende_json(
                        self.relay_url + '?action=stueck',
                        {'v': VERSION, 'krypto': verf, 'marke': marke,
                         'teil': i, 'teile': teile, 'nutzlast': s},
                        self.geheimnis, zaehler=ZAEHLER)
                    if code == 200 and daten.get('ok'):
                        break
                    zaehle('stueck_wiederholt')
                    if versuch < STUECK_WIEDERHOLUNGEN:
                        time.sleep(min(5.0, 0.5 * (2 ** (versuch - 1))))
                else:
                    # Alle Versuche fuer DIESES Stueck verbraucht. Aufgeben,
                    # aber KEIN Verzeichnis ablegen. Lieber gar keine Antwort
                    # als eine, die auf Luecken zeigt.
                    zaehle('stueck_fehler')
                    log('  %s  Stueck %d/%d nicht abgelegt nach %d Versuchen: '
                        'HTTP %s %s'
                        % (marke[:8], i + 1, teile, STUECK_WIEDERHOLUNGEN,
                           code, daten.get('fehler', '')))
                    return False

        if sitzung is not None:
            # Nach aussen bleibt genau ein Feld uebrig. Alles andere steckt
            # im Block.
            nutz = {'chiffre': '' if teile > 1 else stuecke[0]}
        else:
            nutz = {k: antwort.get(k, '') for k in
                    ('gefunden', 'titel', 'quelle', 'inhalt_typ')}
            nutz['gefunden'] = bool(antwort.get('gefunden', False))
            nutz['inhalt_typ'] = antwort.get('inhalt_typ', 'text')
            nutz['inhalt'] = '' if teile > 1 else stuecke[0]

        code, daten = netz.sende_json(
            self.relay_url + '?action=antwort',
            {'v': VERSION, 'krypto': verf, 'marke': marke,
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

    def hole_fragestuecke(self, marke, umschlag):
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
            code, roh, _ = netz.hole('%s/ahpt/%s' % (self.a.basis, datei))
            if code != 200:
                zaehle('frage_stueck_fehler')
                log('  %s  Fragestueck %r: HTTP %s' % (marke[:8], nr, code))
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
            # Waehrend einer Messung ist das der Fuellstoff des eigenen
            # Rundlauf-Tests, kein Fremder. Siehe Messfenster oben.
            if messung_laeuft():
                return None, None
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
                zusammen = self.hole_fragestuecke(marke, umschlag)
                if zusammen is None:
                    return
                nutzlast = {'chiffre': zusammen}
            sitzung, nutzlast = self.entschluessele(marke, nutzlast, uk)
            if sitzung is None:
                return          # Grund wurde dort schon gezaehlt und genannt

        t0 = time.time()
        antwort = self.verteile(nutzlast)
        dauer = time.time() - t0

        if self.lege_ab(marke, antwort, sitzung):
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
                              'antwort_zu_gross', 'schlange_verpasst',
                              'krypto_form', 'krypto_abgewiesen',
                              'client_unbekannt', 'wiederholung',
                              'krypto_fehler'))}
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
        # Das Messfenster liegt neben der Konfiguration -- siehe oben.
        global MESSFENSTER
        MESSFENSTER = os.path.join(
            os.path.dirname(os.path.abspath(os.path.expanduser(a.konfig))),
            'messung_laeuft')
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
