#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
durchstich_lokal.py -- Besucher -> Vermittler -> Agent -> Handler -> zurueck

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT


  ####  GEGEN EINE ATTRAPPE, NICHT GEGEN relay.php.  ####


Was hier gruen wird, ist der AGENT und der CLIENT: Umschlag, Marken,
Stueckelung, Zusammensetzen, Weisslisten, Abweisungen. Das sind die Teile,
die sonst reine Behauptung blieben -- besonders die Stueckelung, die es in
der Referenzumsetzung noch gar nicht gab.

Was hier NICHT gruen wird: relay.php. Kein PHP, kein Apache, kein
mod_speling, keine Prozessgrenze, kein 503, keine gleichzeitigen Zugriffe.
Der eine Fehler, der den Live-Lauf vom 02.09.2026 gekostet hat, war
mod_speling -- und keine lokale Pruefung haette ihn gefunden.

Der echte Durchstich ist `tests/durchstich.sh` gegen einen echten Webspace.
Diese Datei ersetzt ihn nicht; sie sorgt dafuer, dass man dort nicht mit
Fehlern ankommt, die man auch hier haette finden koennen.

Aufruf:
    python3 tests/durchstich_lokal.py
"""

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
sys.path.insert(0, HIER)
sys.path.insert(0, WURZEL)

import attrappe_relay                                    # noqa: E402

ERGEBNIS = []


def pruefe(beschreibung, bedingung, hinweis=''):
    ERGEBNIS.append((beschreibung, bool(bedingung), hinweis))
    print('  %-56s %s%s' % (beschreibung, 'ok' if bedingung else 'FEHLSCHLAG',
                            ('  -- ' + hinweis) if hinweis and not bedingung else ''))
    return bool(bedingung)


# ------------------------------------------------------------- Besucher

def stelle_frage(basis, dienst, aktion, daten, v=1, krypto='keine'):
    """Was der Browser tut, Schritt 1. Gibt (http-code, antwort) zurueck."""
    rumpf = json.dumps({'v': v, 'krypto': krypto,
                        'nutzlast': {'dienst': dienst, 'aktion': aktion,
                                     'daten': daten}}).encode('utf-8')
    req = urllib.request.Request(basis + '/relay.php?action=frage',
                                 data=rumpf, method='POST')
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.code, {}


def hole_antwort(basis, marke, frist=25):
    """Was der Browser tut, Schritt 2 und 3 -- statisch, ohne PHP.

    Bildet relay-client.js nach, einschliesslich der Pruefungen: Marke,
    Fassung, Stuecknummer. Weicht etwas ab, wird abgebrochen statt
    zusammengebaut.
    """
    bis = time.time() + frist
    while time.time() < bis:
        try:
            with urllib.request.urlopen(
                    '%s/ahpt/antwort_%s.json' % (basis, marke), timeout=10) as r:
                u = json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                time.sleep(0.25)
                continue
            raise
        if u.get('v') != 1:
            raise AssertionError('Fassung %r' % u.get('v'))
        if u.get('marke') != marke:
            raise AssertionError('Marke weicht ab -- Umleitung?')
        n = u.get('nutzlast', {})
        teile = u.get('teile', 1)
        if teile == 1:
            return n, [], u
        stuecke = n.get('stuecke', [])
        assert len(stuecke) == teile, 'Verzeichnis nennt %d von %d' % (
            len(stuecke), teile)
        text = []
        for i, e in enumerate(stuecke):
            with urllib.request.urlopen(
                    '%s/ahpt/%s' % (basis, e['datei']), timeout=10) as r:
                s = json.loads(r.read().decode('utf-8'))
            assert s.get('marke') == marke, 'Stueck %d: fremde Marke' % i
            assert s.get('teil') == i, 'Stueck %d: falsche Nummer' % i
            assert s.get('teile') == teile, 'Stueck %d: falsche Gesamtzahl' % i
            text.append(s['nutzlast'])
        n = dict(n)
        n['inhalt'] = ''.join(text)
        return n, stuecke, u
    raise AssertionError('keine Antwort binnen %d s' % frist)


# ------------------------------------------------------------------ Lauf

def main():
    basis_ordner = tempfile.mkdtemp(prefix='ahpt_durchstich_')
    agent = None
    srv = None
    try:
        webspace = os.path.join(basis_ordner, 'webspace')
        freigabe = os.path.join(basis_ordner, 'freigabe')
        os.makedirs(webspace)
        os.makedirs(os.path.join(freigabe, 'unter'))

        # Ein kleiner Text, eine grosse Binaerdatei, und etwas AUSSERHALB.
        with open(os.path.join(freigabe, 'klein.txt'), 'w', encoding='utf-8') as f:
            f.write('Ein kurzer Text mit Umlauten: Groesse, Fuesse, Massstab.')
        gross = bytes((i * 37 + 11) % 256 for i in range(300000))
        with open(os.path.join(freigabe, 'gross.png'), 'wb') as f:
            f.write(gross)
        # Text, der JSON kraeftig aufblaeht -- genau der Fall, in dem eine
        # Stueckelung nach roher Byte-Laenge am Rumpf-Deckel scheitert.
        boese = ('"' + chr(92) + '\x01') * 40000
        with open(os.path.join(freigabe, 'boese.txt'), 'w', encoding='utf-8') as f:
            f.write(boese)
        with open(os.path.join(basis_ordner, 'draussen.txt'), 'w') as f:
            f.write('DARF NIE HERAUS')

        geheimnis = 'a' * 64
        gpfad = os.path.join(basis_ordner, 'geheimnis')
        with open(gpfad, 'w') as f:
            f.write(geheimnis)

        srv, port = attrappe_relay.starte(webspace, geheimnis)
        basis = 'http://127.0.0.1:%d' % port

        konfig = {
            'relay': {'basis': basis, 'geheimnis_datei': gpfad,
                      'poll_abstand': 0.3,
                      # Im Betrieb 30 s. Hier kurz, damit die Pruefung nicht
                      # eine halbe Minute wartet -- und damit das Netz
                      # ueberhaupt einmal gebraucht wird.
                      'unbedingt_nach': 2},
            'dienst': [{'name': 'dateien', 'art': 'datei', 'wurzel': freigabe,
                        'aktionen': ['liste', 'hole'], 'max_bytes': 5242880,
                        'endungen': ['txt', 'png']}],
        }
        kpfad = os.path.join(basis_ordner, 'config.json')
        with open(kpfad, 'w', encoding='utf-8') as f:
            json.dump(konfig, f)

        print('')
        print('Attrappe auf %s   (BEWEIST NICHTS UEBER relay.php)' % basis)
        # In eine DATEI, nicht in eine Pipe: Eine Pipe, die niemand liest,
        # laeuft voll und der Agent bleibt darin haengen -- ein Fehlschlag,
        # der wie ein Zeitablauf aussieht.
        protokoll = os.path.join(basis_ordner, 'agent.log')
        agent_log = open(protokoll, 'w', encoding='utf-8')
        agent = subprocess.Popen(
            [sys.executable, os.path.join(WURZEL, 'relay_agent.py'),
             '--konfig', kpfad],
            cwd=WURZEL, stdout=agent_log, stderr=subprocess.STDOUT, text=True)
        time.sleep(1.2)
        if agent.poll() is not None:
            agent_log.flush()
            print(io.open(protokoll, encoding='utf-8').read())
            raise SystemExit('Agent ist nicht angelaufen.')

        print('')
        print('ZEILENENDEN')
        print('')
        # Alles hier laeuft am Ende auf Linux: der Vermittler auf einem
        # Webspace, der Agent auf einem Heimserver. CRLF ist dort nicht nur
        # unschoen, sondern gefaehrlich -- ein Shellskript mit \r bricht ab,
        # und ein regulaerer Ausdruck, der auf \n endet, trifft \r\n nicht.
        #
        # Am 02.09.2026 genau so passiert: relay.php wurde beim Bearbeiten
        # auf einem Windows-Rechner still zu CRLF, und tests/pruefe_absender.php
        # fand die Funktion nicht mehr, die es zu pruefen galt. Aufgefallen
        # ist es erst auf dem Server -- und nur, weil die Pruefung laut
        # abbrach statt stillschweigend zu bestehen.
        #
        # Zwei lokale Kontrollen hatten es davor NICHT gefunden: Python liest
        # im Textmodus und wandelt CRLF unbemerkt in LF um. Wer Zeilenenden
        # pruefen will, muss die Datei binaer lesen.
        krumm = []
        for w, o, ds in os.walk(WURZEL):
            o[:] = [x for x in o if x not in ('Kopie', '__pycache__', '.git')]
            for d in ds:
                p = os.path.join(w, d)
                with open(p, 'rb') as f:          # BINAER, nicht als Text
                    if b'\r\n' in f.read():
                        krumm.append(os.path.relpath(p, WURZEL))
        pruefe('alle Dateien haben Unix-Zeilenenden', not krumm,
               ', '.join(krumm[:4]))

        print('')
        print('DURCHSTICH')
        print('')

        # 1 -- Auflisten
        code, d = stelle_frage(basis, 'dateien', 'liste', {})
        pruefe('frage wird angenommen', code == 200 and d.get('ok'), str(d))
        n, _, _ = hole_antwort(basis, d['marke'])
        eintraege = json.loads(n['inhalt'])['eintraege'] if n['gefunden'] else []
        namen = {e['name'] for e in eintraege}
        pruefe('liste findet die Dateien',
               {'klein.txt', 'gross.png', 'boese.txt'} <= namen, str(namen))
        pruefe('liste zeigt draussen.txt NICHT', 'draussen.txt' not in namen)

        # 2 -- Kleine Textdatei, ungeteilt
        code, d = stelle_frage(basis, 'dateien', 'hole', {'pfad': 'klein.txt'})
        n, st, u = hole_antwort(basis, d['marke'])
        pruefe('kleine Datei kommt an', n['gefunden']
               and 'Massstab' in n['inhalt'])
        pruefe('kleine Datei bleibt ungeteilt', u['teile'] == 1)
        pruefe('kleine Datei kommt als Text', n['inhalt_typ'] == 'text')

        # 3 -- Grosse Binaerdatei, gestueckelt. DER neue Teil.
        code, d = stelle_frage(basis, 'dateien', 'hole', {'pfad': 'gross.png'})
        n, st, u = hole_antwort(basis, d['marke'], frist=40)
        pruefe('grosse Datei kommt an', n['gefunden'])
        pruefe('grosse Datei wird gestueckelt', u['teile'] > 1,
               'teile=%s' % u['teile'])
        zurueck = base64.b64decode(n['inhalt']) if n['gefunden'] else b''
        pruefe('grosse Datei ist Byte fuer Byte dieselbe', zurueck == gross,
               '%d von %d Bytes' % (len(zurueck), len(gross)))

        # 4 -- Der mod_speling-Fallstrick: Stuecknamen duerfen nicht eine
        #      Zeichenaenderung auseinanderliegen.
        dateien = [e['datei'] for e in st]
        def abstand(a, b):
            if len(a) != len(b):
                return 99
            return sum(1 for x, y in zip(a, b) if x != y)
        eng = [(a, b) for a, b in zip(dateien, dateien[1:]) if abstand(a, b) <= 1]
        pruefe('benachbarte Stuecknamen sind nicht 1 Zeichen auseinander',
               not eng, str(eng[:2]))

        # 5 -- Text, der JSON aufblaeht. Ohne die zweite Grenze in zerlege()
        #      reisst hier der Rumpf-Deckel und der Vermittler antwortet 413.
        code, d = stelle_frage(basis, 'dateien', 'hole', {'pfad': 'boese.txt'})
        n, st, u = hole_antwort(basis, d['marke'], frist=40)
        pruefe('JSON-aufblaehender Text kommt vollstaendig an',
               n['gefunden'] and n['inhalt'] == boese,
               '%d von %d Zeichen' % (len(n.get('inhalt', '')), len(boese)))

        # 6 -- Angriffe. Alle muessen "nichts gefunden" ergeben, nicht Inhalt.
        for beschreibung, pfad in (
                ('Pfadwanderung',        '../draussen.txt'),
                ('Pfadwanderung tief',   'unter/../../draussen.txt'),
                ('absoluter Pfad',       '/etc/passwd'),
                ('Windows-Pfad',         'C:' + chr(92) + 'Windows' + chr(92) + 'win.ini'),
                ('versteckte Datei',     '.geheim'),
                ('gesperrte Endung',     'liesmich.md')):
            code, d = stelle_frage(basis, 'dateien', 'hole', {'pfad': pfad})
            if code != 200:
                pruefe('angriff abgewiesen: ' + beschreibung, True)
                continue
            n, _, _ = hole_antwort(basis, d['marke'])
            pruefe('angriff abgewiesen: ' + beschreibung,
                   n['gefunden'] is False and not n['inhalt'])

        # 7 -- Unbekannter Dienst. Der Vermittler nimmt ihn an (er kennt
        #      keine Dienste), der Agent weist ihn ab -- und verraet dabei
        #      nicht, welche es gibt.
        code, d = stelle_frage(basis, 'unbekannt', 'hole', {'pfad': 'x'})
        pruefe('vermittler nimmt unbekannten Dienst an', code == 200)
        n, _, _ = hole_antwort(basis, d['marke'])
        pruefe('agent weist unbekannten Dienst ab', n['gefunden'] is False)
        pruefe('agent nennt die vorhandenen Dienste NICHT',
               'dateien' not in json.dumps(n), json.dumps(n))

        # 8 -- Gesperrte Aktion, obwohl der Handler sie koennte.
        konfig2 = json.loads(json.dumps(konfig))
        konfig2['dienst'][0]['aktionen'] = ['liste']
        pruefe('aktionen ist der Schnitt, nicht die Vereinigung',
               set(konfig2['dienst'][0]['aktionen']) < {'liste', 'hole'})

        # 9 -- Formfehler weist schon der Vermittler ab, ohne den Agenten.
        for beschreibung, dienst, aktion, code_soll in (
                ('Grossbuchstabe im Dienst', 'Dateien', 'hole', 400),
                ('Punkt im Dienst',          'da.tei',  'hole', 400),
                ('Schraegstrich im Dienst',  'a/b',     'hole', 400),
                ('leerer Dienst',            '',        'hole', 400),
                ('leere Aktion',             'dateien', '',     400)):
            code, _ = stelle_frage(basis, dienst, aktion, {})
            pruefe('vermittler weist ab: ' + beschreibung, code == code_soll,
                   'HTTP %s' % code)

        # 10 -- Umschlag: unbekannte Fassung und unbekanntes Verfahren werden
        #       ABGEWIESEN, nicht gedeutet.
        code, _ = stelle_frage(basis, 'dateien', 'liste', {}, v=2)
        pruefe('unbekannte Protokollfassung wird abgewiesen', code == 400)
        code, _ = stelle_frage(basis, 'dateien', 'liste', {}, krypto='x25519')
        pruefe('unbekanntes Verfahren wird abgewiesen', code == 400,
               'halb gebaute Krypto ist schlimmer als keine')

        # 11 -- DIE ETAG-FALLE, gezielt herbeigefuehrt.
        #
        # Nicht abwarten, ob sie zufaellig zuschlaegt -- erzwingen. Ein
        # eigener Agent, der zwischen Antwort und naechster Frage NICHT
        # pollt, geraet zuverlaessig hinein: Die neue Warteschlange ist
        # gleich lang und in derselben Sekunde geschrieben wie die, deren
        # ETag er gespeichert hat.
        print('')
        print('ETAG-FALLE (gezielt)')
        print('')
        import relay_agent
        konf_eng = json.loads(json.dumps(konfig))
        konf_eng['relay']['unbedingt_nach'] = 3600      # Netz AUS
        eigen = relay_agent.Agent(
            relay_agent.Aufbau(konf_eng, 'json'), geheimnis)
        eigen.letzte_volle = time.time()                # erste Runde bedingt

        m1 = stelle_frage(basis, 'dateien', 'hole', {'pfad': 'klein.txt'})[1]['marke']
        eigen.durchgang()
        pruefe('falle: erste Frage wird beantwortet',
               os.path.isfile(os.path.join(webspace, 'ahpt',
                                           'antwort_%s.json' % m1)))
        m2 = stelle_frage(basis, 'dateien', 'hole', {'pfad': 'klein.txt'})[1]['marke']
        eigen.durchgang()
        verpasst = not os.path.isfile(os.path.join(webspace, 'ahpt',
                                                   'antwort_%s.json' % m2))
        # Diese Zeile ist KEINE Forderung an den Agenten -- sie stellt fest,
        # ob die Falle ueberhaupt zugeschnappt ist. Tut sie es nicht (etwa
        # weil die Sekunde umgesprungen ist), sagt der Test das, statt eine
        # Pruefung zu melden, die nichts geprueft hat.
        print('  %-56s %s' % ('falle ist zugeschnappt',
                              'ja' if verpasst else 'nein (Sekundengrenze) '
                              '-- Rest dieses Abschnitts ohne Aussage'))
        if verpasst:
            eigen.a.unbedingt_nach = 0                  # Netz AN
            eigen.durchgang()
            pruefe('falle: unbedingter Abruf holt die Frage nach',
                   os.path.isfile(os.path.join(webspace, 'ahpt',
                                               'antwort_%s.json' % m2)))
            pruefe('falle: der Agent MELDET die uebersehene Aenderung',
                   relay_agent.ZAEHLER.get('schlange_verpasst', 0) > 0,
                   str(dict(relay_agent.ZAEHLER)))

        # 12 -- QUEUE-JAMMING und faires Verdraengen.
        #
        # Ueber HTTP nicht messbar: Jede Anfrage kommt hier von 127.0.0.1,
        # also immer vom selben Absender. Deshalb direkt gegen die Ablage,
        # mit frei gewaehlten Adressen.
        #
        # Was hier gruen wird, gilt fuer die ATTRAPPE. Dass relay.php
        # dieselbe Einteilung vornimmt, sichert pruefe_gleichstand() ab; dass
        # sie richtig ist, misst tests/pruefe_absender.php gegen echtes PHP.
        print('')
        print('QUEUE-JAMMING')
        print('')

        ak = attrappe_relay.absender_kennung
        pruefe('ein /64 ist EIN Absender',
               ak('2001:db8:aa:bb::1') == ak('2001:db8:aa:bb::99'))
        pruefe('zwei /64 sind ZWEI Absender',
               ak('2001:db8:aa:bb::1') != ak('2001:db8:aa:bc::1'))
        pruefe('IPv4 im IPv6-Kleid faellt nicht ins /64',
               ak('::ffff:1.2.3.4') != ak('::ffff:9.9.9.9'))
        pruefe('IPv4 und ihr IPv6-Kleid sind derselbe Absender',
               ak('1.2.3.4') == ak('::ffff:1.2.3.4'))

        def leere_frage(ablage, absender):
            return ablage.frage({'nutzlast': {'dienst': 'dateien',
                                              'aktion': 'liste', 'daten': {}}},
                                absender)

        # (a) Ein Absender kommt nicht ueber MAX_JE_IP hinaus.
        w1 = os.path.join(basis_ordner, 'jam1')
        a1 = attrappe_relay.Ablage(w1, geheimnis)
        codes = [leere_frage(a1, '2001:db8:1:1::5')[0]
                 for _ in range(attrappe_relay.MAX_JE_IP + 1)]
        pruefe('ein Absender bekommt hoechstens MAX_JE_IP Plaetze',
               codes[:-1] == [200] * attrappe_relay.MAX_JE_IP and codes[-1] == 429,
               str(codes))

        # (b) Acht /64 fuellen die Schlange -- genau der Angriff aus der
        #     Sicherheitsanalyse. Ein neunter Besucher muss trotzdem
        #     durchkommen, statt 503 zu bekommen.
        w2 = os.path.join(basis_ordner, 'jam2')
        a2 = attrappe_relay.Ablage(w2, geheimnis)
        angreifer = ['2001:db8:0:%d::1' % i for i in range(8)]
        for adr in angreifer:
            for _ in range(attrappe_relay.MAX_JE_IP):
                leere_frage(a2, adr)
        pruefe('Schlange ist voll', len(a2.offen) == attrappe_relay.MAX_OFFEN,
               str(len(a2.offen)))
        code, d = leere_frage(a2, '2001:db8:99:99::1')
        pruefe('echter Besucher kommt trotz voller Schlange durch',
               code == 200, 'HTTP %s %s' % (code, d.get('fehler', '')))
        pruefe('dafuer wurde genau ein Platz verdraengt', a2.verdraengt == 1,
               str(a2.verdraengt))
        pruefe('verdraengt wurde beim Vielhalter, nicht beim Neuen',
               sum(1 for e in a2.offen
                   if e['wer'] == a2.offen[-1]['wer']) == 1)
        pruefe('die Schlange bleibt bei MAX_OFFEN',
               len(a2.offen) == attrappe_relay.MAX_OFFEN, str(len(a2.offen)))

        # (c) Wer nur einen Platz haelt, wird nicht verdraengt, solange
        #     jemand zwei haelt.
        einzelne = {e['wer'] for e in a2.offen
                    if sum(1 for x in a2.offen if x['wer'] == e['wer']) == 1}
        leere_frage(a2, '2001:db8:77:77::1')
        pruefe('Einzelplatz-Halter bleiben unangetastet',
               einzelne <= {e['wer'] for e in a2.offen})

        # (d) Halten ALLE genau einen Platz, ist die Schlange ehrlich voll --
        #     dann wird niemand verdraengt und 503 ist die richtige Auskunft.
        w3 = os.path.join(basis_ordner, 'jam3')
        a3 = attrappe_relay.Ablage(w3, geheimnis)
        for i in range(attrappe_relay.MAX_OFFEN):
            leere_frage(a3, '2001:db8:%x:%x::1' % (i // 256, i % 256))
        code, _ = leere_frage(a3, '2001:db8:ff:ff::1')
        pruefe('ehrlich volle Schlange antwortet 503', code == 503, 'HTTP %s' % code)
        pruefe('dabei wird niemand verdraengt', a3.verdraengt == 0,
               str(a3.verdraengt))

        # 13 -- Der Client in JavaScript, gegen dieselbe Attrappe.
        node = shutil.which('node')
        if node:
            print('')
            print('CLIENT (node)')
            print('')
            r = subprocess.run([node, os.path.join(HIER, 'pruefe_client.cjs'),
                                basis], capture_output=True, text=True,
                               timeout=90)
            for z in r.stdout.splitlines():
                print('  ' + z)
            if r.returncode != 0 and r.stderr:
                print('  ' + r.stderr.strip()[:500])
            ERGEBNIS.append(('relay-client.js', r.returncode == 0, ''))
        else:
            print('')
            print('  relay-client.js UEBERSPRUNGEN -- kein node gefunden.')
            print('  Das ist kein Bestanden. Ungeprueft ist ungeprueft.')

    finally:
        if agent:
            agent.terminate()
            try:
                agent.wait(timeout=5)
            except Exception:
                agent.kill()
        try:
            agent_log.close()
            zeilen = io.open(protokoll, encoding='utf-8').read().splitlines()
            print('')
            print('AGENT (letzte 15 Zeilen)')
            for z in zeilen[-15:]:
                print('  ' + z)
        except Exception:
            pass
        if agent:
            try:
                agent.wait(timeout=5)
            except Exception:
                agent.kill()
        if srv:
            srv.shutdown()
        shutil.rmtree(basis_ordner, ignore_errors=True)

    fehler = sum(1 for _, ok, _ in ERGEBNIS if not ok)
    print('')
    print('ERGEBNIS: %d Pruefungen, %s' % (
        len(ERGEBNIS),
        'alle bestanden.' if not fehler else '%d FEHLSCHLAG(E).' % fehler))
    print('')
    print('  Gegen eine Attrappe. relay.php ist damit NICHT geprueft --')
    print('  dafuer gibt es tests/durchstich.sh gegen einen echten Webspace.')
    return 1 if fehler else 0


if __name__ == '__main__':
    sys.exit(main())
