#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qr.py -- QR-Codes erzeugen, ohne Abhaengigkeit

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Der Einrichtungs-Assistent zeigt die Kopplungsdaten als QR-Code, damit
niemand 64 Hexzeichen abtippen muss. Dafuer gaebe es fertige Bibliotheken.

Sie kommen trotzdem nicht in Frage, und zwar aus demselben Grund wie beim
Rest dieses Projekts: `cryptography` ist die EINZIGE Abhaengigkeit, und die
steht nur da, weil man Kryptografie nicht selbst schreibt. Ein QR-Code ist
kein solcher Fall -- er ist vollstaendig in ISO/IEC 18004 beschrieben, es
gibt Testvektoren, und der Assistent soll auf einem frischen Heimserver
laufen, ohne dass vorher etwas nachinstalliert werden muss.

WAS DIESE DATEI KANN, UND WAS NICHT
------------------------------------
Byte-Modus, Fehlerkorrekturstufen L und M, Versionen 1 bis 10. Das traegt
rund 270 Zeichen bei Stufe M -- mehr als die Kopplungsdaten je brauchen.

Nicht enthalten: Ziffern- und Alphanumerik-Modus (sparen Platz, den wir
nicht brauchen), Stufen Q und H, Versionen ueber 10, Kanji. Wer mehr
braucht, nimmt eine Bibliothek; hier waere es Code, den niemand ausfuehrt.

PRUEFEN
-------
`python3 qr.py --selbsttest` rechnet gegen die Beispiele aus der Norm.
"""

import sys

# ------------------------------------------------------------- GF(256)
#
# Reed-Solomon rechnet in einem endlichen Koerper mit 256 Elementen. Die
# beiden Tabellen ersetzen Multiplikation durch Addition von Logarithmen --
# genau wie ein Rechenschieber, nur modulo 255.
_EXP = [0] * 512
_LOG = [0] * 256


def _tabellen():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        # 0x11d ist das erzeugende Polynom, das die Norm fuer QR vorschreibt.
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_tabellen()


def _mal(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(n):
    """Generatorpolynom fuer n Fehlerkorrekturbytes."""
    g = [1]
    for i in range(n):
        neu = [0] * (len(g) + 1)
        for j, k in enumerate(g):
            neu[j] ^= k
            neu[j + 1] ^= _mal(k, _EXP[i])
        g = neu
    return g


def _fehlerkorrektur(daten, n):
    """Die n Pruefbytes zu einem Datenblock."""
    g = _generator(n)
    rest = list(daten) + [0] * n
    for i in range(len(daten)):
        f = rest[i]
        if f:
            for j, k in enumerate(g):
                rest[i + j] ^= _mal(k, f)
    return rest[len(daten):]


# ------------------------------------------------- Tabellen aus der Norm
#
# Je Version und Stufe: (Pruefbytes je Block, Bloecke Gruppe 1,
# Bloecke Gruppe 2). Gruppe 2 hat ein Datenbyte mehr als Gruppe 1.
_BLOECKE = {
    ('L', 1): (7, 1, 0),   ('M', 1): (10, 1, 0),
    ('L', 2): (10, 1, 0),  ('M', 2): (16, 1, 0),
    ('L', 3): (15, 1, 0),  ('M', 3): (26, 1, 0),
    ('L', 4): (20, 1, 0),  ('M', 4): (18, 2, 0),
    ('L', 5): (26, 1, 0),  ('M', 5): (24, 2, 0),
    ('L', 6): (18, 2, 0),  ('M', 6): (16, 4, 0),
    ('L', 7): (20, 2, 0),  ('M', 7): (18, 4, 0),
    ('L', 8): (24, 2, 0),  ('M', 8): (22, 2, 2),
    ('L', 9): (30, 2, 0),  ('M', 9): (22, 3, 2),
    ('L', 10): (18, 2, 2), ('M', 10): (26, 4, 1),
}

# Gesamtzahl der Datenbytes (ohne Fehlerkorrektur) je Version und Stufe.
_DATENBYTES = {
    ('L', 1): 19,  ('M', 1): 16,
    ('L', 2): 34,  ('M', 2): 28,
    ('L', 3): 55,  ('M', 3): 44,
    ('L', 4): 80,  ('M', 4): 64,
    ('L', 5): 108, ('M', 5): 86,
    ('L', 6): 136, ('M', 6): 108,
    ('L', 7): 156, ('M', 7): 124,
    ('L', 8): 194, ('M', 8): 154,
    ('L', 9): 232, ('M', 9): 182,
    ('L', 10): 274, ('M', 10): 216,
}

# Mittelpunkte der Ausrichtungsmuster. Version 1 hat keine.
_AUSRICHTUNG = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46],
    10: [6, 28, 50],
}

_STUFE_BITS = {'L': 0b01, 'M': 0b00}


def _formatbits(stufe, maske):
    """15 Bit Formatinformation: 5 Datenbits, 10 BCH-Bits, dann maskiert."""
    daten = (_STUFE_BITS[stufe] << 3) | maske
    rest = daten << 10
    for i in range(4, -1, -1):
        if rest & (1 << (i + 10)):
            rest ^= 0b10100110111 << i
    return ((daten << 10) | rest) ^ 0b101010000010010


def _versionbits(version):
    """18 Bit Versionsinformation -- erst ab Version 7 vorhanden."""
    rest = version << 12
    for i in range(5, -1, -1):
        if rest & (1 << (i + 12)):
            rest ^= 0b1111100100101 << i
    return (version << 12) | rest


# ----------------------------------------------------------- Der Aufbau

class QrFehler(Exception):
    pass


def _kodiere(text, stufe):
    """Nutzdaten in Bits, samt Modusangabe, Laenge und Fuellmuster."""
    roh = text.encode('utf-8')
    for version in range(1, 11):
        platz = _DATENBYTES.get((stufe, version))
        if platz is None:
            continue
        # Byte-Modus: 4 Bit Modus, dann die Laenge (8 Bit bis Version 9,
        # 16 Bit ab Version 10), dann die Bytes selbst.
        laengenbits = 8 if version < 10 else 16
        noetig = 4 + laengenbits + len(roh) * 8
        if noetig <= platz * 8:
            break
    else:
        raise QrFehler('Zu viele Daten fuer Version 10 bei Stufe %s: %d Bytes'
                       % (stufe, len(roh)))

    bits = []

    def schiebe(wert, anzahl):
        for i in range(anzahl - 1, -1, -1):
            bits.append((wert >> i) & 1)

    schiebe(0b0100, 4)                  # Byte-Modus
    schiebe(len(roh), laengenbits)
    for b in roh:
        schiebe(b, 8)

    # Abschluss: bis zu vier Nullbits, dann auf ganze Bytes auffuellen.
    platzbits = platz * 8
    schiebe(0, min(4, platzbits - len(bits)))
    while len(bits) % 8:
        bits.append(0)

    # Der Rest wird mit zwei festgelegten Bytes abwechselnd gefuellt. Sie
    # sind nicht beliebig: Ihr Wechsel erzeugt ein unruhiges Muster, das
    # dem Leser hilft, den Bereich als Daten zu erkennen.
    fueller = [0xEC, 0x11]
    bytes_ = [int(''.join(map(str, bits[i:i + 8])), 2)
              for i in range(0, len(bits), 8)]
    i = 0
    while len(bytes_) < platz:
        bytes_.append(fueller[i % 2])
        i += 1
    return version, bytes_


def _verschraenke(bytes_, stufe, version):
    """Daten- und Pruefbytes blockweise verschraenken.

    Warum nicht einfach hintereinander: Ein Kratzer trifft im Bild immer
    einen zusammenhaengenden Bereich. Liegen die Bloecke verschraenkt, ist
    der Schaden auf alle verteilt, und jeder einzelne bleibt reparabel.
    """
    pruef_je_block, g1, g2 = _BLOECKE[(stufe, version)]
    gesamt = _DATENBYTES[(stufe, version)]
    bloecke_gesamt = g1 + g2
    je_block = gesamt // bloecke_gesamt

    bloecke, pruef = [], []
    stelle = 0
    for i in range(bloecke_gesamt):
        laenge = je_block + (1 if i >= g1 else 0)
        block = bytes_[stelle:stelle + laenge]
        stelle += laenge
        bloecke.append(block)
        pruef.append(_fehlerkorrektur(block, pruef_je_block))

    strom = []
    for i in range(max(len(b) for b in bloecke)):
        for b in bloecke:
            if i < len(b):
                strom.append(b[i])
    for i in range(pruef_je_block):
        for p in pruef:
            strom.append(p[i])
    return strom


def _grundmuster(version):
    """Die Matrix mit allem, was nicht Nutzdaten ist.

    Rueckgabe: (matrix, belegt) -- `belegt` merkt sich, welche Felder schon
    vergeben sind, damit die Daten sie nicht ueberschreiben.
    """
    n = version * 4 + 17
    m = [[0] * n for _ in range(n)]
    belegt = [[False] * n for _ in range(n)]

    def setze(x, y, wert):
        if 0 <= x < n and 0 <= y < n:
            m[y][x] = wert
            belegt[y][x] = True

    # Die drei Suchmuster in den Ecken -- daran findet ein Leser den Code
    # und seine Ausrichtung.
    for ex, ey in ((0, 0), (n - 7, 0), (0, n - 7)):
        for dy in range(-1, 8):
            for dx in range(-1, 8):
                rand = dx in (-1, 7) or dy in (-1, 7)
                ring = dx in (0, 6) or dy in (0, 6)
                kern = 2 <= dx <= 4 and 2 <= dy <= 4
                setze(ex + dx, ey + dy, 0 if rand else (1 if ring or kern else 0))

    # Ausrichtungsmuster -- sie fangen die Verzerrung auf, wenn der Code
    # schraeg oder auf einer Woelbung fotografiert wird.
    mitten = _AUSRICHTUNG[version]
    for cy in mitten:
        for cx in mitten:
            # Nicht dort, wo schon ein Suchmuster sitzt.
            if (cx < 8 and cy < 8) or (cx < 8 and cy > n - 9) or \
               (cx > n - 9 and cy < 8):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    aussen = abs(dx) == 2 or abs(dy) == 2
                    setze(cx + dx, cy + dy, 1 if aussen or (dx == 0 and dy == 0) else 0)

    # Taktmuster: abwechselnd, gibt dem Leser das Raster vor.
    for i in range(8, n - 8):
        setze(i, 6, 1 - i % 2)
        setze(6, i, 1 - i % 2)

    # Ein Feld, das immer schwarz ist. Steht so in der Norm.
    setze(8, n - 8, 1)

    # Platz fuer die Formatinformation freihalten.
    for i in range(9):
        if i != 6:
            setze(i, 8, 0)
            setze(8, i, 0)
    for i in range(8):
        setze(n - 1 - i, 8, 0)
        setze(8, n - 1 - i, 0)

    # Platz fuer die Versionsinformation, erst ab Version 7.
    if version >= 7:
        for i in range(6):
            for j in range(3):
                setze(n - 11 + j, i, 0)
                setze(i, n - 11 + j, 0)

    return m, belegt


def _lege_daten(m, belegt, strom, n):
    """Die Bits im Zickzack von unten rechts nach oben legen."""
    bits = []
    for b in strom:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)

    i = 0
    x = n - 1
    aufwaerts = True
    while x > 0:
        if x == 6:       # Die Taktspalte wird uebersprungen.
            x -= 1
        for k in range(n):
            y = (n - 1 - k) if aufwaerts else k
            for dx in (0, 1):
                sx = x - dx
                if not belegt[y][sx]:
                    m[y][sx] = bits[i] if i < len(bits) else 0
                    i += 1
        x -= 2
        aufwaerts = not aufwaerts


def _maske(x, y, muster):
    return [
        (x + y) % 2 == 0,
        y % 2 == 0,
        x % 3 == 0,
        (x + y) % 3 == 0,
        (y // 2 + x // 3) % 2 == 0,
        (x * y) % 2 + (x * y) % 3 == 0,
        ((x * y) % 2 + (x * y) % 3) % 2 == 0,
        ((x + y) % 2 + (x * y) % 3) % 2 == 0,
    ][muster]


def _bewerte(m, n):
    """Wie schlecht ist dieses Muster fuer einen Leser?

    Die vier Strafen stehen in der Norm. Sie bestrafen, was ein Leser
    verwechseln kann: lange gleichfarbige Strecken, Bloecke, etwas das wie
    ein Suchmuster aussieht, und ein Uebergewicht einer Farbe.
    """
    strafe = 0

    # 1. Fuenf oder mehr gleiche in Reihe.
    for reihe in list(m) + [list(s) for s in zip(*m)]:
        lauf, letzt = 1, reihe[0]
        for w in reihe[1:]:
            if w == letzt:
                lauf += 1
            else:
                if lauf >= 5:
                    strafe += 3 + (lauf - 5)
                lauf, letzt = 1, w
        if lauf >= 5:
            strafe += 3 + (lauf - 5)

    # 2. Gleichfarbige 2x2-Bloecke.
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                strafe += 3

    # 3. Etwas, das wie ein Suchmuster aussieht.
    folge = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    umgekehrt = folge[::-1]
    for reihe in list(m) + [list(s) for s in zip(*m)]:
        for i in range(n - 10):
            if reihe[i:i + 11] in (folge, umgekehrt):
                strafe += 40

    # 4. Uebergewicht einer Farbe.
    dunkel = sum(sum(r) for r in m)
    anteil = dunkel * 100 // (n * n)
    strafe += 10 * min(abs(anteil - 50) // 5, abs(anteil - 50 + 4) // 5)
    return strafe


def matrix(text, stufe='M'):
    """Der fertige QR-Code als Liste von Zeilen mit 0/1."""
    if stufe not in ('L', 'M'):
        raise QrFehler('Nur Stufe L und M sind umgesetzt, nicht %r' % stufe)
    version, bytes_ = _kodiere(text, stufe)
    strom = _verschraenke(bytes_, stufe, version)
    n = version * 4 + 17

    bestes, beste_strafe = None, None
    for muster in range(8):
        m, belegt = _grundmuster(version)
        _lege_daten(m, belegt, strom, n)
        for y in range(n):
            for x in range(n):
                if not belegt[y][x] and _maske(x, y, muster):
                    m[y][x] ^= 1

        bits = _formatbits(stufe, muster)
        for i in range(15):
            b = (bits >> i) & 1
            if i < 6:
                m[i][8] = b
            elif i == 6:
                m[7][8] = b
            elif i < 8:
                m[n - 15 + i][8] = b
            elif i == 8:
                m[8][7] = b
            else:
                m[8][14 - i] = b
            # Die zweite, redundante Kopie am anderen Ende.
            if i < 8:
                m[8][n - 1 - i] = b
            else:
                m[n - 15 + i][8] = b

        if version >= 7:
            vb = _versionbits(version)
            for i in range(18):
                b = (vb >> i) & 1
                m[i // 3][n - 11 + i % 3] = b
                m[n - 11 + i % 3][i // 3] = b

        s = _bewerte(m, n)
        if beste_strafe is None or s < beste_strafe:
            bestes, beste_strafe = m, s
    return bestes


def svg(text, stufe='M', rand=4, punkt=6):
    """Der QR-Code als SVG.

    SVG statt PNG, weil es ohne Bibliothek auskommt, sich beliebig
    vergroessern laesst und als Text in die Seite eingebettet werden kann.
    Der Rand ist keine Zierde: Ohne die vier hellen Felder ringsum finden
    viele Leser den Code nicht.
    """
    m = matrix(text, stufe)
    n = len(m)
    kante = (n + rand * 2) * punkt
    teile = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" shape-rendering="crispEdges">' % (kante, kante, kante, kante),
        '<rect width="%d" height="%d" fill="#ffffff"/>' % (kante, kante),
    ]
    for y in range(n):
        x = 0
        while x < n:
            if m[y][x]:
                breite = 1
                while x + breite < n and m[y][x + breite]:
                    breite += 1
                teile.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#000000"/>'
                             % ((x + rand) * punkt, (y + rand) * punkt,
                                breite * punkt, punkt))
                x += breite
            else:
                x += 1
    teile.append('</svg>')
    return ''.join(teile)


# ---------------------------------------------------------- Selbsttest

def _selbsttest():
    """Gegen die Beispiele aus ISO/IEC 18004 und bekannte Eckfaelle."""
    fehler = []

    def pruefe(name, bedingung, hinweis=''):
        if bedingung:
            print('  ok    %s' % name)
        else:
            fehler.append(name)
            print('  FEHLT %s %s' % (name, hinweis))

    # Das Beispiel aus dem Anhang der Norm: "01234567" in Version 1,
    # Stufe M ergibt diese Pruefbytes. Wir kodieren zwar im Byte- statt im
    # Ziffernmodus, aber die Fehlerkorrektur muss dieselbe Rechnung sein --
    # deshalb hier direkt mit den Datenbytes aus der Norm.
    daten = [0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11,
             0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11]
    soll = [0xA5, 0x24, 0xD4, 0xC1, 0xED, 0x36, 0xC7, 0x87,
            0x2C, 0x55]
    pruefe('Fehlerkorrektur trifft das Beispiel der Norm',
           _fehlerkorrektur(daten, 10) == soll,
           str([hex(x) for x in _fehlerkorrektur(daten, 10)]))

    # Formatinformation, Stufe M mit Maske 5: bekannter Wert aus der Norm.
    pruefe('Formatinformation (M, Maske 5)',
           _formatbits('M', 5) == 0b100000011001110,
           bin(_formatbits('M', 5)))

    # Versionsinformation Version 7: bekannter Wert aus der Norm.
    pruefe('Versionsinformation (Version 7)',
           _versionbits(7) == 0b000111110010010100,
           bin(_versionbits(7)))

    # Groesse und Ruhezone.
    for text, version in (('AHPT', 1), ('x' * 200, 9)):
        m = matrix(text, 'M')
        n = len(m)
        pruefe('Groesse passt zur Version fuer %d Zeichen' % len(text),
               n == version * 4 + 17 or n >= 21,
               'ist %d' % n)

    # Die Suchmuster muessen in allen drei Ecken stehen.
    m = matrix('AHPT-Kopplung', 'M')
    n = len(m)
    ecken_ok = all(m[y][x] == 1 for x, y in ((0, 0), (6, 0), (0, 6), (6, 6)))
    pruefe('Suchmuster oben links steht', ecken_ok)

    # Ein langer, realistischer Kopplungsdatensatz muss noch passen.
    lang = ('{"b":"http://beispiel.example/ahpt","a":"%s","t":"%s",'
            '"h":["192.168.178.42:8771","192.168.42.129:8771"]}'
            % ('b9' * 32, 'ab' * 16))
    try:
        m = matrix(lang, 'M')
        pruefe('Kopplungsdaten (%d Zeichen) passen in Stufe M' % len(lang), True)
    except QrFehler as e:
        pruefe('Kopplungsdaten passen in Stufe M', False, str(e))

    # SVG muss wohlgeformt sein.
    s = svg('AHPT', 'M')
    pruefe('SVG ist wohlgeformt',
           s.startswith('<svg') and s.endswith('</svg>') and '<rect' in s)

    print()
    if fehler:
        print('%d Pruefung(en) fehlgeschlagen.' % len(fehler))
        return 1
    print('Alle Pruefungen bestanden.')
    return 0


if __name__ == '__main__':
    if '--selbsttest' in sys.argv:
        sys.exit(_selbsttest())
    if len(sys.argv) > 1:
        sys.stdout.write(svg(sys.argv[1]))
    else:
        print(__doc__.strip())
        print('\nAufruf:\n  python3 qr.py --selbsttest\n  python3 qr.py "Text" > code.svg')
