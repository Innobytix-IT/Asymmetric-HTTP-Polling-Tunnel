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

import json
import time
import urllib.error
import urllib.parse
import urllib.request

KENNUNG = 'AHPT-Agent/1'


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
