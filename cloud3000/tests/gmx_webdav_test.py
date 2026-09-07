#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gmx_webdav_test.py -- misst einen WebDAV-Speicher als AHPT-Transportweg

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

Dieses Werkzeug hat die Zahlen erzeugt, die in README.md unter
"Messungen" stehen (GMX, 06.09.2026). Es braucht ein ECHTES Konto und
laeuft ohne keines -- wer nur pruefen will, ob der Code eine Antwort
richtig versteht, nimmt `ahpt/tests/pruefe_transport.py`; das laeuft
ohne Netz.

Braucht `requests` (nicht stdlib):  pip install requests
Der uebrige Quelltext kommt ohne aus; hier ist es bewusst geblieben,
weil dieses Werkzeug die veroeffentlichten Zahlen erzeugt hat und ein
Umbau sie zu Zahlen eines anderen Werkzeugs machen wuerde.

VOR DEM ERSTEN LAUF:  SICHERHEIT.md, Abschnitte 3.6 und 3.7 -- eigenes
Konto, anwendungsspezifisches Passwort, AGB-Graubereich.

Aufruf:

    export AHPT_WEBDAV_BASIS="https://webdav.mc.gmx.net"
    export AHPT_WEBDAV_BENUTZER="konto@example.net"
    export AHPT_WEBDAV_PASSWORT_DATEI="~/.ahpt/webdav.passwort"
    python3 gmx_webdav_test.py [1|2|3|4|alle]

Die Passwortdatei ist eine Zeile, sonst nichts -- wie bei allen
Geheimnis-Dateien in diesem Projekt. Das Passwort wird nie ausgegeben
und nie protokolliert.

Die Messung schreibt in `/ahpt_messung*.txt` im Wurzelverzeichnis des
Speichers und raeumt hinter sich auf.
"""

import os
import statistics
import sys
import time

import requests

BASIS = os.environ.get("AHPT_WEBDAV_BASIS", "").rstrip("/")
BENUTZER = os.environ.get("AHPT_WEBDAV_BENUTZER", "")
GEHEIMNIS_DATEI = os.path.expanduser(
    os.environ.get("AHPT_WEBDAV_PASSWORT_DATEI", ""))
TESTPFAD = "/ahpt_messung.txt"
GROSS_PFAD = "/ahpt_messung_gross.bin"

if not (BASIS and BENUTZER and GEHEIMNIS_DATEI):
    sys.exit("ABBRUCH: AHPT_WEBDAV_BASIS, AHPT_WEBDAV_BENUTZER und "
             "AHPT_WEBDAV_PASSWORT_DATEI muessen gesetzt sein.\n"
             "         Siehe Kopf dieser Datei.")
if not BASIS.startswith("https://"):
    # Basic-Auth traegt das Passwort in JEDER Anfrage mit -- ueber http
    # gaebe dieser Testlauf es preis, und mit ihm in aller Regel das
    # dazugehoerige Postfach. Siehe SICHERHEIT.md 3.6.
    sys.exit("ABBRUCH: Nur https. Ueber http reist das Passwort offen mit.")

try:
    with open(GEHEIMNIS_DATEI, encoding="utf-8") as f:
        PASSWORT = f.read().strip()
except OSError as e:
    sys.exit("ABBRUCH: Passwortdatei nicht lesbar: %s" % e)
if not PASSWORT:
    sys.exit("ABBRUCH: Passwortdatei ist leer: %s" % GEHEIMNIS_DATEI)
AUTH = (BENUTZER, PASSWORT)


def schreibe(pfad, inhalt):
    return requests.put(BASIS + pfad, data=inhalt, auth=AUTH, timeout=30)


def lese(pfad):
    return requests.get(BASIS + pfad, auth=AUTH, timeout=30)


def loesche(pfad):
    return requests.delete(BASIS + pfad, auth=AUTH, timeout=30)


def phase1_grundfunktion():
    print("=== Phase 1: Grundfunktion (schreiben, lesen, loeschen) ===")
    inhalt = b"AHPT ueber WebDAV -- erster Test, " + str(time.time()).encode()

    t0 = time.time()
    r = schreibe(TESTPFAD, inhalt)
    t_schreiben = time.time() - t0
    print(f"  PUT   HTTP {r.status_code}  {t_schreiben:.2f}s")
    if r.status_code not in (200, 201, 204):
        print("  ABBRUCH: Schreiben fehlgeschlagen:", r.text[:200])
        return False

    t0 = time.time()
    r = lese(TESTPFAD)
    t_lesen = time.time() - t0
    print(f"  GET   HTTP {r.status_code}  {t_lesen:.2f}s")
    stimmt = r.content == inhalt
    print(f"  Inhalt korrekt: {stimmt}")

    t0 = time.time()
    r = loesche(TESTPFAD)
    t_loeschen = time.time() - t0
    print(f"  DELETE HTTP {r.status_code}  {t_loeschen:.2f}s")

    return stimmt


def phase2_wiederholte_umlaeufe(n=10):
    print(f"\n=== Phase 2: {n} wiederholte Schreiben+Lesen-Umlaeufe ===")
    zeiten_schreiben = []
    zeiten_lesen = []
    fehler = 0
    for i in range(n):
        inhalt = f"Umlauf {i}, {time.time()}".encode()
        t0 = time.time()
        r1 = schreibe(TESTPFAD, inhalt)
        zeiten_schreiben.append(time.time() - t0)
        t0 = time.time()
        r2 = lese(TESTPFAD)
        zeiten_lesen.append(time.time() - t0)
        ok = r1.status_code in (200, 201, 204) and r2.content == inhalt
        if not ok:
            fehler += 1
            print(f"  Umlauf {i}: FEHLER -- PUT {r1.status_code}, "
                  f"GET {r2.status_code}, Inhalt korrekt: {r2.content == inhalt}")
        time.sleep(0.3)
    loesche(TESTPFAD)
    print(f"  Schreiben: min {min(zeiten_schreiben):.2f}s  "
          f"mittel {statistics.mean(zeiten_schreiben):.2f}s  "
          f"max {max(zeiten_schreiben):.2f}s")
    print(f"  Lesen:     min {min(zeiten_lesen):.2f}s  "
          f"mittel {statistics.mean(zeiten_lesen):.2f}s  "
          f"max {max(zeiten_lesen):.2f}s")
    print(f"  Fehler: {fehler}/{n}")


def phase3_schnelles_pollen(dauer_s=90, abstand_s=1.0):
    print(f"\n=== Phase 3: Pollen alle {abstand_s}s fuer {dauer_s}s "
          f"(so wie AHPT es taete) ===")
    schreibe(TESTPFAD, b"vorhanden")
    ende = time.time() + dauer_s
    anzahl = 0
    fehler = 0
    codes = {}
    zeiten = []
    while time.time() < ende:
        t0 = time.time()
        try:
            r = lese(TESTPFAD)
            dt = time.time() - t0
            zeiten.append(dt)
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
            if r.status_code != 200:
                fehler += 1
        except Exception as e:
            fehler += 1
            codes[f"Ausnahme:{type(e).__name__}"] = (
                codes.get(f"Ausnahme:{type(e).__name__}", 0) + 1)
        anzahl += 1
        time.sleep(max(0, abstand_s - (time.time() - t0)))
    loesche(TESTPFAD)
    print(f"  {anzahl} Abrufe, {fehler} Fehler")
    print(f"  Antwortcodes: {codes}")
    if zeiten:
        print(f"  Antwortzeit: min {min(zeiten):.2f}s  "
              f"mittel {statistics.mean(zeiten):.2f}s  max {max(zeiten):.2f}s")


def phase4_groessere_datei(mb=2):
    print(f"\n=== Phase 4: {mb} MB in einem Stueck ===")
    inhalt = os.urandom(mb * 1024 * 1024)
    t0 = time.time()
    r = schreibe(GROSS_PFAD, inhalt)
    t_schreiben = time.time() - t0
    print(f"  PUT ({mb} MB)  HTTP {r.status_code}  {t_schreiben:.1f}s")
    t0 = time.time()
    r2 = lese(GROSS_PFAD)
    t_lesen = time.time() - t0
    print(f"  GET ({mb} MB)  HTTP {r2.status_code}  {t_lesen:.1f}s")
    print(f"  Inhalt korrekt: {r2.content == inhalt}")
    loesche(GROSS_PFAD)


if __name__ == "__main__":
    stufe = sys.argv[1] if len(sys.argv) > 1 else "alle"
    if stufe in ("1", "alle"):
        if not phase1_grundfunktion():
            print("\nGrundfunktion schlaegt fehl -- weitere Phasen macht das nicht sinnvoller.")
            sys.exit(1)
    if stufe in ("2", "alle"):
        phase2_wiederholte_umlaeufe()
    if stufe in ("3", "alle"):
        phase3_schnelles_pollen()
    if stufe in ("4", "alle"):
        phase4_groessere_datei()
