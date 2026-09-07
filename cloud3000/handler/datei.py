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
Richtung -- IM OEFFENTLICHEN AHPT. Ein Besucher, der Bytes auf den
Heimserver legen kann, ist ein
anderes Sicherheitsmodell -- und keines, das nebenbei entsteht.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import time

from handler import Handler, KonfigFehler, bytes_antwort, text_antwort, nichts

MAX_NAME       = 255        # Zeichen je Bestandteil
MAX_PFAD       = 1024       # Zeichen gesamt
MAX_EINTRAEGE  = 500        # Zeilen einer Auflistung

_VERBOTEN = re.compile(r'[\x00-\x1f\x7f]')


class DateiHandler(Handler):

    ART = 'datei'
    AKTIONEN = frozenset(('liste', 'hole', 'lege', 'lege_block',
                          'neuer_ordner'))

    # Wie lange eine angefangene Uebertragung offen bleibt, bevor ihre
    # Teildatei weggeraeumt wird. Kurz genug, dass ein Abbruch nicht
    # dauerhaft Platz belegt; lang genug fuer eine lahme Mobilverbindung.
    TEIL_TTL = 1800                      # s

    # Ordner fuer angefangene Uebertragungen. Er liegt INNERHALB der Wurzel,
    # damit os.replace() am Ende ohne Dateisystemwechsel auskommt -- ein
    # Verschieben ueber Geraetegrenzen ist nicht atomar, und eine halb
    # sichtbare Datei ist genau das, was Schranke 7 verhindern soll.
    # Der Punkt am Anfang haelt ihn aus jeder Auflistung heraus.
    TEIL_ORDNER = '.ahpt-teil'

    # Groesster Ausschnitt, den ein bereichsweises Lesen liefert.
    #
    # Die Antwort darf 256 Stuecke à 49152 Zeichen lang sein, also rund
    # 12 MiB Base64 -- das sind 9 MiB Rohdaten. 4 MiB laesst Luft fuer die
    # JSON-Huelle und das Siegel und bleibt eine runde Zahl.
    LESE_BLOCK = 4 * 1024 * 1024

    # Deckel fuer GLEICHZEITIGE Bloeckuebertragungen -- unabhaengig von
    # max_bytes.
    #
    # max_bytes begrenzt eine FERTIGE Datei. Es begrenzt NICHT, wieviele
    # gleichzeitige, nie abgeschlossene Uebertragungen sich in TEIL_ORDNER
    # ansammeln -- und das ist seit `max_bytes = 0` (unbegrenzt) der
    # empfohlene Vorgabewert des Einrichtungs-Assistenten geworden, ein
    # ernstzunehmender Fall: ein zugelassenes, aber boesartiges oder
    # fehlerhaftes Geraet koennte sonst den Datentraeger fuellen, indem es
    # viele Uebertragungen beginnt und keine davon abschliesst. Weggeraeumt
    # wird eine solche Leiche erst nach TEIL_TTL, und auch das nur dann,
    # wenn ueberhaupt ein weiterer lege_block-Aufruf sie anstoesst.
    #
    # Zwei Schranken, aus verschiedenen Gruenden: TEIL_MAX_GLEICHZEITIG haelt
    # die Zahl der offenen Uebertragungen klein (schuetzt vor vielen kleinen
    # Leichen), TEIL_MAX_GESAMT deckelt den belegten Platz unabhaengig davon,
    # wie er sich auf die Uebertragungen verteilt (schuetzt vor wenigen
    # grossen). Am 03.09.2026 im Sicherheitsaudit gefunden.
    TEIL_MAX_GLEICHZEITIG = 8
    TEIL_MAX_GESAMT = 4 * 1024 * 1024 * 1024      # 4 GiB

    # TEIL_MAX_GLEICHZEITIG haelt die Zahl der Leichen klein -- aber nur
    # solange der Agent laeuft. Nach einem NEUSTART ist self._teile leer,
    # liegen gebliebene .teil-Dateien aus der Zeit davor sind es nicht (siehe
    # _teil_ordner_bytes). TEIL_MAX_GESAMT ueberlebt das, weil es vom
    # Datentraeger liest -- aber es zaehlt Bytes, nicht Dateien. Viele
    # winzige oder leere .teil-Dateien reissen TEIL_MAX_GESAMT nie, koennten
    # aber die Inodes eines kleinen Webspace-Kontingents erschoepfen, ohne
    # dass ein einziger der beiden bestehenden Deckel das bemerkt. Diese
    # Schranke schliesst genau diese Luecke -- ebenfalls vom Datentraeger
    # gelesen, ebenfalls neustartfest. Am 04.09.2026 nachgeschaerft.
    TEIL_MAX_DATEIEN = 32

    # Zeitlimit fuer einen einzelnen Scan-Aufruf (siehe virenscan_befehl
    # weiter unten). Ein Daemon mit Signaturen im Speicher braucht dafuer
    # Sekunden, keine Minuten -- eine haengende Pruefung darf den Agenten
    # nicht auf unbestimmte Zeit blockieren.
    VIRENSCAN_ZEITLIMIT = 30    # s

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

        # 0 heisst ausdruecklich UNBEGRENZT.
        #
        # Frueher lag die Decke bei 64 MiB, weil eine Datei in EINE Frage
        # passen musste und dort bei rund 4,2 MiB ohnehin Schluss war -- die
        # Zahl war also nie die wirksame Grenze, sondern nur die zweite.
        # Mit `lege_block` geht eine Datei ueber beliebig viele Fragen; damit
        # ist diese Zahl die einzige verbliebene Schranke und muss deshalb
        # frei waehlbar sein.
        #
        # 0 zu setzen ist erlaubt, aber es ist eine Entscheidung: Wer
        # schreiben darf, kann dann die Platte des Heimservers fuellen. Das
        # kann nur ein Geraet aus der Weissliste, also ein eigenes -- aber
        # ein eigenes Geraet mit einem falsch gesetzten Ordner reicht dafuer.
        self.max_bytes = int(konfig.get('max_bytes', 5 * 1024 * 1024))
        if not 0 <= self.max_bytes <= (1 << 40):
            raise KonfigFehler('Dienst "%s": max_bytes unplausibel '
                               '(0 = unbegrenzt, sonst bis 1 TiB).' % self.name)

        endungen = konfig.get('endungen', [])
        if not isinstance(endungen, list) \
                or any(not isinstance(e, str) for e in endungen):
            raise KonfigFehler('Dienst "%s": `endungen` muss eine Liste von '
                               'Zeichenketten sein.' % self.name)
        # Leere Liste heisst ausdruecklich "alles, was die drei Schranken
        # passiert". Das ist erlaubt, aber es soll niemand versehentlich
        # dorthin geraten -- deshalb sagt der Kern es beim Start laut.
        self.endungen = {e.lower().lstrip('.') for e in endungen}

        # Kein fest verdrahteter Scanner. AHPT Cloud muss auf Linux,
        # Windows und Mac laufen koennen, mit welchem Virenscanner auch
        # immer ein Nutzer bei sich installiert hat -- also weiss dieser
        # Kern nichts ueber ClamAV, Windows Defender oder sonst ein
        # Produkt, nur ueber die allgemeine Kommandozeilen-Konvention:
        # Exitcode 0 heisst sauber, alles andere heisst nicht sauber.
        #
        # Als LISTE konfiguriert, nicht als Zeichenkette: Jeder Eintrag
        # ist ein eigenes Argument, der Aufruf laeuft deshalb ohne Shell
        # (siehe _scan_virus) -- plattformunabhaengig identisch, ohne
        # Anfuehrungszeichen- oder Escaping-Fallstricke bei Windows-Pfaden
        # mit Leerzeichen oder Backslashes. "{datei}" wird durch den
        # echten Pfad ersetzt. Leer heisst: kein Scan.
        befehl = konfig.get('virenscan_befehl', [])
        if not isinstance(befehl, list) \
                or any(not isinstance(t, str) for t in befehl):
            raise KonfigFehler('Dienst "%s": `virenscan_befehl` muss eine '
                                'Liste von Zeichenketten sein (leer = kein '
                                'Scan).' % self.name)
        if befehl and '{datei}' not in befehl:
            raise KonfigFehler('Dienst "%s": `virenscan_befehl` muss den '
                                'Platzhalter "{datei}" enthalten.'
                                % self.name)
        self.virenscan_befehl = befehl

        # Angefangene Uebertragungen, je Marke eine.
        #
        # Der Zustand liegt im Arbeitsspeicher, nicht auf der Platte: Ein
        # Neustart des Agenten bricht laufende Uebertragungen ab, und das
        # ist die ehrlichere Antwort. Wuerde er sie fortsetzen, muesste er
        # einer Teildatei glauben, deren Herkunft er nicht mehr belegen
        # kann -- wer sie inzwischen veraendert hat, saehe man nicht.
        self._teile = {}

    def bereit(self):
        if not os.path.isdir(self.wurzel):
            return False, 'Wurzel verschwunden: %s' % self.wurzel
        offen = 'alle Endungen' if not self.endungen \
                else '%d Endungen' % len(self.endungen)
        # 0 heisst ausdruecklich UNBEGRENZT (siehe __init__) -- "bis 0 KiB"
        # laese sich wie "nichts erlaubt", das Gegenteil des Gemeinten.
        deckel = ('je Datei unbegrenzt, insgesamt bis %d GiB'
                  % (self.TEIL_MAX_GESAMT // 1024 // 1024 // 1024)) \
                 if self.max_bytes == 0 else 'bis %d KiB' % (self.max_bytes // 1024)
        return True, '%s   (%s, %s)' % (self.wurzel, offen, deckel)

    # ---------------------------------------------------------- Virenscan

    def _scan_virus(self, pfad):
        """Prueft eine fertig geschriebene Datei mit dem in
        `virenscan_befehl` konfigurierten Aufruf -- welchem auch immer.
        Dieser Kern kennt kein bestimmtes Produkt, nur die Konvention:
        Exitcode 0 heisst sauber, alles andere heisst nicht sauber.

        Rueckgabe: (sauber: bool, meldung: str)

        Jeder Zweifel gilt als NICHT sauber -- ein Scan, der bei einer
        Ungewissheit lieber durchwinkt, waere keiner. Das gilt fuer den
        fehlenden Befehl, die Zeitueberschreitung und jeden Exitcode
        ausser 0 gleichermassen. Wird nur gerufen, wenn
        `virenscan_befehl` nicht leer ist -- der Aufrufer prueft das.
        """
        argumente = [pfad if t == '{datei}' else t
                     for t in self.virenscan_befehl]
        try:
            ergebnis = subprocess.run(
                argumente, capture_output=True, text=True,
                timeout=self.VIRENSCAN_ZEITLIMIT)
        except FileNotFoundError:
            return False, 'Scan-Befehl nicht gefunden: %s' % argumente[0]
        except subprocess.TimeoutExpired:
            return False, ('Scan hat das Zeitlimit ueberschritten (%ds)'
                            % self.VIRENSCAN_ZEITLIMIT)
        except OSError as e:
            return False, 'Scan-Befehl nicht ausfuehrbar: %s' % e
        if ergebnis.returncode == 0:
            return True, 'sauber'
        ausgabe = (ergebnis.stdout.strip() or ergebnis.stderr.strip()
                   or ('Exitcode %d' % ergebnis.returncode))
        return False, ausgabe

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
            gekappt = False
            versteckt = 0
            gefiltert = 0
            try:
                alle = sorted(os.listdir(ordner))
                # Ein abgeschnittenes Verzeichnis MUSS sich zu erkennen geben.
                # Die erste Fassung schnitt still bei MAX_EINTRAEGE ab -- wer
                # 700 Dateien in einem Ordner hat, saehe 500 und haette keinen
                # Anhaltspunkt, dass welche fehlen. Eine unvollstaendige
                # Liste, die wie eine vollstaendige aussieht, ist schlimmer
                # als eine Fehlermeldung.
                gekappt = len(alle) > MAX_EINTRAEGE
                for name in alle[:MAX_EINTRAEGE]:
                    if name.startswith('.'):
                        versteckt += 1
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
                    elif os.path.isfile(echt):
                        if self._endung_ok(name):
                            eintraege.append({'name': name, 'art': 'datei',
                                              'bytes': os.path.getsize(echt)})
                        else:
                            gefiltert += 1
            except OSError as e:
                return nichts('nicht lesbar: %s' % e.strerror)

            # Warum die Liste kuerzer sein kann, als der Ordner Eintraege hat.
            # Ohne diese Angaben ist "der Ordner ist leer" nicht von "hier
            # ist alles gesperrt" zu unterscheiden -- und das kostet den
            # Nutzer eine halbe Stunde Suche am falschen Ende.
            ergebnis = {'eintraege': eintraege}
            if gekappt:
                ergebnis['gekappt'] = MAX_EINTRAEGE
            if versteckt:
                ergebnis['versteckt'] = versteckt
            if gefiltert:
                ergebnis['endung_gesperrt'] = gefiltert
            return text_antwort(
                json.dumps(ergebnis, ensure_ascii=False),
                titel=roh or '/')

        if aktion == 'lege':
            # ---------------------------------------------------------
            # SCHREIBEN. Die gefaehrlichste Aktion des ganzen Projekts.
            #
            # Im oeffentlichen AHPT gibt es sie nicht, und das aus gutem
            # Grund: Wer Bytes auf den Heimserver legen darf, braucht ein
            # anderes Sicherheitsmodell als jemand, der nur liest.
            #
            # Hier gibt es dieses Modell -- der Absender ist durch Noise IK
            # kryptografisch bestimmt und steht in einer Weissliste. Ohne
            # Verschluesselung darf diese Aktion NICHT freigegeben werden;
            # der Agent laesst sie dann gar nicht erst zu (siehe unten).
            #
            # Dieselben drei Schranken wie beim Lesen, plus vier weitere.
            # KEINE zweite Pfadpruefung: Zwei Fassungen derselben Regel
            # laufen auseinander, und die schwaechere gewinnt.
            ziel = self._pfad_erlaubt(daten.get('pfad'))
            if ziel is None:
                return nichts('pfad abgewiesen')

            # Schranke 4: nur in einen Ordner, den es schon gibt. Der
            # Besucher legt keine Ordnerbaeume an, indem er tief genug zielt.
            eltern = os.path.dirname(ziel)
            if not os.path.isdir(eltern):
                return nichts('zielordner gibt es nicht')

            # Schranke 5: dieselbe Endungsliste wie beim Lesen. Was nicht
            # herausgehen darf, darf auch nicht hinein -- sonst waere der
            # Ordner ein Ablageplatz fuer alles, was man spaeter nicht mehr
            # sieht.
            if not self._endung_ok(os.path.basename(ziel)):
                return nichts('endung nicht freigegeben')

            typ = daten.get('inhalt_typ', 'text')
            roh = daten.get('inhalt', '')
            if typ == 'base64':
                try:
                    roh = base64.b64decode(roh, validate=True)
                except Exception:
                    return nichts('inhalt: kein gueltiges base64')
            elif typ == 'text':
                if not isinstance(roh, str):
                    return nichts('inhalt: Text erwartet')
                roh = roh.encode('utf-8')
            else:
                return nichts('inhalt_typ: text oder base64')

            # Schranke 6: Groesse. Dieselbe Grenze wie beim Lesen.
            #
            # max_bytes == 0 heisst UNBEGRENZT (siehe __init__) -- ohne
            # das "self.max_bytes and" davor waere 0 keine Abwesenheit
            # einer Grenze, sondern eine Grenze von null Bytes, und jede
            # nicht-leere Datei schluege fehl. Am 05.09.2026 gefunden,
            # als genau das live passierte: eine 19-Byte-Datei wurde mit
            # "erlaubt 0" abgewiesen. Die Blockuebertragung hatte diese
            # Sonderregel schon immer -- hier fehlte sie.
            if self.max_bytes and len(roh) > self.max_bytes:
                return nichts('zu gross: %d Bytes, erlaubt %d'
                              % (len(roh), self.max_bytes))

            # Schranke 7: NICHT UEBERSCHREIBEN.
            #
            # Wer ueberschreiben kann, kann loeschen -- und ein Loeschen, das
            # als Hochladen daherkommt, faellt niemandem auf. Stattdessen ein
            # neuer Name. Der Zaehler laeuft, statt beim ersten Versuch
            # aufzugeben: Sonst waere ein Ordner mit "bericht (2).pdf" darin
            # fuer immer gegen "bericht.pdf" gesperrt.
            endgueltig = ziel
            if os.path.exists(endgueltig):
                stamm, endung = os.path.splitext(ziel)
                for i in range(2, 1000):
                    endgueltig = '%s (%d)%s' % (stamm, i, endung)
                    if not os.path.exists(endgueltig):
                        break
                else:
                    return nichts('zu viele Dateien gleichen Namens')

            # Atomar schreiben. Eine halb geschriebene Datei, die schon ihren
            # endgueltigen Namen traegt, sieht aus wie eine fertige.
            tmp = endgueltig + '.' + os.urandom(4).hex() + '.teil'
            try:
                with open(tmp, 'wb') as f:
                    f.write(roh)

                # Schranke 8: Virenscan, falls konfiguriert. Erst hier --
                # nach vollstaendigem Schreiben, vor dem Sichtbarwerden.
                if self.virenscan_befehl:
                    sauber, meldung = self._scan_virus(tmp)
                    if not sauber:
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass
                        return nichts('Virenscan: %s' % meldung)

                os.replace(tmp, endgueltig)
            except OSError as e:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                return nichts('nicht schreibbar: %s' % e.strerror)

            name = os.path.relpath(endgueltig, self.wurzel).replace(os.sep, '/')
            return text_antwort(
                json.dumps({'abgelegt': name, 'bytes': len(roh)},
                           ensure_ascii=False),
                titel=name)

        if aktion == 'lege_block':
            # ---------------------------------------------------------
            # SCHREIBEN IN BLOECKEN -- fuer Dateien jeder Groesse.
            #
            # WESHALB UEBERHAUPT
            #
            # `lege` bringt eine Datei in EINER Frage hinauf. Der Vermittler
            # laesst je Frage 160 Stuecke zu; nach zweifacher Base64-
            # Aufblaehung sind das rund 4,2 MiB Nutzdatei. Diese Schranke
            # ist richtig und bleibt: Fragestuecke darf JEDER ablegen, der
            # die Adresse kennt, und sie begrenzt, wieviel Platz ein Fremder
            # auf dem Webspace belegen kann (relay.php, MAX_FRAGE_TEILE).
            #
            # Falsch war nur, eine Datei mit einer Frage gleichzusetzen.
            # Hier geht eine Datei ueber beliebig viele Fragen. Die Schranke
            # des Vermittlers bleibt unangetastet, die Dateigroesse ist offen.
            #
            # WAS DIESE AKTION NICHT LOCKERT
            #
            # Jede der acht Schranken von `lege` gilt weiter. Sie greifen
            # beim ERSTEN Block -- danach steht der Pfad fest und wird nicht
            # mehr aus den Daten gelesen. Wer beim zweiten Block einen
            # anderen Pfad mitschickt, aendert nichts; der Wert wird gar
            # nicht angesehen.
            #
            # WAS SIE NICHT LEISTET
            #
            # Sie bindet die Uebertragung nicht an ein bestimmtes Geraet --
            # `bearbeite` bekommt den Absender nicht. Wer eine fremde
            # Uebertragung fortsetzen wollte, muesste in der Weissliste des
            # Agenten stehen, also ein Geraet des Besitzers sein, UND eine
            # 32 Zeichen lange Zufallsmarke raten. Das ist vertretbar.
            # Waere die Weissliste offen, waere es das nicht.
            self._teile_aufraeumen()

            marke = daten.get('uebertragung')
            if not isinstance(marke, str) \
                    or not re.fullmatch(r'[0-9a-f]{16,64}', marke):
                return nichts('uebertragung: 16 bis 64 Hexzeichen erwartet')

            nr = daten.get('block')
            gesamt = daten.get('bloecke')
            if not isinstance(nr, int) or isinstance(nr, bool) or nr < 0:
                return nichts('block: Zahl ab 0 erwartet')
            if not isinstance(gesamt, int) or isinstance(gesamt, bool) \
                    or gesamt < 1:
                return nichts('bloecke: Zahl ab 1 erwartet')
            if nr >= gesamt:
                return nichts('block liegt hinter bloecke')

            if daten.get('inhalt_typ', 'base64') != 'base64':
                return nichts('inhalt_typ: hier nur base64')
            try:
                roh = base64.b64decode(daten.get('inhalt', ''), validate=True)
            except Exception:
                return nichts('inhalt: kein gueltiges base64')

            if nr == 0:
                # Die acht Schranken -- einmal, hier.
                ziel = self._pfad_erlaubt(daten.get('pfad'))
                if ziel is None:
                    return nichts('pfad abgewiesen')
                if not os.path.isdir(os.path.dirname(ziel)):
                    return nichts('zielordner gibt es nicht')
                if not self._endung_ok(os.path.basename(ziel)):
                    return nichts('endung nicht freigegeben')
                if marke in self._teile:
                    return nichts('uebertragung laeuft schon')

                # Deckel VOR dem Anlegen pruefen, nicht danach -- sonst
                # koennte genau der Block, der die Grenze reisst, noch
                # durchrutschen.
                if len(self._teile) >= self.TEIL_MAX_GLEICHZEITIG:
                    return nichts(
                        'zu viele gleichzeitige Uebertragungen (hoechstens %d)'
                        % self.TEIL_MAX_GLEICHZEITIG)
                belegt = self._teil_ordner_bytes()
                if belegt + len(roh) > self.TEIL_MAX_GESAMT:
                    return nichts(
                        'Uebertragungen belegen zusammen zu viel Platz '
                        '(%d von hoechstens %d Bytes) -- fruehere zuerst '
                        'abschliessen oder ablaufen lassen'
                        % (belegt, self.TEIL_MAX_GESAMT))
                dateien = self._teil_ordner_anzahl()
                if dateien >= self.TEIL_MAX_DATEIEN:
                    return nichts(
                        'zu viele liegen gebliebene Uebertragungen '
                        '(%d von hoechstens %d) -- fruehere zuerst '
                        'abschliessen oder ablaufen lassen'
                        % (dateien, self.TEIL_MAX_DATEIEN))

                ordner = os.path.join(self.wurzel, self.TEIL_ORDNER)
                tmp = os.path.join(ordner, marke + '.teil')
                try:
                    os.makedirs(ordner, exist_ok=True)
                    with open(tmp, 'wb') as f:
                        f.write(roh)
                except OSError as e:
                    return nichts('nicht schreibbar: %s' % e.strerror)

                self._teile[marke] = {
                    'ziel': ziel, 'tmp': tmp, 'erwartet': 1,
                    'bloecke': gesamt, 'bytes': len(roh), 'zeit': time.time(),
                }
            else:
                z = self._teile.get(marke)
                if z is None:
                    return nichts('unbekannte uebertragung -- abgelaufen '
                                  'oder nie begonnen')
                if gesamt != z['bloecke']:
                    return nichts('bloecke zaehlt anders als beim ersten Block')
                # Genau der naechste Block. Kein Puffer fuer die Reihenfolge:
                # Der Absender schickt sie nacheinander, und ein Puffer waere
                # Platz, den ein Fehler beliebig fuellen koennte.
                if nr != z['erwartet']:
                    return nichts('block %d erwartet, %d bekommen'
                                  % (z['erwartet'], nr))
                try:
                    with open(z['tmp'], 'ab') as f:
                        f.write(roh)
                except OSError as e:
                    self._teil_verwerfen(marke)
                    return nichts('nicht schreibbar: %s' % e.strerror)
                z['erwartet'] += 1
                z['bytes'] += len(roh)
                z['zeit'] = time.time()

            z = self._teile[marke]

            # Schranke 6 gilt fuer die GANZE Datei, nicht je Block -- sonst
            # waere sie durch Stueckeln zu umgehen.
            if self.max_bytes and z['bytes'] > self.max_bytes:
                self._teil_verwerfen(marke)
                return nichts('zu gross: %d Bytes, erlaubt sind %d'
                              % (z['bytes'], self.max_bytes))

            if z['erwartet'] < gesamt:
                return text_antwort(
                    json.dumps({'block': nr, 'weiter': True,
                                'bytes': z['bytes']}, ensure_ascii=False),
                    titel='block %d/%d' % (nr + 1, gesamt))

            # --- letzter Block: pruefen, dann ablegen ---
            #
            # Die Pruefsumme deckt ab, was die Verschluesselung je Block
            # NICHT abdeckt: dass alle Bloecke da sind, in der richtigen
            # Reihenfolge, keiner doppelt. Jeder Block fuer sich ist gueltig
            # versiegelt -- das Ganze ist es erst hierdurch.
            soll = daten.get('sha256')
            if not isinstance(soll, str) \
                    or not re.fullmatch(r'[0-9a-f]{64}', soll):
                self._teil_verwerfen(marke)
                return nichts('sha256 des Ganzen fehlt beim letzten Block')
            h = hashlib.sha256()
            try:
                with open(z['tmp'], 'rb') as f:
                    for stueck in iter(lambda: f.read(1 << 20), b''):
                        h.update(stueck)
            except OSError as e:
                self._teil_verwerfen(marke)
                return nichts('nicht lesbar: %s' % e.strerror)
            if h.hexdigest() != soll:
                self._teil_verwerfen(marke)
                return nichts('Pruefsumme stimmt nicht -- nichts abgelegt')

            # Schranke 8: Virenscan, falls konfiguriert. Erst hier -- am
            # vollstaendigen, pruefsummengeprueften Ganzen, nicht je Block
            # (ein Scan auf einem Bruchstueck waere sinnlos).
            if self.virenscan_befehl:
                sauber, meldung = self._scan_virus(z['tmp'])
                if not sauber:
                    self._teil_verwerfen(marke)
                    return nichts('Virenscan: %s' % meldung)

            # Schranke 7: NICHT UEBERSCHREIBEN. Erst hier, nicht beim ersten
            # Block -- sonst waere der Name belegt, waehrend die Datei noch
            # gar nicht vollstaendig ist.
            endgueltig = z['ziel']
            if os.path.exists(endgueltig):
                stamm, endung = os.path.splitext(z['ziel'])
                for i in range(2, 1000):
                    endgueltig = '%s (%d)%s' % (stamm, i, endung)
                    if not os.path.exists(endgueltig):
                        break
                else:
                    self._teil_verwerfen(marke)
                    return nichts('zu viele Dateien gleichen Namens')
            try:
                os.replace(z['tmp'], endgueltig)
            except OSError as e:
                self._teil_verwerfen(marke)
                return nichts('nicht ablegbar: %s' % e.strerror)
            self._teile.pop(marke, None)

            name = os.path.relpath(endgueltig, self.wurzel).replace(os.sep, '/')
            return text_antwort(
                json.dumps({'abgelegt': name, 'bytes': z['bytes'],
                            'bloecke': gesamt}, ensure_ascii=False),
                titel=name)

        if aktion == 'neuer_ordner':
            # Ordner darf man auch ganz klassisch per SSH anlegen -- es gibt
            # keinen Abgleich und keine zweite Liste. Diese Aktion ist reine
            # Bequemlichkeit fuer das Portal.
            ziel = self._pfad_erlaubt(daten.get('pfad'))
            if ziel is None:
                return nichts('pfad abgewiesen')
            if os.path.exists(ziel):
                return nichts('gibt es schon')
            if not os.path.isdir(os.path.dirname(ziel)):
                return nichts('zielordner gibt es nicht')
            try:
                os.mkdir(ziel)
            except OSError as e:
                return nichts('nicht anlegbar: %s' % e.strerror)
            name = os.path.relpath(ziel, self.wurzel).replace(os.sep, '/')
            return text_antwort(json.dumps({'angelegt': name}), titel=name)

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
                st = os.stat(ziel)
            except OSError:
                return nichts('nicht lesbar')
            groesse = st.st_size

            # --- LESEN IN BLOECKEN -- fuer Dateien jeder Groesse. ---
            #
            # Die Antwort des Agenten darf 256 Stuecke lang sein, also rund
            # 12 MiB Rohdaten. Wer eine groessere Datei holen will, holt sie
            # bereichsweise: `von` und `laenge` sagen, welcher Ausschnitt.
            #
            # Mitgeliefert wird immer die Gesamtgroesse UND der Zeitstempel.
            # Der Zeitstempel ist der Punkt: Aendert sich die Datei waehrend
            # des Holens, setzt der Empfaenger sonst Stuecke aus zwei
            # verschiedenen Fassungen zusammen -- und das faellt niemandem
            # auf, weil jedes Stueck fuer sich gueltig ist.
            if 'von' in daten or 'laenge' in daten:
                von = daten.get('von', 0)
                laenge = daten.get('laenge', 0)
                if not isinstance(von, int) or isinstance(von, bool) or von < 0:
                    return nichts('von: Zahl ab 0 erwartet')
                if not isinstance(laenge, int) or isinstance(laenge, bool) \
                        or laenge < 1:
                    return nichts('laenge: Zahl ab 1 erwartet')
                # Nicht mehr, als in eine Antwort passt.
                if laenge > self.LESE_BLOCK:
                    return nichts('laenge hoechstens %d' % self.LESE_BLOCK)
                if von > groesse:
                    return nichts('von liegt hinter dem Dateiende')
                try:
                    with open(ziel, 'rb') as f:
                        f.seek(von)
                        teil = f.read(laenge)
                except OSError as e:
                    return nichts('nicht lesbar: %s' % e.strerror)

                antwort = {
                    'name': os.path.basename(ziel),
                    'gesamt': groesse,
                    'von': von,
                    'laenge': len(teil),
                    'stand': int(st.st_mtime_ns),
                    'inhalt': base64.b64encode(teil).decode('ascii'),
                }
                # Die Pruefsumme kostet einen vollen Durchlauf der Datei --
                # deshalb nur, wenn ausdruecklich verlangt. Der Empfaenger
                # verlangt sie einmal, am Ende.
                if daten.get('pruefsumme'):
                    h = hashlib.sha256()
                    try:
                        with open(ziel, 'rb') as f:
                            for st2 in iter(lambda: f.read(1 << 20), b''):
                                h.update(st2)
                    except OSError as e:
                        return nichts('nicht lesbar: %s' % e.strerror)
                    antwort['sha256'] = h.hexdigest()
                return text_antwort(json.dumps(antwort, ensure_ascii=False),
                                    titel=antwort['name'])

            if self.max_bytes and groesse > self.max_bytes:
                return nichts('zu gross: %d Bytes, erlaubt sind %d '
                              '(bereichsweise holen geht immer)'
                              % (groesse, self.max_bytes))
            try:
                with open(ziel, 'rb') as f:
                    roh = f.read(groesse + 1)
            except OSError as e:
                return nichts('nicht lesbar: %s' % e.strerror)
            # Zwischen stat() und read() kann die Datei gewachsen sein.
            if self.max_bytes and len(roh) > self.max_bytes:
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

    def _teil_verwerfen(self, marke):
        """Eine angefangene Uebertragung wegwerfen, samt Teildatei.

        Wird bei jedem Fehlschlag gerufen. Die halbe Datei stehenzulassen
        waere doppelt schlecht: Sie belegt Platz, und beim naechsten
        Versuch mit derselben Marke wuerde weiter angehaengt -- an Bytes,
        von denen niemand mehr weiss, woher sie stammen.
        """
        z = self._teile.pop(marke, None)
        if not z:
            return
        try:
            os.unlink(z['tmp'])
        except OSError:
            pass

    def _teil_ordner_bytes(self):
        """Summe aller Bytes, die gerade in TEIL_ORDNER liegen.

        Vom DATENTRAEGER gelesen, nicht aus self._teile aufsummiert: Nach
        einem Neustart des Agenten ist self._teile leer, aber liegen
        gebliebene .teil-Dateien sind es nicht. Der Deckel muss auch DANN
        greifen, sonst genuegt ein Neustart, um ihn zu umgehen.
        """
        ordner = os.path.join(self.wurzel, self.TEIL_ORDNER)
        gesamt = 0
        try:
            for n in os.listdir(ordner):
                if not n.endswith('.teil'):
                    continue
                try:
                    gesamt += os.path.getsize(os.path.join(ordner, n))
                except OSError:
                    pass
        except OSError:
            pass
        return gesamt

    def _teil_ordner_anzahl(self):
        """Zahl der .teil-Dateien, die gerade in TEIL_ORDNER liegen.

        Dieselbe Begruendung wie bei _teil_ordner_bytes(): vom DATENTRAEGER
        gezaehlt, nicht aus self._teile, damit ein Neustart des Agenten den
        Deckel nicht umgeht. Getrennt von den Bytes, weil viele kleine oder
        leere Leichen TEIL_MAX_GESAMT nie reissen, aber trotzdem Platz und
        Inodes binden.
        """
        ordner = os.path.join(self.wurzel, self.TEIL_ORDNER)
        anzahl = 0
        try:
            for n in os.listdir(ordner):
                if n.endswith('.teil'):
                    anzahl += 1
        except OSError:
            pass
        return anzahl

    def _teile_aufraeumen(self):
        """Abgelaufene Uebertragungen wegraeumen.

        Aufgerufen bei jedem Block, nicht per Zeitgeber: Der Agent hat
        keinen eigenen Takt, und ein Aufraeumen, das nur laeuft, wenn
        ohnehin gearbeitet wird, kann nicht im Leerlauf danebengreifen.

        Aufgeraeumt wird auch, was gar nicht mehr im Speicher steht --
        nach einem Neustart des Agenten sind die Marken vergessen, die
        Teildateien aber noch da. Ohne das bliebe Platz belegt, den
        niemand mehr freigibt.
        """
        jetzt = time.time()
        for marke in [m for m, z in self._teile.items()
                      if jetzt - z['zeit'] > self.TEIL_TTL]:
            self._teil_verwerfen(marke)

        ordner = os.path.join(self.wurzel, self.TEIL_ORDNER)
        try:
            namen = os.listdir(ordner)
        except OSError:
            return
        for n in namen:
            if not n.endswith('.teil'):
                continue
            if n[:-5] in self._teile:
                continue
            pfad = os.path.join(ordner, n)
            try:
                if jetzt - os.path.getmtime(pfad) > self.TEIL_TTL:
                    os.unlink(pfad)
            except OSError:
                pass

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
