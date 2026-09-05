#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handler/datei.py -- Dateien aus einem festgelegten Ordner ausliefern

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WARUM AUSGERECHNET DIESER HANDLER
----------------------------------
Er beweist zweierlei auf einmal:

1. Dass der Kern wirklich generisch ist. `kiwix` allein bewiese nur, dass
   der Umbau nichts kaputtgemacht hat.
2. Dass die gefaehrlichste Stelle des ganzen Vorhabens beherrschbar ist.

`Zukunftsmusik.txt` benennt sie unter 3B:

    "Wenn man das Protokoll zu 'Liefere mir beliebige Datei X vom
     Heimserver' aufbohrt, muss man extrem aufpassen, dass Besucher nicht
     ploetzlich /etc/shadow, deine FritzBox-Konfiguration oder interne
     Web-Interfaces abrufen koennen."

Genau das ist dieser Handler. Deshalb steht die Pfadpruefung hier weiter
oben als die Auslieferung, hat drei voneinander unabhaengige Schranken und
den laengsten Selbsttest im Projekt.

DIE DREI SCHRANKEN
------------------
1. FORM. Der eingehende Name wird auf Bestandteile geprueft, bevor er das
   Dateisystem auch nur beruehrt: kein fuehrender Schraegstrich, kein
   Rueckwaertsschraegstrich, kein `.` und kein `..` als Bestandteil, keine
   versteckten Namen, keine Steuerzeichen, begrenzte Laenge.
2. LAGE. Der aufgeloeste echte Pfad (`realpath`, also mit verfolgten
   Verknuepfungen) muss innerhalb der aufgeloesten Wurzel liegen. Das faengt
   ab, was die Form nicht sieht: eine symbolische Verknuepfung im Ordner,
   die nach draussen zeigt.
3. ART. Nur gewoehnliche Dateien. Kein Geraet, keine Warteschlange, kein
   Ordner. Und, wenn konfiguriert, nur erlaubte Endungen.

Keine der drei genuegt allein. Schranke 1 sieht keine Verknuepfung,
Schranke 2 sieht keine versteckte Datei innerhalb der Wurzel, Schranke 3
sieht keinen Pfad.

WAS ES HIER NICHT GIBT
----------------------
Kein Schreiben, kein Loeschen, kein Umbenennen. Der Weg geht in eine
Richtung. Ein Besucher, der Bytes auf den Heimserver legen kann, ist ein
anderes Sicherheitsmodell -- und keines, das nebenbei entsteht.
"""

import json
import os
import re

from handler import Handler, KonfigFehler, bytes_antwort, text_antwort, nichts

MAX_NAME       = 255        # Zeichen je Bestandteil
MAX_PFAD       = 1024       # Zeichen gesamt
MAX_EINTRAEGE  = 500        # Zeilen einer Auflistung

_VERBOTEN = re.compile(r'[\x00-\x1f\x7f]')


class DateiHandler(Handler):

    ART = 'datei'
    AKTIONEN = frozenset(('liste', 'hole'))

    def __init__(self, konfig):
        super().__init__(konfig)

        wurzel = konfig.get('wurzel')
        if not isinstance(wurzel, str) or not wurzel:
            raise KonfigFehler('Dienst "%s": `wurzel` fehlt.' % self.name)
        wurzel = os.path.realpath(os.path.expanduser(wurzel))
        if not os.path.isdir(wurzel):
            raise KonfigFehler('Dienst "%s": `wurzel` %r ist kein Ordner.\n'
                               '         Beim Start geprueft, nicht beim ersten '
                               'Abruf -- ein Dienst, der\n'
                               '         erst unter Last auffaellt, faellt zur '
                               'schlechtesten Zeit auf.'
                               % (self.name, wurzel))
        # Eine Wurzel, die auf / oder das Benutzerverzeichnis zeigt, ist fast
        # immer ein Versehen und im Ernstfall die Veroeffentlichung des halben
        # Rechners. Lieber laut abbrechen als still ausliefern.
        heikel = {os.path.realpath(os.sep), os.path.realpath(os.path.expanduser('~'))}
        if wurzel in heikel:
            raise KonfigFehler(
                'Dienst "%s": `wurzel` zeigt auf %r.\n'
                '         Das gaebe den halben Rechner heraus. Wenn das wirklich\n'
                '         gewollt ist, muss ein Unterordner angelegt werden --\n'
                '         eine Absicht soll man aufschreiben muessen.'
                % (self.name, wurzel))
        self.wurzel = wurzel

        self.max_bytes = int(konfig.get('max_bytes', 5 * 1024 * 1024))
        if not 1 <= self.max_bytes <= 64 * 1024 * 1024:
            raise KonfigFehler('Dienst "%s": max_bytes unplausibel.' % self.name)

        endungen = konfig.get('endungen', [])
        if not isinstance(endungen, list) \
                or any(not isinstance(e, str) for e in endungen):
            raise KonfigFehler('Dienst "%s": `endungen` muss eine Liste von '
                               'Zeichenketten sein.' % self.name)
        # Leere Liste heisst ausdruecklich "alles, was die drei Schranken
        # passiert". Das ist erlaubt, aber es soll niemand versehentlich
        # dorthin geraten -- deshalb sagt der Kern es beim Start laut.
        self.endungen = {e.lower().lstrip('.') for e in endungen}

    def bereit(self):
        if not os.path.isdir(self.wurzel):
            return False, 'Wurzel verschwunden: %s' % self.wurzel
        offen = 'alle Endungen' if not self.endungen \
                else '%d Endungen' % len(self.endungen)
        return True, '%s   (%s, bis %d KiB)' % (
            self.wurzel, offen, self.max_bytes // 1024)

    # ------------------------------------------------------ Pfadpruefung

    def _pfad_erlaubt(self, roh):
        """Die drei Schranken. Rueckgabe: echter absoluter Pfad oder None.

        Gibt bewusst NICHT zurueck, WELCHE Schranke gegriffen hat. Der
        Besucher soll aus der Antwort nicht ablesen koennen, ob eine Datei
        existiert, versteckt ist oder ausserhalb liegt.
        """
        # --- Schranke 1: Form. Vor jeder Beruehrung des Dateisystems.
        if not isinstance(roh, str) or not roh or len(roh) > MAX_PFAD:
            return None
        if _VERBOTEN.search(roh):
            return None
        if roh.startswith('/') or roh.startswith('\\') or '\\' in roh:
            return None
        # Ein Laufwerksbuchstabe oder ein Doppelpunkt hat in einem relativen
        # Namen nichts zu suchen -- auf Windows waere "C:passwd" sonst ein
        # Pfad relativ zum aktuellen Ordner von Laufwerk C.
        if ':' in roh:
            return None
        teile = roh.split('/')
        for t in teile:
            if t in ('', '.', '..'):
                return None
            if t.startswith('.'):        # .git, .env, .ssh, .htaccess
                return None
            if len(t) > MAX_NAME:
                return None

        # --- Schranke 2: Lage. Verknuepfungen werden verfolgt.
        ziel = os.path.realpath(os.path.join(self.wurzel, *teile))
        try:
            if os.path.commonpath([ziel, self.wurzel]) != self.wurzel:
                return None
        except ValueError:
            return None                  # verschiedene Laufwerke
        if ziel == self.wurzel:
            return None
        return ziel

    # ------------------------------------------------------- Bearbeiten

    def bearbeite(self, aktion, daten):
        if not isinstance(daten, dict):
            return nichts('daten: Objekt erwartet')

        if aktion == 'liste':
            # Ein leerer Pfad heisst: die Wurzel selbst.
            roh = daten.get('pfad', '')
            if roh in ('', None):
                ordner = self.wurzel
            else:
                ordner = self._pfad_erlaubt(roh)
                if ordner is None or not os.path.isdir(ordner):
                    return nichts('pfad abgewiesen')
            eintraege = []
            try:
                for name in sorted(os.listdir(ordner))[:MAX_EINTRAEGE]:
                    if name.startswith('.'):
                        continue         # versteckt bleibt versteckt
                    voll = os.path.join(ordner, name)
                    # Schranke 2 auch beim Auflisten: eine Verknuepfung, die
                    # nach draussen zeigt, wird gar nicht erst genannt.
                    echt = os.path.realpath(voll)
                    try:
                        if os.path.commonpath([echt, self.wurzel]) != self.wurzel:
                            continue
                    except ValueError:
                        continue
                    if os.path.isdir(echt):
                        eintraege.append({'name': name, 'art': 'ordner'})
                    elif os.path.isfile(echt) and self._endung_ok(name):
                        eintraege.append({'name': name, 'art': 'datei',
                                          'bytes': os.path.getsize(echt)})
            except OSError as e:
                return nichts('nicht lesbar: %s' % e.strerror)
            return text_antwort(
                json.dumps({'eintraege': eintraege}, ensure_ascii=False),
                titel=roh or '/')

        if aktion == 'hole':
            ziel = self._pfad_erlaubt(daten.get('pfad'))
            if ziel is None:
                return nichts('pfad abgewiesen')

            # --- Schranke 3: Art.
            if not os.path.isfile(ziel):
                return nichts('keine gewoehnliche Datei')
            if not self._endung_ok(os.path.basename(ziel)):
                return nichts('endung nicht freigegeben')
            try:
                groesse = os.path.getsize(ziel)
            except OSError:
                return nichts('nicht lesbar')
            if groesse > self.max_bytes:
                return nichts('zu gross: %d Bytes, erlaubt sind %d'
                              % (groesse, self.max_bytes))
            try:
                with open(ziel, 'rb') as f:
                    roh = f.read(self.max_bytes + 1)
            except OSError as e:
                return nichts('nicht lesbar: %s' % e.strerror)
            if len(roh) > self.max_bytes:
                return nichts('zu gross')

            name = os.path.basename(ziel)
            # Text bleibt Text -- das spart ein Drittel Uebertragung und macht
            # die Antwort im Browser ohne Umweg lesbar. Alles andere geht als
            # Bytes hinaus, nie als HTML.
            if self._endung_ok(name) and name.lower().rsplit('.', 1)[-1] in (
                    'txt', 'md', 'csv', 'json', 'log', 'ini', 'toml', 'yaml'):
                try:
                    return text_antwort(roh.decode('utf-8'), titel=name)
                except UnicodeDecodeError:
                    pass
            return bytes_antwort(roh, titel=name)

        return nichts('unbekannte Aktion: %s' % aktion)

    def _endung_ok(self, name):
        if not self.endungen:
            return True
        if '.' not in name:
            return False
        return name.lower().rsplit('.', 1)[-1] in self.endungen

    # ------------------------------------------------------- Selbsttest

    def selbsttest(self):
        """Baut einen kleinen Baum in einem Wegwerfordner und greift ihn an.

        Ohne Netz und ohne den echten Freigabeordner: Ein Selbsttest, der
        die Betriebsdaten braucht, wird nicht gefahren, und einer, der sie
        veraendern koennte, darf nicht gefahren werden.
        """
        import shutil
        import tempfile

        ergebnis = []
        basis = tempfile.mkdtemp(prefix='ahpt_selbsttest_')
        try:
            wurzel = os.path.join(basis, 'freigabe')
            os.makedirs(os.path.join(wurzel, 'unter'))
            with open(os.path.join(wurzel, 'gut.txt'), 'w') as f:
                f.write('harmlos')
            with open(os.path.join(wurzel, 'unter', 'tief.txt'), 'w') as f:
                f.write('auch harmlos')
            with open(os.path.join(wurzel, '.geheim'), 'w') as f:
                f.write('darf nicht heraus')
            with open(os.path.join(basis, 'draussen.txt'), 'w') as f:
                f.write('liegt AUSSERHALB der Wurzel')

            probe = DateiHandler({'name': 'probe', 'wurzel': wurzel})

            faelle = [
                ('gueltige Datei',            'gut.txt',                  True),
                ('gueltig, Unterordner',      'unter/tief.txt',           True),
                ('Pfadwanderung',             '../draussen.txt',          False),
                ('Pfadwanderung, tief',       'unter/../../draussen.txt', False),
                ('absoluter Pfad',            '/etc/passwd',              False),
                ('Windows-Pfad',              'C:\\Windows\\win.ini',     False),
                ('Rueckwaertsschraegstrich',  'unter\\tief.txt',          False),
                ('Laufwerksbuchstabe',        'C:passwd',                 False),
                ('versteckte Datei',          '.geheim',                  False),
                ('versteckt im Unterordner',  'unter/.geheim',            False),
                ('Punkt als Bestandteil',     './gut.txt',                False),
                ('leerer Bestandteil',        'unter//tief.txt',          False),
                ('Steuerzeichen',             'gut\x00.txt',              False),
                ('Zeilenumbruch',             'gut\n.txt',                False),
                ('leerer Pfad',               '',                         False),
                ('kein Text',                 None,                       False),
                ('Zahl statt Pfad',           12345,                      False),
                ('die Wurzel selbst',         '.',                        False),
                ('zu langer Bestandteil',     'a' * (MAX_NAME + 1),       False),
            ]
            for beschreibung, eingabe, soll in faelle:
                ist = probe._pfad_erlaubt(eingabe) is not None
                ergebnis.append(('pfad: ' + beschreibung, ist == soll,
                                 '' if ist == soll else
                                 'erwartet %s, war %s' % (soll, ist)))

            # Schranke 2 gegen eine Verknuepfung nach draussen. Auf Windows
            # ohne Entwicklermodus nicht anlegbar -- dann wird der Fall
            # UEBERSPRUNGEN und das auch gesagt. Ein Test, der still
            # ausfaellt, meldet Erfolg, wo keiner geprueft wurde.
            verkn = os.path.join(wurzel, 'raus.txt')
            try:
                os.symlink(os.path.join(basis, 'draussen.txt'), verkn)
            except (OSError, NotImplementedError, AttributeError):
                ergebnis.append(('verknuepfung nach draussen', True,
                                 'UEBERSPRUNGEN -- hier nicht anlegbar'))
            else:
                ist = probe._pfad_erlaubt('raus.txt') is not None
                ergebnis.append(('verknuepfung nach draussen', ist is False,
                                 '' if ist is False
                                 else 'FOLGT der Verknuepfung nach draussen'))
                a = probe.bearbeite('liste', {})
                ergebnis.append((
                    'verknuepfung wird nicht aufgelistet',
                    'raus.txt' not in a.get('inhalt', ''), ''))

            # Endungs-Weissliste.
            eng = DateiHandler({'name': 'eng', 'wurzel': wurzel,
                                'endungen': ['pdf']})
            ergebnis.append(('endung: pdf erlaubt', eng._endung_ok('x.pdf'), ''))
            ergebnis.append(('endung: txt gesperrt',
                             not eng._endung_ok('x.txt'), ''))
            ergebnis.append(('endung: ohne Punkt gesperrt',
                             not eng._endung_ok('x'), ''))
            ergebnis.append(('endung: Grossschreibung zaehlt nicht',
                             eng._endung_ok('X.PDF'), ''))
            ergebnis.append(('endung: gesperrte Datei wird nicht geliefert',
                             eng.bearbeite('hole', {'pfad': 'gut.txt'})
                             ['gefunden'] is False, ''))

            # Und der Gutfall muss durchgehen -- sonst waere eine Schranke,
            # die alles abweist, "bestanden".
            a = probe.bearbeite('hole', {'pfad': 'gut.txt'})
            ergebnis.append(('gutfall liefert Inhalt',
                             a['gefunden'] and a['inhalt'] == 'harmlos', ''))
            a = probe.bearbeite('hole', {'pfad': '../draussen.txt'})
            ergebnis.append(('angriff liefert nichts',
                             a['gefunden'] is False, ''))

            # Eine unbekannte Wurzel muss beim Start auffallen, nicht spaeter.
            try:
                DateiHandler({'name': 'x', 'wurzel': os.path.join(basis, 'gibtsnicht')})
                ergebnis.append(('fehlende Wurzel bricht ab', False,
                                 'wurde klaglos angenommen'))
            except KonfigFehler:
                ergebnis.append(('fehlende Wurzel bricht ab', True, ''))
        finally:
            shutil.rmtree(basis, ignore_errors=True)

        return ergebnis


HANDLER = DateiHandler
