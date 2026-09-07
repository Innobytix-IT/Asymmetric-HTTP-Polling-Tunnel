#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
krypto.py -- Noise IK fuer AHPT Cloud

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
`SICHERHEIT.md` §3.1 sagt: Der Kanal ist oeffentlich, jeder kann die
Warteschlange pollen und Frage wie Antwort mitlesen. Fuer ein Lexikon ist
das hinnehmbar. Fuer eigene Dateien ist es das Ende.

Diese Datei macht aus dem, was auf dem Webspace liegt, Rauschen.

WARUM NOISE UND NICHT ETWAS SELBSTGEDACHTES
--------------------------------------------
`ARCHITEKTUR.md` §8 warnt ausdruecklich vor selbstgeschriebener
Kryptografie -- und diese Datei sieht auf den ersten Blick genau danach
aus. Der Unterschied liegt in einem einzigen Punkt:

    Hier wird nichts ERFUNDEN. Hier wird eine SPEZIFIKATION UMGESETZT,
    und die Umsetzung wird gegen die offiziellen Testvektoren geprueft.

`tests/pruefe_krypto.py` rechnet den vollstaendigen Handshake gegen
`tests/ik_vektoren.json` nach -- Schluessel, Zwischenzustaende, jeder
Geheimtext, der Handshake-Hash. Weicht ein einziges Byte ab, faellt der
Test um. Das ist der Unterschied zwischen "ich glaube, es stimmt" und "es
stimmt, und zwar nachweislich".

WARUM DIE ENGLISCHEN NAMEN
--------------------------
`MixKey`, `MixHash`, `EncryptAndHash`, `Split` heissen hier so wie in der
Noise-Spezifikation, obwohl das Projekt sonst durchgehend deutsch ist.
Absicht: Wer diese Datei gegen die Spezifikation prueft -- und das MUSS
jemand koennen -- soll Zeile fuer Zeile vergleichen koennen, ohne zu
uebersetzen. Uebersetzte Namen waeren hier keine Sorgfalt, sondern eine
zusaetzliche Fehlerquelle.

Die Begruendungen dazwischen sind deutsch.

WAS NOISE IK LEISTET
--------------------
    IK:
      <- s
      ...
      -> e, es, s, ss
      <- e, ee, se

"IK" heisst: der **I**nitiator kennt den statischen Schluessel des
Antwortenden. Genau die Rollenverteilung von AHPT Cloud -- der Client
kennt den Schluessel des Agenten, weil er ihn von Hand bekommen hat.

Nach der ersten Nachricht weiss der Agent, dass die Frage vom echten Client
kommt (nur der kennt dessen statischen Schluessel). Nach der zweiten weiss
der Client, dass die Antwort vom echten Agenten kommt.

    Die erste Nachricht darf bereits Nutzlast tragen. Deshalb kostet die
    Verschluesselung KEINE zusaetzliche Runde durch den Webspace -- Frage
    und Antwort bleiben ein einziger Umlauf, so wie heute.

Der Preis, und er gehoert benannt:

  * Die Nutzlast in Nachricht 1 hat KEINE Forward Secrecy. Wer spaeter den
    statischen Schluessel des Agenten erbeutet, kann alte FRAGEN
    entschluesseln. Die Antworten nicht -- die haengen am fluechtigen
    Schluessel.
  * Nachricht 1 ist WIEDERHOLBAR. Dagegen hilft keine Kryptografie,
    sondern ein Gedaechtnis: Der Agent merkt sich die gesehenen fluechtigen
    Schluessel und bearbeitet keinen zweimal. Das steht nicht hier, sondern
    dort, wo es hingehoert -- beim Agenten.

ABWEICHUNG VON WIREGUARD, die man nicht verwischen darf: WireGuard nutzt
IKpsk2 ausschliesslich fuer den Handshake und schickt nie Daten darin. Wir
borgen uns das Noise-MUSTER, nicht WireGuards Verwendung davon. Wer sich
auf "auditiert wie WireGuard" beruft, beruft sich auf ein Audit, das etwas
anderes geprueft hat.

ABHAENGIGKEIT
-------------
`cryptography` (X25519, ChaCha20-Poly1305, AES-GCM). Damit bricht die
0-Abhaengigkeits-Zusage -- bewusst, und nur fuer diese private Fassung.
Im oeffentlichen AHPT bleibt `krypto: "keine"` der Grundfall.
"""

import hashlib
import hmac
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

HASHLEN = 32
DHLEN = 32
TAGLEN = 16


class KryptoFehler(Exception):
    """Etwas stimmte nicht -- und zwar ohne zu sagen, was.

    Absichtlich wortkarg: Eine Fehlermeldung, die zwischen "falscher
    Schluessel", "veraendertes Geheimnis" und "falsche Laenge"
    unterscheidet, ist ein Auskunftsdienst fuer den, der es versucht.
    """


# --------------------------------------------------------------- Bausteine

def _oeffentlich(privat: bytes) -> bytes:
    """Oeffentlicher Teil eines X25519-Schluessels, roh (32 Bytes)."""
    return (X25519PrivateKey.from_private_bytes(privat)
            .public_key()
            .public_bytes(serialization.Encoding.Raw,
                          serialization.PublicFormat.Raw))


def schluesselpaar():
    """Neues X25519-Paar. Rueckgabe: (privat, oeffentlich), je 32 Bytes."""
    p = os.urandom(32)
    return p, _oeffentlich(p)


def _dh(privat: bytes, oeffentlich: bytes) -> bytes:
    try:
        return (X25519PrivateKey.from_private_bytes(privat)
                .exchange(X25519PublicKey.from_public_bytes(oeffentlich)))
    except Exception:
        raise KryptoFehler('Schluesselaustausch fehlgeschlagen')


def _hmac(schluessel: bytes, daten: bytes) -> bytes:
    return hmac.new(schluessel, daten, hashlib.sha256).digest()


def _hkdf(ck: bytes, ikm: bytes, anzahl: int):
    """Die HKDF-Variante der NOISE-Spezifikation.

    ACHTUNG: Das ist NICHT `cryptography.hazmat.primitives.kdf.hkdf.HKDF`.
    Noise verkettet HMAC-Aufrufe in einer eigenen Form (jeder Ausgang geht
    in den naechsten ein), ohne `info`-Feld. Wer hier die fertige
    HKDF-Klasse einsetzt, bekommt andere Schluessel -- und merkt es erst,
    wenn die Testvektoren nicht mehr stimmen. Genau deshalb gibt es die
    Testvektoren.
    """
    temp = _hmac(ck, ikm)
    o1 = _hmac(temp, b'\x01')
    if anzahl == 1:
        return (o1,)
    o2 = _hmac(temp, o1 + b'\x02')
    if anzahl == 2:
        return (o1, o2)
    o3 = _hmac(temp, o2 + b'\x03')
    return (o1, o2, o3)


class CipherState:
    """Ein Schluessel und ein Zaehler. Mehr ist es nicht."""

    def __init__(self, aead='ChaChaPoly'):
        self.k = None
        self.n = 0
        self.aead = aead

    def InitializeKey(self, k):
        self.k = k
        self.n = 0

    def HasKey(self):
        return self.k is not None

    def _nonce(self) -> bytes:
        """96 Bit: 32 Bit Null, dann der Zaehler.

        DIE BYTEREIHENFOLGE UNTERSCHEIDET SICH JE VERFAHREN, und das ist
        keine Schlamperei der Spezifikation, sondern folgt den jeweiligen
        Originalarbeiten:

            ChaChaPoly -> little endian
            AESGCM     -> big endian

        Wer beides gleich behandelt, bekommt ein Verfahren, das mit sich
        selbst funktioniert und mit keiner anderen Umsetzung. Der
        Testvektor-Abgleich faellt genau darueber.
        """
        zaehler = self.n.to_bytes(8, 'little' if self.aead == 'ChaChaPoly' else 'big')
        return b'\x00' * 4 + zaehler

    def _werkzeug(self):
        return ChaCha20Poly1305(self.k) if self.aead == 'ChaChaPoly' else AESGCM(self.k)

    def EncryptWithAd(self, ad: bytes, klartext: bytes) -> bytes:
        if self.k is None:
            return klartext
        c = self._werkzeug().encrypt(self._nonce(), klartext, ad)
        self.n += 1
        return c

    def DecryptWithAd(self, ad: bytes, geheim: bytes) -> bytes:
        if self.k is None:
            return geheim
        try:
            p = self._werkzeug().decrypt(self._nonce(), geheim, ad)
        except Exception:
            raise KryptoFehler('Entschluesselung fehlgeschlagen')
        self.n += 1
        return p


class SymmetricState:
    """Kettenschluessel und laufender Hash ueber alles bisher Gesagte."""

    def __init__(self, protokoll_name: str, aead: str):
        name = protokoll_name.encode('ascii')
        # Ist der Name hoechstens so lang wie der Hash, wird er mit Nullen
        # aufgefuellt statt gehasht. Bei uns ist er exakt 32 Zeichen lang.
        if len(name) <= HASHLEN:
            self.h = name + b'\x00' * (HASHLEN - len(name))
        else:
            self.h = hashlib.sha256(name).digest()
        self.ck = self.h
        self.cs = CipherState(aead)

    def MixKey(self, ikm: bytes):
        self.ck, temp_k = _hkdf(self.ck, ikm, 2)
        self.cs.InitializeKey(temp_k)

    def MixHash(self, daten: bytes):
        self.h = hashlib.sha256(self.h + daten).digest()

    def EncryptAndHash(self, klartext: bytes) -> bytes:
        c = self.cs.EncryptWithAd(self.h, klartext)
        self.MixHash(c)
        return c

    def DecryptAndHash(self, geheim: bytes) -> bytes:
        # Gehasht wird der GEHEIMTEXT, nicht der Klartext -- sonst haetten
        # beide Seiten verschiedene Hashes, sobald ein Feld unverschluesselt
        # bleibt.
        p = self.cs.DecryptWithAd(self.h, geheim)
        self.MixHash(geheim)
        return p

    def Split(self):
        t1, t2 = _hkdf(self.ck, b'', 2)
        c1, c2 = CipherState(self.cs.aead), CipherState(self.cs.aead)
        c1.InitializeKey(t1)
        c2.InitializeKey(t2)
        return c1, c2


# ------------------------------------------------------------- Handshake

class HandshakeIK:
    """Der Handshake IK, beide Seiten.

    Verwendung beim Initiator (Client):
        h = HandshakeIK(True, prologue, s_privat, rs=agent_oeffentlich)
        nachricht1 = h.schreibe_nachricht1(frage_bytes)
        antwort    = h.lies_nachricht2(nachricht2)

    Beim Antwortenden (Agent):
        h = HandshakeIK(False, prologue, s_privat)
        frage      = h.lies_nachricht1(nachricht1)
        nachricht2 = h.schreibe_nachricht2(antwort_bytes)

    Danach liefert `h.transportschluessel()` das Paar fuer weitere
    Nachrichten -- AHPT braucht es nicht, weil je Vorgang genau eine Frage
    und eine Antwort reisen. Es steht trotzdem da, weil die Spezifikation
    es vorsieht und ein Weglassen spaeter jemanden ratlos zuruecklassen
    wuerde.
    """

    def __init__(self, initiator: bool, prologue: bytes, s: bytes,
                 rs: bytes = None, e: bytes = None, aead: str = 'ChaChaPoly'):
        if aead not in ('ChaChaPoly', 'AESGCM'):
            raise KryptoFehler('Unbekanntes Verfahren: %r' % (aead,))
        self.ss = SymmetricState('Noise_IK_25519_%s_SHA256' % aead, aead)
        self.ss.MixHash(prologue)
        self.initiator = initiator
        self.s = s
        self.e = e                      # nur fuer Testvektoren vorgegeben
        self.rs = rs
        self.re = None
        self.fertig = False

        # Vornachricht "<- s": Der statische Schluessel des Antwortenden ist
        # dem Initiator schon bekannt. Beide Seiten muessen ihn in den Hash
        # nehmen, sonst laufen die Zustaende auseinander.
        if initiator:
            if rs is None:
                raise KryptoFehler('Initiator ohne Schluessel des Gegenuebers')
            self.ss.MixHash(rs)
        else:
            self.ss.MixHash(_oeffentlich(s))

    # ------------------------------------------------ -> e, es, s, ss

    def schreibe_nachricht1(self, nutzlast: bytes) -> bytes:
        if not self.initiator:
            raise KryptoFehler('Nachricht 1 schreibt der Initiator')
        if self.e is None:
            self.e = os.urandom(32)
        e_pub = _oeffentlich(self.e)
        puffer = bytearray(e_pub)
        self.ss.MixHash(e_pub)                       # e
        self.ss.MixKey(_dh(self.e, self.rs))         # es
        puffer += self.ss.EncryptAndHash(_oeffentlich(self.s))   # s
        self.ss.MixKey(_dh(self.s, self.rs))         # ss
        puffer += self.ss.EncryptAndHash(nutzlast)
        return bytes(puffer)

    def lies_nachricht1(self, nachricht: bytes) -> bytes:
        if self.initiator:
            raise KryptoFehler('Nachricht 1 liest der Antwortende')
        if len(nachricht) < DHLEN + DHLEN + TAGLEN:
            raise KryptoFehler('Nachricht 1 zu kurz')
        self.re = nachricht[:DHLEN]
        self.ss.MixHash(self.re)                     # e
        self.ss.MixKey(_dh(self.s, self.re))         # es  (hier: DH(s, re))
        rest = nachricht[DHLEN:]
        self.rs = self.ss.DecryptAndHash(rest[:DHLEN + TAGLEN])  # s
        self.ss.MixKey(_dh(self.s, self.rs))         # ss
        return self.ss.DecryptAndHash(rest[DHLEN + TAGLEN:])

    # ---------------------------------------------------- <- e, ee, se

    def schreibe_nachricht2(self, nutzlast: bytes) -> bytes:
        if self.initiator:
            raise KryptoFehler('Nachricht 2 schreibt der Antwortende')
        if self.e is None:
            self.e = os.urandom(32)
        e_pub = _oeffentlich(self.e)
        puffer = bytearray(e_pub)
        self.ss.MixHash(e_pub)                       # e
        self.ss.MixKey(_dh(self.e, self.re))         # ee
        self.ss.MixKey(_dh(self.e, self.rs))         # se  (hier: DH(e, rs))
        puffer += self.ss.EncryptAndHash(nutzlast)
        self.fertig = True
        return bytes(puffer)

    def lies_nachricht2(self, nachricht: bytes) -> bytes:
        if not self.initiator:
            raise KryptoFehler('Nachricht 2 liest der Initiator')
        if len(nachricht) < DHLEN + TAGLEN:
            raise KryptoFehler('Nachricht 2 zu kurz')
        self.re = nachricht[:DHLEN]
        self.ss.MixHash(self.re)                     # e
        self.ss.MixKey(_dh(self.e, self.re))         # ee
        self.ss.MixKey(_dh(self.s, self.re))         # se  (hier: DH(s, re))
        klartext = self.ss.DecryptAndHash(nachricht[DHLEN:])
        self.fertig = True
        return klartext

    # ------------------------------------------------------- Danach

    def handshake_hash(self) -> bytes:
        return self.ss.h

    def transportschluessel(self):
        if not self.fertig:
            raise KryptoFehler('Handshake noch nicht abgeschlossen')
        return self.ss.Split()


# -------------------------------------------------- Wiederholungsschutz

class Wiederholungsschutz:
    """Merkt sich gesehene fluechtige Schluessel und weist Wiederholungen ab.

    WARUM DAS NOETIG IST: Die erste Handshake-Nachricht traegt bei IK
    bereits Nutzlast -- das spart eine Runde durch den Webspace und ist der
    Grund, warum Verschluesselung hier nichts an Geschwindigkeit kostet.
    Der Preis ist, dass diese Nachricht WIEDERHOLBAR ist: Wer sie abfaengt,
    kann sie erneut einspielen. Kryptografisch ist sie einwandfrei -- sie
    IST ja echt.

    Dagegen hilft kein Schluessel, sondern ein Gedaechtnis. Der fluechtige
    Schluessel ist je Vorgang neu und damit die natuerliche Kennung.

    Das Zeitfenster entspricht der Lebensdauer einer Marke: Was der
    Vermittler ohnehin verfallen laesst, muss hier nicht laenger erinnert
    werden. Und der Deckel verhindert, dass ein Angreifer den Speicher des
    Agenten volllaufen laesst -- ein Gedaechtnis ohne Grenze ist selbst ein
    Angriffsziel.
    """

    def __init__(self, fenster=120, deckel=10000, uhr=None):
        self.fenster = fenster
        self.deckel = deckel
        self._uhr = uhr or (lambda: __import__('time').time())
        self._gesehen = {}

    def _kehre(self, jetzt):
        alt = [k for k, t in self._gesehen.items() if jetzt - t > self.fenster]
        for k in alt:
            del self._gesehen[k]

    def neu(self, kennung: bytes) -> bool:
        """True, wenn noch nie gesehen. Merkt sie sich dabei."""
        jetzt = self._uhr()
        self._kehre(jetzt)
        if kennung in self._gesehen:
            return False
        if len(self._gesehen) >= self.deckel:
            # Voll und nichts zu raeumen: dann lieber ABWEISEN als vergessen.
            # Wer vergisst, laesst Wiederholungen wieder durch -- und genau
            # das waere das Ziel eines Angreifers, der das Gedaechtnis flutet.
            return False
        self._gesehen[kennung] = jetzt
        return True

    def __len__(self):
        return len(self._gesehen)


# --------------------------------------------------- Schluesselverwaltung

def lies_privat(pfad: str) -> bytes:
    """Privaten Schluessel aus einer Datei lesen (64 Hexzeichen)."""
    with open(pfad, 'r', encoding='utf-8') as f:
        roh = f.read().strip()
    try:
        b = bytes.fromhex(roh)
    except ValueError:
        raise KryptoFehler('%s enthaelt keinen Schluessel in Hexform' % pfad)
    if len(b) != 32:
        raise KryptoFehler('%s: %d Bytes statt 32' % (pfad, len(b)))
    return b


def schreibe_privat(pfad: str, privat: bytes):
    """Privaten Schluessel ablegen -- nur fuer den Eigentuemer lesbar.

    Die Rechte werden VOR dem Schreiben gesetzt, nicht danach: Sonst liegt
    der Schluessel fuer einen Augenblick offen da, und ein Augenblick
    genuegt.
    """
    fd = os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(privat.hex() + '\n')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(
        description='Schluessel fuer AHPT Cloud erzeugen und ansehen.')
    ap.add_argument('--erzeuge', metavar='DATEI',
                    help='neues Schluesselpaar, privater Teil in DATEI')
    ap.add_argument('--zeige', metavar='DATEI',
                    help='oeffentlichen Teil zu einem privaten Schluessel')
    a = ap.parse_args()

    if a.erzeuge:
        if os.path.exists(a.erzeuge):
            print('ABBRUCH: %s gibt es schon.' % a.erzeuge)
            print('         Ein Schluessel wird nicht versehentlich ersetzt --')
            print('         danach kaeme kein Client mehr durch.')
            raise SystemExit(2)
        p, oe = schluesselpaar()
        schreibe_privat(a.erzeuge, p)
        print('Privater Schluessel: %s   (nur fuer dich lesbar)' % a.erzeuge)
        print('')
        print('Oeffentlicher Schluessel -- dieser Wert gehoert in die')
        print('Konfiguration des Clients. Von HAND uebertragen, niemals')
        print('ueber den Webspace: was dort liegt, kann der Hoster')
        print('austauschen, und genau das soll die Verschluesselung')
        print('verhindern.')
        print('')
        print('    %s' % oe.hex())
    elif a.zeige:
        print(_oeffentlich(lies_privat(a.zeige)).hex())
    else:
        ap.print_help()
