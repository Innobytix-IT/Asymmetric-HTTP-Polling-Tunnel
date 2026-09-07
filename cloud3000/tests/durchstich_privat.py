#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
durchstich_privat.py -- Client -> Vermittler -> Agent -> Datei -> zurueck,
                        verschluesselt

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT


  ####  GEGEN EINE ATTRAPPE, NICHT GEGEN relay.php.  ####


Was hier gruen wird, ist der Weg: Client, Agent, Handler, Stueckelung und
vor allem die Verschluesselung. Was hier NICHT gruen wird, ist relay.php --
kein PHP, kein Apache, kein mod_speling, keine Prozessgrenze.

DIE WICHTIGSTE PRUEFUNG STEHT IN ABSCHNITT 3
--------------------------------------------
Dass etwas ankommt, beweist nichts ueber Vertraulichkeit. Ein Kanal, der
alles korrekt uebertraegt UND dabei alles offenlegt, besteht jeden
Gutfall-Test.

Deshalb wird hier nachgesehen, was tatsaechlich auf dem "Webspace" liegt --
und zwar auf ABWESENHEIT geprueft: Dateiname, Inhalt, Dienst und Aktion
duerfen in keiner der abgelegten Dateien vorkommen, in keiner Kodierung.

Aufruf:
    python3 tests/durchstich_privat.py
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
sys.path.insert(0, HIER)
sys.path.insert(0, WURZEL)

import ahpt_client                                       # noqa: E402
import attrappe_relay                                    # noqa: E402
import krypto                                            # noqa: E402

ERGEBNIS = []


def _tempdatei(inhalt, endung):
    """Legt einen Blob in eine Wegwerfdatei. Fuer die Blockuebertragung
    braucht lege_in_bloecken einen echten Pfad, nicht Bytes im Speicher."""
    fd, p = tempfile.mkstemp(suffix=endung, prefix='ahpt_probe_')
    with os.fdopen(fd, 'wb') as f:
        f.write(inhalt)
    return p


def _tempziel(name):
    p = os.path.join(tempfile.gettempdir(), 'ahpt_ziel_' + name)
    if os.path.exists(p):
        os.unlink(p)
    return p


def pruefe(beschreibung, bedingung, hinweis=''):
    ok = bool(bedingung)
    ERGEBNIS.append(ok)
    print('  %-56s %s%s' % (beschreibung, 'ok' if ok else 'FEHLSCHLAG',
                            ('  -- ' + hinweis) if hinweis and not ok else ''))
    return ok


def alle_dateien(ordner):
    """Alles, was auf dem 'Webspace' liegt -- als Rohbytes."""
    raus = {}
    for w, _, ds in os.walk(ordner):
        for d in ds:
            p = os.path.join(w, d)
            with open(p, 'rb') as f:
                raus[os.path.relpath(p, ordner)] = f.read()
    return raus


def kommt_vor(dateien, nadel):
    """Sucht eine Zeichenfolge in ALLEN abgelegten Dateien.

    Auch base64-kodiert und hex -- sonst hiesse "nicht gefunden" nur, dass
    man nicht richtig gesucht hat.
    """
    roh = nadel.encode('utf-8')
    formen = [roh,
              base64.b64encode(roh),
              base64.b64encode(roh).rstrip(b'='),
              roh.hex().encode('ascii')]
    for name, inhalt in dateien.items():
        for f in formen:
            if f and f in inhalt:
                return name
    return None


def main():
    basis_ordner = tempfile.mkdtemp(prefix='ahpt_privat_')
    agent = None
    srv = None
    agent_log = None
    protokoll = os.path.join(basis_ordner, 'agent.log')
    try:
        webspace = os.path.join(basis_ordner, 'webspace')
        freigabe = os.path.join(basis_ordner, 'freigabe')
        os.makedirs(webspace)
        os.makedirs(os.path.join(freigabe, 'unter'))

        GEHEIMER_TEXT = 'Kontonummer DE99 1234 5678 9012 3456 78'
        with open(os.path.join(freigabe, 'gehaltsabrechnung.txt'), 'w',
                  encoding='utf-8') as f:
            f.write(GEHEIMER_TEXT)
        gross = bytes((i * 37 + 11) % 256 for i in range(300000))
        with open(os.path.join(freigabe, 'scan.png'), 'wb') as f:
            f.write(gross)

        # Schluessel. Beide Seiten je eines; der oeffentliche Teil des einen
        # steht in der Konfiguration des anderen -- von Hand, wie im Betrieb.
        a_priv, a_pub = krypto.schluesselpaar()
        c_priv, c_pub = krypto.schluesselpaar()
        f_priv, f_pub = krypto.schluesselpaar()          # ein Fremder
        for name, wert in (('agent.key', a_priv), ('client.key', c_priv),
                           ('fremd.key', f_priv)):
            krypto.schreibe_privat(os.path.join(basis_ordner, name), wert)

        geheimnis = 'a' * 64
        gpfad = os.path.join(basis_ordner, 'geheimnis')
        with open(gpfad, 'w') as f:
            f.write(geheimnis)

        srv, port = attrappe_relay.starte(webspace, geheimnis)
        basis = 'http://127.0.0.1:%d' % port

        akonf = {
            'relay': {'basis': basis, 'geheimnis_datei': gpfad,
                      'poll_abstand': 0.3, 'unbedingt_nach': 2},
            'krypto': {'verfahren': 'noise_ik',
                       'schluessel': os.path.join(basis_ordner, 'agent.key'),
                       'clients': [c_pub.hex()]},
            'dienst': [{'name': 'dateien', 'art': 'datei', 'wurzel': freigabe,
                        'aktionen': ['liste', 'hole', 'lege',
                                     'neuer_ordner'],
                        # mp4 ist bewusst dabei -- fuer die Blockprobe unten.
                        # exe bleibt draussen fuer die "gesperrte Endung"-
                        # Pruefung, txt/png fuer die alten Faelle. Zeigt
                        # gleichzeitig, dass die Weissliste weiter greift.
                        'endungen': ['txt', 'png', 'mp4'],
                        # 10 MiB, damit die Blockprobe (6,5 MiB, drei Bloecke)
                        # durchgeht. Die Vorgabe 5 MiB wuerde sie ablehnen --
                        # richtig, aber nicht das, was hier geprueft wird.
                        'max_bytes': 10 * 1024 * 1024}],
        }
        akpfad = os.path.join(basis_ordner, 'agent.json')
        with open(akpfad, 'w', encoding='utf-8') as f:
            json.dump(akonf, f)

        def klient(privat=None, agent_pub=None):
            return ahpt_client.Client(ahpt_client.Aufbau({
                # wiederholungen=1: Dieser Test prueft absichtlich Faelle
                # ohne Antwort (Kapitel "fail-closed"). Mit dem Standardwert
                # muesste jeder dieser Faelle die volle Frist mehrfach
                # abwarten, statt einmal schnell und eindeutig zu scheitern.
                #
                # gesundheit_datei EXPLIZIT in basis_ordner: Ohne sie liegt
                # sie neben dem (hier nicht existierenden) "client.toml" im
                # Arbeitsverzeichnis -- geteilt mit JEDEM anderen Lauf, der
                # zufaellig vom selben Ordner aus startet. Isoliert wie
                # jede andere Zustandsdatei dieses Tests.
                'relay': {'basis': basis, 'frist': 40, 'abstand': 0.25,
                          'wiederholungen': 1,
                          'gesundheit_datei': os.path.join(
                              basis_ordner, 'client-gesundheit.json')},
                'krypto': {'verfahren': 'noise_ik',
                           'schluessel': privat or os.path.join(basis_ordner,
                                                                'client.key'),
                           'agent': (agent_pub or a_pub).hex()}}))

        print('')
        print('Attrappe auf %s   (BEWEIST NICHTS UEBER relay.php)' % basis)
        agent_log = open(protokoll, 'w', encoding='utf-8')
        agent = subprocess.Popen(
            [sys.executable, os.path.join(WURZEL, 'relay_agent.py'),
             '--konfig', akpfad],
            cwd=WURZEL, stdout=agent_log, stderr=subprocess.STDOUT, text=True)
        time.sleep(1.5)
        if agent.poll() is not None:
            agent_log.flush()
            print(open(protokoll, encoding='utf-8').read())
            raise SystemExit('Agent ist nicht angelaufen.')

        # ---------------------------------------------------- 1. Der Weg
        print('')
        print('1 -- DURCHSTICH')
        print('')
        k = klient()

        a = k.frage('dateien', 'liste', {'pfad': ''})
        pruefe('Auflistung kommt an', a.get('gefunden'), str(a)[:80])
        namen = [e['name'] for e in json.loads(a.get('inhalt', '{}'))
                 .get('eintraege', [])]
        pruefe('Auflistung nennt die Dateien',
               'gehaltsabrechnung.txt' in namen and 'scan.png' in namen,
               str(namen))

        a = k.frage('dateien', 'hole', {'pfad': 'gehaltsabrechnung.txt'})
        pruefe('kleine Datei kommt unverfaelscht an',
               a.get('gefunden') and a.get('inhalt') == GEHEIMER_TEXT)

        a = k.frage('dateien', 'hole', {'pfad': 'scan.png'})
        zurueck = base64.b64decode(a.get('inhalt', '')) if a.get('gefunden') else b''
        pruefe('grosse Datei ist Byte fuer Byte dieselbe', zurueck == gross,
               '%d von %d Bytes' % (len(zurueck), len(gross)))

        # ------------------------------------------------ 1b. Hochladen
        print('')
        print('1b -- HOCHLADEN')
        print('')

        klein = b'Ein kleiner Beleg.'
        a = k.frage('dateien', 'lege', {
            'pfad': 'beleg.txt', 'inhalt_typ': 'base64',
            'inhalt': base64.b64encode(klein).decode('ascii')})
        pruefe('kleine Datei wird abgelegt', a.get('gefunden'),
               str(a.get('grund', ''))[:60])
        ziel = os.path.join(freigabe, 'beleg.txt')
        pruefe('sie liegt wirklich auf dem Heimserver',
               os.path.isfile(ziel) and open(ziel, 'rb').read() == klein)

        # Noch einmal derselbe Name: darf NICHT ueberschreiben.
        a = k.frage('dateien', 'lege', {
            'pfad': 'beleg.txt', 'inhalt_typ': 'base64',
            'inhalt': base64.b64encode(b'etwas anderes').decode('ascii')})
        neuname = json.loads(a.get('inhalt', '{}')).get('abgelegt', '')
        pruefe('zweite Datei ueberschreibt nicht', neuname == 'beleg (2).txt',
               'wurde %r' % neuname)
        pruefe('das Original ist unveraendert',
               open(ziel, 'rb').read() == klein)

        # Grosse Datei: das Chiffrat passt nicht mehr in eine Nachricht,
        # also gestueckelt hinauf.
        gross_hoch = bytes((i * 91 + 7) % 256 for i in range(200000))
        a = k.frage('dateien', 'lege', {
            'pfad': 'unter/scan_hoch.png', 'inhalt_typ': 'base64',
            'inhalt': base64.b64encode(gross_hoch).decode('ascii')})
        pruefe('grosse Datei wird gestueckelt hochgeladen', a.get('gefunden'),
               str(a.get('grund', ''))[:60])
        zielg = os.path.join(freigabe, 'unter', 'scan_hoch.png')
        pruefe('grosse Datei kam Byte fuer Byte an',
               os.path.isfile(zielg) and open(zielg, 'rb').read() == gross_hoch,
               '%d statt %d Bytes' % (
                   os.path.getsize(zielg) if os.path.isfile(zielg) else -1,
                   len(gross_hoch)))

        a = k.frage('dateien', 'neuer_ordner', {'pfad': 'rechnungen'})
        pruefe('Ordner wird angelegt',
               a.get('gefunden')
               and os.path.isdir(os.path.join(freigabe, 'rechnungen')))

        # --- BLOCKUEBERTRAGUNG: Datei jeder Groesse, jedes Format ---
        #
        # 6 MiB > 4 MiB Blockgroesse des CLI-Clients -- MUSS ueber mehrere
        # Bloecke gehen, sonst nichts bewiesen. Endung .mp4 waere vor dem
        # Umbau doppelt abgewiesen worden: einmal wegen der Weissliste,
        # einmal weil das Chiffrat nicht in EINE Frage passt.
        gross = bytes((i * 251 + 13) % 256 for i in range(6_500_000))
        d = ahpt_client.lege_in_bloecken(
            k, 'dateien', _tempdatei(gross, '.mp4'), 'bericht.mp4', laut=False)
        pruefe('grosse Datei in Bloecken hinaufgelegt',
               isinstance(d, dict) and d.get('bloecke', 0) >= 2,
               'bloecke=%r' % (d or {}).get('bloecke'))
        pruefe('grosse Datei kam Byte fuer Byte an',
               os.path.isfile(os.path.join(freigabe, 'bericht.mp4'))
               and open(os.path.join(freigabe, 'bericht.mp4'), 'rb').read() == gross)
        pruefe('keine Teildatei zurueckgeblieben',
               not os.path.isdir(os.path.join(freigabe, '.ahpt-teil'))
               or len(os.listdir(os.path.join(freigabe, '.ahpt-teil'))) == 0)

        # Gegenprobe herunter -- bereichsweise, mit Pruefsumme.
        rueck = _tempziel('bericht_rueck.mp4')
        n = ahpt_client.hole_in_bloecken(k, 'dateien', 'bericht.mp4',
                                         rueck, laut=False)
        pruefe('grosse Datei bereichsweise heruntergeholt', n == len(gross),
               '%d statt %d' % (n or -1, len(gross)))
        pruefe('herunter Byte fuer Byte dieselbe Datei',
               open(rueck, 'rb').read() == gross)

        # Und die Schranken beim SCHREIBEN -- die gefaehrlichste Aktion.
        for boese, was in (('../draussen.txt', 'Pfadwanderung'),
                           ('/etc/cron.d/x',   'absoluter Pfad'),
                           ('.bashrc',         'versteckte Datei'),
                           ('unter/../../x.txt', 'Wanderung ueber Unterordner')):
            a = k.frage('dateien', 'lege', {
                'pfad': boese, 'inhalt_typ': 'text', 'inhalt': 'boese'})
            pruefe('Schreiben abgewiesen: %s' % was, not a.get('gefunden'))
        pruefe('nichts ausserhalb der Wurzel entstanden',
               not os.path.exists(os.path.join(basis_ordner, 'draussen.txt'))
               and not os.path.exists(os.path.join(basis_ordner, 'x.txt')))

        a = k.frage('dateien', 'lege', {
            'pfad': 'schad.exe', 'inhalt_typ': 'text', 'inhalt': 'x'})
        pruefe('Schreiben abgewiesen: nicht freigegebene Endung',
               not a.get('gefunden'))

        # ------------------------------------- 2. Was der Webspace sieht
        print('')
        print('2 -- WAS AUF DEM WEBSPACE LIEGT')
        print('')
        dateien = alle_dateien(webspace)
        print('  %d Dateien abgelegt' % len(dateien))
        # DIE NADELN MUESSEN LANG SEIN, und mindestens eine davon muss ein
        # Zeichen enthalten, das Base64 gar nicht kennen kann.
        #
        # Am 03.09.2026 schlug diese Pruefung fehl, weil nach `hole` gesucht
        # wurde -- vier Zeichen. In 400 KB Base64-Rauschen taucht jede
        # Vierzeichenfolge irgendwann zufaellig auf (64^4 sind nur 16
        # Millionen Moeglichkeiten). Der Befund war ein Fehlalarm, und ein
        # Pruefer, der grundlos Alarm schlaegt, wird beim zweiten Mal
        # ignoriert -- und findet danach auch die echten Fehler nicht mehr.
        #
        # Mit Anfuehrungszeichen ist die Nadel doppelt sicher: Sie ist laenger,
        # UND das Anfuehrungszeichen kommt im Base64-Alphabet nicht vor. Was
        # gesucht wird, ist ohnehin die JSON-Form -- genau die stuende dort,
        # wenn nicht verschluesselt wuerde.
        for nadel, was in (
                (GEHEIMER_TEXT,          'der Inhalt der Datei'),
                ('gehaltsabrechnung',    'der Dateiname'),
                ('"dateien"',            'der Name des Dienstes'),
                ('"hole"',               'die Aktion'),
                ('"eintraege"',          'die Struktur der Auflistung'),
                ('"gefunden"',           'ob etwas gefunden wurde'),
                ('"beleg.txt"',          'der Name der hochgeladenen Datei'),
                ('Ein kleiner Beleg',    'der Inhalt der hochgeladenen Datei'),
                ('"rechnungen"',         'der Name des neuen Ordners')):
            wo = kommt_vor(dateien, nadel)
            pruefe('nicht auffindbar: %s' % was, wo is None,
                   'steht in %s' % wo)

        # Die Gegenprobe: Ohne sie hiesse "nichts gefunden" womoeglich nur,
        # dass die Suche nicht funktioniert.
        pruefe('Gegenprobe: die Suche findet, was da IST',
               kommt_vor(dateien, '"krypto"') is not None
               and kommt_vor(dateien, 'noise_ik') is not None,
               'wenn das nicht gefunden wird, sucht die Pruefung falsch')
        # Anmerkung zur vorigen Zeile: Hier liegen zu diesem Zeitpunkt nur
        # Dateien des PYTHON-Clients, und der nutzt `noise_ik`. Das Portal
        # (`noise_ik_aes`) laeuft erst danach. Der erste Entwurf suchte nach
        # `noise_ik_aes` und schlug fehl -- die Gegenprobe selbst war falsch,
        # nicht das Gepruefte.

        # ----------------------------------------------------- 2b. Portal
        #
        # Der Browser-Quelltext gegen denselben Agenten. Testvektoren zeigen,
        # dass beide Seiten die Spezifikation treffen -- ob sie MITEINANDER
        # reden koennen, zeigt nur das hier.
        node = shutil.which('node')
        if not node:
            print('')
            print('PORTAL')
            print('')
            print('  %-56s %s' % ('Portal gegen den echten Agenten',
                                  'UEBERSPRUNGEN -- kein node'))
        else:
            r = subprocess.run(
                [node, os.path.join(HIER, 'pruefe_portal.cjs'), basis,
                 c_priv.hex(), a_pub.hex()],
                capture_output=True, text=True, timeout=300)
            print(r.stdout.rstrip())
            if r.returncode != 0 and r.stderr.strip():
                print('  ' + r.stderr.strip()[:400])
            # Das Ergebnis des Unterprogramms zaehlt als EINE Pruefung hier --
            # die Einzelheiten stehen oben in seiner eigenen Ausgabe.
            pruefe('Portal-JavaScript spricht mit dem Python-Agenten',
                   r.returncode == 0)

        # -------------------------------------------------- 3. Angriffe
        print('')
        print('3 -- ANGRIFFE')
        print('')

        fremd = klient(privat=os.path.join(basis_ordner, 'fremd.key'))
        try:
            fremd.frage('dateien', 'hole', {'pfad': 'gehaltsabrechnung.txt'})
            pruefe('fremder Client bekommt nichts', False, 'bekam eine Antwort')
        except ahpt_client.ClientFehler as e:
            pruefe('fremder Client bekommt nichts', 'Zeit abgelaufen' in str(e),
                   str(e)[:60])

        falsch = klient(agent_pub=f_pub)
        try:
            falsch.frage('dateien', 'liste', {'pfad': ''})
            pruefe('an den falschen Schluessel gerichtet: keine Antwort',
                   False, 'bekam eine Antwort')
        except ahpt_client.ClientFehler as e:
            pruefe('an den falschen Schluessel gerichtet: keine Antwort',
                   'Zeit abgelaufen' in str(e), str(e)[:60])

        # Wiederholung: dieselbe erste Nachricht ein zweites Mal einspielen.
        sitzung = krypto.HandshakeIK(True, ahpt_client.PROLOG, c_priv, rs=a_pub)
        m1 = sitzung.schreibe_nachricht1(json.dumps(
            {'dienst': 'dateien', 'aktion': 'liste', 'daten': {'pfad': ''}}
        ).encode('utf-8'))
        chiffre = base64.b64encode(m1).decode('ascii')

        def sende_roh(c):
            return ahpt_client._sende(
                basis + '/relay.php?action=frage',
                {'v': 1, 'krypto': 'noise_ik', 'nutzlast': {'chiffre': c}})

        code, d1 = sende_roh(chiffre)
        code, d2 = sende_roh(chiffre)          # dasselbe noch einmal
        time.sleep(2.5)
        da1 = os.path.isfile(os.path.join(webspace, 'ahpt',
                                          'antwort_%s.json' % d1['marke']))
        da2 = os.path.isfile(os.path.join(webspace, 'ahpt',
                                          'antwort_%s.json' % d2['marke']))
        pruefe('erste Einspielung wird beantwortet', da1)
        pruefe('WIEDERHOLUNG wird nicht beantwortet', not da2)

        # Ein veraendertes Byte im Chiffrat.
        #
        # MIT EINEM FRISCHEN Handshake, nicht mit dem von oben. Der erste
        # Entwurf veraenderte das letzte Byte der schon eingespielten
        # Nachricht -- deren fluechtiger Schluessel steht aber unveraendert
        # am Anfang, also griff der WIEDERHOLUNGSSCHUTZ, und entschluesselt
        # wurde nie. Die Pruefung bestand, ohne zu pruefen, was sie behauptet.
        s2 = krypto.HandshakeIK(True, ahpt_client.PROLOG, c_priv, rs=a_pub)
        kaputt = bytearray(s2.schreibe_nachricht1(json.dumps(
            {'dienst': 'dateien', 'aktion': 'liste', 'daten': {'pfad': ''}}
        ).encode('utf-8')))
        kaputt[-1] ^= 0x01
        code, d3 = sende_roh(base64.b64encode(bytes(kaputt)).decode('ascii'))
        time.sleep(2.0)
        pruefe('veraendertes Chiffrat wird nicht beantwortet',
               not os.path.isfile(os.path.join(webspace, 'ahpt',
                                               'antwort_%s.json' % d3['marke'])))

        # Unverschluesselt fragen, obwohl der Agent verschluesselt erwartet.
        code, d4 = ahpt_client._sende(
            basis + '/relay.php?action=frage',
            {'v': 1, 'krypto': 'keine',
             'nutzlast': {'dienst': 'dateien', 'aktion': 'liste', 'daten': {}}})
        # Der Vermittler MUSS die Frage annehmen -- er ist inhaltsblind und
        # weiss nicht, dass der Agent verschluesselt erwartet. Wird sie hier
        # schon abgewiesen, prueft der Rest nichts.
        if not d4.get('marke'):
            pruefe('Rueckfall auf Klartext: Vermittler nimmt die Frage an',
                   False, 'HTTP %s %s -- nicht gemessen'
                   % (code, d4.get('fehler', '')))
            d4 = {'marke': '0' * 32}
        time.sleep(2.0)
        pruefe('Rueckfall auf Klartext wird nicht beantwortet',
               not os.path.isfile(os.path.join(webspace, 'ahpt',
                                               'antwort_%s.json' % d4['marke'])),
               'eine Verschluesselung, die sich durch Weglassen abschalten '
               'laesst, ist keine')

    finally:
        if agent:
            agent.terminate()
            try:
                agent.wait(timeout=5)
            except Exception:
                agent.kill()
        if agent_log:
            agent_log.close()
            try:
                zeilen = open(protokoll, encoding='utf-8').read().splitlines()
                print('')
                print('AGENT (letzte 14 Zeilen)')
                for z in zeilen[-14:]:
                    print('  ' + z)
            except OSError:
                pass
        if srv:
            srv.shutdown()
        shutil.rmtree(basis_ordner, ignore_errors=True)

    fehler = sum(1 for ok in ERGEBNIS if not ok)
    print('')
    print('ERGEBNIS: %d Pruefungen, %s' % (
        len(ERGEBNIS),
        'alle bestanden.' if not fehler else '%d FEHLSCHLAG(E).' % fehler))
    print('')
    print('  Gegen eine Attrappe. relay.php ist damit NICHT geprueft.')
    return 1 if fehler else 0


if __name__ == '__main__':
    sys.exit(main())
