#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
einrichten.py -- Einrichtungs-Assistent fuer AHPT Cloud

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Der Weg von einem frischen Heimserver bis zur laufenden Privaten Cloud
besteht aus einer Handvoll Schritte, die man einzeln lesen und richtig
tippen muss. Wer das schon gemacht hat, weiss wie es geht. Wer es zum
ersten Mal macht, verliert die Uebersicht.

Dieser Assistent macht die Schritte SELBST, mit der Bestaetigung des
Nutzers. Er erzeugt Schluessel wirklich, schreibt `agent_privat.toml`
wirklich, laedt `relay.php` wirklich hoch -- und pruefte jeden Zwischen-
stand, bevor er weitergeht. Kein Kopieren, kein Vertippen.

AUFBAU
------
Ein kleiner HTTP-Server hoert auf ALLEN Adressen dieses Rechners
(127.0.0.1 UND der LAN-Adresse). Zugang haben nur Anfragen mit dem
Zugangs-Token, das beim Start erzeugt und in der Konsole ausgegeben wird:

    http://<lan-adresse>:8771/?t=<token>

Der Nutzer oeffnet die URL im Browser -- kann auf demselben Rechner sein,
kann sein Laptop im gleichen WLAN sein.

Der Assistent HANDELT statt zu erklaeren: was er tut, sieht der Nutzer
danach. Er speichert seinen Stand in ~/.ahpt/einrichten_stand.json, so
dass der Nutzer den Browser schliessen und spaeter fortfahren kann.

SICHERHEIT
----------
* Das Zugangs-Token wird beim Start neu erzeugt (32 Byte Zufall).
* Ohne Token -> HTTP 403. Kein Umweg.
* Das FTP-Passwort geht per HTTPS-freiem HTTP durch. Das ist tragbar,
  weil der Server nur auf localhost/LAN hoert -- nicht ans Internet.
  Das Passwort wird SOFORT nach ~/.netrc geschrieben (Modus 0600) und
  danach aus jedem Ort geloescht. Es wird nie geloggt, nie zurueckgegeben.
* Der Assistent laesst sich nur EINMAL gleichzeitig starten.
"""

import argparse
import ipaddress
import io
import json
import os
import re
import secrets
import socket
import socketserver
import subprocess
import sys
import textwrap
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler

HIER = os.path.dirname(os.path.abspath(__file__))
KONFIG_ORDNER = os.path.expanduser('~/.ahpt')
STANDDATEI = os.path.join(KONFIG_ORDNER, 'einrichten_stand.json')

# ---------------------------------------------------------------- Zustand
#
# Ein einziger Zustand fuer den ganzen Assistenten, geschuetzt durch ein
# Schloss. Alles was zwischen Neustarts erhalten bleibt, steht in
# STANDDATEI -- das Token gehoert bewusst NICHT dazu.

_schloss = threading.Lock()
_token = None
_port = 8771      # wird beim Start auf den tatsaechlichen Wert gesetzt
_stand = {}


def stand_lesen():
    if not os.path.isfile(STANDDATEI):
        return {}
    try:
        with open(STANDDATEI, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def stand_schreiben(neu):
    """Atomar schreiben. Halb geschriebene Konfig ist schlimmer als keine."""
    os.makedirs(KONFIG_ORDNER, exist_ok=True)
    tmp = STANDDATEI + '.' + secrets.token_hex(4) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(neu, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STANDDATEI)


# ---------------------------------------------------- Netz-Adressen finden
#
# Der Assistent zeigt dem Nutzer eine URL, die er im Browser oeffnen soll.
# Wenn er auf demselben Rechner sitzt, ist 127.0.0.1 richtig. Wenn er
# per Laptop drauf zugreift, braucht er die LAN-Adresse. Beides zeigen.

def eigene_adressen():
    """LAN-Adressen dieses Rechners, ohne loopback."""
    liste = ['127.0.0.1']
    try:
        # Trick: udp-"Verbindung" zu 8.8.8.8 zwingt das Betriebssystem,
        # die passende Absenderadresse zu waehlen -- ohne dass ein Paket
        # gesendet wuerde.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        try:
            s.connect(('8.8.8.8', 80))
            liste.insert(0, s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass

    # Der Trick oben findet nur die Adresse der Standardroute. Steckt das
    # Handy per USB am Rechner und teilt seine Verbindung (USB-Tethering),
    # entsteht eine ZWEITE Schnittstelle -- und ueber die kommt das Handy
    # zurueck, nicht ueber die erste. Ohne sie in der Liste laeuft die
    # Kopplung am Kabel ins Leere.
    #
    # Plattformuebergreifend und ohne Abhaengigkeit bleibt nur der Umweg
    # ueber den eigenen Rechnernamen. Er findet nicht immer alles, aber die
    # Tethering-Adresse taucht dort in aller Regel auf.
    try:
        for eintrag in socket.getaddrinfo(socket.gethostname(), None,
                                          socket.AF_INET):
            liste.append(eintrag[4][0])
    except (OSError, socket.gaierror):
        pass

    # Doppelte raus, Reihenfolge halten. 127.0.0.1 nach hinten: Es traegt
    # nur auf demselben Rechner, und wer koppelt, sitzt am anderen Geraet.
    gesehen = set()
    raus = []
    for a in liste:
        if a not in gesehen:
            gesehen.add(a); raus.append(a)
    return [a for a in raus if a != '127.0.0.1'] +            (['127.0.0.1'] if '127.0.0.1' in gesehen else [])


# ------------------------------------------------------------ Schritt-Logik
#
# Jeder Schritt ist eine Funktion, die JSON zurueckgibt. Fehler werfen
# EinrichtenFehler mit einer Meldung, die der Nutzer LESEN kann -- kein
# stack trace, keine Pfade, die er nicht braucht.

class EinrichtenFehler(Exception):
    pass


def schritt_pruefen(_daten):
    """Voraussetzungen: python3, ahpt-Ordner, Schreibrechte."""
    p = []
    p.append(('Python 3.9 oder neuer', sys.version_info >= (3, 9),
              'derzeit %d.%d' % sys.version_info[:2]))

    # ahpt-Ordner: relay.php, relay_agent.py, handler/datei.py, portal/index.html
    fehlt = [n for n in ('relay.php', 'relay_agent.py',
                         'handler/datei.py', 'portal/index.html')
             if not os.path.exists(os.path.join(HIER, n))]
    p.append(('AHPT-Dateien vollstaendig', not fehlt,
              'fehlt: ' + ', '.join(fehlt) if fehlt else 'alle da'))

    # Schreibrechte auf ~/.ahpt
    try:
        os.makedirs(KONFIG_ORDNER, exist_ok=True)
        probe = os.path.join(KONFIG_ORDNER, '.schreibprobe')
        with open(probe, 'w') as f:
            f.write('x')
        os.unlink(probe)
        schreibbar = True; grund = KONFIG_ORDNER
    except OSError as e:
        schreibbar = False; grund = str(e)
    p.append(('Konfig-Ordner beschreibbar', schreibbar, grund))

    # curl vorhanden -- fuer FTP-Uebertragung
    curl = _hat_befehl('curl')
    p.append(('curl vorhanden', curl,
              'fuer die Uebertragung von relay.php gebraucht'))

    ok = all(x[1] for x in p)
    return {'ok': ok, 'pruefungen': [{'was': a, 'ok': b, 'hinweis': c}
                                     for a, b, c in p]}


def schritt_webspace(daten):
    """Adresse pruefen: ist der Server erreichbar? Wenn schon eine
    relay.php dort liegt -- dessen Selbsttest ansehen."""
    adresse = (daten.get('adresse') or '').strip()
    if not adresse:
        raise EinrichtenFehler('Bitte gib die Adresse ein.')
    adresse = _adresse_normalisieren(adresse)

    grunderreichbar = _webspace_erreichbar(adresse)
    if not grunderreichbar:
        raise EinrichtenFehler(
            'Der Webspace unter %s antwortet nicht. Ist die Adresse '
            'richtig geschrieben? (Ohne "http://" geht auch -- ich '
            'setze es hinzu.)' % adresse)

    relay = _relay_selbsttest(adresse)

    # Stand fortschreiben
    with _schloss:
        _stand['webspace'] = adresse
        _stand['relay_vorhanden'] = relay is not None
        stand_schreiben(_stand)

    return {'adresse': adresse,
            'erreichbar': True,
            'relay_vorhanden': relay is not None,
            'relay_selbsttest': relay,
            'weiter': 'ftp' if relay is not None else 'hochladen'}


def schritt_ftp(daten):
    """FTP-Zugang in ~/.netrc anlegen. Passwort geht raus, wird nicht
    gespeichert -- ausser dort, wo curl es liest."""
    host = (daten.get('host') or '').strip()
    benutzer = (daten.get('benutzer') or '').strip()
    passwort = daten.get('passwort') or ''
    if not host or not benutzer or not passwort:
        raise EinrichtenFehler(
            'Host, Benutzer und Passwort werden alle drei gebraucht.')
    if len(host) > 253 or len(benutzer) > 200 or len(passwort) > 500:
        raise EinrichtenFehler('Zu lange Eingabe.')
    if any(c in benutzer + host for c in '\r\n \t'):
        raise EinrichtenFehler(
            'Weissraum in Host oder Benutzer -- so kann .netrc nicht '
            'geschrieben werden.')

    netrc = os.path.expanduser('~/.netrc')
    _netrc_eintragen(netrc, host, benutzer, passwort)
    del passwort  # nicht laenger als noetig im Speicher halten

    # Probe: klappt ein LIST auf dem Wurzelordner?
    annehmen = bool(daten.get('zertifikat_annehmen'))
    try:
        _ftp_liste(host, annehmen)
    except EinrichtenFehler:
        raise
    except Exception as e:
        raise EinrichtenFehler(
            'FTP-Verbindung steht, aber der Ordner ist nicht auflistbar: '
            '%s' % str(e)[:200])

    with _schloss:
        _stand['ftp_host'] = host
        _stand['ftp_benutzer'] = benutzer
        # Merken, damit das Hochladen gleich weiterlaeuft. Es steht als
        # eigener Wert da und nicht implizit im Erfolg der Probe: Wer spaeter
        # in die Konfiguration schaut, soll sehen, dass hier ein Zertifikat
        # ungeprueft angenommen wird.
        _stand['ftp_zertifikat_annehmen'] = annehmen
        stand_schreiben(_stand)

    return {'ok': True, 'host': host, 'benutzer': benutzer,
            'zertifikat_angenommen': annehmen,
            'weiter': 'hochladen'}


def schritt_hochladen(daten):
    """relay.php und .htaccess auf den Webspace hochladen."""
    roh_ordner = (daten.get('fernordner') or '/privat').strip()
    # Segmentweise pruefen -- dieselbe Disziplin wie _pfad_erlaubt() im
    # Datei-Handler (handler/datei.py). Ohne das koennte ein Wert wie
    # "../../andereseite" relay.php ausserhalb des vorgesehenen Ordners
    # ablegen: ein FTP-Konto sperrt zwar meist den Aufstieg UEBER die
    # eigene Kontowurzel hinaus, aber INNERHALB des eigenen Kontos --
    # etwa in den Ordner einer anderen, unabhaengigen Website desselben
    # Hosting-Vertrags -- gibt es dort keine vergleichbare Schranke.
    # Am 03.09.2026 im Sicherheitsaudit gefunden.
    teile = [t for t in roh_ordner.split('/') if t]
    for t in teile:
        if t in ('.', '..'):
            raise EinrichtenFehler(
                'Zielordner darf keine "." oder ".." Bestandteile '
                'enthalten (gefunden: %r).' % t)
    ordner = '/' + '/'.join(teile) if teile else '/privat'
    host = _stand.get('ftp_host')
    if not host:
        raise EinrichtenFehler(
            'FTP-Zugang fehlt. Bitte den vorigen Schritt ausfuellen.')

    quelle = os.path.join(HIER, 'relay.php')
    if not os.path.isfile(quelle):
        raise EinrichtenFehler(
            'relay.php ist neben mir nicht auffindbar. Wurde der Ordner '
            'unvollstaendig entpackt?')

    # Geheimnis-Datei erzeugen (falls sie es noch nicht gibt) und mit
    # hochladen. Das ist der Schluessel, mit dem der Agent bei relay.php
    # schreiben darf.
    geheimnis_datei = os.path.join(KONFIG_ORDNER, 'geheimnis_privat')
    if not os.path.isfile(geheimnis_datei):
        with open(geheimnis_datei, 'wb') as f:
            os.chmod(geheimnis_datei, 0o600)
            f.write(secrets.token_hex(32).encode('ascii'))
    with open(geheimnis_datei, 'rb') as f:
        geheimnis = f.read().decode('ascii').strip()

    # relay_token.php: PHP-Datei, die das Geheimnis enthaelt.
    token_php = ('<?php return %s;' % json.dumps(geheimnis)).encode('utf-8')

    # relay_state.php: leerer Ausgangszustand.
    state_php = b'<?php return ["stand" => 0, "warteschlange" => []];'

    hoch = [
        ('relay.php', open(quelle, 'rb').read()),
        ('relay_token.php', token_php),
        ('relay_state.php', state_php),
    ]

    ergebnisse = []
    for name, inhalt in hoch:
        ergebnisse.append(_ftp_hochladen(host, ordner + '/' + name, inhalt))

    # Ergebnis pruefen ueber HTTP -- so weiss ich, dass es wirklich liegt.
    adresse = _stand.get('webspace', '')
    if adresse:
        adresse_ordner = adresse.rstrip('/') + ordner
        selbsttest = _relay_selbsttest(adresse_ordner)
        if selbsttest is None:
            raise EinrichtenFehler(
                'Hochgeladen, aber der Selbsttest von relay.php antwortet '
                'nicht. Vielleicht laeuft PHP auf dem Webspace nicht?')

        with _schloss:
            _stand['webspace'] = adresse_ordner
            _stand['relay_vorhanden'] = True
            stand_schreiben(_stand)

        return {'ok': True, 'dateien': [n for n, _ in hoch],
                'selbsttest': selbsttest,
                'adresse': adresse_ordner,
                'weiter': 'schluessel'}

    return {'ok': True, 'dateien': [n for n, _ in hoch],
            'weiter': 'schluessel'}


# ------------------------------------------- Vermittler von Hand hochladen
#
# WARUM ES DIESEN WEG GIBT
# -------------------------
# Der FTP-Weg nimmt dem Nutzer alles ab -- wenn er funktioniert. Er setzt
# aber voraus, dass der Hoster FTP anbietet, dass curl da ist, und dass das
# Passwort durch dieses Netz gehen darf. Nichts davon ist selbstverstaendlich:
# Manche Anbieter haben nur SFTP oder eine Weboberflaeche, in manchen Netzen
# will man kein Passwort im Klartext schicken, und am 07.09.2026 scheiterte
# der FTP-Schritt hier an einem selbstsignierten Zertifikat.
#
# Dann soll niemand feststecken. Die drei Dateien sind klein, und sie
# irgendwo hochzuladen kann jeder, der schon einmal eine Webseite betrieben
# hat. Der Assistent packt sie zusammen, erklaert die Schritte und prueft
# hinterher nach -- was er beim FTP-Weg ohnehin tut.

def vermittler_paket():
    """Die Dateien, die auf den Webspace gehoeren -- als ZIP.

    Dasselbe, was der FTP-Weg hochlaedt. Das Geheimnis wird dabei erzeugt,
    falls es noch keins gibt: Es muss auf BEIDEN Seiten dasselbe sein, und
    der Agent liest es spaeter aus derselben Datei.
    """
    quelle = os.path.join(HIER, 'relay.php')
    if not os.path.isfile(quelle):
        raise EinrichtenFehler(
            'relay.php ist neben mir nicht auffindbar. Wurde der Ordner '
            'unvollstaendig entpackt?')

    geheimnis_datei = os.path.join(KONFIG_ORDNER, 'geheimnis_privat')
    if not os.path.isfile(geheimnis_datei):
        os.makedirs(KONFIG_ORDNER, exist_ok=True)
        with open(geheimnis_datei, 'wb') as f:
            f.write(secrets.token_hex(32).encode('ascii'))
        os.chmod(geheimnis_datei, 0o600)
    with open(geheimnis_datei, 'rb') as f:
        geheimnis = f.read().decode('ascii').strip()

    dateien = [
        ('relay.php', open(quelle, 'rb').read()),
        ('relay_token.php', ('<?php return %s;' % json.dumps(geheimnis)).encode('utf-8')),
        ('relay_state.php', b'<?php return ["stand" => 0, "warteschlange" => []];'),
    ]
    htaccess = os.path.join(HIER, 'htaccess-beispiel')
    if os.path.isfile(htaccess):
        # Im Paket heisst sie .htaccess -- unter dem Namen wird sie gebraucht.
        # Achtung beim Entpacken: Viele Dateimanager blenden Namen mit
        # fuehrendem Punkt aus. Darauf weist die Seite hin.
        dateien.append(('.htaccess', open(htaccess, 'rb').read()))

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, inhalt in dateien:
            z.writestr(name, inhalt)
    return puffer.getvalue(), [n for n, _ in dateien]


def schritt_vermittler_pruefen(daten):
    """Liegt der Vermittler wirklich dort, wo der Nutzer ihn hingelegt hat?

    Dieselbe Pruefung wie am Ende des FTP-Weges, und aus demselben Grund:
    Am 02.09.2026 meldete ein FTP-Programm zweimal einen gruenen Haken,
    waehrend auf dem Server die alte Datei lag. Ein "ich habe hochgeladen"
    des Nutzers ist genauso wenig wert -- gemessen wird ueber HTTP.
    """
    roh = (daten.get('adresse') or _stand.get('webspace') or '').strip()
    if not roh:
        raise EinrichtenFehler(
            'Es fehlt die Adresse des Ordners, in dem relay.php jetzt liegt.')
    adresse = _adresse_normalisieren(roh)

    selbsttest = _relay_selbsttest(adresse)
    if selbsttest is None:
        raise EinrichtenFehler(
            'Unter %s antwortet kein relay.php. Moegliche Gruende: die '
            'Dateien liegen in einem anderen Ordner, sie sind noch nicht '
            'vollstaendig hochgeladen, oder PHP laeuft auf diesem Webspace '
            'nicht.' % adresse)

    with _schloss:
        _stand['webspace'] = adresse
        _stand['relay_vorhanden'] = True
        stand_schreiben(_stand)
    return {'ok': True, 'adresse': adresse, 'selbsttest': selbsttest,
            'weiter': 'schluessel'}


# ------------------------------------------------------ FTP-Hilfen (curl)

def _hat_befehl(name):
    try:
        subprocess.run([name, '--version'],
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _netrc_eintragen(pfad, host, benutzer, passwort):
    """Fuegt einen machine-Eintrag ein oder ersetzt einen bestehenden.
    Modus wird auf 0600 gesetzt, sonst weigert sich curl."""
    zeilen = []
    if os.path.isfile(pfad):
        with open(pfad, encoding='utf-8', errors='replace') as f:
            drin = f.read()
        # Alten Eintrag fuer diesen host entfernen. Ein Eintrag lauft von
        # `machine <host>` bis zum naechsten `machine` oder Dateiende.
        block = re.compile(
            r'(?:^|\n)machine\s+' + re.escape(host)
            + r'\b.*?(?=(?:\nmachine\b|\ndefault\b|\Z))',
            re.DOTALL | re.IGNORECASE)
        drin = block.sub('', drin).strip() + '\n' if drin.strip() else ''
        zeilen.append(drin)
    zeilen.append('machine %s login %s password %s\n'
                  % (host, benutzer, passwort))
    inhalt = ''.join(zeilen)
    # Mode ZUERST auf 0600 setzen, DANN schreiben. Umgekehrt gaebe es einen
    # Augenblick, in dem der Inhalt mit den Standardrechten dasteht.
    fd = os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(inhalt)


def _curl_deuten(kode, stderr):
    """Aus einem curl-Fehlercode eine Meldung machen, die weiterhilft.

    Frueher stand hier bei JEDEM Fehler "Passt Benutzer und Passwort?" --
    auch bei 60, und der hat mit dem Passwort nichts zu tun. Am 07.09.2026
    hat genau das in die Irre gefuehrt: bplaced weist ein selbstsigniertes
    Zertifikat vor, curl bricht ab, und der Nutzer sucht seinen Tippfehler
    im Passwort, das voellig in Ordnung ist.
    """
    kurz = stderr.strip().splitlines()
    kurz = kurz[-1][:200] if kurz else ''
    deutungen = {
        6:  'Der Rechnername liess sich nicht aufloesen. Steht er richtig da?',
        7:  'Keine Verbindung zum FTP-Dienst. Laeuft er, und ist es der '
            'richtige Rechner?',
        9:  'Der Server hat den Zugriff verweigert -- meist ein Pfad, den es '
            'so nicht gibt, oder fehlende Rechte im Konto.',
        28: 'Zeitueberschreitung. Der Server antwortet nicht schnell genug.',
        60: 'ZERTIFIKAT: Der Server weist eines vor, das sich nicht pruefen '
            'laesst -- meist ein selbstsigniertes. Das hat NICHTS mit '
            'Benutzer oder Passwort zu tun. Bei manchen Anbietern (bplaced '
            'zum Beispiel) ist das der Normalfall. Unten laesst sich das '
            'Zertifikat annehmen; die Verbindung bleibt dann verschluesselt, '
            'nur ungeprueft, WER am anderen Ende sitzt.',
        67: 'Anmeldung abgelehnt. Hier passen Benutzer oder Passwort '
            'tatsaechlich nicht.',
        78: 'Die angegebene Datei oder der Ordner existiert dort nicht.',
    }
    return 'FTP: %s (curl-Fehler %d%s)' % (
        deutungen.get(kode, 'curl bricht ab.'), kode,
        ': ' + kurz if kurz else '')


def _ftp_liste(host, zertifikat_annehmen=False):
    """Testet .netrc + FTPS-Verbindung mit einem einfachen LIST."""
    befehl = ['curl', '-sS', '--netrc', '--ssl-reqd']
    if zertifikat_annehmen:
        # Verschluesselt bleibt es, nur ungeprueft. Das ist eine bewusste
        # Entscheidung des Nutzers, kein stiller Rueckfall -- deshalb steht
        # der Schalter in der Oberflaeche und nicht hier fest verdrahtet.
        befehl.append('--insecure')
    befehl.append('ftp://%s/' % host)
    p = subprocess.run(befehl, capture_output=True, timeout=25)
    if p.returncode != 0:
        raise EinrichtenFehler(
            _curl_deuten(p.returncode, p.stderr.decode('utf-8', 'replace')))
    return p.stdout.decode('utf-8', 'replace')


def _ftp_hochladen(host, fernpfad, inhalt):
    """Legt EINEN Inhalt unter fernpfad ab. fernpfad ist bereits
    URL-kodiert oder besteht nur aus harmlosen Zeichen."""
    ferner = urllib.parse.quote(fernpfad, safe='/')
    tmp = os.path.join(KONFIG_ORDNER, '.upload_' + secrets.token_hex(4))
    try:
        with open(tmp, 'wb') as f:
            f.write(inhalt)
        befehl = ['curl', '-sS', '--netrc', '--ssl-reqd', '--ftp-create-dirs']
        if _stand.get('ftp_zertifikat_annehmen'):
            befehl.append('--insecure')
        befehl += ['-T', tmp, 'ftp://%s%s' % (host, ferner)]
        p = subprocess.run(befehl, capture_output=True, timeout=60)
        if p.returncode != 0:
            raise EinrichtenFehler(
                'Hochladen von %s scheiterte. %s'
                % (fernpfad,
                   _curl_deuten(p.returncode,
                                p.stderr.decode('utf-8', 'replace'))))
        return {'pfad': fernpfad, 'bytes': len(inhalt)}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------- Webspace-Kleinigkeiten

def _adresse_normalisieren(a):
    if '://' not in a:
        a = 'http://' + a
    return a.rstrip('/')


def _webspace_erreichbar(basis):
    try:
        r = urllib.request.urlopen(basis + '/', timeout=8)
        r.read(1024); r.close()
        return True
    except Exception:
        # Wurzel kann 403 sein wenn kein Verzeichnislisting; das ist okay.
        try:
            r = urllib.request.urlopen(basis + '/nicht-existent-xyz.html',
                                       timeout=8)
            r.close()
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            return False


def _relay_selbsttest(basis):
    """relay.php nach seinem eigenen Befinden fragen.

    Der Parameter heisst `action`, nicht `was` -- das stand hier jahrelang
    falsch, und die Folge war, dass die Nachpruefung NIE gelang: relay.php
    antwortete mit "Protokollfassung erwartet", der Assistent verstand das
    als "antwortet nicht" und meldete einen Fehlschlag, obwohl alles lag.
    Am 08.09.2026 gefunden, als der haendische Weg dieselbe Pruefung
    benutzte und an einem nachweislich laufenden Vermittler scheiterte.
    """
    try:
        r = urllib.request.urlopen(basis + '/relay.php?action=selbsttest',
                                   timeout=8)
        d = json.loads(r.read())
        return d
    except Exception:
        return None


def schritt_schluessel(_daten):
    """Erzeugt das Schluesselpaar des Agenten -- ODER liest ein
    bestehendes ein. Zweimal erzeugen wuerde die Weissliste des
    Nutzers still ungueltig machen; der Assistent zeigt dann den Weg
    zum Ersetzen, macht es aber nicht von selbst.
    """
    import krypto
    pfad = os.path.join(KONFIG_ORDNER, 'agent_privat.key')
    if os.path.isfile(pfad):
        priv = krypto.lies_privat(pfad)
        pub = krypto._oeffentlich(priv)
        neu = False
    else:
        priv, pub = krypto.schluesselpaar()
        krypto.schreibe_privat(pfad, priv)
        neu = True
    with _schloss:
        _stand['agent_key'] = pfad
        _stand['agent_oeffentlich'] = pub.hex()
        stand_schreiben(_stand)
    return {'oeffentlich': pub.hex(),
            'pfad': pfad,
            'neu_erzeugt': neu,
            'weiter': 'konfig'}


def schritt_konfig(daten):
    """Schreibt agent_privat.toml. Client-Weissliste bleibt leer -- die
    fuellt der Nutzer erst, wenn er ein Portal-Geraet einrichtet."""
    ordner = os.path.expanduser(daten.get('freigabe') or '~/ahpt-freigabe')
    ordner = os.path.abspath(ordner)
    if not os.path.isdir(ordner):
        try:
            os.makedirs(ordner, exist_ok=True)
        except OSError as e:
            raise EinrichtenFehler(
                'Freigabe-Ordner "%s" liess sich nicht anlegen: %s'
                % (ordner, e))
    # Sicherheit: die Wurzel darf nicht / oder ~ sein.
    heikel = (os.sep, os.path.expanduser('~'))
    if os.path.realpath(ordner) in [os.path.realpath(h) for h in heikel]:
        raise EinrichtenFehler(
            'Der Freigabe-Ordner darf nicht dein Home-Ordner oder '
            'die Wurzel des Dateisystems sein. Waehle einen '
            'Unterordner.')

    webspace = _stand.get('webspace')
    agent_key = _stand.get('agent_key')
    if not webspace or not agent_key:
        raise EinrichtenFehler(
            'Es fehlen frueheren Schritte. Bitte von vorne durchgehen.')

    # Geheimnis, das Agent und Vermittler teilen -- steht schon in
    # ~/.ahpt/geheimnis_privat (Schritt 5).
    geheimnis_datei = os.path.join(KONFIG_ORDNER, 'geheimnis_privat')

    inhalt = _konfig_bauen(webspace, geheimnis_datei, agent_key, ordner)
    pfad = os.path.join(KONFIG_ORDNER, 'agent_privat.toml')
    tmp = pfad + '.neu'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(inhalt)
    os.replace(tmp, pfad)
    with _schloss:
        _stand['agent_konfig'] = pfad
        _stand['freigabe'] = ordner
        stand_schreiben(_stand)
    return {'pfad': pfad, 'freigabe': ordner, 'weiter': 'agent'}


def _agent_konfig_pfad():
    """Pfad der Agent-Konfiguration -- aus dem Stand DIESER Sitzung, sonst
    der feste, altbekannte Ort.

    Der Rueckgriff ist noetig, weil `_stand` nur gefuellt ist, wenn die
    Einrichtung in EINER durchgehenden Sitzung des Assistenten lief. Ein
    Agent, der schon vorher (auch von Hand) eingerichtet wurde, hat seine
    Konfiguration trotzdem an diesem festen Ort -- `_konfig_bauen` legt sie
    nirgendwo anders ab.
    """
    return _stand.get('agent_konfig') \
        or os.path.join(KONFIG_ORDNER, 'agent_privat.toml')


def _agent_stoppen(pid_datei):
    try:
        with open(pid_datei) as f:
            pid = int(f.read().strip())
        os.kill(pid, 15)
    except (OSError, ValueError):
        pass


def schritt_agent(daten):
    """Startet, stoppt oder startet den Agenten neu. Zurueck kommt der
    Anfang des Logs -- der Nutzer soll die Bestaetigung SELBST lesen."""
    was = daten.get('was') or 'start'
    pid_datei = os.path.join(KONFIG_ORDNER, 'agent_privat.pid')
    log_datei = os.path.join(KONFIG_ORDNER, 'agent_privat.log')
    konfig = _agent_konfig_pfad()

    if was == 'status':
        laeuft = _agent_laeuft(pid_datei)
        return {'laeuft': laeuft, 'log_ende': _log_ende(log_datei, 40)}

    if was == 'stop':
        _agent_stoppen(pid_datei)
        return {'laeuft': False}

    if was not in ('start', 'restart'):
        raise EinrichtenFehler('unbekannte Aktion: %r' % was)

    if was == 'start' and _agent_laeuft(pid_datei):
        return {'laeuft': True,
                'meldung': 'Der Agent lief bereits.',
                'log_ende': _log_ende(log_datei, 40)}

    if was == 'restart' and _agent_laeuft(pid_datei):
        # Der Agent liest seine Konfiguration nur beim Start -- eine
        # geaenderte clients-Liste wirkt erst nach einem echten Neustart,
        # nicht von selbst.
        _agent_stoppen(pid_datei)
        time.sleep(1)

    if not os.path.isfile(konfig):
        raise EinrichtenFehler(
            'Agent-Konfiguration (%s) fehlt -- vorigen Schritt ausfuellen.'
            % konfig)
    agent_datei = os.path.join(HIER, 'relay_agent.py')
    if not os.path.isfile(agent_datei):
        raise EinrichtenFehler('relay_agent.py neben mir nicht gefunden.')

    # setsid: entkoppelt vom Wizard -- wenn der Wizard endet, laeuft
    # der Agent weiter. Und Sohn-Prozess braucht kein Terminal.
    with open(log_datei, 'ab') as log:
        try:
            p = subprocess.Popen(
                [sys.executable, agent_datei, '--konfig', konfig],
                stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True)
        except OSError as e:
            raise EinrichtenFehler('Konnte Agent nicht starten: %s' % e)
    with open(pid_datei, 'w') as f:
        f.write(str(p.pid))
    time.sleep(2)  # kurze Anlaufzeit, damit "Bereit" im Log steht
    return {'laeuft': _agent_laeuft(pid_datei),
            'pid': p.pid,
            'log_ende': _log_ende(log_datei, 60)}


def schritt_geraet_hinzufuegen(daten):
    """Traegt den oeffentlichen Schluessel eines Geraets in die
    clients-Liste der Agent-Konfiguration ein und startet neu.

    Ersetzt SSH + Texteditor fuer den einen Handgriff, der bei jeder neuen
    Geraete-Einrichtung wiederkehrt. Unbedenklich: der Schluessel ist
    OEFFENTLICH (der Agent nennt seinen eigenen genauso offen im Log) --
    was hier geschuetzt werden muss, ist nicht der Wert, sondern WER ihn
    eintragen darf. Das leistet die Token-Pruefung des Servers bereits,
    bevor diese Funktion je aufgerufen wird.
    """
    roh = daten.get('schluessel')
    if not isinstance(roh, str):
        raise EinrichtenFehler('schluessel fehlt.')
    schluessel = roh.strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', schluessel):
        sauber = re.sub(r'[^0-9a-fA-F]', '', roh)
        raise EinrichtenFehler(
            'Schluessel muss aus 64 Hexzeichen bestehen (hat %d).'
            % len(sauber))

    konfig = _agent_konfig_pfad()
    if not os.path.isfile(konfig):
        raise EinrichtenFehler(
            'Agent-Konfiguration (%s) gibt es noch nicht -- erst die '
            'Einrichtung durchlaufen.' % konfig)

    with open(konfig, encoding='utf-8') as f:
        text = f.read()

    war_schon_da = ('"%s"' % schluessel) in text
    if not war_schon_da:
        treffer = re.search(r'^clients\s*=\s*\[(.*?)\]', text, re.M | re.S)
        if not treffer:
            raise EinrichtenFehler(
                'Die Zeile "clients = [...]" wurde in der Konfiguration '
                'nicht gefunden -- von Hand nachsehen.')
        innen = treffer.group(1).strip()
        neu_innen = (innen + ', "%s"' % schluessel) if innen \
            else '"%s"' % schluessel
        neuer_text = (text[:treffer.start(1)] + neu_innen
                     + text[treffer.end(1):])

        # Zusaetzliche Sicherung, wo verfuegbar: die neue Fassung muss
        # sich als TOML lesen lassen, bevor sie geschrieben wird. Auf
        # Python < 3.11 (kein tomllib) wird nur binnen des regulaeren
        # Ausdrucks eingefuegt, ohne diese zweite Pruefung -- der Agent
        # selbst verlangt ohnehin tomllib und wuerde eine kaputte Datei
        # beim naechsten Start genauso ablehnen.
        try:
            import tomllib
            tomllib.loads(neuer_text)
        except ImportError:
            pass
        except Exception as e:
            raise EinrichtenFehler(
                'Nichts geschrieben: die geaenderte Konfiguration waere '
                'kein gueltiges TOML mehr (%s). Vermutlich wurde die '
                'Datei von Hand angepasst -- bitte dort nachsehen.'
                % type(e).__name__)

        tmp = konfig + '.' + secrets.token_hex(4) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(neuer_text)
        os.replace(tmp, konfig)
        text = neuer_text

    anzahl = len(re.findall(r'"[0-9a-f]{64}"', text))
    ergebnis = schritt_agent({'was': 'restart'})
    return {
        'ok': True, 'war_schon_da': war_schon_da,
        'anzahl_geraete': anzahl,
        'log_ende': ergebnis.get('log_ende', ''),
    }


# --------------------------------------------------------------- Kopplung
#
# Ein Geraet einzurichten hiess bisher: oeffentlichen Schluessel des Agenten
# abtippen (64 Hexzeichen), Adresse abtippen, dann den Schluessel des Geraets
# zurueck zum Server tragen. Dreimal Gelegenheit, sich zu vertippen.
#
# Der QR-Code nimmt die eine Richtung ab. Die andere -- der oeffentliche
# Schluessel des Geraets muss zum Agenten -- geht NICHT per QR: Der Rechner
# hat keine Kamera, die das Handy abliest. Deshalb steht im Code auch die
# Adresse dieses Assistenten samt Token, und das Geraet meldet sich von
# selbst zurueck. Beide sind im selben Netz, ob ueber WLAN oder ueber ein
# USB-Kabel mit eingeschaltetem Tethering.
#
# WAS UEBER DEN QR-CODE GEHT, UND WAS NICHT
# ------------------------------------------
# Nur Oeffentliches: die Adresse des Vermittlers, der oeffentliche
# Schluessel des Agenten, die Adressen dieses Assistenten, das Zugangs-Token.
# Der PRIVATE Schluessel des Geraets entsteht auf dem Geraet und verlaesst es
# nie -- daran aendert die Kopplung nichts.
#
# Das Token ist der einzige Wert im Code, der schuetzenswert ist. Es lebt nur
# so lange wie dieser Assistent und gilt nur im eigenen Netz. Wer es
# abfotografiert, kann ein Geraet zulassen -- deshalb sollte man den Code
# nicht herumzeigen und den Assistenten beenden, wenn man fertig ist.

_zuletzt_gekoppelt = None


# --------------------------------------------------------- Firewall-Lage
#
# WARUM DAS HIER STEHT
# ---------------------
# Am 07.09.2026 ist die Kopplung ZWEIMAL an einer Firewall gescheitert: die
# Windows-Firewall auf dem Rechner mit dem Assistenten, und ufw auf dem
# Heimserver, das aus dem LAN nur Port 80 durchliess. Beide Male stand der
# QR-Code sauber auf dem Bildschirm, das Handy scannte ihn richtig -- und
# dann passierte nichts, ohne dass irgendwo stand warum.
#
# Ein Assistent, der einen Port oeffnet und einen Code zeigt, laesst den
# Nutzer in genau diese Falle laufen. Deshalb sieht er vorher nach.
#
# WAS DIESE PRUEFUNG NICHT KANN
# ------------------------------
# Sie kann nicht feststellen, ob wirklich jemand von aussen durchkommt --
# das wuesste nur ein zweites Geraet. Sie liest die Regeln, soweit sie ohne
# Rootrechte lesbar sind, und sagt sonst "weiss ich nicht". Ein "weiss ich
# nicht" ist brauchbar; ein falsches "alles gut" waere schlimmer als keine
# Pruefung, weil der Nutzer dann woanders sucht.

def _ufw_regeln():
    """Freigegebene TCP-Ports laut ufw, oder None wenn nicht lesbar."""
    try:
        e = subprocess.run(['sudo', '-n', 'ufw', 'status'],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if e.returncode != 0 or 'Status' not in e.stdout:
        return None
    if 'inaktiv' in e.stdout or 'inactive' in e.stdout:
        return 'aus'
    return {int(m) for m in re.findall(r'^(\d+)/tcp\s+ALLOW', e.stdout, re.M)}


def _windows_firewall_an():
    """Ist die Windows-Firewall fuer das aktive Profil eingeschaltet?"""
    try:
        e = subprocess.run(['netsh', 'advfirewall', 'show', 'currentprofile'],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if e.returncode != 0:
        return None
    return bool(re.search(r'^\s*State\s+ON|^\s*Status\s+EIN', e.stdout, re.M | re.I))


def firewall_lage(port):
    """Wie stehen die Chancen, dass ein anderes Geraet diesen Port erreicht?

    zustand: 'offen'     -- eine Regel gibt ihn ausdruecklich frei
             'zu'        -- eine Firewall laeuft und kennt ihn nicht
             'aus'       -- keine Firewall aktiv
             'unbekannt' -- nicht lesbar (kein Rootrecht, fremdes System)
    """
    if sys.platform.startswith('win'):
        an = _windows_firewall_an()
        if an is None:
            return {'zustand': 'unbekannt', 'werkzeug': 'Windows-Firewall'}
        if not an:
            return {'zustand': 'aus', 'werkzeug': 'Windows-Firewall'}
        # Ob eine Regel fuer genau diesen Port existiert, ist ueber netsh
        # nur mit erheblichem Aufwand herauszufinden -- und die Antwort
        # waere trotzdem nicht sicher, weil Regeln sich ueberlagern.
        return {
            'zustand': 'unbekannt',
            'werkzeug': 'Windows-Firewall',
            'hinweis': 'Die Windows-Firewall ist eingeschaltet. Beim ersten '
                       'Start fragt sie meist nach, ob Python ins Netz darf '
                       '-- wurde das abgelehnt, kommt kein anderes Geraet '
                       'hier an.',
        }

    regeln = _ufw_regeln()
    if regeln is None:
        return {'zustand': 'unbekannt', 'werkzeug': 'ufw'}
    if regeln == 'aus':
        return {'zustand': 'aus', 'werkzeug': 'ufw'}
    if port in regeln:
        return {'zustand': 'offen', 'werkzeug': 'ufw', 'offene': sorted(regeln)}
    return {
        'zustand': 'zu',
        'werkzeug': 'ufw',
        'offene': sorted(regeln),
        'befehl': 'sudo ufw allow from 192.168.0.0/16 to any port %d proto tcp'
                  % port,
    }


def frage_wo_bedienen():
    """Hier am Geraet bedienen, oder von einem anderen im Heimnetz?

    Die Frage steht VOR der Portwahl, weil sie sie erübrigen kann: Wer den
    Assistenten ohnehin auf diesem Rechner oeffnet, braucht keinen Port nach
    aussen -- und soll auch keinen bekommen. Erst wer von einem anderen
    Geraet kommen will, hat ueberhaupt ein Firewall-Problem.

    Rueckgabe: 'hier' oder 'netz', oder None wenn nicht gefragt werden kann
    (kein Terminal, etwa beim Start ueber nohup).
    """
    if not sys.stdin.isatty():
        return None
    print()
    print('Wo willst du den Assistenten bedienen?')
    print()
    print('  1) Hier auf diesem Geraet')
    print('     Nichts muss durch eine Firewall, nichts geht durchs Netz.')
    print('  2) Von einem anderen Geraet im Heimnetz')
    print('     Zum Beispiel vom Laptop aus, waehrend der Server im Keller')
    print('     steht. Braucht einen Port, der durch die Firewall kommt.')
    print()
    while True:
        try:
            w = input('Deine Wahl [1]: ').strip() or '1'
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if w in ('1', '2'):
            return 'hier' if w == '1' else 'netz'
        print('Bitte 1 oder 2.')


def _browser_oeffnen(url):
    """Den Browser aufmachen -- aber nur einen grafischen.

    `webbrowser.open` nimmt auf einem Linux-Server ohne Oberflaeche das,
    was es findet, und das ist oft w3m oder lynx. Der uebernimmt dann das
    Terminal, in dem der Assistent gerade seine Adresse ausgegeben hat --
    und der Nutzer sitzt in einem Textbrowser fest, den er nicht wollte.
    Am 08.09.2026 genau so passiert.

    Ohne DISPLAY oder WAYLAND_DISPLAY gibt es hier also nichts zu oeffnen;
    die Adresse steht ja auf der Konsole.
    """
    if sys.platform.startswith('linux') and not (
            os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    try:
        import webbrowser
        return webbrowser.open(url)
    except Exception:
        return False


def _port_frei(port):
    """Laesst sich dieser Port ueberhaupt binden?"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def waehle_port(wunsch):
    """Einen Port nehmen, der auch durch die Firewall kommt.

    Der Nutzer soll nicht als erstes eine Firewall-Regel schreiben muessen,
    um einen Einrichtungs-Assistenten zu erreichen. Ist der Wunschport durch
    eine Regel gedeckt oder laeuft gar keine Firewall, bleibt es bei ihm.
    Ist er nachweislich zu, waehlt der Assistent einen der Ports, die
    ohnehin freigegeben sind -- und sagt in der Startausgabe, warum.

    Rueckgabe: (port, begruendung oder None)
    """
    lage = firewall_lage(wunsch)
    if lage['zustand'] in ('offen', 'aus', 'unbekannt'):
        return wunsch, None

    # 'zu': unter den freigegebenen einen suchen, der frei ist.
    for p in lage.get('offene', []):
        # Ports unter 1024 braeuchten Rootrechte, und 80/443 gehoeren
        # ueblicherweise einem Webserver -- da draengt sich niemand dazwischen.
        if p < 1024 or not _port_frei(p):
            continue
        return p, ('Port %d ist laut %s nicht freigegeben, %d dagegen schon '
                   '-- der Assistent nimmt deshalb %d.'
                   % (wunsch, lage['werkzeug'], p, p))
    return wunsch, ('Port %d ist laut %s nicht freigegeben, und unter den '
                    'freigegebenen war keiner frei. Von einem anderen Geraet '
                    'aus wird der Assistent so nicht erreichbar sein. '
                    'Abhilfe: %s'
                    % (wunsch, lage['werkzeug'], lage.get('befehl', '')))


def _aus_agent_konfig():
    """Adresse und oeffentlichen Schluessel aus der LAUFENDEN Konfiguration.

    Der Stand des Assistenten ist nur sein eigener Zwischenspeicher. Wer den
    Agenten von Hand eingerichtet hat -- und das war bei diesem Projekt der
    Normalfall, bevor es den Assistenten gab --, hat dort nichts stehen. Die
    Wahrheit liegt in agent_privat.toml, und von dort kommt sie hier.
    """
    pfad = os.path.join(KONFIG_ORDNER, 'agent_privat.toml')
    if not os.path.isfile(pfad):
        return {}
    try:
        import tomllib
        with open(pfad, 'rb') as f:
            d = tomllib.load(f)
    except Exception:
        return {}
    raus = {}
    basis = (d.get('relay') or {}).get('basis')
    if basis:
        raus['basis'] = str(basis)
    sd = (d.get('krypto') or {}).get('schluessel')
    if sd:
        try:
            import krypto
            priv = krypto.lies_privat(os.path.expanduser(str(sd)))
            raus['agent'] = krypto._oeffentlich(priv).hex()
        except Exception:
            pass
    return raus


def kopplungsdaten():
    """Was in den QR-Code gehoert. Kurze Schluesselnamen, damit der Code
    klein bleibt: Jedes Zeichen kostet Flaeche, und ein grosser Code ist
    schwerer zu treffen."""
    with _schloss:
        basis = _stand.get('webspace')
        agent = _stand.get('agent_oeffentlich')
    if not basis or not agent:
        aus = _aus_agent_konfig()
        basis = basis or aus.get('basis')
        agent = agent or aus.get('agent')
    if not basis:
        raise EinrichtenFehler(
            'Die Adresse des Vermittlers steht weder im Stand des Assistenten '
            'noch in agent_privat.toml. Entweder den Schritt "Webspace" '
            'durchlaufen oder [relay] basis in der Konfiguration setzen.')
    if not agent:
        raise EinrichtenFehler(
            'Der oeffentliche Schluessel des Agenten liess sich nicht '
            'ermitteln -- weder aus dem Stand des Assistenten noch aus der '
            'Schluesseldatei, die [krypto] schluessel in agent_privat.toml '
            'nennt. Laeuft der Agent ueberhaupt schon?')
    return {
        'b': _adresse_normalisieren(basis),
        'a': agent,
        't': _token,
        'h': ['%s:%d' % (a, _port) for a in eigene_adressen()],
    }


def schritt_koppeln(daten):
    """Nimmt den oeffentlichen Schluessel eines Geraets entgegen.

    Ruft dieselbe Funktion wie der Handeintrag -- das ist Absicht. Der Weg
    ueber den QR-Code ist bequemer, aber er darf nicht LOCKERER sein: Was
    hier ankommt, durchlaeuft dieselbe Pruefung und landet in derselben
    Zeile derselben Datei.
    """
    global _zuletzt_gekoppelt
    name = str(daten.get('geraet') or 'Unbenanntes Geraet')[:60]
    # Nur Zeichen, die man gefahrlos anzeigen kann. Der Name kommt vom
    # Geraet, also von aussen -- er wird nur gezeigt, nie ausgefuehrt oder
    # in eine Datei geschrieben, aber Steuerzeichen in einer Konsolenzeile
    # sind trotzdem unschoen.
    name = ''.join(c for c in name if c.isprintable())
    ergebnis = schritt_geraet_hinzufuegen(daten)
    _zuletzt_gekoppelt = {
        'geraet': name,
        'war_schon_da': ergebnis.get('war_schon_da', False),
        'anzahl_geraete': ergebnis.get('anzahl_geraete'),
        'zeit': time.time(),
    }
    return {'ok': True, 'geraet': name,
            'war_schon_da': ergebnis.get('war_schon_da', False)}


def _konfig_bauen(webspace, geheimnis_datei, agent_key, freigabe):
    """Baut den TOML-Text von Hand -- weniger Aufwand als tomli_w als
    Abhaengigkeit dazuzunehmen."""
    def q(x):
        # Escaped Rueckstrich und Anfuehrungszeichen -- UND Steuerzeichen.
        #
        # Ohne Letzteres wuerde ein eingebetteter Zeilenumbruch die
        # TOML-Zeichenkette mitten im Wert beenden: eine "einfache" TOML-
        # Zeichenkette darf laut Spezifikation KEINEN rohen Zeilenumbruch
        # enthalten. Ein strenger Parser wie tomllib weist das zwar ab,
        # anstatt eine zweite Zeile als neuen Schluessel zu lesen -- die
        # Konfiguration ginge also nur kaputt, nicht unbemerkt zusaetzliche
        # Werte hinein. Sauberer ist trotzdem, es gar nicht erst zuzulassen.
        # Am 03.09.2026 im Sicherheitsaudit gefunden.
        s = str(x)
        raus = []
        for ch in s:
            if ch == '\\':
                raus.append('\\\\')
            elif ch == '"':
                raus.append('\\"')
            elif ch == '\n':
                raus.append('\\n')
            elif ch == '\r':
                raus.append('\\r')
            elif ch == '\t':
                raus.append('\\t')
            elif ord(ch) < 0x20 or ord(ch) == 0x7f:
                raus.append('\\u%04x' % ord(ch))
            else:
                raus.append(ch)
        return '"' + ''.join(raus) + '"'
    return (
        '# agent_privat.toml -- vom Einrichtungs-Assistenten erzeugt.\n'
        '# Handschrift-Aenderungen sind erlaubt; der Assistent lernt sie beim\n'
        '# naechsten Durchgang, statt sie zu ueberschreiben.\n'
        '\n'
        '[relay]\n'
        'basis           = %s\n'
        'geheimnis_datei = %s\n'
        'poll_abstand    = 1.0\n'
        'unbedingt_nach  = 5\n'
        '\n'
        '[krypto]\n'
        '# Wie ausgetauscht wird. noise_ik gilt fuer CLI, das Portal spricht\n'
        '# noise_ik_aes -- der Agent kann beide gleichzeitig.\n'
        'verfahren  = "noise_ik"\n'
        'schluessel = %s\n'
        '# Weissliste der zugelassenen Geraete. Am Anfang leer -- der\n'
        '# oeffentliche Schluessel deines ersten Portal-Geraets kommt hier\n'
        '# beim ersten Verbindungsversuch dazu (der Agent nennt ihn dann\n'
        '# im Log).\n'
        'clients    = []\n'
        '\n'
        '[[dienst]]\n'
        'name      = "dateien"\n'
        'art       = "datei"\n'
        'wurzel    = %s\n'
        'aktionen  = ["liste", "hole", "lege", "neuer_ordner"]\n'
        '# Leer heisst: alle Dateiformate. Wenn du das einschraenken willst,\n'
        '# eine Liste eintragen, z.B. ["pdf", "jpg", "docx"].\n'
        'endungen  = []\n'
        '# 0 heisst: kein Limit. Sonst Zahl in Byte. 100 MiB = 104857600\n'
        'max_bytes = 0\n'
    ) % (q(webspace), q(geheimnis_datei), q(agent_key), q(freigabe))


def _agent_laeuft(pid_datei):
    try:
        with open(pid_datei) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)  # signal 0: nur pruefen, ob PID existiert
        return True
    except OSError:
        return False


def _log_ende(log_datei, zeilen):
    try:
        with open(log_datei, 'rb') as f:
            f.seek(0, 2)
            groesse = f.tell()
            f.seek(max(0, groesse - 8192))
            roh = f.read().decode('utf-8', 'replace')
    except OSError:
        return ''
    return '\n'.join(roh.splitlines()[-zeilen:])

# ----------------------------------------------------------- HTTP-Server

class Auslieferer(BaseHTTPRequestHandler):
    def _autorisiert(self):
        """Token aus Cookie ODER Query -- und zwar BEIDE pruefen.

        Frueher gewann der Cookie: War einer da, wurde die Query gar nicht
        mehr angesehen. Das faellt genau dann auf die Fuesse, wenn man den
        Assistenten neu startet und den Browser offen laesst -- der alte
        Cookie traegt dann ein Token, das es nicht mehr gibt, und die
        frische URL mit dem richtigen Token kommt nicht durch. Der Nutzer
        sieht "Zugangs-Token fehlt", obwohl er es gerade eingegeben hat.
        Am 07.09.2026 beim Koppeln aufgefallen.
        """
        kandidaten = []
        m = re.search(r'(?:^|;\s*)at=([0-9a-f]+)', self.headers.get('Cookie', ''))
        if m:
            kandidaten.append(m.group(1))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if q.get('t'):
            kandidaten.append(q['t'][0])
        return any(secrets.compare_digest(k, _token) for k in kandidaten)

    def log_message(self, *_a): pass  # keine Konsolenzeile je Anfrage

    def _antwort(self, code, typ, koerper, cookie=None):
        if isinstance(koerper, str):
            koerper = koerper.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', typ)
        self.send_header('Content-Length', str(len(koerper)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(koerper)

    def do_GET(self):
        pfad = urllib.parse.urlparse(self.path).path
        # Anmelden per Token in der URL -> Cookie setzen und ohne Token
        # weiterschicken.
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        # Nur die SEITE bekommt den Cookie-Umweg. Ein Abruf unter /api/ oder
        # /kopplung.svg soll direkt antworten: Das Handy holt sich diese
        # Adressen beim Koppeln, und es folgt keiner Umleitung, um sich
        # einen Cookie abzuholen, den es nachher nicht braucht.
        # Der Cookie-Umweg ist fuer die SEITE gedacht. Alles, was ein
        # Programm direkt abruft -- die App beim Koppeln, ein Download --
        # soll unmittelbar antworten statt eine Umleitung zu schicken, der
        # es folgen muesste, um sich einen Cookie zu holen.
        _direkt = pfad.startswith('/api/') or pfad in ('/kopplung.svg',
                                                       '/vermittler.zip')
        if 't' in q and not _direkt:
            t = q['t'][0]
            if secrets.compare_digest(t, _token):
                cookie = 'at=%s; Path=/; HttpOnly; SameSite=Strict' % _token
                self.send_response(303)
                self.send_header('Location', pfad)
                self.send_header('Set-Cookie', cookie)
                self.end_headers()
                return
        if not self._autorisiert():
            return self._antwort(403, 'text/plain; charset=utf-8',
                                 'Zugangs-Token fehlt. Die vollstaendige '
                                 'URL steht auf der Konsole, auf der der '
                                 'Assistent gestartet wurde.')
        if pfad == '/' or pfad == '/index.html':
            return self._antwort(200, 'text/html; charset=utf-8', HTML)
        if pfad == '/api/stand':
            return self._antwort(200, 'application/json; charset=utf-8',
                                 json.dumps({'stand': _stand}))
        if pfad == '/api/kopplung':
            try:
                return self._antwort(200, 'application/json; charset=utf-8',
                                     json.dumps(kopplungsdaten()))
            except EinrichtenFehler as e:
                return self._antwort(400, 'application/json; charset=utf-8',
                                     json.dumps({'fehler': str(e)}))
        if pfad == '/kopplung.svg':
            try:
                import qr
                daten = json.dumps(kopplungsdaten(), separators=(',', ':'))
                return self._antwort(200, 'image/svg+xml; charset=utf-8',
                                     qr.svg(daten, 'M', punkt=6))
            except EinrichtenFehler as e:
                return self._antwort(400, 'text/plain; charset=utf-8', str(e))
            except Exception as e:
                return self._antwort(500, 'text/plain; charset=utf-8',
                                     'QR-Code fehlgeschlagen: %s' % e)
        if pfad == '/vermittler.zip':
            try:
                inhalt, _ = vermittler_paket()
            except EinrichtenFehler as e:
                return self._antwort(400, 'text/plain; charset=utf-8', str(e))
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Length', str(len(inhalt)))
            self.send_header('Content-Disposition',
                             'attachment; filename="ahpt-vermittler.zip"')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(inhalt)
            return
        if pfad == '/api/vermittler_dateien':
            try:
                _, namen = vermittler_paket()
            except EinrichtenFehler as e:
                return self._antwort(400, 'application/json; charset=utf-8',
                                     json.dumps({'fehler': str(e)}))
            return self._antwort(200, 'application/json; charset=utf-8',
                                 json.dumps({'dateien': namen}))
        if pfad == '/api/firewall':
            lage = firewall_lage(_port)
            lage['port'] = _port
            return self._antwort(200, 'application/json; charset=utf-8',
                                 json.dumps(lage))
        if pfad == '/api/gekoppelt':
            # Die Seite fragt das im Takt ab, waehrend der Code auf dem
            # Bildschirm steht. Sobald sich ein Geraet gemeldet hat, steht
            # es hier -- der Nutzer muss nichts anklicken.
            return self._antwort(200, 'application/json; charset=utf-8',
                                 json.dumps({'zuletzt': _zuletzt_gekoppelt}))
        if pfad == '/api/pruefen':
            try:
                return self._antwort(200, 'application/json; charset=utf-8',
                                     json.dumps(schritt_pruefen({})))
            except EinrichtenFehler as e:
                return self._antwort(
                    400, 'application/json; charset=utf-8',
                    json.dumps({'fehler': str(e)}))
        return self._antwort(404, 'text/plain; charset=utf-8', 'nicht da')

    def do_POST(self):
        if not self._autorisiert():
            return self._antwort(403, 'text/plain; charset=utf-8', 'nein')
        pfad = urllib.parse.urlparse(self.path).path
        laenge = int(self.headers.get('Content-Length', '0') or '0')
        if laenge > 65536:
            return self._antwort(413, 'text/plain; charset=utf-8',
                                 'zu gross')
        roh = self.rfile.read(laenge) if laenge else b''
        try:
            daten = json.loads(roh or b'{}')
        except ValueError:
            return self._antwort(400, 'text/plain; charset=utf-8',
                                 'JSON erwartet')

        aktion = {
            '/api/webspace':   schritt_webspace,
            '/api/ftp':        schritt_ftp,
            '/api/hochladen':  schritt_hochladen,
            '/api/schluessel': schritt_schluessel,
            '/api/konfig':     schritt_konfig,
            '/api/agent':      schritt_agent,
            '/api/geraet_hinzufuegen': schritt_geraet_hinzufuegen,
            '/api/koppeln':    schritt_koppeln,
            '/api/vermittler_pruefen': schritt_vermittler_pruefen,
        }.get(pfad)
        if aktion is None:
            return self._antwort(404, 'text/plain; charset=utf-8',
                                 'nicht da')
        try:
            ergebnis = aktion(daten)
        except EinrichtenFehler as e:
            return self._antwort(
                400, 'application/json; charset=utf-8',
                json.dumps({'fehler': str(e)}))
        except Exception as e:
            return self._antwort(
                500, 'application/json; charset=utf-8',
                json.dumps({'fehler': 'unerwartet: %s' % type(e).__name__}))
        return self._antwort(200, 'application/json; charset=utf-8',
                             json.dumps(ergebnis))


class LauschEndpunkt(socketserver.ThreadingTCPServer):
    allow_reuse_address = (os.name != 'nt')
    daemon_threads = True


# --------------------------------------------------------- die Oberflaeche
#
# Alles in EINER Datei: Aufbau, Stil, Verhalten. Kein Nachladen.

HTML = r"""<!DOCTYPE html>
<html lang="de"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AHPT Cloud -- Einrichtung</title>
<style>
:root {
  --grund:#0e1013; --karte:#151820; --rand:#242832;
  --text:#e7eaef; --leise:#9aa3b2;
  --akzent:#67d69b; --akzent-hell:#1c2c25;
  --warn:#e0b166; --warn-hell:#2c2519;
  --fehler:#e07c7c; --fehler-hell:#2c1a1a;
}
* { box-sizing: border-box }
body { margin: 0; background: var(--grund); color: var(--text);
       font: 15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       min-height: 100vh; }
.kopf { padding: 22px 32px; border-bottom: 1px solid var(--rand);
        display: flex; align-items: baseline; gap: 20px }
.kopf h1 { margin: 0; font-size: 18px; font-weight: 600 }
.kopf .leise { color: var(--leise); font-size: 13px }
.leiste { display: flex; gap: 4px; padding: 14px 32px;
          border-bottom: 1px solid var(--rand); font-size: 12.5px;
          color: var(--leise); overflow-x: auto }
.leiste .stufe { padding: 4px 10px; border-radius: 999px;
                 background: transparent; white-space: nowrap }
.leiste .stufe.jetzt { background: var(--akzent-hell); color: var(--akzent);
                       font-weight: 600 }
.leiste .stufe.fertig { color: var(--akzent) }
.leiste .stufe.klickbar { cursor: pointer }
.leiste .stufe.klickbar:hover { background: var(--flaeche-hoch);
  color: var(--akzent-glut) }
main { max-width: 720px; margin: 0 auto; padding: 32px 24px 96px }
.karte { background: var(--karte); border: 1px solid var(--rand);
         border-radius: 12px; padding: 24px 28px; margin-bottom: 20px }
h2 { margin: 0 0 10px; font-size: 20px; font-weight: 600 }
h3 { margin: 20px 0 8px; font-size: 15px; font-weight: 600 }
p  { margin: 0 0 14px }
.leise { color: var(--leise) }
label { display: block; margin: 16px 0 6px; font-size: 13px;
        color: var(--leise) }
input[type=text], input[type=password] {
  width: 100%; padding: 10px 12px; border-radius: 8px;
  border: 1px solid var(--rand); background: #0b0d11; color: var(--text);
  font-size: 14px; font-family: inherit;
}
input:focus { outline: 2px solid var(--akzent); outline-offset: -1px }
.fussleiste { display: flex; justify-content: space-between; gap: 12px;
              margin-top: 20px }
button { padding: 10px 18px; border-radius: 8px; border: 1px solid var(--rand);
         background: #1e222a; color: var(--text); font-size: 14px;
         cursor: pointer; font-family: inherit }
button:hover { background: #262b35 }
button.haupt { background: var(--akzent); color: #0b0d11; border-color: transparent;
               font-weight: 600 }
button.haupt:hover { background: #7de1a9 }
button:disabled { opacity: .5; cursor: not-allowed }
.meldung { padding: 12px 16px; border-radius: 8px; margin: 14px 0;
           border: 1px solid transparent; font-size: 13.5px }
.meldung.gut { background: var(--akzent-hell); color: var(--akzent); border-color: var(--akzent) }
.meldung.warn { background: var(--warn-hell); color: var(--warn); border-color: var(--warn) }
.meldung.fehler { background: var(--fehler-hell); color: var(--fehler); border-color: var(--fehler) }
.pruefung { display: flex; justify-content: space-between; padding: 10px 0;
            border-bottom: 1px solid var(--rand); align-items: baseline }
.pruefung:last-child { border-bottom: 0 }
.pruefung .marke { font-size: 11px; padding: 2px 8px; border-radius: 999px }
.pruefung.ok .marke { background: var(--akzent-hell); color: var(--akzent) }
.pruefung.aus .marke { background: var(--fehler-hell); color: var(--fehler) }
.pruefung .hinweis { color: var(--leise); font-size: 12px; margin-top: 4px }
details { margin: 14px 0; border: 1px solid var(--rand); border-radius: 8px }
details summary { cursor: pointer; padding: 10px 14px; color: var(--leise);
                  font-size: 13px; user-select: none }
details[open] summary { border-bottom: 1px solid var(--rand) }
details > div { padding: 12px 14px; color: var(--leise); font-size: 13px }
code { background: #0b0d11; padding: 2px 5px; border-radius: 4px;
       font-family: "SF Mono","Consolas",monospace; font-size: 12.5px }
pre { background: #0b0d11; padding: 12px 14px; border-radius: 8px;
      font-family: "SF Mono","Consolas",monospace; font-size: 12.5px;
      overflow-x: auto; margin: 10px 0 }
</style>
</head><body>

<div class="kopf">
  <h1>AHPT Cloud &mdash; Einrichtung</h1>
  <span class="leise" id="wo">wird geladen...</span>
</div>

<div class="leiste" id="leiste"></div>

<main id="haupt"></main>

<script>
'use strict';

const $ = s => document.querySelector(s);
const zeig = h => { $('#haupt').innerHTML = h; };

const SCHRITTE = [
  { name: 'willkommen', titel: 'Willkommen'       },
  { name: 'pruefen',    titel: 'Voraussetzungen'  },
  { name: 'webspace',   titel: 'Webspace'         },
  { name: 'ftp',        titel: 'Vermittler'       },
  { name: 'hochladen',  titel: 'Hochladen'        },
  { name: 'schluessel', titel: 'Schluessel'       },
  { name: 'agent',      titel: 'Agent'            },
  { name: 'portal',     titel: 'Portal'           },
  { name: 'fertig',     titel: 'Fertig'           },
];

/* Welche Funktion zeigt welchen Schritt.
 *
 * Gebraucht, damit die Leiste oben ANKLICKBAR wird. Vorher war sie reine
 * Anzeige, und der Assistent fing immer bei "Willkommen" an -- wer nur
 * seinen Webspace wechseln wollte, musste sich durch alles davor klicken.
 * Genau das haelt Leute davon ab, etwas zu aendern. */
const ZEIGER = {
  willkommen: () => zeigeWillkommen(),
  pruefen:    () => zeigePruefen(),
  webspace:   () => zeigeWebspace(),
  ftp:        () => zeigeWieHochladen(),
  hochladen:  () => zeigeHochladen(),
  schluessel: () => zeigeSchluessel(),
  agent:      () => zeigeAgent(),
  portal:     () => zeigePortal(),
  fertig:     () => zeigeFertig(),
};
let stand = {};
let jetzt = 0;

/* Ist die Einrichtung einmal durchgelaufen?
 *
 * Davon haengt ab, ob die Leiste oben anklickbar ist -- und das ist keine
 * Feinheit. WAEHREND der Ersteinrichtung baut jeder Schritt auf dem
 * vorigen auf: ohne Webspace kein Hochladen, ohne Schluessel keine
 * Konfiguration. Eine anklickbare Leiste laedt dort dazu ein, etwas zu
 * ueberspringen, und das Ergebnis waere eine halbe Einrichtung, die
 * irgendwo spaeter mit einer raetselhaften Meldung scheitert.
 *
 * DANACH ist es umgekehrt: Wer seinen Webspace wechselt, will genau zu
 * diesem einen Schritt und nicht durch acht andere. */
let fertigEingerichtet = false;

function leiste() {
  const l = $('#leiste');
  l.innerHTML = SCHRITTE.map((s, i) => {
    const klasse = i < jetzt ? 'fertig' : i === jetzt ? 'jetzt' : '';
    // Springen nur bei fertiger Einrichtung, und nur rueckwaerts oder auf
    // den aktuellen Schritt.
    const offen = fertigEingerichtet && i <= jetzt;
    return '<span class="stufe ' + klasse + (offen ? ' klickbar' : '') + '"'
      + (offen ? ' onclick="springe(' + i + ')" title="Zu diesem Schritt"' : '')
      + '>' + (i + 1) + '. ' + s.titel + '</span>';
  }).join('');
}

function springe(i) {
  const f = ZEIGER[SCHRITTE[i].name];
  if (f) f();
}

async function jsonAn(pfad, koerper) {
  const r = await fetch(pfad, {
    method: koerper === undefined ? 'GET' : 'POST',
    headers: koerper === undefined ? {} : { 'Content-Type': 'application/json' },
    body: koerper === undefined ? undefined : JSON.stringify(koerper),
  });
  const t = await r.text();
  let d = {};
  try { d = JSON.parse(t); } catch (e) {}
  if (!r.ok) throw new Error(d.fehler || ('HTTP ' + r.status));
  return d;
}

function meldung(text, art) {
  return '<div class="meldung ' + (art || 'gut') + '">' + text + '</div>';
}

function huelle(inhalt, links, rechts) {
  return '<div class="karte">' + inhalt
       + '<div class="fussleiste">'
       + (links  || '<span></span>')
       + (rechts || '')
       + '</div></div>';
}

function warum(titel, text) {
  return '<details><summary>' + titel + '</summary><div>' + text + '</div></details>';
}

/* ------------------------------------------------------- Schritt 1 */
function zeigeWillkommen() {
  jetzt = 0; leiste();
  zeig(huelle(
    '<h2>Willkommen</h2>'
    + '<p>Dieser Assistent baut in wenigen Schritten deine private '
    + 'Cloud auf: ein Ordner auf deinem Heimserver, den du von unterwegs '
    + '&uuml;ber ein einfaches Webportal erreichen kannst &mdash; ohne '
    + 'offenen Port zuhause, ohne fremden Dienst dazwischen, verschl&uuml;sselt.</p>'
    + '<h3>Was du brauchst</h3>'
    + '<ul class="leise">'
    + '<li>diesen Heimserver hier (Linux, mit Python)</li>'
    + '<li>einen g&uuml;nstigen Webspace, der PHP kann, mit FTP-Zugang</li>'
    + '<li>10 Minuten</li>'
    + '</ul>'
    + warum('Warum ein Webspace?',
        'Dein Heimserver hat keinen offenen Port ins Internet -- und '
      + 'das soll so bleiben. Der Webspace ist der Briefkasten: '
      + 'dein Laptop hinterl&auml;sst dort eine Frage, dein Heimserver '
      + 'holt sie ab und legt die Antwort daneben. Weder der Webspace-'
      + 'Anbieter noch sonst wer im Netz kann mitlesen -- alles ist '
      + 'zwischen Laptop und Heimserver verschl&uuml;sselt.'),
    '',
    '<button class="haupt" onclick="zeigePruefen()">Los</button>'
  ));
}

/* ------------------------------------------------------- Schritt 2 */
async function zeigePruefen() {
  jetzt = 1; leiste();
  zeig(huelle(
    '<h2>Voraussetzungen</h2>'
    + '<p class="leise">Ich pr&uuml;fe kurz, ob alles da ist.</p>'
    + '<div id="proben">wird gepr&uuml;ft ...</div>',
    '<button onclick="zeigeWillkommen()">Zur&uuml;ck</button>',
    '<button class="haupt" id="knopfWeiter" disabled>Weiter</button>'
  ));
  try {
    const d = await jsonAn('/api/pruefen');
    $('#proben').innerHTML = d.pruefungen.map(p =>
      '<div class="pruefung ' + (p.ok ? 'ok' : 'aus') + '">'
      + '<div><b>' + p.was + '</b>'
      + '<div class="hinweis">' + p.hinweis + '</div></div>'
      + '<span class="marke">' + (p.ok ? 'ok' : 'fehlt') + '</span>'
      + '</div>').join('');
    if (d.ok) {
      const k = $('#knopfWeiter');
      k.disabled = false;
      k.onclick = zeigeWebspace;
    } else {
      $('#proben').insertAdjacentHTML('afterend',
        meldung('Bitte behebe die roten Punkte oben und lade die Seite neu.', 'warn'));
    }
  } catch (e) {
    $('#proben').innerHTML = meldung('Konnte nicht pr&uuml;fen: ' + e.message, 'fehler');
  }
}

/* ------------------------------------------------------- Schritt 3 */
function zeigeWebspace() {
  jetzt = 2; leiste();
  const alt = stand.webspace || '';
  zeig(huelle(
    '<h2>Webspace</h2>'
    + '<p>Die Adresse, unter der dein Webspace erreichbar ist. '
    + 'Beispiel: <code>dein-webspace.example.com/ahpt</code>.</p>'
    + warum('Warum ein Unterordner?',
        'Wenn du den Webspace fuer andere Sachen (eine Webseite) '
      + 'auch nutzt, sollen die Vermittler-Dateien nicht mitten drin '
      + 'liegen. Ein eigener Ordner haelt es getrennt und macht '
      + 'sp&auml;teres Umziehen einfacher.')
    + '<label>Adresse</label>'
    + '<input type="text" id="fWebspace" placeholder="dein-webspace.example.com/ahpt" value="' + alt + '">'
    + '<div id="webErgebnis"></div>',
    '<button onclick="zeigePruefen()">Zur&uuml;ck</button>',
    '<button class="haupt" onclick="pruefeWebspace()">Pr&uuml;fen und weiter</button>'
  ));
}

async function pruefeWebspace() {
  const adresse = $('#fWebspace').value.trim();
  const ort = $('#webErgebnis');
  ort.innerHTML = meldung('teste ...', 'warn');
  try {
    const d = await jsonAn('/api/webspace', { adresse: adresse });
    stand.webspace = d.adresse;
    if (d.relay_vorhanden) {
      ort.innerHTML = meldung(
        'Erreichbar &mdash; und es liegt bereits eine <code>relay.php</code> dort. '
        + 'Wir k&ouml;nnen den n&auml;chsten Schritt &uuml;berspringen.', 'gut');
      setTimeout(() => zeigeSchluessel(), 800);
    } else {
      ort.innerHTML = meldung(
        'Erreichbar. <code>relay.php</code> ist noch nicht da &mdash; im '
        + 'n&auml;chsten Schritt kommt sie hin.', 'gut');
      setTimeout(() => zeigeWieHochladen(), 800);
    }
  } catch (e) {
    ort.innerHTML = meldung(e.message, 'fehler');
  }
}

/* ------------------------------------------------------- Schritt 4 */
/* ------------------------------------------- Schritt 4a: Wie hochladen? */
function zeigeWieHochladen() {
  jetzt = 3; leiste();
  zeig(huelle(
    '<h2>Wie soll der Vermittler auf den Webspace?</h2>'
    + '<p>Auf deinem Webspace muss <code>relay.php</code> liegen. Das ist der '
    + 'Briefkasten zwischen deinem Heimserver und dir, wenn du unterwegs '
    + 'bist &ndash; vier kleine Dateien, sonst nichts.</p>'

    + '<div class="meldung" style="margin:14px 0">'
    + '<b>Der Assistent macht es</b><br>'
    + 'Er braucht dazu die FTP-Zugangsdaten deines Hosters. Danach ruft er '
    + 'die Adresse ab und pr&uuml;ft, ob wirklich angekommen ist, was er '
    + 'geschickt hat.'
    + '</div>'
    + '<div class="meldung" style="margin:14px 0">'
    + '<b>Du machst es selbst</b><br>'
    + 'Der Assistent packt die Dateien zusammen, und du l&auml;dst sie mit '
    + 'dem Werkzeug hoch, das du ohnehin benutzt &ndash; einem '
    + 'FTP-Programm, dem Datei-Manager deines Hosters, was auch immer. '
    + 'Gepr&uuml;ft wird danach genauso. Dieser Weg ist der richtige, wenn '
    + 'dein Hoster kein FTP anbietet, wenn du dein Passwort nicht durch '
    + 'dieses Netz schicken willst, oder wenn der FTP-Weg klemmt.'
    + '</div>',
    '<button onclick="zeigeWebspace()">Zur&uuml;ck</button>',
    '<button onclick="zeigeHaendisch()">Ich mache es selbst</button> '
    + '<button class="haupt" onclick="zeigeFtp()">Der Assistent macht es</button>'
  ));
}

/* ------------------------------------ Schritt 4b: von Hand hochladen */
function zeigeHaendisch() {
  jetzt = 3; leiste();
  const ordner = (stand.webspace || '').replace(/\/+$/, '');
  zeig(huelle(
    '<h2>Vermittler selbst hochladen</h2>'
    + '<p>Vier Schritte. Am Ende ruft der Assistent deinen Webspace selbst '
    + 'auf und sieht nach, ob der Vermittler antwortet &ndash; du musst dich '
    + 'nicht darauf verlassen, dass das Hochladen geklappt hat.</p>'

    + '<p><b>1. Paket herunterladen</b><br>'
    + 'Es enth&auml;lt <code>relay.php</code>, <code>relay_token.php</code>, '
    + '<code>relay_state.php</code> und <code>.htaccess</code>.</p>'
    + '<p><a class="knopf haupt" href="/vermittler.zip" '
    + 'download="ahpt-vermittler.zip">Hier herunterladen</a></p>'

    + '<p style="margin-top:18px"><b>2. Entpacken</b><br>'
    + 'Achtung bei <code>.htaccess</code>: Namen mit f&uuml;hrendem Punkt '
    + 'blenden viele Dateimanager aus. Wenn du sie nicht siehst, schalte '
    + '&bdquo;versteckte Dateien anzeigen&ldquo; ein &ndash; ohne sie liegen '
    + 'deine Fragen und Antworten offen im Verzeichnis.</p>'

    + '<p><b>3. Alle vier Dateien in EINEN Ordner auf den Webspace legen</b><br>'
    + 'Der Ordner muss &uuml;ber das Web erreichbar sein, welcher es ist, '
    + 'spielt keine Rolle. Die Dateien geh&ouml;ren nebeneinander, nicht in '
    + 'Unterordner. Womit du sie hochl&auml;dst, ist egal.</p>'

    + '<p><b>4. Die Adresse dieses Ordners hier eintragen</b></p>'
    + '<label>Adresse des Ordners, in dem <code>relay.php</code> jetzt liegt</label>'
    + '<input type="text" id="fHaendischAdresse" '
    + 'placeholder="dein-webspace.example.com/ahpt" value="'
    + ordner.replace(/"/g, '&quot;') + '">'
    + '<div id="haendischErgebnis"></div>'

    + warum('Was steht im Paket, und was ist daran heikel?',
        '<code>relay.php</code> ist der Vermittler selbst. '
      + '<code>relay_token.php</code> enth&auml;lt das GEHEIMNIS, mit dem '
      + 'dein Agent dort Antworten ablegen darf &ndash; es wurde gerade '
      + 'erzeugt und liegt auch bei dir unter '
      + '<code>~/.ahpt/geheimnis_privat</code>. Wer es hat, kann gef&auml;lschte '
      + 'Antworten hinterlegen; mitlesen kann er nichts, das verhindert die '
      + 'Verschl&uuml;sselung. L&ouml;sch das entpackte Paket, wenn du fertig '
      + 'bist. <code>relay_state.php</code> ist nur ein leerer Anfangszustand, '
      + '<code>.htaccess</code> sperrt das Verzeichnis gegen Neugierige.'),

    '<button onclick="zeigeWieHochladen()">Zur&uuml;ck</button>',
    '<button class="haupt" id="knopfHaendisch" onclick="tuHaendischPruefen()">'
    + 'Pr&uuml;fen und weiter</button>'
  ));
}

async function tuHaendischPruefen() {
  const ort = $('#haendischErgebnis');
  const adresse = $('#fHaendischAdresse').value.trim();
  if (!adresse) {
    ort.innerHTML = meldung('Bitte die Adresse des Ordners eintragen.', 'fehler');
    return;
  }
  $('#knopfHaendisch').disabled = true;
  ort.innerHTML = meldung('rufe die Adresse ab &hellip;', 'warn');
  try {
    const d = await jsonAn('/api/vermittler_pruefen', { adresse: adresse });
    stand.webspace = d.adresse;
    stand.relay_vorhanden = true;
    // Der Selbsttest sagt mehr als "da". Diese drei Werte sind die, an
    // denen es sonst haengt: eine vergessene Datei, ein leer gebliebenes
    // relay_token.php, ein Ablageordner ohne Schreibrecht.
    const st = d.selbsttest || {};
    const zeile = (gut, text) =>
      '<br>' + (gut ? '&#10003; ' : '&#10007; ') + text;
    ort.innerHTML = meldung(
      'Gefunden und geantwortet. Der Vermittler liegt unter <code>'
      + d.adresse.replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))
      + '</code>.'
      + zeile(st.datei_da, 'relay_token.php liegt daneben')
      + zeile(st.geheim_zeichen === 64,
              st.geheim_zeichen === 64
                ? 'das Geheimnis darin hat die richtige L&auml;nge'
                : 'das Geheimnis darin hat ' + (st.geheim_zeichen || 0)
                  + ' Zeichen statt 64')
      + zeile(st.ablage_schreib, 'der Vermittler darf in sein Verzeichnis schreiben'),
      (st.datei_da && st.geheim_zeichen === 64 && st.ablage_schreib)
        ? 'gut' : 'warn');
    setTimeout(zeigeSchluessel, 900);
  } catch (e) {
    ort.innerHTML = meldung(String(e.message), 'fehler');
    $('#knopfHaendisch').disabled = false;
  }
}

function zeigeFtp() {
  jetzt = 3; leiste();
  // Host aus der Webspace-Adresse ableiten
  let host = '';
  try {
    host = new URL(stand.webspace).hostname;
  } catch (e) {}
  // Laeuft dieser Browser NICHT auf demselben Rechner wie der Assistent
  // (also ueber die LAN-Adresse, nicht ueber 127.0.0.1), verlaesst das
  // Passwort gleich diesen Rechner UNVERSCHLUESSELT -- der Assistent hat
  // kein Zertifikat und kann kein https anbieten. Ueber die Loopback-
  // Adresse verlaesst nichts jemals die Maschine; die Warnung gilt nur
  // fuer den LAN-Fall und soll nicht grundlos aufscheinen.
  // Am 03.09.2026 im Sicherheitsaudit gefunden: bislang stand nirgends,
  // dass genau dieser Schritt neu ist -- bisher wurde ein FTP-Passwort nie
  // ueber ein Netz geschickt, sondern direkt in ~/.netrc getippt.
  const imLan = !['127.0.0.1', 'localhost', '::1'].includes(location.hostname);
  zeig(huelle(
    '<h2>FTP-Zugang</h2>'
    + '<p>Zum Hochladen von <code>relay.php</code> brauchst du die '
    + 'FTP-Zugangsdaten deines Webspace-Anbieters &mdash; dieselben, '
    + 'die du zum Hochladen einer Webseite verwenden w&uuml;rdest.</p>'
    + (imLan ? meldung(
        '<b>Du bist gerade &uuml;ber das Netzwerk verbunden, nicht &uuml;ber '
      + 'diesen Rechner selbst.</b> Der Assistent spricht nur '
      + '<code>http://</code> (kein Zertifikat m&ouml;glich) -- das '
      + 'Passwort geht auf den n&auml;chsten Schritten deshalb '
      + '<b>unverschl&uuml;sselt durch dein WLAN</b>. Im eigenen Heimnetz '
      + 'ist das ein akzeptables Risiko; in einem Hotel-, Caf&eacute;- oder '
      + 'Firmen-WLAN nicht &mdash; dort k&ouml;nnte ein Mitleser im '
      + 'selben Netz es abfangen. Mach diesen Schritt dann lieber direkt '
      + 'am Heimserver.', 'warn') : '')
    + warum('Was passiert mit meinem Passwort?',
        'Es wird SOFORT in ~/.netrc auf diesem Rechner geschrieben '
      + '(Modus 0600 -- nur du kannst es lesen). Danach wird es aus '
      + 'meinem Speicher entfernt. curl liest es aus .netrc, damit '
      + 'es nie in einer Kommandozeile auftaucht, die andere sehen '
      + 'k&ouml;nnten. Der Assistent zeigt es nirgends zur&uuml;ck.'
      + '<br><br>Das gilt fuer die Verarbeitung HIER auf dem Heimserver. '
      + 'Der WEG dorthin ist eine andere Frage -- siehe den Hinweis oben, '
      + 'falls er zu sehen ist.')
    + '<label>FTP-Host</label>'
    + '<input type="text" id="fHost" value="' + host + '">'
    + '<label>Benutzer</label>'
    + '<input type="text" id="fBenutzer" autocomplete="off">'
    + '<label>Passwort</label>'
    + '<input type="password" id="fPasswort" autocomplete="off">'
    + '<div id="ftpErgebnis"></div>',
    '<button onclick="zeigeWebspace()">Zur&uuml;ck</button>',
    '<button class="haupt" onclick="pruefeFtp()">Testen und weiter</button>'
  ));
}

async function pruefeFtp() {
  const ort = $('#ftpErgebnis');
  ort.innerHTML = meldung('verbinde ...', 'warn');
  try {
    const d = await jsonAn('/api/ftp', {
      host:     $('#fHost').value.trim(),
      benutzer: $('#fBenutzer').value.trim(),
      passwort: $('#fPasswort').value,
      zertifikat_annehmen: $('#fZertifikat') ? $('#fZertifikat').checked : false,
    });
    // Passwortfeld leeren
    $('#fPasswort').value = '';
    ort.innerHTML = meldung(
      'Verbunden. Ordner ist auflistbar.'
      + (d.zertifikat_angenommen
         ? ' Das Zertifikat wurde dabei ungeprueft angenommen.' : ''), 'gut');
    setTimeout(() => zeigeHochladen(), 700);
  } catch (e) {
    ort.innerHTML = meldung(e.message, 'fehler');
    // Genau bei diesem Fehler hilft das Kaestchen -- also erst dann zeigen.
    // Vorher waere es eine Einladung, die Pruefung abzuschalten, bevor
    // ueberhaupt etwas schiefging.
    if (/curl-Fehler 60/.test(e.message) && !$('#fZertifikat')) {
      ort.insertAdjacentHTML('beforeend',
        '<div style="margin-top:10px">'
        + '<label><input type="checkbox" id="fZertifikat"> '
        + 'Zertifikat annehmen, ohne es zu pruefen</label>'
        + '<div class="klein" style="margin-top:4px">'
        + 'Die Verbindung bleibt verschluesselt &ndash; ungeprueft bleibt '
        + 'nur, WER am anderen Ende sitzt. Im eigenen Heimnetz gegen den '
        + 'eigenen Hoster ist das vertretbar; in einem fremden Netz koennte '
        + 'sich jemand dazwischenschalten und das Passwort mitlesen. '
        + 'Danach noch einmal auf &bdquo;Testen und weiter&ldquo;.</div></div>');
    }
  }
}

/* ------------------------------------------------------- Schritt 5 */
function zeigeHochladen() {
  jetzt = 4; leiste();
  // Zielordner aus der Webspace-Adresse ableiten
  let ordner = '/privat';
  try {
    const u = new URL(stand.webspace);
    ordner = u.pathname || '/privat';
  } catch (e) {}
  zeig(huelle(
    '<h2>Vermittler hochladen</h2>'
    + '<p>Der Assistent l&auml;dt <code>relay.php</code> und zwei kleine '
    + 'Nachbardateien auf den Webspace. Danach ist der Briefkasten da.</p>'
    + warum('Was genau kommt hoch?',
        '<b>relay.php</b> nimmt Fragen entgegen und legt Antworten '
      + 'daneben. <b>relay_token.php</b> ist das Geheimnis, mit dem '
      + 'dein Agent bei relay.php SCHREIBEN darf -- lesen darf jeder, '
      + 'aber die Fragen sind verschl&uuml;sselt. <b>relay_state.php</b> '
      + 'ist der Anfangszustand des Z&auml;hlers.')
    + '<label>Zielordner auf dem Webspace</label>'
    + '<input type="text" id="fOrdner" value="' + ordner + '">'
    + '<div id="hochErgebnis"></div>',
    '<button onclick="zeigeFtp()">Zur&uuml;ck</button>',
    '<button class="haupt" id="knopfHoch" onclick="tuHochladen()">Hochladen</button>'
  ));
}

async function tuHochladen() {
  const ort = $('#hochErgebnis');
  $('#knopfHoch').disabled = true;
  ort.innerHTML = meldung('l&auml;dt hoch ...', 'warn');
  try {
    const d = await jsonAn('/api/hochladen', {
      fernordner: $('#fOrdner').value.trim(),
    });
    ort.innerHTML = meldung(
      'Hochgeladen: <code>' + d.dateien.join('</code>, <code>') + '</code>. '
      + (d.selbsttest ? '<br>Selbsttest von relay.php: OK '
        + '(Fassung ' + (d.selbsttest.protokoll || '?') + ').' : ''),
      'gut');
    setTimeout(() => zeigeSchluessel(), 900);
  } catch (e) {
    ort.innerHTML = meldung(e.message, 'fehler');
    $('#knopfHoch').disabled = false;
  }
}

/* ------------------------------------------------------- Schritt 6: Schluessel */
function zeigeSchluessel() {
  jetzt = 5; leiste();
  zeig(huelle(
    '<h2>Schl&uuml;ssel</h2>'
    + '<p>Der Agent braucht ein Schl&uuml;sselpaar. Der <b>private</b> Teil '
    + 'bleibt in <code>~/.ahpt/agent_privat.key</code> auf diesem Rechner. '
    + 'Den <b>&ouml;ffentlichen</b> Teil brauchst du gleich in Schritt 8, '
    + 'wenn du das Portal einrichtest.</p>'
    + warum('Warum ein Schl&uuml;sselpaar?',
        'Der private Schl&uuml;ssel beweist gegen&uuml;ber deinen Ger&auml;ten, '
      + 'dass DIESE Antwort wirklich von deinem Heimserver kommt und '
      + 'niemand sie unterwegs vertauscht hat. Der &ouml;ffentliche '
      + 'Schl&uuml;ssel darf jeder wissen; er verr&auml;t nichts.')
    + '<div id="schErgebnis"></div>',
    '<button onclick="zeigeHochladen()">Zur&uuml;ck</button>',
    '<button class="haupt" id="knopfSch" onclick="tuSchluessel()">Erzeugen</button>'
  ));
}

async function tuSchluessel() {
  $('#knopfSch').disabled = true;
  const ort = $('#schErgebnis');
  ort.innerHTML = meldung('erzeuge ...', 'warn');
  try {
    const d = await jsonAn('/api/schluessel', {});
    stand.agent_oeffentlich = d.oeffentlich;
    ort.innerHTML = meldung(
      (d.neu_erzeugt ? 'Erzeugt.' : 'Schl&uuml;sselpaar war bereits da.')
      + '<br>Privat: <code>' + d.pfad + '</code>'
      + '<br>&Ouml;ffentlich: <code>' + d.oeffentlich + '</code>',
      'gut');
    setTimeout(() => zeigeAgent(), 1100);
  } catch (e) {
    ort.innerHTML = meldung(e.message, 'fehler');
    $('#knopfSch').disabled = false;
  }
}

/* ------------------------------------------------------- Schritt 7: Agent */
function zeigeAgent() {
  jetzt = 6; leiste();
  const alt = stand.freigabe || '~/ahpt-freigabe';
  zeig(huelle(
    '<h2>Agent einrichten und starten</h2>'
    + '<p>Der Agent ist das Programm auf diesem Rechner, das Fragen vom '
    + 'Vermittler abholt, entschl&uuml;sselt, im freigegebenen Ordner '
    + 'nachsieht und die Antwort verschl&uuml;sselt zur&uuml;ckschickt.</p>'
    + warum('Was passiert genau?',
        'Der Assistent schreibt eine <code>agent_privat.toml</code> mit '
      + 'den Werten der vorigen Schritte, startet dann '
      + '<code>relay_agent.py</code> im Hintergrund. Der Agent l&auml;uft '
      + 'weiter, auch wenn du diesen Browser schlie&szlig;t.')
    + '<label>Ordner, den der Agent freigibt</label>'
    + '<input type="text" id="fFreigabe" value="' + alt + '">'
    + '<p class="leise">Dieser Ordner wird angelegt, falls es ihn '
    + 'nicht gibt. Er darf NICHT dein Home-Ordner sein.</p>'
    + '<div id="agErgebnis"></div>'
    + '<div id="agLog"></div>',
    '<button onclick="zeigeSchluessel()">Zur&uuml;ck</button>',
    '<button class="haupt" id="knopfAg" onclick="tuAgent()">Konfigurieren und starten</button>'
  ));
}

async function tuAgent() {
  $('#knopfAg').disabled = true;
  const ort = $('#agErgebnis');
  ort.innerHTML = meldung('schreibe Konfiguration ...', 'warn');
  try {
    const k = await jsonAn('/api/konfig', {
      freigabe: $('#fFreigabe').value.trim(),
    });
    stand.freigabe = k.freigabe;
    ort.innerHTML = meldung(
      'Konfiguration: <code>' + k.pfad + '</code><br>'
      + 'Freigabe: <code>' + k.freigabe + '</code>', 'gut');
    ort.insertAdjacentHTML('afterend',
      '<div id="agStart">' + meldung('starte Agent ...', 'warn') + '</div>');

    const s = await jsonAn('/api/agent', { was: 'start' });
    document.getElementById('agStart').innerHTML = meldung(
      s.laeuft ? ('Agent l&auml;uft (PID ' + s.pid + ').')
               : 'Der Agent scheint nicht zu laufen -- pr&uuml;fe das Log.',
      s.laeuft ? 'gut' : 'fehler');
    if (s.log_ende) {
      $('#agLog').innerHTML =
        '<h3>Log des Agenten (Ende)</h3>'
        + '<pre>' + s.log_ende.replace(/[<>&]/g, c => (
            {'<':'&lt;','>':'&gt;','&':'&amp;'}[c])) + '</pre>';
    }
    if (s.laeuft) setTimeout(() => zeigePortal(), 1800);
    else $('#knopfAg').disabled = false;
  } catch (e) {
    ort.innerHTML = meldung(e.message, 'fehler');
    $('#knopfAg').disabled = false;
  }
}

/* ------------------------------------------------------- Schritt 8: Portal */
function zeigePortal() {
  jetzt = 7; leiste();
  const pub = stand.agent_oeffentlich || '(nicht bekannt)';
  const web = stand.webspace || '';
  zeig(huelle(
    '<h2>Portal auf deinem Ger&auml;t</h2>'
    + '<p>Der Agent l&auml;uft und wartet auf verschl&uuml;sselte Fragen. '
    + 'Jetzt brauchst du das Portal &mdash; das ist die Weboberfl&auml;che, '
    + 'die du auf deinem Laptop oder Handy &ouml;ffnest, um an deine '
    + 'Dateien zu kommen. Egal welches Ger&auml;t: die Datei '
    + '<code>ahpt-portal-lokal.html</code> muss wirklich AUF diesem Ger&auml;t '
    + 'liegen und von dort ge&ouml;ffnet werden &mdash; nie &uuml;ber eine '
    + 'Netzwerk-Adresse, denn diese Datei h&auml;lt gleich einen privaten '
    + 'Schl&uuml;ssel, und der geh&ouml;rt nicht ins WLAN.</p>'

    + '<h3>Verbindungsdatei herunterladen</h3>'
    + '<p>Erspart dir, Adresse und Schl&uuml;ssel von Hand abzutippen '
    + '&mdash; genau da schleicht sich am ehesten ein Tippfehler ein. '
    + 'Lade die Datei herunter, bring sie zusammen mit '
    + '<code>ahpt-portal-lokal.html</code> aufs Ger&auml;t, und lies sie '
    + 'dort im Einrichtungs-Bildschirm des Portals mit dem Knopf '
    + '&bdquo;Verbindungsdatei laden&ldquo; ein.</p>'
    + '<button onclick="verbindungsdateiHerunterladen()">'
    + 'ahpt-verbindung.json herunterladen</button>'
    + warum('Ist das gefahrlos, so eine Datei herumzuschicken?',
        'Ja. Sie enth&auml;lt nur die Adresse des Vermittlers und den '
      + '&ouml;ffentlichen Schl&uuml;ssel des Agenten &mdash; beides ist '
      + 'ohnehin nicht geheim, der Schl&uuml;ssel steht sogar oben im Log. '
      + 'Der PRIVATE Schl&uuml;ssel jedes Ger&auml;ts entsteht separat, '
      + 'im Portal selbst, und steht in keiner Datei, die man '
      + 'verschicken k&ouml;nnte.')

    + '<h3>Von Hand eintragen (Alternative)</h3>'
    + '<p>Geht genauso, nur mehr Tipparbeit:</p>'
    + '<pre>'
    + 'Adresse des Vermittlers: ' + web + '\n'
    + 'Schl&uuml;ssel des Agenten:\n  ' + pub
    + '</pre>'
    + '<p>Danach im Portal auf <b>Schl&uuml;ssel erzeugen</b> klicken. Der '
    + 'neue Wert (64 Hex-Zeichen) muss dann noch beim Agenten eingetragen '
    + 'werden &mdash; dafuer bringt Schritt 9 einen eigenen Knopf mit, '
    + 'kein Rein-SSH und Texteditor mehr n&ouml;tig.</p>'
    + warum('Warum muss der Schl&uuml;ssel jedes Ger&auml;ts EINZELN eingetragen werden?',
        'Damit niemand sonst mit deinem Agent reden kann, auch wenn er '
      + 'die Adresse des Vermittlers kennt. Jedes Ger&auml;t weist sich '
      + 'mit seinem eigenen Schl&uuml;ssel aus; nur die in der '
      + 'clients-Liste kommen durch. Ein einmaliger Handgriff, dann '
      + 'gilt der Zugang.'),
    '<button onclick="zeigeAgent()">Zur&uuml;ck</button>',
    '<button class="haupt" onclick="zeigeFertig()">Fertig, ich bin durch</button>'
  ));
}

function verbindungsdateiHerunterladen() {
  // Nur die zwei oeffentlichen Werte -- kein Geheimnis darin. Siehe die
  // Begruendung im "warum"-Kasten daneben.
  const inhalt = JSON.stringify({
    typ: 'ahpt-verbindung', version: 1,
    basis: stand.webspace || '',
    agent_oeffentlich: stand.agent_oeffentlich || '',
  }, null, 2);
  const blob = new Blob([inhalt], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'ahpt-verbindung.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/* ------------------------------------------------------- Schritt 9: Fertig */
function zeigeFertig() {
  jetzt = 8; leiste();
  const web = stand.webspace || '';
  const pub = stand.agent_oeffentlich || '';
  zeig(huelle(
    '<h2>Das war&apos;s.</h2>'
    + '<p>Deine private Cloud steht. Zum Nachschlagen:</p>'
    + '<h3>Wichtige Werte</h3>'
    + '<pre>'
    + 'Vermittler:     ' + web + '\n'
    + 'Agent auf:      dieser Rechner\n'
    + 'Konfig:         ~/.ahpt/agent_privat.toml\n'
    + 'Log:            ~/.ahpt/agent_privat.log\n'
    + 'Portal:         ahpt-portal-lokal.html (auf jedem Ger&auml;t)\n'
    + '&Ouml;ffentl. Schl&uuml;ssel: ' + pub
    + '</pre>'
    + '<h3>Was, wenn etwas nicht mehr geht?</h3>'
    + '<ul class="leise">'
    + '<li>Der Agent ist tot: <code>python3 relay_agent.py --konfig '
    + '~/.ahpt/agent_privat.toml</code> im Terminal starten.</li>'
    + '<li>Ein neues Ger&auml;t einrichten: den Knopf unten benutzen, '
    + 'kein SSH und Texteditor n&ouml;tig.</li>'
    + (fertigEingerichtet
       ? '<li>Etwas &auml;ndern &ndash; anderer Webspace, anderer Ordner, neue '
         + 'Schl&uuml;ssel: oben in der Leiste auf den Schritt klicken. Das '
         + 'geht erst jetzt, wo alles einmal durchgelaufen ist.</li>'
       : '')
    + '<li>Diesen Assistenten nochmal aufrufen: <code>python3 einrichten.py</code>, '
    + 'oder im Fenster &bdquo;AHPT Cloud&ldquo; auf &bdquo;Einstellungen '
    + '&auml;ndern&ldquo;. Er &uuml;bernimmt den letzten Stand.</li>'
    + '</ul>'
    + meldung('Du kannst dieses Fenster jetzt schlie&szlig;en. '
      + 'Der Agent l&auml;uft weiter.', 'gut'),
    '<button onclick="zeigePortal()">Zur&uuml;ck</button>',
    '<button class="haupt" onclick="zeigeGeraetHinzufuegen()">'
    + '+ Weiteres Ger&auml;t hinzuf&uuml;gen</button>'
  ));
}

/* ------------------------------------------------- Extra: Geraet hinzufuegen */
//
// Kein eigener Punkt in der Leiste oben -- das ist keine einmalige Etappe
// der Einrichtung, sondern etwas, zu dem man beliebig oft zurueckkehrt.
// Bequemer als SSH + Texteditor, und macht denselben Fehler unmoeglich,
// den ein handgetippter Schluessel begehen kann: ein Tippfehler in einem
// von 64 Zeichen faellt hier sofort auf (Laengenpruefung), statt erst beim
// Verbindungsversuch als raetselhafte Ablehnung.
function zeigeGeraetHinzufuegen() {
  zeig(huelle(
    '<h2>Weiteres Ger&auml;t hinzuf&uuml;gen</h2>'

    + '<p>Zur Cloud f&uuml;hren zwei gleichwertige Wege: die App auf dem '
    + 'Handy oder das Portal im Browser. Beide brauchen dasselbe &ndash; die '
    + 'Adresse des Vermittlers und den Schl&uuml;ssel des Agenten &ndash;, und '
    + 'von beiden muss der eigene &ouml;ffentliche Schl&uuml;ssel hierher '
    + 'zur&uuml;ck. Nur der WEG dorthin unterscheidet sich.</p>'

    + '<h3>Die App: abfotografieren</h3>'
    + '<p>In der AHPT-App auf &bdquo;Code abfotografieren&ldquo; tippen. Die '
    + 'App richtet sich selbst ein und meldet sich hier zur&uuml;ck &ndash; '
    + 'nichts abzutippen, in keiner Richtung.</p>'
    + '<div id="qrOrt" style="text-align:center;margin:14px 0">'
    + '<img src="/kopplung.svg" alt="Kopplungscode" '
    + 'style="width:260px;height:260px;image-rendering:pixelated;'
    + 'background:#fff;padding:8px;border-radius:4px" '
    + 'onerror="qrFehlt()"></div>'
    + '<div id="qrWarten">' + meldung('Warte auf das Ger&auml;t &hellip;', 'warn')
    + '</div>'
    + '<div id="qrFirewall"></div>'
    + warum('Was steht in dem Code?',
        'Nur &Ouml;ffentliches: die Adresse des Vermittlers, der '
      + '&ouml;ffentliche Schl&uuml;ssel des Agenten, die Adressen dieses '
      + 'Assistenten und sein Zugangs-Token. Der PRIVATE Schl&uuml;ssel des '
      + 'Handys entsteht dort und verl&auml;sst es nie. '
      + 'Das Token ist der einzige schutzw&uuml;rdige Wert darin: Es lebt nur '
      + 'so lange wie dieser Assistent und gilt nur im eigenen Netz &ndash; '
      + 'aber wer den Code abfotografiert, kann ein Ger&auml;t zulassen. '
      + 'Also nicht herumzeigen und den Assistenten beenden, wenn du fertig '
      + 'bist. '
      + 'Kein WLAN zur Hand? Handy per USB anschlie&szlig;en und dort '
      + 'USB-Tethering einschalten &ndash; die Adressen im Code decken beides ab.')

    + '<h3 style="margin-top:22px">Das Portal: Schl&uuml;ssel eintragen</h3>'
    + '<p>Das Portal l&auml;uft im Browser und liest keine QR-Codes. Daf&uuml;r '
    + 'braucht es auch keine Kamera: Die Verbindungsdatei bekommst du im '
    + 'Schritt &bdquo;Portal&ldquo;, und den Schl&uuml;ssel, den das Portal '
    + 'beim ersten &Ouml;ffnen erzeugt, tr&auml;gst du hier ein. Derselbe Weg '
    + 'gilt, wenn die Kamera eines Handys nicht mitspielt.</p>'
    + '<label>&Ouml;ffentlicher Schl&uuml;ssel des neuen Ger&auml;ts</label>'
    + '<input type="text" id="fNeuesGeraet" placeholder="64 Hexzeichen">'
    + '<div id="geraetErgebnis"></div>',
    '<button onclick="zeigeFertig()">Zur&uuml;ck</button>',
    '<button class="haupt" id="knopfGeraet" onclick="tuGeraetHinzufuegen()">'
    + 'Hinzuf&uuml;gen</button>'
  ));
  wartAufGeraet();
  zeigeFirewallLage();
}

/* Was die Firewall zu diesem Port sagt.
 *
 * Zweimal am 07.09.2026 stand der Code sauber auf dem Bildschirm, das Handy
 * las ihn richtig -- und nichts passierte, weil eine Firewall dazwischen
 * lag. Das darf der Nutzer nicht erraten muessen. */
async function zeigeFirewallLage() {
  const ort = $('#qrFirewall');
  if (!ort) return;
  let d;
  try { d = await jsonAn('/api/firewall'); } catch (e) { return; }
  if (d.zustand === 'offen' || d.zustand === 'aus') return;   // nichts zu sagen

  if (d.zustand === 'zu') {
    ort.innerHTML = meldung(
      '<b>Die Firewall sperrt Port ' + d.port + '.</b> Ein anderes Ger&auml;t '
      + 'erreicht diesen Assistenten so nicht &ndash; der Code n&uuml;tzt dann '
      + 'nichts. Entweder den Assistenten auf einem freigegebenen Port starten '
      + '(<code>--port</code>), oder die Regel setzen:<br>'
      + '<code>' + (d.befehl || '').replace(/[<>&]/g, c => (
          {'<':'&lt;','>':'&gt;','&':'&amp;'}[c])) + '</code>', 'fehler');
  } else if (d.hinweis) {
    ort.innerHTML = meldung(d.hinweis, 'warn');
  }
}

function qrFehlt() {
  $('#qrOrt').innerHTML = meldung(
    'Der Kopplungscode l&auml;sst sich nicht erzeugen. Meist fehlt noch die '
    + 'Adresse des Vermittlers oder der Schl&uuml;ssel des Agenten &ndash; '
    + 'dann zuerst die Einrichtung zu Ende f&uuml;hren. Der Weg &uuml;ber '
    + 'das Eintragen unten funktioniert unabh&auml;ngig davon.', 'warn');
  $('#qrWarten').innerHTML = '';
}

/* Auf die Rueckmeldung des Handys warten.
 *
 * Das Intervall haelt sich selbst an, sobald sein Anzeigeort nicht mehr im
 * Dokument steht -- so muss keine andere Stelle daran denken, es zu
 * beenden, wenn der Nutzer weiterklickt. */
let geraetSeit = 0;
function wartAufGeraet() {
  geraetSeit = Date.now() / 1000;
  let gesagt = false;
  const takt = setInterval(async () => {
    const ort = document.getElementById('qrWarten');
    if (!ort) { clearInterval(takt); return; }
    // Nach einer Dreiviertelminute ohne Rueckmeldung: sagen, wo man
    // ueblicherweise sucht. Wer bis dahin gescannt hat und nichts sieht,
    // faengt sonst an, den QR-Code zu verdaechtigen -- und der ist es
    // fast nie.
    if (!gesagt && Date.now() / 1000 - geraetSeit > 45) {
      gesagt = true;
      ort.insertAdjacentHTML('beforeend', meldung(
        'Das dauert l&auml;nger als &uuml;blich. Wenn du schon gescannt hast: '
        + 'Der h&auml;ufigste Grund ist, dass Handy und Rechner nicht im selben '
        + 'Netz sind &ndash; oder eine Firewall dazwischen liegt. Der Weg '
        + '&uuml;ber das Eintragen unten funktioniert unabh&auml;ngig davon.',
        'warn'));
    }
    try {
      const d = await jsonAn('/api/gekoppelt');
      const z = d.zuletzt;
      if (z && z.zeit > geraetSeit) {
        clearInterval(takt);
        ort.innerHTML = meldung(
          '<b>' + (z.geraet || 'Ger&auml;t').replace(/[<>&]/g, c => (
            {'<':'&lt;','>':'&gt;','&':'&amp;'}[c])) + '</b> '
          + (z.war_schon_da ? 'war schon zugelassen.' : 'ist jetzt zugelassen.')
          + ' Der Agent l&auml;uft mit ' + z.anzahl_geraete
          + ' Ger&auml;t(en).', 'gut');
      }
    } catch (e) { /* Ein Aussetzer beim Abfragen ist kein Grund aufzuhoeren. */ }
  }, 1500);
}

async function tuGeraetHinzufuegen() {
  const feld = $('#fNeuesGeraet');
  const wert = feld.value.trim().toLowerCase().replace(/[^0-9a-f]/g, '');
  const ort = $('#geraetErgebnis');
  if (wert.length !== 64) {
    ort.innerHTML = meldung('Muss 64 Hexzeichen sein (hat ' + wert.length
      + ').', 'fehler');
    return;
  }
  $('#knopfGeraet').disabled = true;
  ort.innerHTML = meldung('trage ein und starte den Agenten neu ...', 'warn');
  try {
    const d = await jsonAn('/api/geraet_hinzufuegen', { schluessel: wert });
    ort.innerHTML = meldung(
      (d.war_schon_da ? 'War schon eingetragen. ' : 'Eingetragen. ')
      + 'Agent l&auml;uft mit ' + d.anzahl_geraete + ' zugelassenen Ger&auml;ten.',
      'gut');
    feld.value = '';
    if (d.log_ende) {
      ort.insertAdjacentHTML('beforeend',
        '<pre>' + d.log_ende.replace(/[<>&]/g, c => (
          {'<':'&lt;','>':'&gt;','&':'&amp;'}[c])) + '</pre>');
    }
  } catch (e) {
    ort.innerHTML = meldung(e.message, 'fehler');
  } finally {
    $('#knopfGeraet').disabled = false;
  }
}

/* ------------------------------------------------------- Start */
(async () => {
  try {
    const d = await jsonAn('/api/stand');
    stand = d.stand || {};
    $('#wo').textContent = 'laeuft auf ' + location.host;
    // Wer schon eingerichtet ist, faengt nicht wieder bei "Willkommen" an.
    // Er kommt aus einem bestimmten Grund zurueck -- ein Geraet zulassen,
    // den Webspace wechseln -- und findet beides auf der Schlussseite bzw.
    // ueber die Leiste oben. Ein Assistent, der Eingerichtete durch neun
    // Schritte schickt, wird beim zweiten Mal nicht mehr geoeffnet.
    if (stand.relay_vorhanden && stand.agent_oeffentlich) {
      fertigEingerichtet = true;
      jetzt = SCHRITTE.length - 1;
      zeigeFertig();
    } else {
      zeigeWillkommen();
    }
  } catch (e) {
    document.body.innerHTML = '<pre>Konnte den Stand nicht laden: '
      + e.message + '</pre>';
  }
})();
</script>
</body></html>"""


# --------------------------------------------------------------- main

def main():
    global _token, _stand, _port
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=None,
                    help='Vorgabe 8771. Ohne Angabe weicht der Assistent aus, '
                         'wenn eine Firewall diesen Port nachweislich sperrt.')
    ap.add_argument('--nur-localhost', action='store_true',
                    help='Nur 127.0.0.1, nicht ans LAN.')
    a = ap.parse_args()

    _token = secrets.token_hex(16)

    # Erst fragen, dann Port waehlen -- die Antwort kann die Portwahl
    # erübrigen. Ausdrueckliche Angaben (--port, --nur-localhost) gehen vor:
    # wer sie setzt, weiss was er will und soll nicht gefragt werden.
    _firewall_hinweis = None
    _nur_hier_grund = None
    if a.port is None and not a.nur_localhost:
        wahl = frage_wo_bedienen()
        if wahl == 'hier':
            a.nur_localhost = True
        elif wahl == 'netz':
            a.port, _firewall_hinweis = waehle_port(8771)
            # Blieb es beim Wunschport, obwohl der gesperrt ist, hat
            # waehle_port keinen brauchbaren gefunden -- dann ist dieses
            # Geraet der einzige Ort, an dem der Assistent zu bedienen ist.
            lage = firewall_lage(a.port)
            if lage['zustand'] == 'zu':
                _nur_hier_grund = (
                    'Es liess sich kein Port finden, der durch die Firewall '
                    'kommt. Der Assistent laeuft deshalb nur auf DIESEM '
                    'Geraet -- von einem anderen aus waere er nicht '
                    'erreichbar. Wer das aendern will: %s'
                    % lage.get('befehl', 'eine Firewall-Regel setzen'))
                a.nur_localhost = True
        else:
            # Keine Frage moeglich (kein Terminal): wie bisher automatisch.
            a.port, _firewall_hinweis = waehle_port(8771)

    if a.port is None:
        a.port = 8771
    _port = a.port
    _stand = stand_lesen()

    binden = '127.0.0.1' if a.nur_localhost else '0.0.0.0'
    try:
        server = LauschEndpunkt((binden, a.port), Auslieferer)
    except OSError as e:
        print('ABBRUCH: Port %d nicht verfuegbar (%s).' % (a.port, e))
        print('   Ein anderer AHPT-Einrichter laeuft schon, ODER es liegt')
        print('   irgendetwas anderes auf diesem Port. Anderen Port waehlen:')
        print('     python3 einrichten.py --port 8772')
        return 2

    # flush=True: bei Umleitung in eine Datei bleibt sonst alles im
    # Puffer, weil serve_forever() nie zurueckkehrt und der Prozess
    # nie beendet wird.
    def zeile(t=''):
        print(t, flush=True)

    zeile()
    zeile('AHPT Cloud -- Einrichtungs-Assistent')
    zeile('=' * 50)
    zeile('Oeffne diese Adresse im Browser dieses Rechners:'
          if a.nur_localhost else
          'Oeffne diese Adresse im Browser deines Laptops:')
    zeile()
    # Bei --nur-localhost lauscht der Server ausschliesslich auf 127.0.0.1.
    # Die LAN-Adressen trotzdem zu nennen, waere eine Einladung, es von
    # einem anderen Geraet zu versuchen -- und dort kommt nichts an.
    for adr in (['127.0.0.1'] if a.nur_localhost else eigene_adressen()):
        zeile('    http://%s:%d/?t=%s' % (adr, a.port, _token))
    zeile()
    if _nur_hier_grund:
        zeile('NUR AUF DIESEM GERAET:')
        for stueck in textwrap.wrap(_nur_hier_grund, 66):
            zeile(stueck)
        zeile()
    if _firewall_hinweis and not _nur_hier_grund:
        zeile('ZUR FIREWALL:')
        for stueck in textwrap.wrap(_firewall_hinweis, 66):
            zeile(stueck)
        zeile()
    if not a.nur_localhost:
        # WICHTIG, nicht nur Zierrat: Wer diese Adresse ueber das WLAN
        # oeffnet statt ueber 127.0.0.1, schickt beim FTP-Schritt sein
        # Passwort unverschluesselt durch dieses Netz -- der Assistent
        # kann kein https anbieten (kein Zertifikat vorhanden). Ueber
        # localhost verlaesst nichts jemals diesen Rechner. Am 03.09.2026
        # im Sicherheitsaudit gefunden: das stand bisher nirgends.
        zeile('ACHTUNG: Der FTP-Schritt schickt das Passwort unverschluesselt')
        zeile('durch dein Netzwerk, wenn du diese Seite nicht auf DIESEM')
        zeile('Rechner selbst oeffnest (also ueber die LAN-Adresse oben, nicht')
        zeile('ueber 127.0.0.1). Im eigenen Heimnetz vertretbar, in einem')
        zeile('Hotel-/Cafe-/Firmen-WLAN nicht. Dann: --nur-localhost verwenden')
        zeile('und den Assistenten direkt am Heimserver bedienen.')
        zeile()
    zeile('Der Assistent laeuft nur, solange dieses Fenster offen ist.')
    zeile('Zum Beenden: Strg-C')
    zeile()

    # Wer hier am Geraet bedient, soll nicht die Adresse abtippen muessen.
    # Auf einem Server ohne Oberflaeche tut sich nichts -- dann steht die
    # Adresse eben auf der Konsole, und das ist in Ordnung.
    if a.nur_localhost and _browser_oeffnen(
            'http://127.0.0.1:%d/?t=%s' % (a.port, _token)):
        zeile('Der Browser sollte sich gerade oeffnen.')
        zeile()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nBeendet.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
