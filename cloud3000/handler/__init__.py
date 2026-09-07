#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handler/__init__.py -- der Vertrag zwischen Kern und Diensten

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU DIESE TRENNUNG
-------------------
In `tunnel_agent.py` sind Transport und kiwix miteinander verschmolzen. Das
war richtig, solange es genau einen Dienst gab. Fuer beliebige Dienste muss
der Kern aufhoeren, den Dienst zu kennen -- und genau da entsteht die
Gefahr, vor der `Zukunftsmusik.txt` unter 3B warnt:

    "Deine aktuelle Version ist deshalb so sicher, weil sie dumm ist."

Die Aufloesung ist, WELCHE Dummheit wo bleibt:

    Der Kern wird inhaltsblind. Er darf das -- er hat nie etwas vom Inhalt
    gebraucht.

    Der Handler bleibt nicht ueberredbar. Er darf das nie verlieren.

Deshalb steht die gesamte Weissliste im Handler, nicht im Kern und schon
gar nicht im Netz. Der Kern prueft Protokollfassung, Marke, Form und
Deckel -- danach ruft er auf und mischt sich nicht ein.

DIE FUENF PFLICHTEN EINES HANDLERS
-----------------------------------
1. Er nennt seine AKTIONEN. Weissliste, nie Ausschlussliste. Eine
   Ausschlussliste ist einen Tippfehler von einem offenen Tor entfernt.
2. Er prueft seine Konfiguration BEIM START und wirft `KonfigFehler`, wenn
   etwas fehlt. Nicht beim ersten Aufruf -- dann faellt es erst auf, wenn
   ein Besucher wartet.
3. Er prueft JEDES Feld aus `daten` selbst, auch wenn schon jemand geprueft
   hat. Eine Schranke, die nur an einer Stelle steht, ist eine Schranke auf
   Zuruf.
4. Er gibt Text oder Bytes zurueck, NIE HTML zum Einbetten. Sonst traegt
   der Inhalt eines Dienstes Skript in die Seite des Besuchers.
5. Er bringt seinen eigenen Selbsttest mit -- und ohne den wird er nicht
   geladen.

Punkt 5 ist der wichtigste und der einzige, der erzwungen wird. Die 27
Agent-Pruefungen der Referenzumsetzung waren kein Beiwerk; sie sind der
Grund, warum man dem Agenten glauben kann. Sie gehoeren dorthin, wo die
Schranken stehen. Wer einen Handler hinzufuegt, muss seine Schranken
beschreiben, sonst laeuft der Agent nicht an. Das ist die einzige Art, wie
eine Weissliste mitwachsen kann, ohne dass jemand sie im Kopf behaelt.
"""

import base64
import importlib


class KonfigFehler(Exception):
    """Die Konfiguration ist unbrauchbar. Der Agent laeuft nicht an.

    Absichtlich toedlich statt uebergangen: Ein Agent, der mit halber
    Konfiguration startet, antwortet auf jede Frage "nichts gefunden" --
    und das sieht von aussen genauso aus wie ein leeres Archiv.
    """


# ------------------------------------------------------------- Antworten
#
# Der Kern setzt `quelle` spaeter auf den Dienstnamen aus der config.toml.
# Ein Handler koennte das auch selbst -- aber dann gaebe es zwei Stellen,
# an denen derselbe Name entsteht, und irgendwann liefen sie auseinander.

def sicherer_titel(t):
    """Entschaerft einen Anzeigenamen, der zurueckgespiegelt wird.

    `titel` ist VON AUSSEN BESTIMMT: Bei einer Suche ist es der Suchbegriff,
    bei einer Datei der angefragte Pfad. Er geht unveraendert an den Browser
    zurueck. Schreibt ein Entwickler dort `innerHTML = a.titel`, hat ein
    Angreifer Stored XSS mit frei gewaehltem Inhalt -- und er braucht dafuer
    weder eine Datei noch ein Archiv, nur eine Frage.

    Ohne die spitzen Klammern laesst sich kein Tag oeffnen.

    DAS MACHT `innerHTML` NICHT SICHER. `inhalt` bleibt beliebig, und das
    muss es auch: Wer die Nutzlast saeubert, liefert nicht mehr aus, sondern
    verfaelscht. Es nimmt der schaerfsten Kante die Spitze, mehr nicht --
    der richtige Weg bleibt `textContent`, und dafuer gibt es
    `AhptClient.zeige()` im SDK.

    Eine Stelle, nicht drei: Jede Antwort entsteht hier, also wird auch hier
    entschaerft. Ein Handler, der es selbst taete, waere die zweite Fassung
    derselben Regel -- und an zwei Fassungen derselben Sache sind in diesem
    Projekt schon mehrere Fehler gestorben.
    """
    t = str(t)
    t = ''.join(c for c in t if c >= ' ' and c != '\x7f' and c not in '<>')
    return t[:200]


def text_antwort(inhalt, titel=''):
    """Reiner Text. Kein HTML -- der Besucher darf das nie als Markup
    einhaengen, und mit reinem Text kann er es auch nicht versehentlich."""
    return {'gefunden': True, 'titel': sicherer_titel(titel), 'quelle': '',
            'inhalt_typ': 'text', 'inhalt': str(inhalt)}


def bytes_antwort(rohbytes, titel=''):
    """Bytes, base64-kodiert. Fuer Bilder, PDF, alles Binaere."""
    return {'gefunden': True, 'titel': sicherer_titel(titel), 'quelle': '',
            'inhalt_typ': 'base64',
            'inhalt': base64.b64encode(rohbytes).decode('ascii')}


def nichts(grund=''):
    """Bearbeitet, nichts gefunden.

    Das ist ausdruecklich KEIN Fehler und muss vom Fehler unterscheidbar
    bleiben: "Es gibt den Artikel nicht" und "Ich konnte nicht nachsehen"
    sind fuer den Besucher zwei verschiedene Auskuenfte, und die zweite als
    die erste auszugeben ist eine Luege mit Anschein von Auskunft.
    """
    return {'gefunden': False, 'titel': '', 'quelle': '',
            'inhalt_typ': 'text', 'inhalt': '', 'grund': str(grund)}


# --------------------------------------------------------------- Vertrag

class Handler:
    """Basis. Wer erbt, erfuellt die fuenf Pflichten oben."""

    ART = ''                    # muss zum Dateinamen handler/<ART>.py passen
    AKTIONEN = frozenset()      # Weissliste

    def __init__(self, konfig):
        """konfig ist der [[dienst]]-Block aus der config.toml.

        Hier wird geprueft, nicht spaeter. Was fehlt, wirft KonfigFehler.
        """
        self.konfig = konfig
        self.name = konfig.get('name', '')

    def bereit(self):
        """Einmal beim Start, MIT Netz. Rueckgabe: (bereit, hinweis).

        Getrennt von __init__, weil __init__ ohne Netz auskommen muss --
        sonst laesst sich der Selbsttest nicht ohne den Dienst fahren, und
        ein Selbsttest, der den Dienst braucht, prueft nicht die Schranken,
        sondern das Wetter.

        Wer hier False meldet, wird nicht bedient; der Kern sagt es beim
        Start und nennt den Grund. Ein Dienst, der still auf jede Frage
        "nichts gefunden" antwortet, sieht von aussen aus wie ein leeres
        Archiv -- und niemand sucht dann nach der Ursache.
        """
        return True, ''

    def bearbeite(self, aktion, daten):
        """Loest eine Frage lokal auf. Gibt eine Antwort nach oben zurueck.

        `aktion` hat der Kern bereits gegen AKTIONEN geprueft. `daten` hat
        er NICHT geprueft und kann es nicht -- das ist die Aufgabe hier.
        """
        raise NotImplementedError

    def selbsttest(self):
        """Prueft die eigenen Schranken. Ohne Netz, ohne den Dienst.

        Rueckgabe: Liste von (beschreibung, bestanden, hinweis).

        Hier gehoeren die Angriffsversuche hin, nicht die Gutfaelle: fremde
        Adresse, Pfadwanderung, Steuerzeichen, fremdes Ziel. Ein Selbsttest,
        der nur zeigt, dass das Erlaubte klappt, beweist nichts ueber das
        Verbotene.
        """
        raise NotImplementedError


def lade(art):
    """Laedt handler/<art>.py und gibt die Klasse zurueck.

    Prueft dabei, dass der Handler seine Pflichten erfuellt. Ein Handler,
    der beim Laden durchfaellt, laesst den Agenten gar nicht erst
    anlaufen -- und das ist der Sinn: Der spaeteste Zeitpunkt, an dem eine
    fehlende Schranke noch billig ist, ist der Start.
    """
    if not isinstance(art, str) or not art.isidentifier() or art.startswith('_'):
        raise KonfigFehler('Unbrauchbare Handler-Art: %r' % (art,))
    try:
        modul = importlib.import_module('handler.' + art)
    except ImportError as e:
        raise KonfigFehler('Handler-Art "%s" gibt es nicht (handler/%s.py). '
                           'Vorhanden: %s' % (art, art, ', '.join(vorhandene())))
    kl = getattr(modul, 'HANDLER', None)
    if kl is None or not isinstance(kl, type) or not issubclass(kl, Handler):
        raise KonfigFehler('handler/%s.py nennt kein HANDLER, das von '
                           'Handler erbt.' % art)
    if not kl.AKTIONEN:
        raise KonfigFehler('Handler "%s" nennt keine AKTIONEN. Eine leere '
                           'Weissliste ist keine Weissliste.' % art)
    for a in kl.AKTIONEN:
        if not (isinstance(a, str) and a and a.islower()
                and a.replace('_', 'x').isalnum()):
            raise KonfigFehler('Handler "%s": Aktion %r passt nicht zu '
                               '^[a-z][a-z0-9_]*$' % (art, a))
    # DIE Regel: kein Selbsttest, kein Laden.
    if kl.selbsttest is Handler.selbsttest:
        raise KonfigFehler(
            'Handler "%s" bringt keinen selbsttest() mit.\n'
            '         Das ist keine Formsache. Ein Handler ist die Stelle, an\n'
            '         der die Weissliste steht -- und eine Weissliste, deren\n'
            '         Wirkung niemand nachprueft, ist eine Behauptung.' % art)
    return kl


def vorhandene():
    """Namen der Dateien in handler/, ohne __init__."""
    import os
    hier = os.path.dirname(os.path.abspath(__file__))
    return sorted(d[:-3] for d in os.listdir(hier)
                  if d.endswith('.py') and not d.startswith('_'))
