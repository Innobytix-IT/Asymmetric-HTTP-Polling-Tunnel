#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transport.py -- Transportwege fuer AHPT Cloud 3000, austauschbar und
beliebig viele gleichzeitig.

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
AHPT Cloud kennt genau einen Weg: einen PHP-Webspace als Vermittler.
AHPT Cloud 3000 kennt mehrere -- unter anderem WebDAV-Speicher, wie ihn
viele E-Mail-Anbieter kostenlos mitliefern (siehe README.md fuer die
Messungen gegen GMX vom 06.09.2026). Diese Datei haelt den WebDAV-Weg und
das geteilte Gesundheits-Gedaechtnis, mit dem ein dauerhaft toter Weg
nicht bei jeder einzelnen Nachricht erneut seine volle Frist verstreichen
laesst.

DER UNTERSCHIED ZU relay.php
-----------------------------
WebDAV ist dummer Speicher -- PUT, GET, DELETE, PROPFIND, sonst nichts.
Keine Buchfuehrung, keine Marke, keine Deckel, keine Sperre gegen
Gleichzeitigkeit. All das, was `relay.php` serverseitig erledigt, muss
hier also im Transportweg selbst stecken -- nicht, weil es eine bessere
Bauart waere, sondern weil WebDAV keine andere Wahl laesst.

Der Ausgleich: Ein einzelnes PUT/GET braucht bei WebDAV KEINE Stueckelung
wie bei PHP -- gemessen bis 12 MB in einem Rutsch (README.md). Und
PROPFIND ersetzt die Warteschlangen-Datei durch eine echte
Verzeichnisliste, ohne das Wettlauf-Risiko einer gemeinsam beschriebenen
Datei ohne Sperre.
"""

import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import netz

# Deckel fuer eine einzelne Frage/Antwort ueber WebDAV. Grosszuegig ueber
# dem Gemessenen (12 MB, README.md), aber nicht grenzenlos -- eine Anfrage,
# die ihn reisst, ist vermutlich ein Fehler beim Aufrufer, keine Datei, die
# man einfach durchwinkt.
MAX_WEBDAV_NUTZLAST = 64 * 1024 * 1024


# --------------------------------------------------------- WebDAV-Transport

class WebDavTransport:
    """Ein WebDAV-Speicher (z.B. GMX MediaCenter) als AHPT-Transportweg.

    `name` ist eine frei waehlbare Bezeichnung fuer Protokoll und
    Gesundheits-Gedaechtnis (z.B. "webdav:gmx-privat") -- nicht Teil des
    Protokolls selbst, nur zur Unterscheidung, wenn mehrere WebDAV-Konten
    gleichzeitig eingetragen sind.
    """

    art = 'webdav'

    def __init__(self, name, basis, benutzer, passwort_datei, timeout=20):
        self.name = name
        self.basis = basis.rstrip('/')
        self.benutzer = benutzer
        with open(passwort_datei, 'r', encoding='utf-8') as f:
            self.passwort = f.read().strip()
        self.timeout = timeout

    # ------------------------------------------------------- Rohzugriff
    def _put(self, pfad, daten):
        return netz.webdav('PUT', self.basis + pfad, self.benutzer,
                            self.passwort, daten=daten, timeout=self.timeout)

    def _get(self, pfad):
        return netz.webdav('GET', self.basis + pfad, self.benutzer,
                            self.passwort, timeout=self.timeout)

    def _delete(self, pfad):
        netz.webdav('DELETE', self.basis + pfad, self.benutzer,
                     self.passwort, timeout=self.timeout)

    def _namen_im_verzeichnis(self):
        code, koerper = netz.webdav(
            'PROPFIND', self.basis + '/', self.benutzer, self.passwort,
            kopfzeilen={'Depth': '1'}, timeout=self.timeout)
        if code != 207:
            grund = (koerper.decode('utf-8', 'replace') if code == 0
                     else 'HTTP %s' % code)
            return None, grund
        # Das Namensraum-KUERZEL vor "href" ist NICHT festgelegt -- jeder
        # WebDAV-Server waehlt seines frei (GMX schreibt "D:href", freenet
        # "x1:href", beides gueltig, beides dieselbe Bedeutung). Ein
        # echter XML-Parser loest ueber den NAMENSRAUM selbst auf
        # ("DAV:"), unabhaengig vom Kuerzel -- ein Regex auf ein festes
        # Kuerzel waere bei jedem neuen Anbieter erneut zerbrechlich. Am
        # 07.09.2026 bei freenet genau so gefunden: identische Antwort,
        # anderes Kuerzel, `hole_offene_marken` fand nichts, obwohl die
        # Datei nachweislich da war.
        try:
            wurzel = ET.fromstring(koerper)
        except ET.ParseError as e:
            return None, 'Antwort ist kein gueltiges XML: %s' % e
        href = [el.text for el in wurzel.iter('{DAV:}href') if el.text]
        # KEIN einziges href ist NICHT dasselbe wie ein leeres Verzeichnis:
        # Eine PROPFIND-Antwort auf eine Sammlung nennt immer mindestens
        # die Sammlung selbst. Kommt gar nichts, ist es etwas anderes als
        # eine Verzeichnisliste -- eine Wartungsseite etwa, die zufaellig
        # wohlgeformtes XML ist. Als "nichts offen" gelesen, wuerde der
        # Agent daran ewig geduldig vorbeipollen, ohne dass der
        # Kreislauf-Unterbrecher je anschlaegt.
        if not href:
            return None, 'Antwort enthaelt kein einziges href'
        return [urllib.parse.unquote(h.rstrip('/').rsplit('/', 1)[-1])
                for h in href], None

    # -------------------------------------------------- AHPT-Operationen
    def lege_frage(self, marke, umschlag):
        return self._lege('/frage_%s.json' % marke, umschlag)

    def hole_frage(self, marke):
        return self._hole('/frage_%s.json' % marke)

    def loesche_frage(self, marke):
        self._delete('/frage_%s.json' % marke)

    def lege_antwort(self, marke, umschlag):
        return self._lege('/antwort_%s.json' % marke, umschlag)

    def hole_antwort(self, marke):
        return self._hole('/antwort_%s.json' % marke)

    def loesche_antwort(self, marke):
        self._delete('/antwort_%s.json' % marke)

    def hole_offene_marken(self, bekannt):
        """Marken mit `frage_*.json`, die `bekannt` noch nicht enthaelt.

        Ersetzt die Warteschlangen-Datei des PHP-Wegs: PROPFIND listet das
        Verzeichnis direkt. Kein gemeinsam beschriebenes Buch, das ohne
        Sperre einen Eintrag verlieren koennte -- gemessen 06.09.2026,
        PROPFIND arbeitet gegen GMX einwandfrei.

        `bekannt` ist die Menge der Marken, die dieser Agent schon
        bearbeitet hat (dasselbe Gedaechtnis wie `erledigt` beim
        PHP-Weg) -- so wird nicht jedesmal alles neu verarbeitet.
        """
        namen, fehler = self._namen_im_verzeichnis()
        if namen is None:
            return None, fehler
        marken = []
        for n in namen:
            m = re.fullmatch(r'frage_([0-9a-f]{32})\.json', n)
            if m and m.group(1) not in bekannt:
                marken.append(m.group(1))
        return marken, None

    # ------------------------------------------------------------ intern
    def _lege(self, pfad, umschlag):
        daten = json.dumps(umschlag, ensure_ascii=False).encode('utf-8')
        if len(daten) > MAX_WEBDAV_NUTZLAST:
            return False, ('zu gross: %d Bytes, Deckel %d'
                            % (len(daten), MAX_WEBDAV_NUTZLAST))
        code, koerper = self._put(pfad, daten)
        if code in (200, 201, 204):
            return True, ''
        if code == 0:
            return False, 'nicht erreichbar: %s' % koerper.decode('utf-8', 'replace')
        # Den Rumpf mitnehmen, nicht nur den Code: bei einem 4xx steht die
        # eigentliche Ursache (falscher Pfad, Kontingent, WebDAV-eigene
        # Ablehnung) fast immer NUR darin, nie im Statuscode allein. Am
        # 07.09.2026 im Nachttest genau deshalb ein "HTTP 400" ohne
        # jeden Hinweis gefunden, was es eigentlich war.
        rumpf = koerper.decode('utf-8', 'replace')[:300]
        return False, 'HTTP %s%s' % (code, (': ' + rumpf) if rumpf else '')

    def _hole(self, pfad):
        code, koerper = self._get(pfad)
        if code == 404:
            return False, None, ''            # noch nicht da -- kein Fehler
        if code != 200:
            grund = ('nicht erreichbar: %s' % koerper.decode('utf-8', 'replace')
                     if code == 0 else 'HTTP %s' % code)
            return False, None, grund
        try:
            return True, json.loads(koerper.decode('utf-8')), ''
        except Exception as e:
            return False, None, 'Antwort ist kein JSON: %s' % e


# ------------------------------------------------------------ PHP-Transport
#
# Grenzen aus relay.php uebernommen -- weichen sie ab, weist der Vermittler
# mit 413 ab, was der Agent zwar meldet, aber erst im Betrieb.
PHP_MAX_STUECK            = 49152    # Bytes je Stueck, dekodiert
PHP_MAX_JSON              = 60000    # Bytes je POST-Rumpf (MAX_RUMPF: 65536)
PHP_MAX_TEILE             = 256
PHP_STUECK_WIEDERHOLUNGEN = 5
PHP_UNBEDINGT_NACH        = 30
PHP_FRAGE_MAX_ALTER       = 110
PHP_GEDAECHTNIS           = 600

# Nur fuer die CLIENT-seitige Haelfte (`lege_frage`): eine Frage darf kleiner
# sein als eine Antwort, und sie darf in WENIGER Stuecke gehen -- relay.php
# kann Freund und Feind bei einer Frage nicht unterscheiden (sie ist ja noch
# nicht entschluesselt), Antwortstuecke legt dagegen der ausgewiesene Agent
# ab. Siehe MAX_FRAGE/MAX_FRAGE_TEILE in relay.php.
PHP_MAX_FRAGE             = 4096
PHP_MAX_FRAGE_TEILE       = 160


def zerlege(text, max_bytes=PHP_MAX_STUECK, max_json=PHP_MAX_JSON):
    """Teilt eine Zeichenkette in uebertragbare Stuecke.

    Nur der PHP-Weg braucht das -- ueber WebDAV gemessen bis 12 MB in einem
    Rutsch (README.md), keine Stueckelung noetig.

    ZWEI Grenzen, nicht eine, und das ist kein Uebereifer:

      max_bytes   misst der Vermittler am DEKODIERTEN Inhalt (MAX_STUECK).
      max_json    ist der ganze POST-Rumpf (MAX_RUMPF).

    Die beiden laufen auseinander, sobald Text Anfuehrungszeichen,
    Rueckwaertsschraegstriche oder Steuerzeichen enthaelt: JSON verdoppelt
    sie, Steuerzeichen werden sechsfach lang. Ein Stueck, das die erste
    Grenze haelt, kann die zweite reissen -- und dann kommt HTTP 413 zurueck,
    im Betrieb und nicht im Test.

    Geschnitten wird an Zeichengrenzen, nie an Byte-Grenzen: Eine in der
    Mitte zerschnittene UTF-8-Folge waere in beiden Haelften unlesbar.
    """
    if not text:
        return ['']
    stuecke = []
    i, n = 0, len(text)
    while i < n:
        j = min(n, i + max_bytes)
        while j > i + 1:
            teil = text[i:j]
            b  = len(teil.encode('utf-8'))
            jb = len(json.dumps(teil, ensure_ascii=False).encode('utf-8'))
            if b <= max_bytes and jb <= max_json:
                break
            # Verhaeltnismaessig verkleinern statt Zeichen fuer Zeichen --
            # das trifft fast immer im zweiten Anlauf.
            faktor = min(max_bytes / b, max_json / jb)
            neu = i + max(1, int((j - i) * faktor * 0.97))
            j = neu if neu < j else j - 1
        stuecke.append(text[i:j])
        i = j
    return stuecke


class PhpTransport:
    """Der urspruengliche AHPT-Weg: ein PHP-Vermittler auf einem Webspace.

    Uebernimmt wortgetreu, was `relay_agent.py` vor der Transport-
    Abstraktion selbst tat: Warteschlange mit ETag/Folge-Absicherung,
    Fragen mit Stueck-Wiederzusammensetzung beim Hochladen, Antworten mit
    Stueckelung und Wiederholung je Stueck beim Ablegen. Nichts davon ist
    eine bessere Bauart -- es ist die Anpassung an PHP-Grenzen, die WebDAV
    nicht kennt (siehe `WebDavTransport`).

    `zaehle_fn`/`log_fn`/`einmal_fn` sind dieselben Zaehl- und Melde-
    Funktionen wie im Agenten selbst, injiziert statt importiert: Diese
    Datei soll nichts von Agent-spezifischen Zaehlernamen wissen muessen,
    aber der Agent soll nach der Abspaltung weiterhin GENAU dieselben
    Zaehler und Meldetexte sehen wie zuvor. `zaehler_dict` ist derselbe
    Zaehler nochmal als blosses dict, weil `netz.sende_json` selbst
    hineinschreibt (503-Wiederholungen) -- ein zweites, eigenes dict wuerde
    diese Zaehlung vom Rest des Agenten trennen.
    """

    art = 'php'

    def __init__(self, name, basis, geheimnis, version,
                 unbedingt_nach=PHP_UNBEDINGT_NACH,
                 frage_max_alter=PHP_FRAGE_MAX_ALTER,
                 gedaechtnis=PHP_GEDAECHTNIS,
                 timeout=8, zaehle_fn=None, log_fn=None, einmal_fn=None,
                 zaehler_dict=None):
        # `geheimnis` darf leer/None sein: Der CLIENT braucht es NICHT
        # (er stellt Fragen, dafuer verlangt relay.php keinen Ausweis --
        # nur der AGENT weist sich damit aus, wenn er Stuecke oder die
        # Antwort ablegt). Ein client-seitig gebauter PhpTransport uebergibt
        # hier einfach nichts; die client-seitigen Methoden (`lege_frage`,
        # `hole_antwort`) brauchen den Wert nicht, und die agent-seitigen
        # (`lege_antwort`, `stueck`) wuerden mit einem leeren Wert ohnehin
        # nur konsequent abgewiesen -- kein stilles Falsch-Ausweisen.
        self.name = name
        self.basis = basis.rstrip('/')
        self.schlange_url = self.basis + '/ahpt/warteschlange.json'
        self.relay_url = self.basis + '/relay.php'
        self.geheimnis = geheimnis or ''
        self.version = version
        self.unbedingt_nach = unbedingt_nach
        self.frage_max_alter = frage_max_alter
        self.gedaechtnis = gedaechtnis
        self.timeout = timeout
        self._zaehle = zaehle_fn or (lambda *a, **k: None)
        self._log = log_fn or (lambda *a, **k: None)
        self._einmal = einmal_fn or (lambda *a, **k: None)
        self._zaehler_dict = zaehler_dict

        self.etag = None
        self.letzte_folge = None
        self.nur_304 = 0
        self.letzte_volle = 0.0
        # Zu alte Fragen, schon gezaehlt -- eigenes Gedaechtnis, damit
        # dieselbe stehengebliebene Marke nicht bei jedem Durchgang erneut
        # gezaehlt wird, ohne das GETEILTE `erledigt`-Gedaechtnis des
        # Agenten anzufassen (das bleibt ueber alle Transportwege hinweg
        # gemeinsam -- siehe Agent.durchgang).
        self._veraltet_gemeldet = {}

    # -------------------------------------------------- AHPT-Operationen

    def hole_offene_marken(self, bekannt):
        jetzt = time.time()
        for m, t in list(self._veraltet_gemeldet.items()):
            if jetzt - t > self.gedaechtnis:
                del self._veraltet_gemeldet[m]

        # In Abstaenden unbedingt holen, damit ein uebersehener ETag den
        # Agenten nicht dauerhaft blind macht (siehe PHP_UNBEDINGT_NACH).
        unbedingt = (jetzt - self.letzte_volle) >= self.unbedingt_nach
        code, koerper, neuer_etag = netz.hole(
            self.schlange_url, None if unbedingt else self.etag,
            timeout=self.timeout)

        if code == 304:
            self._zaehle('poll_304')
            self.nur_304 += 1
            return [], None
        if code == 404:
            # KEIN Fehler: Solange nie jemand gefragt hat, gibt es die
            # Datei nicht. relay.php legt sie mit der ersten Frage an.
            self._zaehle('schlange_leer')
            self._einmal('leer-%s' % self.name,
                          '  [%s] Noch keine Warteschlange -- normal, bis '
                          'die erste Frage kommt.' % self.name)
            return [], None
        if code != 200:
            self._zaehle('poll_fehler')
            self._einmal('poll-%s' % self.name,
                          '  [%s] Warteschlange nicht erreichbar (HTTP %s)'
                          % (self.name, code))
            return None, 'HTTP %s' % code

        self._zaehle('poll_ok')
        if unbedingt:
            self.letzte_volle = jetzt
        if neuer_etag:
            self.etag = neuer_etag
        try:
            schlange = json.loads(koerper.decode('utf-8', 'replace'))
            offen = schlange.get('offen', [])
        except Exception:
            self._zaehle('poll_fehler')
            self._einmal('schlange-kaputt-%s' % self.name,
                          '  [%s] Warteschlange nicht lesbar -- schreibt '
                          'die Gegenseite nicht atomar?' % self.name)
            return None, 'kaputt'

        # Fortlaufende Nummer der Warteschlange. Springt sie weiter,
        # waehrend wir nur 304er bekommen haben, ist uns eine Aenderung
        # entgangen -- der ETag hat sie nicht angezeigt.
        folge = schlange.get('folge')
        if isinstance(folge, int):
            if self.letzte_folge is not None and self.nur_304 > 0 \
                    and folge > self.letzte_folge + 1:
                self._zaehle('schlange_verpasst')
                self._einmal(
                    'verpasst-%s' % self.name,
                    '  [%s] UEBERSEHENE AENDERUNG: Warteschlange sprang von '
                    '%d auf %d, dazwischen nur 304er.'
                    % (self.name, self.letzte_folge, folge))
                self._einmal(
                    'verpasst2',
                    '  Ursache ist fast immer der ETag: Apache bildet ihn '
                    'aus Sekunde und Groesse,')
                self._einmal(
                    'verpasst3',
                    '  und zwei gleich lange Warteschlangen in derselben '
                    'Sekunde sind dann nicht zu unterscheiden.')
                self._einmal(
                    'verpasst4',
                    '  Abhilfe: `FileETag INode MTime Size` in die '
                    '.htaccess (siehe htaccess-beispiel).')
            self.letzte_folge = folge
        self.nur_304 = 0

        marken = []
        for eintrag in offen:
            if not isinstance(eintrag, dict):
                continue
            marke = eintrag.get('marke', '')
            if not isinstance(marke, str) \
                    or not re.fullmatch(r'[0-9a-f]{32}', marke):
                continue
            if marke in bekannt:
                continue
            if jetzt - eintrag.get('ts', 0) > self.frage_max_alter:
                if marke not in self._veraltet_gemeldet:
                    self._zaehle('frage_zu_alt')
                    self._veraltet_gemeldet[marke] = jetzt
                continue
            marken.append(marke)
        return marken, None

    def hole_frage(self, marke):
        """Holt die Fragedatei. Die Wiederzusammensetzung gestueckelter
        Fragen bleibt beim Aufrufer (`hole_frage_stueck` je Teil) --
        der kennt Fassung und Verschluesselung, die hier nichts angehen.
        Zaehlt/meldet Fehlschlaege selbst, mit denselben Namen wie vor der
        Abspaltung in diese Klasse.
        """
        code, koerper, _ = netz.hole(
            '%s/ahpt/frage_%s.json' % (self.basis, marke),
            timeout=self.timeout)
        if code != 200:
            self._zaehle('frage_unlesbar')
            self._einmal('frage-weg-%s' % self.name,
                          '  [%s] Fragedatei nicht abrufbar (HTTP %s)'
                          % (self.name, code))
            return False, None, 'HTTP %s' % code
        try:
            umschlag = json.loads(koerper.decode('utf-8', 'replace'))
        except Exception:
            self._zaehle('frage_unlesbar')
            return False, None, 'kein JSON'
        if not isinstance(umschlag, dict):
            self._zaehle('frage_unlesbar')
            return False, None, 'kein Objekt'
        return True, umschlag, ''

    def hole_frage_stueck(self, dateiname):
        """Holt EIN hochgeladenes Fragestueck (`fstueck_*.json`) als rohe
        Bytes. Die strukturelle Pruefung (Marke, Teilnummer, Anzahl) bleibt
        beim Aufrufer -- der kennt die Fassung des Protokolls, diese
        Klasse soll sie nicht kennen muessen.
        """
        code, koerper, _ = netz.hole(
            '%s/ahpt/%s' % (self.basis, dateiname), timeout=self.timeout)
        if code != 200:
            return False, None, 'HTTP %s' % code
        return True, koerper, ''

    def lege_antwort(self, marke, stuecke, metadaten, feldname, verf):
        """Legt eine BEREITS gestueckelte Antwort ab und wiederholt jedes
        Stueck einzeln (siehe PHP_STUECK_WIEDERHOLUNGEN-Kommentar in
        relay_agent.py).

        `stuecke` ist die fertige Liste (mindestens ein Element -- vom
        Aufrufer mit `transport.zerlege()` gebildet), `metadaten` die
        begleitenden Felder OHNE das Inhaltsfeld selbst, `feldname` der
        Name, unter dem der letzte/einzige Teil im Verzeichnis auftaucht
        ("chiffre" bei Verschluesselung, sonst "inhalt").

        BEWUSST OHNE eigene Deckelpruefung (MAX_TEILE): Ob eine zu grosse
        Antwort durch eine leere Fehlerantwort ERSETZT wird, ist eine
        Protokollentscheidung, keine Transportentscheidung -- bei
        verschluesselten Sitzungen etwa wird dabei NICHTS Lesbares
        nachgereicht, um keine Information ausserhalb der Verschluesselung
        preiszugeben. Das entscheidet `Agent.lege_ab`, bevor diese Methode
        ueberhaupt aufgerufen wird.

        REIHENFOLGE IST VERBINDLICH: erst alle Stuecke, dann das
        Verzeichnis -- siehe Agent.lege_ab in relay_agent.py.
        """
        teile = len(stuecke)

        if teile > 1:
            for i, s in enumerate(stuecke):
                for versuch in range(1, PHP_STUECK_WIEDERHOLUNGEN + 1):
                    code, daten = netz.sende_json(
                        self.relay_url + '?action=stueck',
                        {'v': self.version, 'krypto': verf, 'marke': marke,
                         'teil': i, 'teile': teile, 'nutzlast': s},
                        self.geheimnis, timeout=self.timeout,
                        zaehler=self._zaehler_dict)
                    if code == 200 and daten.get('ok'):
                        break
                    self._zaehle('stueck_wiederholt')
                    if versuch < PHP_STUECK_WIEDERHOLUNGEN:
                        time.sleep(min(5.0, 0.5 * (2 ** (versuch - 1))))
                else:
                    # Alle Versuche fuer DIESES Stueck verbraucht. Aufgeben,
                    # aber KEIN Verzeichnis ablegen. Lieber gar keine
                    # Antwort als eine, die auf Luecken zeigt.
                    self._zaehle('stueck_fehler')
                    self._log(
                        '  %s  Stueck %d/%d nicht abgelegt nach %d '
                        'Versuchen: HTTP %s %s'
                        % (marke[:8], i + 1, teile, PHP_STUECK_WIEDERHOLUNGEN,
                           code, daten.get('fehler', '')))
                    return False, 'stueck-fehler'

        nutz = dict(metadaten)
        nutz[feldname] = '' if teile > 1 else stuecke[0]

        code, daten = netz.sende_json(
            self.relay_url + '?action=antwort',
            {'v': self.version, 'krypto': verf, 'marke': marke,
             'teile': teile, 'nutzlast': nutz},
            self.geheimnis, timeout=self.timeout, zaehler=self._zaehler_dict)

        if code == 200 and daten.get('ok'):
            self._zaehle('beantwortet')
            return True, ''
        if code == 404:
            self._zaehle('marke_verfallen')
            self._log('  %s  zu spaet -- Marke war schon verfallen'
                       % marke[:8])
            return False, 'verfallen'
        self._zaehle('ablage_fehler')
        self._log('  %s  ANTWORT NICHT ABGELEGT: HTTP %s %s'
                   % (marke[:8], code, daten.get('fehler', '')))
        return False, 'HTTP %s' % code

    # Kein serverseitiges Aufraeumen noetig oder moeglich: relay.php raeumt
    # verfallene Marken selbst weg (MARKE_TTL). Anders als bei WebDAV gibt
    # es hier keinen Papierkorb, den der Agent leeren muesste.
    def loesche_frage(self, marke):
        pass

    def loesche_antwort(self, marke):
        pass

    # ------------------------------------------- Client-seitige Haelfte

    def lege_frage(self, marke, umschlag):
        """Stellt eine neue Frage -- mit der VOM CLIENT vorgegebenen Marke.

        relay.php uebernimmt sie, statt selbst eine zu erzeugen (siehe
        Kommentar dort) -- noetig, damit dieselbe Marke einen Transport-
        wechsel ueberlebt, und zwingend fuer WebDAV: dort gibt es keine
        Ablage, die eine Marke ERZEUGT, ein PUT braucht sie vorher.

        Stueckelt automatisch, wenn die Chiffre nicht in eine einzelne
        Nachricht passt -- relay.php nimmt eine gestueckelte Frage nur
        verschluesselt an (`k !== 'keine'`).
        """
        krypto = umschlag.get('krypto', 'keine')
        nutz = umschlag.get('nutzlast') or {}
        chiffre = nutz.get('chiffre', '') if krypto != 'keine' else ''

        if krypto != 'keine' and len(chiffre) > PHP_MAX_FRAGE:
            return self._lege_frage_gestueckelt(marke, krypto, chiffre)

        code, daten = netz.sende_json(
            self.relay_url + '?action=frage',
            {'v': self.version, 'krypto': krypto, 'marke': marke,
             'nutzlast': nutz},
            self.geheimnis, timeout=15, zaehler=self._zaehler_dict)
        if code == 200 and daten.get('ok'):
            return True, ''
        if code == 409:
            # "Marke bereits in Gebrauch": Das ist NUR ein Fehler, wenn es
            # jemand ANDERES war -- bei einer eigenen Wiederholung (siehe
            # Client.frage in ahpt_client.py: dieselbe Marke ueberlebt
            # einen Transportwechsel und kann denselben Weg ein zweites
            # Mal treffen, wenn nur zwei Wege konfiguriert sind) heisst es
            # schlicht: sie liegt schon da, genau wie gewollt. Am
            # 07.09.2026 im Mischbetrieb-Test gefunden -- ohne diese
            # Ausnahme scheiterte jede Wiederholung, die zufaellig auf
            # denselben Weg zurueckkam, obwohl nichts falsch gelaufen war.
            return True, ''
        return False, 'HTTP %s %s' % (code, daten.get('fehler', ''))

    def _lege_frage_gestueckelt(self, marke, krypto, chiffre):
        """Eine grosse Frage in Stuecken hinaufbringen (Spiegelbild von
        `lege_antwort`s Stueckelung, nur beim Hochladen statt beim Ablegen).

        Verschluesselt wird VORHER, als Ganzes -- der Aufrufer liefert
        `chiffre` schon fertig. Geteilt wird erst der fertige Geheimtext,
        aus demselben Grund wie bei der Antwort: ein einzeln veraendertes
        Stueck soll das Ganze unbrauchbar machen, nicht nur einen Teil.
        """
        teile = max(2, (len(chiffre) + PHP_MAX_STUECK - 1) // PHP_MAX_STUECK)
        if teile > PHP_MAX_FRAGE_TEILE:
            return False, ('zu gross: %d Stuecke, erlaubt sind %d'
                            % (teile, PHP_MAX_FRAGE_TEILE))

        code, daten = netz.sende_json(
            self.relay_url + '?action=frage',
            {'v': self.version, 'krypto': krypto, 'marke': marke,
             'teile': teile, 'nutzlast': {'chiffre': ''}},
            self.geheimnis, timeout=30, zaehler=self._zaehler_dict)
        if code == 409:
            # Siehe Kommentar in lege_frage: 409 bei einer eigenen
            # Wiederholung ist kein Fehler -- das Verzeichnis liegt schon
            # da. Anders als beim einfachen Fall gibt es hier aber noch
            # Stuecke UND einen frage_fertig-Ruf danach -- beide laufen
            # bei einer eigenen Wiederholung schon vollstaendig durch,
            # sonst waere `lege_frage` beim ERSTEN Mal nie zurueckgekehrt
            # (der Ablauf ist synchron: erst alle Stuecke, dann fertig,
            # dann return). Ein zweiter Anlauf braeuchte also nur noch
            # dieselben Stuecke NOCHMAL abzulegen -- unnoetig, und bei
            # `frage_fertig` sogar SCHAEDLICH: relay.php weist Stuecke zu
            # einer bereits "bereit"-gemeldeten Marke mit 404 ab (siehe
            # `case 'frage_stueck'`), weil eine bereits sichtbare Marke
            # nichts mehr annehmen soll. Am 07.09.2026 im Mischbetrieb-
            # Test genau so gefunden: der zweite Anlauf schlug NUR wegen
            # dieses ueberfluessigen Nachholversuchs fehl, nicht weil
            # irgendetwas wirklich kaputt war. Deshalb hier sofort zurueck,
            # ohne Stuecke oder frage_fertig ein zweites Mal anzufassen.
            return True, ''
        if not (code == 200 and daten.get('ok')):
            return False, 'HTTP %s %s' % (code, daten.get('fehler', ''))

        # Schnittgroesse aus der Stueckzahl ableiten, nicht umgekehrt in
        # feste PHP_MAX_STUECK-Bloecke schneiden -- sonst waere bei einer
        # kurzen Chiffre und teile=2 das zweite Stueck leer, und leer
        # scheitert bei `frage_stueck` an derselben Pruefung.
        stueckgroesse = -(-len(chiffre) // teile)
        for i in range(teile):
            stueck = chiffre[i * stueckgroesse:(i + 1) * stueckgroesse]
            for versuch in range(1, PHP_STUECK_WIEDERHOLUNGEN + 1):
                code, daten = netz.sende_json(
                    self.relay_url + '?action=frage_stueck',
                    {'v': self.version, 'krypto': krypto, 'marke': marke,
                     'teil': i, 'teile': teile, 'nutzlast': stueck},
                    self.geheimnis, timeout=30, zaehler=self._zaehler_dict)
                if code == 200 and daten.get('ok'):
                    break
                if versuch < PHP_STUECK_WIEDERHOLUNGEN:
                    time.sleep(min(5.0, 0.5 * (2 ** (versuch - 1))))
            else:
                return False, ('Stueck %d/%d nach %d Versuchen abgewiesen: '
                                'HTTP %s %s'
                                % (i + 1, teile, PHP_STUECK_WIEDERHOLUNGEN,
                                   code, daten.get('fehler', '')))

        # Erst jetzt sichtbar machen. relay.php sieht selbst nach, ob
        # wirklich alle Stuecke daliegen.
        code, daten = netz.sende_json(
            self.relay_url + '?action=frage_fertig',
            {'v': self.version, 'krypto': krypto, 'marke': marke,
             'teile': teile},
            self.geheimnis, timeout=30, zaehler=self._zaehler_dict)
        if code == 200 and daten.get('ok'):
            return True, ''
        return False, 'HTTP %s %s' % (code, daten.get('fehler', ''))

    def hole_antwort(self, marke):
        """Fragt direkt nach `antwort_<marke>.json` -- statisch, kein PHP.

        Der urspruengliche Client fragte stattdessen erst die Warteschlange
        (ob die Marke in `fertig` steht) und ERST DANN die Antwortdatei ab --
        einzig wegen CORS im Browser-Portal (ein 404 vom Hoster traegt dort
        keine CORS-Kopfzeile und erreicht das JavaScript nicht als 404,
        siehe portal/ahpt.js). Das gilt fuer diesen Python-Client nicht, und
        der direkte Weg ist derselbe Kostenpunkt (eine statische Datei),
        nur ohne den zweiten Umlauf.
        """
        code, koerper, _ = netz.hole(
            '%s/ahpt/antwort_%s.json' % (self.basis, marke),
            timeout=self.timeout)
        if code == 404:
            return False, None, ''            # noch nicht da -- kein Fehler
        if code != 200:
            grund = ('nicht erreichbar: %s' % koerper.decode('utf-8', 'replace')
                     if code == 0 else 'HTTP %s' % code)
            return False, None, grund
        try:
            return True, json.loads(koerper.decode('utf-8', 'replace')), ''
        except Exception as e:
            return False, None, 'Antwort ist kein JSON: %s' % e

    def hole_antwort_stueck(self, dateiname):
        """Holt EIN Antwort-Stueck als rohe Bytes -- Spiegelbild von
        `hole_frage_stueck`, nur in die andere Richtung. Die strukturelle
        Pruefung (Marke, Teilnummer, Anzahl) bleibt beim Aufrufer.
        """
        code, koerper, _ = netz.hole(
            '%s/ahpt/%s' % (self.basis, dateiname), timeout=self.timeout)
        if code != 200:
            return False, None, 'HTTP %s' % code
        return True, koerper, ''


# ------------------------------------------------------------- Gesundheit

class Gesundheit:
    """Verfolgt Fehlschlaege je Transportweg, sperrt ihn nach wiederholtem
    Versagen voruebergehend.

    Ohne das wuerde jede einzelne Nachricht bei einem DAUERHAFT toten Weg
    erst dessen volle Frist verstreichen lassen muessen, bevor sie zum
    naechsten Weg wechselt -- fuer immer, bis ein Mensch es bemerkt.

    Die Sperrzeit waechst mit jedem weiteren Fehlschlag ueber die Schwelle
    (gedeckelt), das ist das uebliche "halb offene" Kreislauf-Unterbrecher-
    Muster: nach der Sperrzeit genau EIN Testversuch, kein Dauerfeuer gegen
    einen Weg, der ohnehin nicht antwortet.
    """
    SCHWELLE = 2
    SPERRZEIT = 300
    SPERRZEIT_DECKEL = 3600

    def __init__(self, zustand=None):
        self.zustand = zustand if zustand is not None else {}

    def verfuegbar(self, name, jetzt=None):
        jetzt = jetzt if jetzt is not None else time.time()
        eintrag = self.zustand.get(name)
        if not eintrag or not eintrag.get('gesperrt_bis'):
            return True
        return jetzt >= eintrag['gesperrt_bis']

    def erfolg(self, name):
        self.zustand[name] = {'fehler': 0, 'gesperrt_bis': None}

    def fehlschlag(self, name, jetzt=None):
        jetzt = jetzt if jetzt is not None else time.time()
        eintrag = self.zustand.setdefault(
            name, {'fehler': 0, 'gesperrt_bis': None})
        eintrag['fehler'] += 1
        if eintrag['fehler'] >= self.SCHWELLE:
            ueberschuss = eintrag['fehler'] - self.SCHWELLE
            dauer = min(self.SPERRZEIT * (2 ** ueberschuss),
                        self.SPERRZEIT_DECKEL)
            eintrag['gesperrt_bis'] = jetzt + dauer
            return eintrag['gesperrt_bis']
        return None

    def stand(self, name, jetzt=None):
        """Fuer die Uebersicht im Portal/CLI: verfuegbar oder gesperrt."""
        jetzt = jetzt if jetzt is not None else time.time()
        eintrag = self.zustand.get(name)
        if not eintrag or not eintrag.get('gesperrt_bis'):
            return 'verfuegbar'
        if jetzt >= eintrag['gesperrt_bis']:
            return 'wird erneut geprueft'
        rest = int(eintrag['gesperrt_bis'] - jetzt)
        return ('gesperrt -- noch %ds (%d Fehlschlaege in Folge)'
                % (rest, eintrag['fehler']))


def lies_gesundheit(pfad):
    """Gesundheitszustand aus einer JSON-Datei laden.

    Fuer den Kommandozeilen-Client gedacht, dessen Prozess nach jedem
    Aufruf endet -- der Agent und das Portal koennen denselben Zustand
    stattdessen einfach im Speicher halten, ueber die ganze Laufzeit.
    """
    try:
        with open(pfad, 'r', encoding='utf-8') as f:
            return Gesundheit(json.load(f))
    except (OSError, ValueError):
        return Gesundheit()


def schreibe_gesundheit(pfad, gesundheit):
    """Atomar schreiben -- ein abgebrochener Schreibvorgang darf die Datei
    nicht halb befuellt zuruecklassen, sonst scheitert der naechste Aufruf
    schon beim Lesen."""
    tmp = pfad + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(gesundheit.zustand, f)
    os.replace(tmp, pfad)
