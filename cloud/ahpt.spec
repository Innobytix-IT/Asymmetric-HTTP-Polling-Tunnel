# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller-Bauplan fuer die abhaengigkeitsfreie Windows-.exe.
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Manuel Person, InnoBytix-IT
#
# Bauen (im Projektordner):
#     pyinstaller ahpt.spec
# Ergebnis: dist/AHPT-Cloud.exe -- eine einzelne, fensterlose Datei.
#
# WARUM DIESE DATEIEN MITMUESSEN
# ------------------------------
# Der Assistent prueft beim Start, ob er in einem VOLLSTAENDIGEN Ordner liegt
# (relay.php, relay_agent.py, handler/datei.py, portal/index.html), und baut
# spaeter das Vermittler-Paket aus relay.php + htaccess-beispiel. Eingefroren
# liegen diese Dateien im entpackten Bundle (_MEIPASS); deshalb reisen sie als
# Daten mit. Die .py-Dateien sind zusaetzlich als importierbare Module drin --
# der Einstieg (ahpt_start.py) fuehrt sie ueber ihren Namen aus.

import os

BASIS = SPECPATH  # der Ordner dieser .spec = der Projektordner

_dateien = [
    'relay.php', 'relay-client.js',
    'htaccess-beispiel', 'htaccess-ablage-beispiel',
    'relay_agent.py', 'einrichten.py', 'miss_leitung.py', 'starten.py',
    'krypto.py', 'qr.py', 'netz.py', 'ahpt_client.py',
]
datas = [(os.path.join(BASIS, n), '.') for n in _dateien]
datas += [
    (os.path.join(BASIS, 'portal'),  'portal'),
    (os.path.join(BASIS, 'handler'), 'handler'),
]

hiddenimports = [
    'starten', 'einrichten', 'relay_agent', 'miss_leitung', 'ahpt_client',
    'netz', 'krypto', 'qr',
    'handler', 'handler.datei', 'handler.kiwix',
    'tkinter',
]

a = Analysis(
    [os.path.join(BASIS, 'ahpt_start.py')],
    pathex=[BASIS],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tests', 'pytest'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AHPT-Cloud',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,              # fensterlos: kein schwarzes Konsolenfenster
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
