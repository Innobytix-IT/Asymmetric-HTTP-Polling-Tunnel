#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pruefe_krypto.py -- rechnet krypto.py gegen die offiziellen Testvektoren nach

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Diese Datei ist der einzige Grund, warum `krypto.py` ueberhaupt
verantwortbar ist.

`ARCHITEKTUR.md` §8 des oeffentlichen Projekts warnt vor
selbstgeschriebener Kryptografie -- zu Recht. Der Unterschied zwischen
"selbst ausgedacht" und "selbst umgesetzt" ist genau dieser Abgleich:
Stimmt jeder Geheimtext Byte fuer Byte mit dem ueberein, was andere
Umsetzungen derselben Spezifikation erzeugen, dann ist es dieselbe
Spezifikation. Weicht ein Byte ab, ist es etwas anderes -- und etwas
anderes ist in der Kryptografie immer das Schlechtere.

Die Vektoren stammen aus `cacophony.txt` des Projekts *snow* (der
verbreiteten Rust-Umsetzung von Noise), geholt am 03.09.2026. Sie liegen
als `ik_vektoren.json` im Projekt, damit diese Pruefung ohne Netz laeuft --
ein Test, der ins Internet greifen muss, wird irgendwann nicht mehr
gefahren.

WAS HIER GEPRUEFT WIRD
----------------------
Nicht nur "es laeuft durch", sondern jeder Zwischenschritt:

  * jeder Geheimtext beider Handshake-Nachrichten
  * die zurueckgewonnenen Klartexte auf der Gegenseite
  * der Handshake-Hash am Ende
  * alle Transportnachrichten danach, in beide Richtungen
  * und dass Manipulation auffaellt

Der letzte Punkt ist der wichtigste: Eine Kryptografie, die alles
entschluesselt, was man ihr hinhaelt, besteht jeden Gutfall-Test.

Aufruf:
    python3 tests/pruefe_krypto.py
"""

import json
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))

import krypto                                            # noqa: E402

ERGEBNIS = []


def pruefe(beschreibung, bedingung, hinweis=''):
    ok = bool(bedingung)
    ERGEBNIS.append(ok)
    print('  %-56s %s%s' % (beschreibung, 'ok' if ok else 'FEHLSCHLAG',
                            ('  -- ' + hinweis) if hinweis and not ok else ''))
    return ok


def h(s):
    return bytes.fromhex(s)


def vektor_pruefen(v):
    name = v['protocol_name']
    aead = 'ChaChaPoly' if 'ChaChaPoly' in name else 'AESGCM'
    print('')
    print(name)
    print('')

    i_s   = h(v['init_static'])
    i_e   = h(v['init_ephemeral'])
    i_rs  = h(v['init_remote_static'])
    r_s   = h(v['resp_static'])
    r_e   = h(v['resp_ephemeral'])
    i_pro = h(v.get('init_prologue', ''))
    r_pro = h(v.get('resp_prologue', ''))
    nachr = v['messages']

    # Vorprobe: Der dem Initiator bekannte Schluessel MUSS der oeffentliche
    # Teil des Antwortenden sein. Stimmt das nicht, prueft der Rest Unsinn.
    pruefe('Vorprobe: bekannter Schluessel passt zum Antwortenden',
           krypto._oeffentlich(r_s) == i_rs)

    ini = krypto.HandshakeIK(True,  i_pro, i_s, rs=i_rs, e=i_e, aead=aead)
    ant = krypto.HandshakeIK(False, r_pro, r_s,          e=r_e, aead=aead)

    # --- Nachricht 1:  -> e, es, s, ss
    m1 = ini.schreibe_nachricht1(h(nachr[0]['payload']))
    pruefe('Nachricht 1, Geheimtext stimmt Byte fuer Byte',
           m1 == h(nachr[0]['ciphertext']),
           '%d statt %d Bytes' % (len(m1), len(h(nachr[0]['ciphertext']))))
    zurueck = ant.lies_nachricht1(h(nachr[0]['ciphertext']))
    pruefe('Nachricht 1, Antwortender gewinnt den Klartext zurueck',
           zurueck == h(nachr[0]['payload']))
    pruefe('Nachricht 1, Antwortender erkennt den Absender',
           ant.rs == krypto._oeffentlich(i_s))

    # --- Nachricht 2:  <- e, ee, se
    m2 = ant.schreibe_nachricht2(h(nachr[1]['payload']))
    pruefe('Nachricht 2, Geheimtext stimmt Byte fuer Byte',
           m2 == h(nachr[1]['ciphertext']),
           '%d statt %d Bytes' % (len(m2), len(h(nachr[1]['ciphertext']))))
    zurueck = ini.lies_nachricht2(h(nachr[1]['ciphertext']))
    pruefe('Nachricht 2, Initiator gewinnt den Klartext zurueck',
           zurueck == h(nachr[1]['payload']))

    # --- Der Hash ueber alles Gesagte
    pruefe('Handshake-Hash beider Seiten gleich',
           ini.handshake_hash() == ant.handshake_hash())
    if 'handshake_hash' in v:
        pruefe('Handshake-Hash stimmt mit dem Vektor',
               ini.handshake_hash() == h(v['handshake_hash']))

    # --- Transportnachrichten danach, abwechselnd
    i1, i2 = ini.transportschluessel()      # i1: Initiator -> Antwortender
    a1, a2 = ant.transportschluessel()      # a1: Initiator -> Antwortender
    pruefe('beide Seiten leiten dieselben Transportschluessel ab',
           i1.k == a1.k and i2.k == a2.k)

    for nr in range(2, len(nachr)):
        von_initiator = (nr % 2 == 0)
        sender, empfaenger = (i1, a1) if von_initiator else (a2, i2)
        soll = h(nachr[nr]['ciphertext'])
        p    = h(nachr[nr]['payload'])
        c = sender.EncryptWithAd(b'', p)
        pruefe('Transportnachricht %d (%s) stimmt' % (
                   nr + 1, 'Client -> Agent' if von_initiator else 'Agent -> Client'),
               c == soll)
        pruefe('Transportnachricht %d wird zurueckgewonnen' % (nr + 1),
               empfaenger.DecryptWithAd(b'', soll) == p)


def angriffe_pruefen():
    """Das Verbotene. Ein Gutfall-Test beweist nichts ueber die Schranke."""
    print('')
    print('ANGRIFFE')
    print('')

    a_s, a_p = krypto.schluesselpaar()      # Agent
    c_s, c_p = krypto.schluesselpaar()      # Client
    f_s, f_p = krypto.schluesselpaar()      # Fremder

    def neuer_lauf():
        return (krypto.HandshakeIK(True,  b'', c_s, rs=a_p),
                krypto.HandshakeIK(False, b'', a_s))

    # 1 -- Gutfall, damit die Angriffe nicht gegen etwas Kaputtes laufen.
    ini, ant = neuer_lauf()
    m1 = ini.schreibe_nachricht1(b'geheime Frage')
    pruefe('Gutfall: Frage kommt an', ant.lies_nachricht1(m1) == b'geheime Frage')
    m2 = ant.schreibe_nachricht2(b'geheime Antwort')
    pruefe('Gutfall: Antwort kommt an', ini.lies_nachricht2(m2) == b'geheime Antwort')

    # 2 -- Ein einzelnes veraendertes Byte im Geheimtext.
    ini, ant = neuer_lauf()
    m1 = bytearray(ini.schreibe_nachricht1(b'geheime Frage'))
    m1[-1] ^= 0x01
    try:
        ant.lies_nachricht1(bytes(m1))
        pruefe('veraendertes Byte wird abgewiesen', False, 'ging durch')
    except krypto.KryptoFehler:
        pruefe('veraendertes Byte wird abgewiesen', True)

    # 3 -- Ein veraenderter fluechtiger Schluessel (die ersten 32 Bytes).
    ini, ant = neuer_lauf()
    m1 = bytearray(ini.schreibe_nachricht1(b'geheime Frage'))
    m1[0] ^= 0x01
    try:
        ant.lies_nachricht1(bytes(m1))
        pruefe('veraenderter fluechtiger Schluessel faellt auf', False, 'ging durch')
    except krypto.KryptoFehler:
        pruefe('veraenderter fluechtiger Schluessel faellt auf', True)

    # 4 -- Ein Fremder schreibt an den Agenten. Er KANN das (der oeffentliche
    #      Schluessel des Agenten ist kein Geheimnis) -- der Agent muss danach
    #      aber sehen, dass es nicht der eigene Client war.
    fremd = krypto.HandshakeIK(True, b'', f_s, rs=a_p)
    ant   = krypto.HandshakeIK(False, b'', a_s)
    ant.lies_nachricht1(fremd.schreibe_nachricht1(b'ich bin es, ehrlich'))
    pruefe('Fremder wird als fremd erkannt',
           ant.rs != c_p and ant.rs == f_p)

    # 5 -- Der Agent-Schluessel stimmt nicht: dann scheitert schon der
    #      Handshake, und zwar auf der Empfaengerseite.
    ini = krypto.HandshakeIK(True, b'', c_s, rs=f_p)     # falsches Ziel
    ant = krypto.HandshakeIK(False, b'', a_s)
    try:
        ant.lies_nachricht1(ini.schreibe_nachricht1(b'x'))
        pruefe('Frage an den falschen Schluessel scheitert', False, 'ging durch')
    except krypto.KryptoFehler:
        pruefe('Frage an den falschen Schluessel scheitert', True)

    # 6 -- Zwei Laeufe mit derselben Frage ergeben verschiedene Geheimtexte.
    #      Sonst waere von aussen erkennbar, wann dasselbe gefragt wird.
    a = krypto.HandshakeIK(True, b'', c_s, rs=a_p).schreibe_nachricht1(b'gleich')
    b = krypto.HandshakeIK(True, b'', c_s, rs=a_p).schreibe_nachricht1(b'gleich')
    pruefe('gleiche Frage ergibt verschiedene Geheimtexte', a != b)

    # 7 -- Ein leerer Prologue auf einer Seite, ein anderer auf der anderen:
    #      muss auffallen. Der Prologue bindet den Zusammenhang.
    ini = krypto.HandshakeIK(True,  b'AHPT/1', c_s, rs=a_p)
    ant = krypto.HandshakeIK(False, b'anders', a_s)
    try:
        ant.lies_nachricht1(ini.schreibe_nachricht1(b'x'))
        pruefe('abweichender Prologue faellt auf', False, 'ging durch')
    except krypto.KryptoFehler:
        pruefe('abweichender Prologue faellt auf', True)


def wiederholung_pruefen():
    """Der Schutz gegen erneut eingespielte erste Nachrichten.

    Kryptografie hilft hier nicht: Eine wiederholte Nachricht ist echt.
    Nur ein Gedaechtnis kann sie erkennen.
    """
    print('')
    print('WIEDERHOLUNGSSCHUTZ')
    print('')

    jetzt = [1000.0]
    w = krypto.Wiederholungsschutz(fenster=120, uhr=lambda: jetzt[0])

    k1, k2 = os.urandom(32), os.urandom(32)
    pruefe('erste Nachricht geht durch', w.neu(k1) is True)
    pruefe('dieselbe Nachricht noch einmal wird abgewiesen', w.neu(k1) is False)
    pruefe('eine andere geht durch', w.neu(k2) is True)

    jetzt[0] += 121
    pruefe('nach Ablauf des Fensters wieder erlaubt', w.neu(k1) is True,
           'die Marke ist dann ohnehin verfallen')
    pruefe('altes wurde weggeraeumt', len(w) == 1, '%d Eintraege' % len(w))

    # Der Deckel: Ein Angreifer darf das Gedaechtnis nicht fluten und
    # dadurch Wiederholungen wieder durchbekommen.
    klein = krypto.Wiederholungsschutz(fenster=120, deckel=3, uhr=lambda: jetzt[0])
    for _ in range(3):
        klein.neu(os.urandom(32))
    pruefe('bei vollem Gedaechtnis wird ABGEWIESEN, nicht vergessen',
           klein.neu(os.urandom(32)) is False)


def schluessel_pruefen():
    print('')
    print('SCHLUESSELVERWALTUNG')
    print('')
    import stat
    import tempfile

    d = tempfile.mkdtemp(prefix='ahpt_schluessel_')
    try:
        p, oe = krypto.schluesselpaar()
        pfad = os.path.join(d, 'agent.key')
        krypto.schreibe_privat(pfad, p)
        pruefe('privater Schluessel wird zurueckgelesen',
               krypto.lies_privat(pfad) == p)
        pruefe('oeffentlicher Teil bleibt derselbe',
               krypto._oeffentlich(krypto.lies_privat(pfad)) == oe)

        # Auf Windows sagt der Rechtebegriff wenig -- dann ausdruecklich
        # UEBERSPRUNGEN statt "ok". Ein Test, der nichts misst, darf nicht
        # bestehen.
        if os.name == 'posix':
            m = stat.S_IMODE(os.stat(pfad).st_mode)
            pruefe('Datei nur fuer den Eigentuemer lesbar (0600)', m == 0o600,
                   'Rechte %o' % m)
        else:
            print('  %-56s %s' % ('Dateirechte', 'UEBERSPRUNGEN -- kein POSIX'))

        with open(os.path.join(d, 'kaputt.key'), 'w') as f:
            f.write('kein hex\n')
        try:
            krypto.lies_privat(os.path.join(d, 'kaputt.key'))
            pruefe('unbrauchbare Schluesseldatei bricht ab', False, 'ging durch')
        except krypto.KryptoFehler:
            pruefe('unbrauchbare Schluesseldatei bricht ab', True)

        with open(os.path.join(d, 'kurz.key'), 'w') as f:
            f.write('aabb\n')
        try:
            krypto.lies_privat(os.path.join(d, 'kurz.key'))
            pruefe('zu kurzer Schluessel bricht ab', False, 'ging durch')
        except krypto.KryptoFehler:
            pruefe('zu kurzer Schluessel bricht ab', True)
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def main():
    pfad = os.path.join(HIER, 'ik_vektoren.json')
    if not os.path.isfile(pfad):
        print('ABBRUCH: %s fehlt -- ohne Vektoren prueft diese Datei nichts.' % pfad)
        return 2
    d = json.load(open(pfad, encoding='utf-8'))
    print('')
    print('TESTVEKTOREN   %s' % d.get('quelle', '?'))

    for v in d['vectors']:
        vektor_pruefen(v)
    angriffe_pruefen()
    wiederholung_pruefen()
    schluessel_pruefen()

    fehler = sum(1 for ok in ERGEBNIS if not ok)
    print('')
    print('ERGEBNIS: %d Pruefungen, %s' % (
        len(ERGEBNIS),
        'alle bestanden.' if not fehler else '%d FEHLSCHLAG(E).' % fehler))
    if not fehler:
        print('')
        print('  Damit ist krypto.py keine selbstgedachte Kryptografie mehr,')
        print('  sondern eine gegen fremde Vektoren gepruefte Umsetzung.')
    return 1 if fehler else 0


if __name__ == '__main__':
    sys.exit(main())
