#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handler/kiwix.py -- kiwix als Dienst hinter AHPT

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

Das ist die Logik aus `tunnel_agent.py`, herausgeloest und sonst nichts.
Die beiden HTML-Leser sind woertlich uebernommen -- sie sind gemessen und
im Betrieb bewiesen, und eine "verbesserte" Fassung waere eine zweite
Umsetzung derselben Sache. Genau daran sind in diesem Projekt schon
mehrere Fehler gestorben.

WAS HIER WEGGEFALLEN IST
------------------------
Die Kappung bei 64 KiB. `tunnel_agent.py` musste Artikel abschneiden und
"[Artikel hier gekuerzt]" anhaengen, weil eine Antwort in eine einzige
Datei passen musste. Der Kern stueckelt jetzt; der Handler gibt den ganzen
Text zurueck und muss nichts mehr wegwerfen.

WARUM DIESER HANDLER ABSICHTLICH DUMM IST
------------------------------------------
Er sucht nicht den besten Artikel aus, waehlt nicht zwischen Archiven und
kuerzt keinen Ausschnitt um die Fundstelle. Das steht im Browser
(`titelGuete`, `kuerzeUmTreffer`, `NOTFALL_ZUORDNUNG`) und ist die Lehre
aus den Bugs 13-17: Zwischen "das Wort kommt vor" und "der Artikel handelt
davon" liegen vier Fehler, jeder davon im Krisenfall gefaehrlicher als gar
kein Archiv.

Er liefert deshalb nur Rohstoff, in genau der Form, die der Browser ohnehin
erzeugt. Kostet einen zweiten Umlauf, spart eine zweite Umsetzung.

Und: Ein dummer Handler laesst sich nicht ueberreden, klug zu sein.
"""

import json
import re
import urllib.parse
from html.parser import HTMLParser

import netz
from handler import Handler, KonfigFehler, text_antwort, nichts

KIWIX_TIMEOUT = 10          # s -- Suche im 48-GiB-Archiv darf dauern


# --------------------------------------------------------- kiwix auslesen

class TrefferLeser(HTMLParser):
    """Liest die Trefferliste der kiwix-Suchseite.

    Erzeugt genau die Form, die sucheKiwix() im Browser erzeugt:
    {titel, text, href}. Wer das hier aendert, muss dort nachziehen --
    deshalb steht es so knapp wie moeglich.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.treffer, self._in_li, self._in_a, self._in_cite = [], False, False, False
        self._href, self._titel, self._text = '', [], []
        self._tiefe_ul = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'div' and 'results' in (a.get('class') or ''):
            self._tiefe_ul = 1
        if not self._tiefe_ul:
            return
        if tag == 'li':
            self._in_li, self._href, self._titel, self._text = True, '', [], []
        elif tag == 'a' and self._in_li:
            self._in_a, self._href = True, a.get('href', '')
        elif tag == 'cite' and self._in_li:
            self._in_cite = True

    def handle_endtag(self, tag):
        if tag == 'a':
            self._in_a = False
        elif tag == 'cite':
            self._in_cite = False
        elif tag == 'li' and self._in_li:
            self._in_li = False
            titel = ' '.join(''.join(self._titel).split())
            if self._href and titel:
                self.treffer.append({
                    'titel': titel,
                    'text':  ' '.join(''.join(self._text).split()),
                    'href':  self._href,
                })
        elif tag == 'div' and self._tiefe_ul and not self._in_li:
            self._tiefe_ul = 0

    def handle_data(self, d):
        if self._in_a:
            self._titel.append(d)
        elif self._in_cite:
            self._text.append(d)


class TextLeser(HTMLParser):
    """Zieht die Absaetze aus einem kiwix-Artikel.

    Bildet holeArtikelText() aus index.html nach: Navigation, Tabellen,
    Infoboxen, Skripte raus; nur <p> mit mehr als 30 Zeichen behalten.
    """

    WEG = {'nav', 'table', 'script', 'style', 'sup', 'head'}
    WEG_KLASSEN = ('infobox', 'navbox', 'toc', 'thumb', 'mw-editsection')

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.absaetze, self._in_p, self._puffer = [], False, []
        self._unterdrueckt = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        klasse = a.get('class') or ''
        if tag in self.WEG or any(k in klasse for k in self.WEG_KLASSEN):
            self._unterdrueckt += 1
            return
        if self._unterdrueckt:
            return
        if tag == 'p':
            self._in_p, self._puffer = True, []

    def handle_endtag(self, tag):
        if self._unterdrueckt:
            if tag in self.WEG or tag in ('div', 'span', 'table'):
                self._unterdrueckt = max(0, self._unterdrueckt - 1)
            return
        if tag == 'p' and self._in_p:
            self._in_p = False
            t = ' '.join(''.join(self._puffer).split())
            if len(t) > 30:
                self.absaetze.append(t)

    def handle_data(self, d):
        if self._in_p and not self._unterdrueckt:
            self._puffer.append(d)


# Medizin-Hinweise raus. Begruendung steht in index.html: das Modell wuerde
# sie als einzige Faktenquelle treu wiedergeben und im Offline-Krisenfall
# "gehe zum Arzt" antworten -- zu einem Arzt, den es dann nicht gibt.
_DISCLAIMER = [
    re.compile(r'Dieser Artikel behandelt ein Gesundheitsthema[^\n]*'),
    re.compile(r'Er dient weder der Selbstdiagnose[^\n]*'),
    re.compile(r'eine Diagnose durch einen Arzt ersetzt[^\n]*'),
    re.compile(r'Bitte hierzu den Hinweis zu Gesundheitsthemen[^\n]*'),
]


def artikel_zu_text(roh_html):
    p = TextLeser()
    try:
        p.feed(roh_html)
    except Exception:
        pass
    text = '\n\n'.join(p.absaetze)
    for rx in _DISCLAIMER:
        text = rx.sub('', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


# ---------------------------------------------------------- Pfadpruefung

_TITEL_VERBOTEN = re.compile(r'[\x00-\x1f]|\.\.')


def pfad_erlaubt(href, buch):
    """Prueft einen von aussen kommenden kiwix-Pfad.

    Erlaubt ist genau: /<buch>/<rest ohne Schraegstrich> oder
    /<buch>/A/<rest ohne Schraegstrich>. Nichts weiter.

    Abgewiesen wird damit alles, was aus dem Pfad wieder eine Adresse
    machen koennte: Schema (http://...), Netzwerkpfad (//host/...),
    Rueckwaertsschritte (..), Query, Fragment, Steuerzeichen -- und jeder
    Buchname, den diese Maschine nicht selbst gemeldet hat.

    Rueckgabe: der bereinigte Pfad oder None.
    """
    if not isinstance(href, str) or not href.startswith('/') or href.startswith('//'):
        return None
    if '?' in href or '#' in href or '\\' in href:
        return None
    teile = href.split('/')
    if teile[0] != '' or len(teile) < 3:
        return None
    if teile[1] != buch:                      # nur das eigene Buch
        return None
    rest = teile[2:]
    if rest and rest[0] == 'A':
        rest = rest[1:]
    if len(rest) != 1 or not rest[0]:
        return None
    # Auch die dekodierte Form darf nicht ausbrechen (%2e%2e, %2f).
    try:
        klar = urllib.parse.unquote(rest[0])
    except Exception:
        return None
    if '/' in klar or _TITEL_VERBOTEN.search(klar):
        return None
    return href


# --------------------------------------------------------------- Handler

class KiwixHandler(Handler):

    ART = 'kiwix'
    AKTIONEN = frozenset(('suche', 'artikel'))

    MAX_BEGRIFF = 400

    def __init__(self, konfig):
        super().__init__(konfig)
        ziel = konfig.get('ziel')
        if not isinstance(ziel, str) or not ziel:
            raise KonfigFehler('Dienst "%s": `ziel` fehlt.' % self.name)
        if not netz.ziel_erlaubt(ziel):
            raise KonfigFehler(
                'Dienst "%s": `ziel` ist %r.\n'
                '         Erlaubt sind nur 127.0.0.1, localhost und ::1, und nur\n'
                '         als blosse Basis ohne Pfad. Ein Handler, der ins LAN\n'
                '         greifen darf, ist von aussen bedienbar -- Drucker,\n'
                '         Router, NAS. Das ist der eine Fehler, der alles\n'
                '         kaputtmacht.' % (self.name, ziel))
        self.ziel = ziel.rstrip('/')
        self.max_treffer = int(konfig.get('max_treffer', 8))
        if not 1 <= self.max_treffer <= 50:
            raise KonfigFehler('Dienst "%s": max_treffer muss zwischen 1 und 50 '
                               'liegen.' % self.name)
        self.buch = None            # wird bei bereit() gelernt, nicht geraten

    # ---------------------------------------------------------- Start

    def bereit(self):
        """Fragt die eigene kiwix-Instanz, unter welchem Pfad sie ausliefert.

        Der Pfad wird EMPIRISCH aus einem echten Suchtreffer gelesen, nicht
        aus dem Dateinamen abgeleitet. Grund: kiwix 3.2.0 liefert unter
        /<zim-name>/A/<Titel> aus, aeltere und neuere Fassungen unter
        /content/<buch>/... -- geraten haette man dreimal falsch (am
        02.09.2026 gemessen).

        Das Ergebnis ist die WEISSLISTE fuer eingehende Artikelpfade. Sie
        stammt damit ausschliesslich aus dem eigenen Haus und nie aus dem
        Netz.
        """
        code, koerper, _ = netz.hole(
            self.ziel + '/search?pattern=Wasser&pageLength=1',
            timeout=KIWIX_TIMEOUT)
        if code != 200:
            return False, 'nicht erreichbar (%s)' % (code or 'Netzfehler')
        p = TrefferLeser()
        try:
            p.feed(koerper.decode('utf-8', 'replace'))
        except Exception:
            pass
        if not p.treffer:
            return False, 'erreichbar, aber kein Treffer -- Archiv leer?'
        teile = [t for t in p.treffer[0]['href'].split('/') if t]
        if not teile:
            return False, 'unverstaendlicher Pfad: %s' % p.treffer[0]['href']
        self.buch = teile[0]
        return True, '%s   Buchpfad /%s/' % (self.ziel, self.buch)

    # ------------------------------------------------------- Bearbeiten

    def bearbeite(self, aktion, daten):
        if not isinstance(daten, dict):
            return nichts('daten: Objekt erwartet')
        if self.buch is None:
            return nichts('archiv-nicht-bereit')

        if aktion == 'suche':
            begriff = daten.get('begriff')
            if not isinstance(begriff, str) or not begriff \
                    or len(begriff) > self.MAX_BEGRIFF:
                return nichts('begriff fehlt oder ist zu lang')
            # Steuerzeichen raus: der Begriff wandert in eine URL.
            if re.search(r'[\x00-\x1f]', begriff):
                return nichts('begriff enthaelt Steuerzeichen')

            url = '%s/search?pattern=%s&pageLength=%d' % (
                self.ziel, urllib.parse.quote(begriff), self.max_treffer)
            code, koerper, _ = netz.hole(url, timeout=KIWIX_TIMEOUT)
            if code != 200:
                return nichts('kiwix-suche antwortet %s' % code)
            p = TrefferLeser()
            try:
                p.feed(koerper.decode('utf-8', 'replace'))
            except Exception:
                pass
            # Nur Treffer aus dem eigenen Buch weiterreichen -- damit kann
            # der Besucher spaeter nichts anfordern, was hier nicht erlaubt
            # waere. Die Ausgabe ist zugleich die Weissliste der naechsten
            # Frage.
            treffer = [t for t in p.treffer if pfad_erlaubt(t['href'], self.buch)]
            if not treffer:
                return nichts('keine Treffer')
            return text_antwort(
                json.dumps({'treffer': treffer[:self.max_treffer]},
                           ensure_ascii=False),
                titel=begriff)

        if aktion == 'artikel':
            pfad = pfad_erlaubt(daten.get('pfad'), self.buch)
            if not pfad:
                return nichts('pfad abgewiesen -- nicht aus dem eigenen Buch')
            code, koerper, _ = netz.hole(self.ziel + pfad, timeout=KIWIX_TIMEOUT)
            if code != 200:
                return nichts('kiwix-artikel antwortet %s' % code)
            text = artikel_zu_text(koerper.decode('utf-8', 'replace'))
            if not text:
                return nichts('kein Text im Artikel')
            return text_antwort(text,
                                titel=pfad.rsplit('/', 1)[-1].replace('_', ' '))

        return nichts('unbekannte Aktion: %s' % aktion)

    # ------------------------------------------------------- Selbsttest

    def selbsttest(self):
        """Prueft die Pfadschranke -- ohne Netz, ohne kiwix.

        Geprueft wird das VERBOTENE. Dass ein gueltiger Pfad durchgeht,
        beweist nichts ueber die Schranke; dass ein fremder abprallt, schon.
        """
        b = self.buch or 'wikipedia_de_all_maxi'
        faelle = [
            ('gueltig, ohne A',            '/%s/Wasser' % b,              True),
            ('gueltig, mit A',             '/%s/A/Wasser' % b,            True),
            ('fremdes Buch',               '/anderes_buch/Wasser',        False),
            ('absolute Adresse',           'http://192.168.1.1/x',        False),
            ('Netzwerkpfad',               '//192.168.1.1/x',             False),
            ('Pfadwanderung',              '/%s/../../etc/passwd' % b,    False),
            ('kodierte Pfadwanderung',     '/%s/%%2e%%2e%%2fetc' % b,     False),
            ('kodierter Schraegstrich',    '/%s/a%%2fb' % b,              False),
            ('Query angehaengt',           '/%s/Wasser?x=1' % b,          False),
            ('Fragment angehaengt',        '/%s/Wasser#x' % b,            False),
            ('Rueckwaertsschraegstrich',   '/%s/a\\b' % b,                False),
            ('Steuerzeichen',              '/%s/Wa\x00sser' % b,          False),
            ('zu tief',                    '/%s/A/B/Wasser' % b,          False),
            ('leerer Titel',               '/%s/' % b,                    False),
            ('kein fuehrender Schraegstr', '%s/Wasser' % b,               False),
            ('gar kein Text',              None,                          False),
        ]
        ergebnis = []
        for beschreibung, eingabe, soll in faelle:
            ist = pfad_erlaubt(eingabe, b) is not None
            ergebnis.append(('pfad: ' + beschreibung, ist == soll,
                             '' if ist == soll else
                             'erwartet %s, war %s' % (soll, ist)))

        # Das Ziel darf nur auf den eigenen Rechner zeigen.
        for beschreibung, url, soll in (
                ('ziel loopback',      'http://127.0.0.1:8081', True),
                ('ziel localhost',     'http://localhost:8081', True),
                ('ziel LAN',           'http://192.168.1.50:8081', False),
                ('ziel fremder Name',  'http://example.com', False),
                ('ziel mit Pfad',      'http://127.0.0.1:8081/x', False),
                ('ziel file-Schema',   'file:///etc/passwd', False)):
            ist = netz.ziel_erlaubt(url)
            ergebnis.append((beschreibung, ist == soll,
                             '' if ist == soll else
                             'erwartet %s, war %s' % (soll, ist)))

        # Eine Antwort darf nie HTML zum Einbetten sein.
        a = text_antwort('<script>alert(1)</script>')
        ergebnis.append(('antwort ist reiner Text', a['inhalt_typ'] == 'text', ''))

        return ergebnis


HANDLER = KiwixHandler
