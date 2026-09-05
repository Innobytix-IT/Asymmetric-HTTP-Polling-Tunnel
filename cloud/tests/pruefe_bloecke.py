#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pruefe_bloecke.py -- Dateien jeder Groesse, hin und zurueck

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
`lege` bringt eine Datei in EINER Frage hinauf. Der Vermittler laesst je
Frage 160 Stuecke zu, also nach zweifacher Base64-Aufblaehung rund 4,2 MiB
Nutzdatei. Am 03.09.2026 ist genau das aufgefallen: eine 22 MiB grosse PNG
wurde abgewiesen -- mit einer Meldung, die von Videos sprach und in
Stuecken rechnete.

Die Schranke des Vermittlers ist richtig und bleibt. Fragestuecke darf
JEDER ablegen, der die Adresse kennt; sie begrenzt, wieviel Platz ein
Fremder auf dem Webspace belegen kann. Falsch war nur, eine Datei mit
einer Frage gleichzusetzen.

`lege_block` und das bereichsweise `hole` loesen das. Diese Datei prueft
sie -- gegen den ECHTEN Handler, ohne Tunnel, ohne Verschluesselung. Was
hier gruen wird, ist die Logik; ueber den Weg sagt es nichts. Dafuer gibt
es durchstich_privat.py.

GEPRUEFT WIRD VOR ALLEM, WAS NICHT PASSIEREN DARF
-------------------------------------------------
Dass eine grosse Datei ankommt, ist die leichtere Haelfte. Die schwerere:
eine abgebrochene Uebertragung darf nicht als vollstaendige Datei
erscheinen, und die acht Schranken von `lege` duerfen sich nicht durch
Stueckeln umgehen lassen.

Aufruf:
    python3 tests/pruefe_bloecke.py
"""

import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))

from handler import KonfigFehler                # noqa: E402
from handler.datei import DateiHandler          # noqa: E402

EICAR = (r'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE'
         r'!$H+H*').encode('ascii')
ATTRAPPE = os.path.join(HIER, 'anhang_scan_attrappe.py')

GRUEN, ROT, GRAU, AUS = '\033[32m', '\033[31m', '\033[90m', '\033[0m'
if os.name == 'nt' or not sys.stdout.isatty():
    GRUEN = ROT = GRAU = AUS = ''

_zahl = [0, 0]


def pruef(was, bedingung, hinweis=''):
    _zahl[0] += 1
    if bedingung:
        print('  %-56s %sok%s' % (was, GRUEN, AUS))
    else:
        _zahl[1] += 1
        print('  %-56s %sFEHLGESCHLAGEN%s' % (was, ROT, AUS))
        if hinweis:
            print('      %s%s%s' % (GRAU, hinweis, AUS))


def abschnitt(t):
    print('\n%s\n' % t.upper())


def b64(b):
    return base64.b64encode(b).decode('ascii')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def mach_handler(wurzel, **mehr):
    konfig = {'name': 'dateien', 'art': 'datei', 'wurzel': wurzel,
              'aktionen': ['liste', 'hole', 'lege', 'lege_block',
                           'neuer_ordner'],
              'endungen': []}
    konfig.update(mehr)
    return DateiHandler(konfig)


def lege_ganz(h, ziel, roh, blockgroesse, marke=None, summe=None):
    """Eine Datei in Bloecken ablegen. Gibt die letzte Antwort zurueck."""
    marke = marke or os.urandom(16).hex()
    bloecke = max(1, (len(roh) + blockgroesse - 1) // blockgroesse)
    summe = summe if summe is not None else sha(roh)
    antw = None
    for i in range(bloecke):
        teil = roh[i * blockgroesse:(i + 1) * blockgroesse]
        d = {'uebertragung': marke, 'block': i, 'bloecke': bloecke,
             'inhalt_typ': 'base64', 'inhalt': b64(teil)}
        if i == 0:
            d['pfad'] = ziel
        if i == bloecke - 1:
            d['sha256'] = summe
        antw = h.bearbeite('lege_block', d)
        if not antw.get('gefunden'):
            return antw
    return antw


def hole_ganz(h, pfad, blockgroesse):
    """Eine Datei bereichsweise holen. Gibt (bytes, letzte_angaben)."""
    aus = b''
    gesamt = None
    stand = None
    summe = None
    while gesamt is None or len(aus) < gesamt:
        rest = None if gesamt is None else gesamt - len(aus)
        laenge = blockgroesse if rest is None else min(blockgroesse, rest)
        d = {'pfad': pfad, 'von': len(aus), 'laenge': laenge}
        if gesamt is None or rest <= laenge:
            d['pruefsumme'] = True
        antw = h.bearbeite('hole', d)
        if not antw.get('gefunden'):
            return None, antw
        a = json.loads(antw['inhalt'])
        if gesamt is None:
            gesamt, stand = int(a['gesamt']), a.get('stand')
        if a.get('sha256'):
            summe = a['sha256']
        aus += base64.b64decode(a['inhalt'])
    return aus, {'gesamt': gesamt, 'stand': stand, 'sha256': summe}


def teildateien(wurzel):
    o = os.path.join(wurzel, DateiHandler.TEIL_ORDNER)
    try:
        return sorted(n for n in os.listdir(o) if n.endswith('.teil'))
    except OSError:
        return []


def main():
    arbeit = tempfile.mkdtemp(prefix='ahpt-bloecke-')
    wurzel = os.path.join(arbeit, 'freigabe')
    os.makedirs(wurzel)
    try:
        h = mach_handler(wurzel, max_bytes=0)

        # ------------------------------------------------------------- 1
        abschnitt('1 -- hinauf, in Bloecken')

        klein = b'Nur eine Notiz.\n'
        a = lege_ganz(h, 'notiz.txt', klein, 3 << 20)
        pruef('kleine Datei, ein Block',
              a.get('gefunden') and os.path.isfile(
                  os.path.join(wurzel, 'notiz.txt')),
              a.get('grund', ''))
        pruef('sie ist Byte fuer Byte dieselbe',
              open(os.path.join(wurzel, 'notiz.txt'), 'rb').read() == klein)

        # 22 MiB -- die Groesse, die den Anlass gab. Aus os.urandom, damit
        # kein Muster einen Fehler in der Reihenfolge verdecken kann:
        # Bei gleichfoermigen Daten faellt ein vertauschter Block nicht auf.
        gross = os.urandom(22 * 1024 * 1024)
        blk = 3 * 1024 * 1024
        a = lege_ganz(h, 'grosse.bin', gross, blk)
        pfad = os.path.join(wurzel, 'grosse.bin')
        pruef('22 MiB ueber 8 Bloecke', a.get('gefunden'), a.get('grund', ''))
        pruef('22 MiB Byte fuer Byte dieselben',
              os.path.isfile(pfad) and open(pfad, 'rb').read() == gross)
        pruef('die Antwort nennt die Zahl der Bloecke',
              json.loads(a.get('inhalt', '{}')).get('bloecke') == 8,
              'gemeldet: %s' % a.get('inhalt', ''))
        pruef('keine Teildatei zurueckgeblieben', teildateien(wurzel) == [],
              'liegt noch: %s' % teildateien(wurzel))

        leer = b''
        a = lege_ganz(h, 'leer.txt', leer, blk)
        pruef('leere Datei geht auch',
              a.get('gefunden')
              and os.path.getsize(os.path.join(wurzel, 'leer.txt')) == 0,
              a.get('grund', ''))

        # ------------------------------------------------------------- 2
        abschnitt('2 -- was nicht passieren darf')

        # Falsche Pruefsumme. Der Kern der Sache: Jeder Block ist fuer sich
        # gueltig verschluesselt. Nur die Summe des Ganzen faengt eine
        # abgebrochene oder vertauschte Uebertragung.
        roh = os.urandom(7 << 20)
        a = lege_ganz(h, 'falsch.bin', roh, blk, summe=sha(b'etwas anderes'))
        pruef('falsche Pruefsumme wird abgewiesen', not a.get('gefunden'),
              a.get('grund', ''))
        pruef('  und es liegt NICHTS da',
              not os.path.exists(os.path.join(wurzel, 'falsch.bin')))
        pruef('  und keine Teildatei bleibt uebrig',
              teildateien(wurzel) == [],
              'liegt noch: %s' % teildateien(wurzel))

        # Fehlende Pruefsumme beim letzten Block.
        marke = os.urandom(16).hex()
        h.bearbeite('lege_block', {
            'uebertragung': marke, 'pfad': 'ohne.bin', 'block': 0,
            'bloecke': 2, 'inhalt_typ': 'base64', 'inhalt': b64(b'AB')})
        a = h.bearbeite('lege_block', {
            'uebertragung': marke, 'block': 1, 'bloecke': 2,
            'inhalt_typ': 'base64', 'inhalt': b64(b'CD')})
        pruef('letzter Block ohne Pruefsumme abgewiesen',
              not a.get('gefunden'), a.get('grund', ''))
        pruef('  und es liegt NICHTS da',
              not os.path.exists(os.path.join(wurzel, 'ohne.bin')))

        # Reihenfolge.
        marke = os.urandom(16).hex()
        h.bearbeite('lege_block', {
            'uebertragung': marke, 'pfad': 'reihe.bin', 'block': 0,
            'bloecke': 3, 'inhalt_typ': 'base64', 'inhalt': b64(b'A')})
        a = h.bearbeite('lege_block', {
            'uebertragung': marke, 'block': 2, 'bloecke': 3,
            'inhalt_typ': 'base64', 'inhalt': b64(b'C')})
        pruef('uebersprungener Block abgewiesen', not a.get('gefunden'),
              a.get('grund', ''))
        a = h.bearbeite('lege_block', {
            'uebertragung': marke, 'block': 0, 'bloecke': 3,
            'inhalt_typ': 'base64', 'inhalt': b64(b'A')})
        pruef('doppelter Block abgewiesen', not a.get('gefunden'),
              a.get('grund', ''))
        h._teil_verwerfen(marke)

        # Unbekannte Marke.
        a = h.bearbeite('lege_block', {
            'uebertragung': os.urandom(16).hex(), 'block': 1, 'bloecke': 2,
            'inhalt_typ': 'base64', 'inhalt': b64(b'X')})
        pruef('unbekannte Uebertragung abgewiesen', not a.get('gefunden'),
              a.get('grund', ''))

        # Marke muss hex sein -- sonst ist sie ein Pfadbestandteil.
        for boese in ('../../weg', 'a' * 8, 'GROSS' * 4, '', 'a/b'):
            a = h.bearbeite('lege_block', {
                'uebertragung': boese, 'pfad': 'x.bin', 'block': 0,
                'bloecke': 1, 'inhalt_typ': 'base64', 'inhalt': b64(b'X'),
                'sha256': sha(b'X')})
            if a.get('gefunden'):
                break
        pruef('krumme Uebertragungsmarke abgewiesen', not a.get('gefunden'),
              'durchgelassen: %r' % boese)

        # Pfadwanderung beim ersten Block.
        a = lege_ganz(h, '../entwischt.bin', b'X' * 100, blk)
        pruef('Pfadwanderung beim ersten Block abgewiesen',
              not a.get('gefunden'), a.get('grund', ''))
        pruef('  nichts ausserhalb der Wurzel entstanden',
              not os.path.exists(os.path.join(arbeit, 'entwischt.bin')))

        # Pfad beim ZWEITEN Block wird ignoriert. Sonst koennte man die
        # Schranken beim ersten Block passieren und danach umlenken.
        marke = os.urandom(16).hex()
        h.bearbeite('lege_block', {
            'uebertragung': marke, 'pfad': 'brav.bin', 'block': 0,
            'bloecke': 2, 'inhalt_typ': 'base64', 'inhalt': b64(b'AA')})
        a = h.bearbeite('lege_block', {
            'uebertragung': marke, 'pfad': '../umgelenkt.bin', 'block': 1,
            'bloecke': 2, 'inhalt_typ': 'base64', 'inhalt': b64(b'BB'),
            'sha256': sha(b'AABB')})
        pruef('Umlenken beim zweiten Block wirkungslos',
              a.get('gefunden')
              and os.path.isfile(os.path.join(wurzel, 'brav.bin'))
              and not os.path.exists(os.path.join(arbeit, 'umgelenkt.bin')),
              a.get('grund', ''))

        # Groesse laesst sich nicht durch Stueckeln umgehen.
        eng = mach_handler(wurzel, max_bytes=1024)
        a = lege_ganz(eng, 'zuviel.bin', b'X' * 4096, 512)
        pruef('max_bytes gilt fuer das Ganze, nicht je Block',
              not a.get('gefunden'), a.get('grund', ''))
        pruef('  und es liegt NICHTS da',
              not os.path.exists(os.path.join(wurzel, 'zuviel.bin')))

        # Endungsliste greift beim ersten Block.
        streng = mach_handler(wurzel, endungen=['txt'])
        a = lege_ganz(streng, 'verboten.exe', b'MZ', 512)
        pruef('gesperrte Endung abgewiesen', not a.get('gefunden'),
              a.get('grund', ''))

        # Nicht ueberschreiben -- erst beim letzten Block, sonst waere der
        # Name belegt, waehrend die Datei noch unvollstaendig ist.
        a = lege_ganz(h, 'notiz.txt', b'etwas Neues\n', blk)
        d = json.loads(a.get('inhalt', '{}'))
        pruef('zweite Datei ueberschreibt nicht',
              a.get('gefunden') and d.get('abgelegt') == 'notiz (2).txt',
              'abgelegt als: %s' % d.get('abgelegt'))
        pruef('  das Original ist unveraendert',
              open(os.path.join(wurzel, 'notiz.txt'), 'rb').read() == klein)

        # ------------------------------------------------------------- 3
        abschnitt('3 -- herunter, in Bloecken')

        aus, ang = hole_ganz(h, 'grosse.bin', 4 << 20)
        pruef('22 MiB bereichsweise geholt', aus is not None,
              str(ang.get('grund', '')))
        pruef('22 MiB Byte fuer Byte dieselben', aus == gross)
        pruef('die Gesamtgroesse wird gemeldet',
              ang.get('gesamt') == len(gross),
              'gemeldet: %s' % ang.get('gesamt'))
        pruef('die Pruefsumme wird gemeldet und stimmt',
              ang.get('sha256') == sha(gross))
        pruef('der Zeitstempel wird gemeldet', ang.get('stand') is not None)

        aus, _ = hole_ganz(h, 'notiz.txt', 4 << 20)
        pruef('kleine Datei in einem Zug', aus == klein)

        aus, _ = hole_ganz(h, 'leer.txt', 4 << 20)
        pruef('leere Datei geht auch', aus == b'')

        # Ein zu grosser Ausschnitt muss abgewiesen werden -- sonst baute
        # der Agent eine Antwort, die der Vermittler nicht mehr annimmt.
        a = h.bearbeite('hole', {'pfad': 'grosse.bin', 'von': 0,
                                 'laenge': DateiHandler.LESE_BLOCK + 1})
        pruef('zu grosser Ausschnitt abgewiesen', not a.get('gefunden'),
              a.get('grund', ''))

        a = h.bearbeite('hole', {'pfad': 'grosse.bin',
                                 'von': len(gross) + 1, 'laenge': 10})
        pruef('Anfang hinter dem Dateiende abgewiesen',
              not a.get('gefunden'), a.get('grund', ''))

        for schlecht in ({'von': -1, 'laenge': 10}, {'von': 0, 'laenge': 0},
                         {'von': 'a', 'laenge': 10},
                         {'von': 0, 'laenge': True}):
            d = {'pfad': 'grosse.bin'}
            d.update(schlecht)
            a = h.bearbeite('hole', d)
            if a.get('gefunden'):
                break
        pruef('krumme Bereichsangaben abgewiesen', not a.get('gefunden'),
              'durchgelassen: %r' % schlecht)

        # Am Dateiende genau aufhoeren.
        a = h.bearbeite('hole', {'pfad': 'notiz.txt', 'von': len(klein) - 3,
                                 'laenge': 999})
        pruef('Ausschnitt ueber das Ende wird gekappt, nicht abgewiesen',
              a.get('gefunden')
              and base64.b64decode(json.loads(a['inhalt'])['inhalt'])
              == klein[-3:], a.get('grund', ''))

        # Grosse Datei OHNE Bereich: max_bytes muss weiter greifen.
        eng = mach_handler(wurzel, max_bytes=1024)
        a = eng.bearbeite('hole', {'pfad': 'grosse.bin'})
        pruef('ganze grosse Datei ohne Bereich abgewiesen',
              not a.get('gefunden'), a.get('grund', ''))
        aus, _ = hole_ganz(eng, 'grosse.bin', 4 << 20)
        pruef('  bereichsweise geht sie trotzdem', aus == gross)

        # ------------------------------------------------------------- 4
        abschnitt('4 -- aufraeumen')

        a = h.bearbeite('liste', {'pfad': ''})
        namen = a.get('inhalt', '')
        pruef('der Teil-Ordner steht in keiner Auflistung',
              DateiHandler.TEIL_ORDNER not in namen,
              'gefunden in: %s' % namen[:120])

        # Liegengebliebene Teildatei, deren Marke der Agent nicht mehr
        # kennt -- so sieht es nach einem Neustart aus. Ohne Aufraeumen
        # bliebe der Platz fuer immer belegt.
        o = os.path.join(wurzel, DateiHandler.TEIL_ORDNER)
        os.makedirs(o, exist_ok=True)
        alt = os.path.join(o, 'aa' * 8 + '.teil')
        with open(alt, 'wb') as f:
            f.write(b'X' * 1000)
        vergangen = time.time() - DateiHandler.TEIL_TTL - 60
        os.utime(alt, (vergangen, vergangen))
        h._teile_aufraeumen()
        pruef('vergessene alte Teildatei wird weggeraeumt',
              not os.path.exists(alt))

        frisch = os.path.join(o, 'bb' * 8 + '.teil')
        with open(frisch, 'wb') as f:
            f.write(b'X')
        h._teile_aufraeumen()
        pruef('frische Teildatei bleibt', os.path.exists(frisch))
        os.unlink(frisch)

        # Gegenprobe: Prueft der Prueber ueberhaupt? Eine Suche, die nie
        # etwas findet, macht jede Abwesenheit gruen.
        a = lege_ganz(h, 'gegenprobe.txt', b'da', blk)
        pruef('GEGENPROBE: was erlaubt ist, geht durch', a.get('gefunden'),
              a.get('grund', ''))

        # --------------------------------------------------------- 5
        #
        # Am 03.09.2026 im Sicherheitsaudit gefunden: max_bytes deckelt
        # eine FERTIGE Datei, aber nichts deckelte, wieviele gleichzeitige,
        # nie abgeschlossene Uebertragungen sich ansammeln durften -- vor
        # allem seit max_bytes = 0 (unbegrenzt) zum empfohlenen
        # Vorgabewert des Einrichtungs-Assistenten wurde.
        abschnitt('5 -- deckel gegen viele gleichzeitige uebertragungen')

        h2 = mach_handler(wurzel, max_bytes=0)
        # Klein gesetzt, damit der Test nicht wirklich Gigabytes anlegen
        # muss -- die Konstanten selbst bleiben in der echten Vorgabe
        # unangetastet, das hier ist eine Instanz-Eigenschaft.
        h2.TEIL_MAX_GLEICHZEITIG = 3
        h2.TEIL_MAX_GESAMT = 10_000

        marken = []
        for i in range(3):
            m = os.urandom(16).hex()
            a = h2.bearbeite('lege_block', {
                'uebertragung': m, 'block': 0, 'bloecke': 2,
                'pfad': 'vieleuebertragungen_%d.bin' % i,
                'inhalt_typ': 'base64', 'inhalt': b64(b'x' * 100)})
            pruef('Uebertragung %d von 3 wird angenommen' % (i + 1),
                  a.get('gefunden'), a.get('grund', ''))
            marken.append(m)

        m4 = os.urandom(16).hex()
        a = h2.bearbeite('lege_block', {
            'uebertragung': m4, 'block': 0, 'bloecke': 2,
            'pfad': 'zuviele.bin',
            'inhalt_typ': 'base64', 'inhalt': b64(b'x' * 100)})
        pruef('vierte gleichzeitige Uebertragung abgewiesen',
              not a.get('gefunden'))
        pruef('nichts von der vierten blieb liegen',
              not any('zuviele' in n for n in os.listdir(wurzel)
                      if os.path.isfile(os.path.join(wurzel, n))))

        # Eine der drei abschliessen -- danach muss wieder Platz sein.
        a = h2.bearbeite('lege_block', {
            'uebertragung': marken[0], 'block': 1, 'bloecke': 2,
            'inhalt_typ': 'base64', 'inhalt': b64(b'y' * 50),
            'sha256': sha(b'x' * 100 + b'y' * 50)})
        pruef('erste Uebertragung erfolgreich abgeschlossen',
              a.get('gefunden'), a.get('grund', ''))

        a = h2.bearbeite('lege_block', {
            'uebertragung': m4, 'block': 0, 'bloecke': 2,
            'pfad': 'jetztgehtsdoch.bin',
            'inhalt_typ': 'base64', 'inhalt': b64(b'x' * 100)})
        pruef('nach Abschluss einer alten ist wieder Platz',
              a.get('gefunden'), a.get('grund', ''))

        # Restliche offene Uebertragungen aufraeumen, bevor der GESAMT-
        # Deckel getestet wird -- der zaehlt unabhaengig davon, wieviele
        # es sind.
        for m in marken[1:] + [m4]:
            h2._teil_verwerfen(m)

        h3 = mach_handler(wurzel, max_bytes=0)
        h3.TEIL_MAX_GESAMT = 500
        a = h3.bearbeite('lege_block', {
            'uebertragung': os.urandom(16).hex(), 'block': 0, 'bloecke': 2,
            'pfad': 'zugross.bin',
            'inhalt_typ': 'base64', 'inhalt': b64(b'x' * 1000)})
        pruef('Uebertragung ueber dem Gesamt-Deckel abgewiesen',
              not a.get('gefunden'))
        pruef('und lag danach nicht auf der Platte',
              h3._teil_ordner_bytes() == 0,
              '%d Bytes liegen noch' % h3._teil_ordner_bytes())

        # Der Gesamt-Deckel gilt auch nach einem Neustart -- er liest vom
        # Datentraeger, nicht aus dem (dann leeren) Speicher des Agenten.
        o = os.path.join(wurzel, DateiHandler.TEIL_ORDNER)
        os.makedirs(o, exist_ok=True)
        liegen_geblieben = os.path.join(o, 'cc' * 8 + '.teil')
        with open(liegen_geblieben, 'wb') as f:
            f.write(b'X' * 400)
        h4 = mach_handler(wurzel, max_bytes=0)   # frischer Handler, self._teile leer
        h4.TEIL_MAX_GESAMT = 500
        a = h4.bearbeite('lege_block', {
            'uebertragung': os.urandom(16).hex(), 'block': 0, 'bloecke': 2,
            'pfad': 'nachneustart.bin',
            'inhalt_typ': 'base64', 'inhalt': b64(b'x' * 150)})
        pruef('Gesamt-Deckel wirkt auch gegen liegen gebliebene Teildateien '
              '(nach einem Neustart)', not a.get('gefunden'))
        os.unlink(liegen_geblieben)

        # --------------------------------------------------------- 6
        #
        # Am 04.09.2026 nachgeschaerft: TEIL_MAX_GESAMT deckelt Bytes,
        # TEIL_MAX_GLEICHZEITIG deckelt self._teile -- aber nur im
        # Arbeitsspeicher. Viele winzige oder leere .teil-Dateien reissen
        # keinen der beiden Deckel, ueberleben aber wie jede andere
        # liegen gebliebene Datei einen Neustart. TEIL_MAX_DATEIEN schliesst
        # genau diese Luecke.
        abschnitt('6 -- deckel gegen viele kleine liegen gebliebene dateien')

        h5 = mach_handler(wurzel, max_bytes=0)
        h5.TEIL_MAX_DATEIEN = 3

        marken5 = []
        for i in range(3):
            m = os.urandom(16).hex()
            a = h5.bearbeite('lege_block', {
                'uebertragung': m, 'block': 0, 'bloecke': 2,
                'pfad': 'winzig_%d.bin' % i,
                'inhalt_typ': 'base64', 'inhalt': b64(b'')})
            pruef('winzige Uebertragung %d von 3 wird angenommen' % (i + 1),
                  a.get('gefunden'), a.get('grund', ''))
            marken5.append(m)

        m6 = os.urandom(16).hex()
        a = h5.bearbeite('lege_block', {
            'uebertragung': m6, 'block': 0, 'bloecke': 2,
            'pfad': 'zuviele_dateien.bin',
            'inhalt_typ': 'base64', 'inhalt': b64(b'')})
        pruef('vierte Uebertragung am Dateizahl-Deckel abgewiesen, '
              'obwohl sie kaum Bytes braucht', not a.get('gefunden'))

        for m in marken5:
            h5._teil_verwerfen(m)

        # Wie beim Gesamt-Deckel: gilt auch nach einem Neustart, weil vom
        # Datentraeger gelesen wird, nicht aus self._teile. Drei leere
        # Leichen reissen TEIL_MAX_GESAMT nicht ansatzweise.
        o = os.path.join(wurzel, DateiHandler.TEIL_ORDNER)
        os.makedirs(o, exist_ok=True)
        leichen = [os.path.join(o, ('d%d' % i) * 8 + '.teil') for i in range(3)]
        for pfad in leichen:
            with open(pfad, 'wb'):
                pass    # 0 Bytes -- genau der Fall, den nur der Zaehler sieht
        h6 = mach_handler(wurzel, max_bytes=0)   # frischer Handler, self._teile leer
        h6.TEIL_MAX_DATEIEN = 3
        a = h6.bearbeite('lege_block', {
            'uebertragung': os.urandom(16).hex(), 'block': 0, 'bloecke': 2,
            'pfad': 'nachneustart2.bin',
            'inhalt_typ': 'base64', 'inhalt': b64(b'x' * 10)})
        pruef('Dateizahl-Deckel wirkt auch gegen liegen gebliebene leere '
              'Teildateien (nach einem Neustart)', not a.get('gefunden'))
        for pfad in leichen:
            os.unlink(pfad)

        # --------------------------------------------------------- 7
        #
        # Schranke 8, am 04.09.2026 hinzugefuegt: AHPT Cloud kennt keinen
        # bestimmten Virenscanner -- nur die Kommandozeilen-Konvention
        # (Exitcode 0 = sauber). Geprueft wird das gegen eine Attrappe,
        # nicht gegen ein echtes ClamAV; die Konvention ist dieselbe.
        abschnitt('7 -- virenscan (schranke 8)')

        # Ohne Konfiguration: unveraendertes Verhalten, auch mit
        # EICAR-Inhalt -- Voreinstellung ist AUS, niemandem wird ein
        # Scanner aufgezwungen.
        h7 = mach_handler(wurzel)
        a = h7.bearbeite('lege', {
            'pfad': 'ohne_scan.bin', 'inhalt_typ': 'base64', 'inhalt': b64(EICAR)})
        pruef('ohne virenscan_befehl: EICAR-Inhalt wird trotzdem angenommen',
              a.get('gefunden'), a.get('grund', ''))

        # Ungueltige Konfiguration: fehlender Platzhalter muss beim
        # Anlegen abbrechen, nicht erst beim ersten Hochladen.
        try:
            mach_handler(wurzel, virenscan_befehl=['echo', 'ohne_platzhalter'])
            pruef('virenscan_befehl ohne {datei} wird beim Start abgewiesen',
                  False, 'keine Ausnahme ausgeloest')
        except KonfigFehler:
            pruef('virenscan_befehl ohne {datei} wird beim Start abgewiesen', True)

        # Mit Attrappe, saubere Datei -- muss normal durchgehen.
        h8 = mach_handler(wurzel, virenscan_befehl=[
            sys.executable, ATTRAPPE, '{datei}'])
        a = h8.bearbeite('lege', {
            'pfad': 'sauber.bin', 'inhalt_typ': 'base64', 'inhalt': b64(b'harmlos')})
        pruef('saubere Datei besteht den Scan und wird abgelegt',
              a.get('gefunden'), a.get('grund', ''))
        pruef('  Inhalt stimmt', os.path.exists(os.path.join(wurzel, 'sauber.bin')))

        # Mit Attrappe, EICAR -- muss abgewiesen werden, nichts bleibt liegen.
        a = h8.bearbeite('lege', {
            'pfad': 'befallen.bin', 'inhalt_typ': 'base64', 'inhalt': b64(EICAR)})
        pruef('EICAR-Inhalt wird vom Scan abgewiesen', not a.get('gefunden'))
        pruef('  Meldung nennt den Virenscan',
              'Virenscan' in (a.get('grund') or ''), a.get('grund', ''))
        pruef('  nichts blieb unter dem Zielnamen liegen',
              not os.path.exists(os.path.join(wurzel, 'befallen.bin')))
        pruef('  keine Temp-Datei blieb liegen',
              not any(n.startswith('befallen.bin.') for n in os.listdir(wurzel)))

        # Derselbe Fund, aber ueber die Blockuebertragung -- die zweite
        # Einbaustelle (nach der Pruefsumme, vor Schranke 7) muss ebenso
        # greifen.
        a = lege_ganz(h8, 'befallen_block.bin', EICAR, blockgroesse=8)
        pruef('EICAR-Inhalt wird auch bei der Blockuebertragung abgewiesen',
              not a.get('gefunden'))
        pruef('  nichts blieb unter dem Zielnamen liegen',
              not os.path.exists(os.path.join(wurzel, 'befallen_block.bin')))
        pruef('  keine liegen gebliebene Teildatei',
              not os.listdir(os.path.join(wurzel, DateiHandler.TEIL_ORDNER))
              if os.path.isdir(os.path.join(wurzel, DateiHandler.TEIL_ORDNER))
              else True)

        # Scan-Befehl existiert nicht -- gilt als NICHT sauber (fail
        # closed), nicht als "kein Scan".
        h9 = mach_handler(wurzel, virenscan_befehl=[
            'es_gibt_diesen_befehl_ganz_sicher_nicht_xyz', '{datei}'])
        a = h9.bearbeite('lege', {
            'pfad': 'trotzdem_harmlos.bin', 'inhalt_typ': 'base64',
            'inhalt': b64(b'harmlos')})
        pruef('fehlender Scan-Befehl fuehrt zur Ablehnung (fail closed)',
              not a.get('gefunden'))

        # Zeitueberschreitung -- ebenfalls NICHT sauber. Absichtlich kurzes
        # Zeitlimit, damit der Test nicht selbst haengt.
        h10 = mach_handler(wurzel, virenscan_befehl=[
            sys.executable, '-c', 'import time; time.sleep(5)', '{datei}'])
        h10.VIRENSCAN_ZEITLIMIT = 1
        start = time.time()
        a = h10.bearbeite('lege', {
            'pfad': 'zeitlimit.bin', 'inhalt_typ': 'base64',
            'inhalt': b64(b'harmlos')})
        dauer = time.time() - start
        pruef('Zeitueberschreitung beim Scan fuehrt zur Ablehnung',
              not a.get('gefunden'))
        pruef('  Ablehnung kam zuegig, nicht erst nach den vollen 5s',
              dauer < 4, '%.1fs' % dauer)

        # Geschwindigkeit -- gemessen, nicht behauptet. Die Attrappe
        # braucht selbst kaum Zeit (liest eine kleine Datei, sucht eine
        # Zeichenkette); das misst also im Wesentlichen die Kosten des
        # Unterprozess-Aufrufs an sich, NICHT die Rechenzeit eines
        # echten Scanners -- die haengt vom jeweils konfigurierten
        # Produkt ab und laesst sich hier nicht vorhersagen. Ein
        # laufender clamd etwa haelt seine Signaturen im Speicher und
        # scannt typischerweise im einstelligen Millisekundenbereich je
        # kleiner Datei, aber das ist eine Messung auf DEINEM Server,
        # keine, die dieser Test treffen kann.
        DURCHLAEUFE = 20
        klein = b64(b'x' * 1024)   # 1 KiB, klein genug, dass Schreiben
                                   # selbst nicht mitgemessen wird

        h_ohne = mach_handler(wurzel)
        start = time.time()
        for i in range(DURCHLAEUFE):
            h_ohne.bearbeite('lege', {
                'pfad': 'takt_ohne_%d.bin' % i, 'inhalt_typ': 'base64',
                'inhalt': klein})
        dauer_ohne = (time.time() - start) / DURCHLAEUFE

        h_mit = mach_handler(wurzel, virenscan_befehl=[
            sys.executable, ATTRAPPE, '{datei}'])
        start = time.time()
        for i in range(DURCHLAEUFE):
            h_mit.bearbeite('lege', {
                'pfad': 'takt_mit_%d.bin' % i, 'inhalt_typ': 'base64',
                'inhalt': klein})
        dauer_mit = (time.time() - start) / DURCHLAEUFE

        print('\n  Zeitmessung (Mittel ueber %d Durchlaeufe, 1 KiB je Datei):'
              % DURCHLAEUFE)
        print('    ohne Virenscan:  %6.1f ms je Vorgang' % (dauer_ohne * 1000))
        print('    mit Virenscan:   %6.1f ms je Vorgang  (+%.1f ms)\n'
              % (dauer_mit * 1000, (dauer_mit - dauer_ohne) * 1000))

        # --------------------------------------------------------- 8
        #
        # Am 05.09.2026 live gefunden: max_bytes = 0 soll UNBEGRENZT
        # heissen, aber Schranke 6 beim einfachen `lege` pruefte
        # "laenge > max_bytes" ohne Sonderfall fuer 0 -- damit wurde jede
        # nicht-leere Datei abgewiesen ("erlaubt 0"). Die Blockuebertragung
        # hatte die Sonderregel schon immer; hier fehlte sie.
        abschnitt('8 -- max_bytes = 0 heisst wirklich unbegrenzt')

        h11 = mach_handler(wurzel, max_bytes=0)
        a = h11.bearbeite('lege', {
            'pfad': 'unbegrenzt_klein.bin', 'inhalt_typ': 'base64',
            'inhalt': b64(b'x' * 19)})
        pruef('19 Bytes werden bei max_bytes=0 angenommen (einfacher Weg)',
              a.get('gefunden'), a.get('grund', ''))

        a = h11.bearbeite('lege', {
            'pfad': 'unbegrenzt_gross.bin', 'inhalt_typ': 'base64',
            'inhalt': b64(b'x' * (2 * 1024 * 1024))})
        pruef('2 MiB werden bei max_bytes=0 angenommen (einfacher Weg)',
              a.get('gefunden'), a.get('grund', ''))

        # Gegenprobe: eine ECHTE Grenze muss weiterhin greifen.
        h12 = mach_handler(wurzel, max_bytes=10)
        a = h12.bearbeite('lege', {
            'pfad': 'echte_grenze.bin', 'inhalt_typ': 'base64',
            'inhalt': b64(b'x' * 11)})
        pruef('eine echte max_bytes-Grenze (nicht 0) greift weiterhin',
              not a.get('gefunden'))

    finally:
        shutil.rmtree(arbeit, ignore_errors=True)

    ganz, schlecht = _zahl
    print('\nERGEBNIS: %d Pruefungen, %s.\n'
          % (ganz, 'alle bestanden' if not schlecht
             else '%s%d fehlgeschlagen%s' % (ROT, schlecht, AUS)))
    print('  Gegen den echten Handler, ohne Tunnel. Ueber relay.php und')
    print('  die Verschluesselung sagt das nichts -- dafuer durchstich_privat.\n')
    return 1 if schlecht else 0


if __name__ == '__main__':
    sys.exit(main())
