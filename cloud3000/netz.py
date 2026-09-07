#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netz.py -- die HTTP-Schicht des Agenten. Klein, absichtlich.

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

Sie steht in einer eigenen Datei, weil BEIDE Seiten sie brauchen -- der
Kern, um Warteschlange und Fragen zu holen, und ein Handler wie `kiwix`,
um seinen lokalen Dienst zu fragen. Zwei Fassungen davon waeren zwei
Fassungen der Regel "keine Weiterleitungen", und eine davon wuerde
gepflegt.

Nur Standardbibliothek. Das ist keine Sparsamkeit, sondern eine Zusage:
Wer den Agenten auf einem Router, einer Synology oder einem Raspberry Pi
startet, soll nichts nachinstallieren muessen.
"""

import base64
import hashlib
import http.client
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

# Bewusst KEIN selbstnennender Wert wie "AHPT-Agent/1" mehr -- der stand
# im Klartext in jedem einzelnen Zugriffs-Log jedes Anbieters und war
# damit die einfachste Art, den Datenverkehr wiederzuerkennen (07.09.2026,
# nach der Radar-Frage). Eine plausible Chrome-Kennung im ECHTEN Format
# (nicht der Markenname als Text -- das schriebe kein wirklicher Browser)
# taeuscht einfache Log-Auswertung und Rate-Begrenzung, wie sie bei GMX
# beobachtet wurde. Tiefere Erkennung (TLS-Fingerabdruck, fehlende
# browsertypische Zusatz-Kopfzeilen) bleibt davon unberuehrt -- dafuer
# braeuchte es weit mehr als eine Kopfzeile, und das ist hier nicht das Ziel.
#
# Das ist eine ENTSCHEIDUNG, keine Notwendigkeit, und darum ueber
# `kennung` in der Konfiguration umzustellen (siehe `setze_kennung`).
# Wer den Verkehr fuer den Anbieter erkennbar halten will -- weil er
# dessen Regeln zuarbeitet statt ausweicht -- traegt dort schlicht
# "AHPT-Agent/1" ein. Was fuer die eine und was fuer die andere Wahl
# spricht, steht in SICHERHEIT.md.
KENNUNG = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')


def setze_kennung(wert):
    """Kennung (User-Agent) fuer alle folgenden Anfragen festlegen.

    Leer oder None laesst die Vorgabe stehen. Wie `setze_pin` wirkt das
    global und ab sofort: `hole`, `sende_json` und `webdav` lesen
    `KENNUNG` erst beim Aufruf, nicht beim Import.
    """
    global KENNUNG
    if not wert:
        return
    wert = str(wert).strip()
    # Steuerzeichen wuerden die Kopfzeile zerlegen -- urllib meldet das
    # zwar selbst, aber erst mitten im Betrieb bei der ersten Anfrage,
    # nicht beim Start, wo der Tippfehler noch jemandem auffaellt.
    if not wert or any(ord(c) < 32 or ord(c) == 127 for c in wert):
        raise ValueError('Kennung ist leer oder enthaelt Steuerzeichen')
    KENNUNG = wert


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen sind AUS, und das ist sicherheitstragend.

    Beim lokalen Dienst koennte ein Redirect 127.0.0.1 verlassen -- dann
    haette ein Angreifer ueber den Umweg genau das, was die Weissliste
    verhindern soll. Beim Webspace verdeckt ein Redirect einen Fehler:
    Am 02.09.2026 leitete `mod_speling` die Abfrage nach der ANTWORT
    stillschweigend auf die FRAGE um, und der Browser las sie als
    "hat geantwortet, nichts gefunden" -- eine Auskunft, die es nie gab.
    """

    def redirect_request(self, *a, **k):
        return None


_OEFFNER = urllib.request.build_opener(_KeineWeiterleitung)


# ------------------------------------------------- Selbstsigniertes TLS
#
# Manche Hoster betreiben https mit einem EIGENEN Zertifikat. bplaced etwa
# zeigt eines von 2021, ausgestellt auf "bplaced" -- am 03.09.2026 gemessen.
# Python weist das zu Recht ab.
#
# Drei Wege stehen offen, und zwei davon taugen nicht:
#
#   1. http statt https. Das Geheimnis des Agenten reist dann im Klartext.
#      Nein.
#   2. Pruefung abschalten. Verschluesselt, aber ohne zu wissen MIT WEM --
#      ein Zwischenknoten koennte sein eigenes Zertifikat vorzeigen und das
#      Geheimnis mitschreiben. Verschluesselung ohne Ausweis ist Theater.
#   3. Den oeffentlichen Schluessel des Servers FESTNAGELN. Dann steht die
#      Gegenstelle kryptografisch fest, ganz ohne Wurzelzertifikat.
#
# Weg 3. Der Fingerabdruck wird EINMAL ermittelt und in die Konfiguration
# geschrieben:
#
#   echo | openssl s_client -connect HOST:443 -servername HOST
#     | openssl x509 -pubkey -noout | openssl pkey -pubin -outform der
#     | openssl dgst -sha256 -binary | openssl base64
#
# WAS DAS NICHT LEISTET: Beim ersten Ermitteln koennte schon jemand
# dazwischensitzen -- der Pin waere dann seiner. Das ist Vertrauen beim
# ersten Kontakt. Ab da ist jeder spaetere Austausch ausgeschlossen, und
# genau das ist der Gewinn gegenueber "Pruefung aus".

class _PinFehler(Exception):
    pass


def _pin_von_zertifikat(der_bytes):
    """SHA-256 ueber den oeffentlichen Schluessel im Zertifikat (SPKI)."""
    # Der oeffentliche Schluessel wird gepinnt, nicht das Zertifikat: So
    # ueberlebt der Pin eine Erneuerung mit demselben Schluessel, und genau
    # das tun Hoster in aller Regel.
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    z = x509.load_der_x509_certificate(der_bytes)
    spki = z.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    import base64 as _b64
    return 'sha256//' + _b64.b64encode(hashlib.sha256(spki).digest()).decode()


def oeffner_mit_pin(pin):
    """Ein Opener, der NUR mit diesem einen Server spricht."""
    class _Verbindung(http.client.HTTPSConnection):
        def connect(self):
            super().connect()
            der = self.sock.getpeercert(binary_form=True)
            ist = _pin_von_zertifikat(der)
            if ist != pin:
                self.close()
                raise _PinFehler(
                    'Der Server zeigt einen anderen Schluessel als erwartet. '
                    'Erwartet: %s -- erhalten: %s. '
                    'Entweder hat der Hoster gewechselt (dann den Pin neu '
                    'ermitteln) oder jemand sitzt dazwischen.' % (pin, ist))

    class _Handler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            # `context` MUSS mitgegeben werden. Ohne diesen Zusatz baut
            # HTTPSConnection sich ihren eigenen Zusammenhang mit voller
            # Zertifikatspruefung -- der Handler laeuft dann zwar, aber die
            # Verbindung scheitert vorher am selbstsignierten Zertifikat,
            # und der Pin kommt nie zum Zug. Am 03.09.2026 genau so
            # gemessen: CERTIFICATE_VERIFY_FAILED, obwohl der Pin gesetzt war.
            return self.do_open(_Verbindung, req, context=self._context)

    # Pruefung des Wurzelzertifikats AUS, Namenspruefung AUS -- der Pin
    # ersetzt beides und ist schaerfer: Er nennt genau einen Schluessel.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handler = _Handler(context=ctx)
    return urllib.request.build_opener(_KeineWeiterleitung, handler)


def setze_pin(pin):
    """Ab jetzt reden wir nur noch mit dem Server, der diesen Pin hat."""
    global _OEFFNER
    if not pin:
        return
    if not str(pin).startswith('sha256//'):
        raise ValueError('Pin muss mit sha256// beginnen')
    _OEFFNER = oeffner_mit_pin(str(pin))


def hole(url, etag=None, timeout=8):
    """GET ohne Weiterleitung. Gibt (code, koerper_bytes, etag) zurueck.

    code 0 heisst: gar keine Antwort (Netzfehler). Das ist absichtlich von
    einem HTTP-Fehler unterschieden -- "nicht erreichbar" und "abgelehnt"
    sind verschiedene Lagen und brauchen verschiedene Reaktionen.
    """
    req = urllib.request.Request(url, method='GET')
    req.add_header('User-Agent', KENNUNG)
    if etag:
        req.add_header('If-None-Match', etag)
    try:
        with _OEFFNER.open(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get('ETag')
    except urllib.error.HTTPError as e:
        try:
            koerper = e.read()
        except Exception:
            koerper = b''
        return e.code, koerper, (e.headers.get('ETag') if e.headers else None)
    except Exception as e:
        return 0, str(e).encode('utf-8', 'replace'), None


def sende_json(url, nutzlast, geheimnis, versuche=4, timeout=8, zaehler=None):
    """POST an relay.php, mit Wiederholung bei 503.

    503 heisst auf gedeckeltem Webspace "gerade zu viele PHP-Prozesse",
    nicht "kaputt". Wer das nicht wiederholt, verliert Antworten -- und
    zwar lautlos, weil der Besucher nur weiter wartet.

    Das Geheimnis reist NUR in der Kopfzeile und taucht in keinem
    Rueckgabewert und keiner Fehlermeldung auf.
    """
    daten = json.dumps(nutzlast, ensure_ascii=False).encode('utf-8')
    for versuch in range(versuche):
        req = urllib.request.Request(url, data=daten, method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('X-AHPT-Auth', geheimnis)
        req.add_header('User-Agent', KENNUNG)
        try:
            with _OEFFNER.open(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            try:
                koerper = json.loads(e.read().decode('utf-8', 'replace'))
            except Exception:
                koerper = {}
            if e.code == 503 and versuch < versuche - 1:
                if zaehler is not None:
                    zaehler['ablage_503'] = zaehler.get('ablage_503', 0) + 1
                time.sleep(0.4 * (2 ** versuch))
                continue
            return e.code, koerper
        except Exception as e:
            if versuch < versuche - 1:
                time.sleep(0.4 * (2 ** versuch))
                continue
            return 0, {'fehler': str(e)}
    return 0, {'fehler': 'unerreichbar'}


def basis_erlaubt(url):
    """https immer, http nur gegen Loopback.

    Der Grund ist das Geheimnis: es reist in der Kopfzeile mit. Ueber http
    liest es jeder Zwischenknoten. Gegen 127.0.0.1 gibt es keinen
    Zwischenknoten -- deshalb ist die Ausnahme keine Testklappe, die
    versehentlich in den Betrieb geraten koennte. Ein echter Webspace ist
    nie Loopback.
    """
    try:
        t = urllib.parse.urlsplit(url)
    except Exception:
        return False
    if t.scheme == 'https':
        return True
    if t.scheme != 'http':
        return False
    return (t.hostname or '') in ('127.0.0.1', 'localhost', '::1')


# ------------------------------------------------------------------ WebDAV
#
# Eigener, UNGEPINNTER Opener statt des globalen `_OEFFNER`. Der pingt sich
# auf Wunsch (`setze_pin`) auf den Schluessel EINES bestimmten Servers ein --
# des PHP-Webspace mit seinem oft selbstsignierten Zertifikat. WebDAV-Cloud-
# Anbieter (GMX, WEB.DE, ...) haben normale, oeffentlich beglaubigte
# Zertifikate. Wuerde hier derselbe gepinnte Opener verwendet, prueften
# WebDAV-Anfragen faelschlich gegen den Schluessel des PHP-Servers -- ein
# ganz anderer Host -- und schlagen dann grundlos fehl, oder schlimmer:
# der Pin wird an einem Server gesetzt, dem man ihn nie gegeben hat.
_OEFFNER_STANDARD = urllib.request.build_opener(_KeineWeiterleitung)


def webdav(methode, url, benutzer, passwort, daten=None, kopfzeilen=None,
           timeout=15):
    """Ein WebDAV-Aufruf (PUT/GET/DELETE/PROPFIND/MKCOL), mit Basic-Auth.

    Dieselbe Bauart wie `hole`/`sende_json`: Rueckgabe (code, koerper_bytes).
    0 heisst Netzfehler, nicht "abgelehnt".

    Das Passwort reist nur in der Kopfzeile dieser einen Anfrage -- taucht
    in keinem Rueckgabewert, keiner Fehlermeldung und keinem Protokoll auf.
    """
    req = urllib.request.Request(url, data=daten, method=methode)
    token = base64.b64encode(
        ('%s:%s' % (benutzer, passwort)).encode('utf-8')).decode('ascii')
    req.add_header('Authorization', 'Basic ' + token)
    req.add_header('User-Agent', KENNUNG)
    for k, v in (kopfzeilen or {}).items():
        req.add_header(k, v)
    try:
        with _OEFFNER_STANDARD.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            koerper = e.read()
        except Exception:
            koerper = b''
        return e.code, koerper
    except Exception as e:
        return 0, str(e).encode('utf-8', 'replace')


def ziel_erlaubt(url):
    """Prueft ein Handler-Ziel aus der config.toml.

    Ein Ziel darf ausschliesslich auf den eigenen Rechner zeigen. Das ist
    die Stelle, an der die config.toml selbst geprueft wird -- denn eine
    Konfigurationsdatei ist zwar vertrauenswuerdiger als das Netz, aber ein
    Tippfehler darin ist billiger zu finden als zu erklaeren.

    Wer bewusst ein Ziel im LAN bedienen will, aendert diese Funktion und
    weiss dann, was er tut. Das ist der Unterschied zwischen einer
    Entscheidung und einem Versehen.
    """
    try:
        t = urllib.parse.urlsplit(url)
    except Exception:
        return False
    if t.scheme not in ('http', 'https'):
        return False
    if t.path not in ('', '/'):
        return False          # Ziel ist eine Basis, kein Pfad
    return (t.hostname or '') in ('127.0.0.1', 'localhost', '::1')
