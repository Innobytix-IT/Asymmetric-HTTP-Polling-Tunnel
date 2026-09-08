#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
starten.py -- AHPT Cloud bedienen, ohne Terminal

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Drei Dinge, die vorher nur ueber eine Konsole gingen -- oder gar nicht:

  1. Den Einrichtungs-Assistenten ueberhaupt starten. Wer AHPT Cloud auf
     einem Linux Mint oder einem Windows-Rechner benutzt, hat mit einer
     Konsole nichts zu tun und soll auch nicht anfangen muessen.
  2. Den Agenten spaeter anhalten oder wieder starten. Das ging bisher GAR
     NICHT ueber die Oberflaeche: Der Assistent kennt zwar `stop` und
     `status`, aber die Seite ruft nur `start` auf. Wer den Agenten
     loswerden wollte, brauchte den Task-Manager.
  3. Nachsehen, ob der Vermittler noch mitspielt. Das ging bisher gar nicht,
     und es fehlte an der wichtigsten Stelle: "AHPT ist langsam geworden"
     hat bei freiem Webspace fast immer eine Ursache beim HOSTER -- gedrosselt
     oder ueberbucht -- und die sieht man ihm nicht an. Wer nicht messen
     kann, sucht den Fehler bei sich und findet ihn nie.

ZWEI PROZESSE, DIE MAN NICHT VERWECHSELN DARF
----------------------------------------------
Der ASSISTENT (einrichten.py) ist die Einrichtungsseite. Er laeuft nur,
solange man ihn braucht, und wird beim Schliessen dieses Fensters beendet --
er ist eine offene Tuer mit einem Zugangs-Token, die nicht laenger offen
stehen soll als noetig.

Der AGENT (relay_agent.py) ist AHPT selbst. Er laeuft entkoppelt weiter,
wenn dieses Fenster zugeht, und ueberlebt auch das Ende des Assistenten.
Genau so soll es sein: Wer sein Fenster schliesst, will nicht seine Cloud
abschalten. Zum Anhalten gibt es hier einen Knopf.

WAS DIESE DATEI AUSDRUECKLICH NICHT IST
----------------------------------------
Kein zweiter Assistent. Die Messung oben ist keiner: Sie richtet nichts
ein, sie sieht nach. Jeder EINRICHTUNGS-Schritt, den es hier gaebe,
muesste es zweimal geben: einmal in Tkinter und einmal im Browser. Zwei
Oberflaechen fuer dieselbe Sache laufen auseinander, sobald man eine davon
aendert -- und gepflegt wuerde am Ende nur eine. Hier steht deshalb nur, was
VOR oder NACH der Einrichtung noetig ist.

WENN ES KEINE OBERFLAECHE GIBT
-------------------------------
Auf einem Heimserver ohne Desktop gibt es kein Fenster, und auf manchen
Linux-Installationen fehlt tkinter (es steckt dort in einem eigenen Paket).
Dann sagt diese Datei, was zu tun ist, statt mit einem Importfehler
abzubrechen -- der Weg ueber die Konsole funktioniert ja unveraendert.

Aufruf:
    python3 starten.py
    Doppelklick (Windows: starten.pyw -- dann ohne Konsolenfenster)
"""

import os
import subprocess
import sys
import threading
import time

HIER = os.path.dirname(os.path.abspath(__file__))


def ohne_oberflaeche(grund):
    """Ohne Fenster bleibt die Konsole -- also den Weg dorthin zeigen."""
    print('AHPT Cloud')
    print('=' * 50)
    print()
    print('Ein Fenster laesst sich hier nicht oeffnen:')
    print('   %s' % grund)
    print()
    print('Es geht trotzdem, nur eben auf der Konsole:')
    print()
    print('   Einrichten:      python3 %s'
          % os.path.join(HIER, 'einrichten.py'))
    print('   Agent starten:   python3 %s --konfig ~/.ahpt/agent_privat.toml'
          % os.path.join(HIER, 'relay_agent.py'))
    print()
    return 1


# ------------------------------------------------------------- Autostart
#
# WARUM DAS HIERHER GEHOERT
# --------------------------
# Ohne Autostart ist AHPT nach jedem Neustart des Rechners tot, und der
# Nutzer muesste den Assistenten wieder oeffnen und zum Agenten-Schritt
# klicken. Das faellt niemandem von selbst ein -- und wer es einmal
# herausgefunden hat, macht es beim naechsten Mal trotzdem wieder falsch.
#
# Beide Wege unten kommen OHNE Administratorrechte aus. Ein Dienst
# (systemd, Windows-Dienst) waere sauberer, braucht aber genau die Rechte,
# die ein normaler Anwender nicht hat und nicht haben sollte.

def _autostart_pfad():
    if sys.platform.startswith('win'):
        return os.path.join(os.environ.get('APPDATA', ''), 'Microsoft',
                            'Windows', 'Start Menu', 'Programs', 'Startup',
                            'AHPT Cloud.bat')
    return os.path.expanduser('~/.config/autostart/ahpt-cloud.desktop')


def autostart_an():
    return os.path.isfile(_autostart_pfad())


def autostart_setzen(an, konfig):
    """Den Agenten beim Anmelden mitstarten -- oder eben nicht mehr."""
    pfad = _autostart_pfad()
    if not an:
        try:
            os.remove(pfad)
        except OSError:
            pass
        return

    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    agent = os.path.join(HIER, 'relay_agent.py')
    if sys.platform.startswith('win'):
        # pythonw statt python: sonst blitzt bei jeder Anmeldung ein
        # schwarzes Konsolenfenster auf und bleibt stehen.
        pyw = sys.executable.replace('python.exe', 'pythonw.exe')
        with open(pfad, 'w', encoding='utf-8') as f:
            f.write('@echo off\r\n')
            f.write('start "" "%s" "%s" --konfig "%s"\r\n'
                    % (pyw, agent, konfig))
    else:
        with open(pfad, 'w', encoding='utf-8') as f:
            f.write('[Desktop Entry]\n'
                    'Type=Application\n'
                    'Name=AHPT Cloud\n'
                    'Comment=Startet den AHPT-Agenten beim Anmelden\n'
                    'Exec=%s %s --konfig %s\n'
                    'Terminal=false\n'
                    'X-GNOME-Autostart-enabled=true\n'
                    % (sys.executable, agent, konfig))


def main():
    # Erst pruefen, ob ueberhaupt ein Fenster moeglich ist. Ein
    # Importfehler mitten im Programm waere fuer genau den Nutzer
    # unverstaendlich, fuer den diese Datei gedacht ist.
    if sys.platform.startswith('linux') and not (
            os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return ohne_oberflaeche('kein Bildschirm angeschlossen (DISPLAY fehlt)')
    try:
        import tkinter as tk
    except ImportError:
        return ohne_oberflaeche(
            'tkinter fehlt. Unter Debian/Ubuntu/Mint:\n'
            '   sudo apt install python3-tk')

    sys.path.insert(0, HIER)
    try:
        import einrichten
    except Exception as e:
        return ohne_oberflaeche('einrichten.py laesst sich nicht laden: %s' % e)

    einrichten._stand = einrichten.stand_lesen()
    PID = os.path.join(einrichten.KONFIG_ORDNER, 'agent_privat.pid')
    KONFIG = os.path.join(einrichten.KONFIG_ORDNER, 'agent_privat.toml')

    # Dieselbe Palette wie Portal und App -- Terminal-Gruen. Tkinter kann
    # keine Schatten und keine feinen Raender, aber Farbe und Schrift
    # tragen den Wiedererkennungswert.
    GRUND, FLAECHE = '#070b08', '#0c130d'
    TEXT, LEISE, AKZENT = '#c9f7d6', '#5fa876', '#3cff77'
    WARN, FEHLER = '#ffb84d', '#ff4d6a'
    SCHRIFT = ('TkFixedFont', 10)
    SCHRIFT_GROSS = ('TkFixedFont', 15, 'bold')

    fenster = tk.Tk()
    fenster.title('AHPT Cloud')
    fenster.configure(bg=GRUND)
    fenster.minsize(580, 520)

    rahmen = tk.Frame(fenster, bg=GRUND, padx=24, pady=20)
    rahmen.pack(fill='both', expand=True)

    tk.Label(rahmen, text='AHPT Cloud', bg=GRUND, fg=AKZENT,
             font=SCHRIFT_GROSS, anchor='w').pack(fill='x')

    lage = tk.Label(rahmen, text='', bg=GRUND, fg=LEISE, font=SCHRIFT,
                    anchor='w', justify='left', wraplength=520)
    lage.pack(fill='x', pady=(6, 14))

    inhalt = tk.Frame(rahmen, bg=GRUND)
    inhalt.pack(fill='both', expand=True)

    stand = tk.Label(rahmen, text='', bg=GRUND, fg=LEISE, font=SCHRIFT,
                     anchor='w', justify='left', wraplength=520)
    stand.pack(fill='x', pady=(12, 0))

    ausgabe = tk.Text(rahmen, height=2, bg=FLAECHE, fg=AKZENT, font=SCHRIFT,
                      relief='flat', highlightthickness=0, wrap='char')

    zustand = {'prozess': None}

    def melde(text, farbe=LEISE):
        stand.configure(text=text, fg=farbe)
        fenster.update_idletasks()

    def zeige_ausgabe(text, farbe, hoehe):
        ausgabe.pack(fill='x', pady=(4, 0))
        ausgabe.configure(state='normal', fg=farbe, height=hoehe)
        ausgabe.delete('1.0', 'end')
        ausgabe.insert('1.0', text)
        ausgabe.configure(state='disabled')

    def leeren(w):
        for k in w.winfo_children():
            k.destroy()

    def knopf(eltern, text, befehl, haupt=False):
        return tk.Button(
            eltern, text=text, command=befehl,
            bg=AKZENT if haupt else FLAECHE,
            fg='#04140a' if haupt else TEXT,
            activebackground=AKZENT if haupt else FLAECHE,
            activeforeground='#04140a' if haupt else AKZENT,
            font=SCHRIFT, relief='flat', padx=16, pady=6)

    # ------------------------------------------------- Agent bedienen

    def agent_laeuft():
        return einrichten._agent_laeuft(PID)

    def agent_starten():
        melde('starte den Agenten ...')
        try:
            e = einrichten.schritt_agent({'was': 'start'})
        except Exception as ex:
            melde('Der Agent liess sich nicht starten: %s' % ex, FEHLER)
            return
        if e.get('laeuft'):
            melde('Der Agent laeuft.', AKZENT)
        else:
            # Die letzten Protokollzeilen sagen warum. Dieses Fenster ist
            # die einzige Stelle, an der sie jemand zu sehen bekommt.
            melde('Der Agent ist nicht angelaufen:', FEHLER)
            zeige_ausgabe(e.get('log_ende', '') or 'keine Ausgabe', FEHLER, 8)
        zeichne()

    def agent_stoppen():
        melde('halte den Agenten an ...')
        try:
            einrichten.schritt_agent({'was': 'stop'})
        except Exception as ex:
            melde('Fehler beim Anhalten: %s' % ex, FEHLER)
            return
        melde('Der Agent ist angehalten. Von unterwegs ist jetzt nichts '
              'mehr erreichbar.', WARN)
        zeichne()

    # ------------------------------------------- Vermittler pruefen
    #
    # WARUM DAS HIER HINEINGEHOERT UND KEIN ZWEITER ASSISTENT IST
    # -----------------------------------------------------------
    # Es richtet nichts ein. Es ist eine DIAGNOSE, und die braucht man
    # genau dann, wenn die Einrichtung laengst hinter einem liegt: "Warum
    # ist AHPT seit ein paar Tagen so langsam?" Die Antwort steht nirgends
    # -- der Webspace laedt, der Agent laeuft, und trotzdem kriecht alles.
    #
    # Ohne Messung sucht der Anwender den Fehler bei sich: im WLAN, im
    # Handy, in der Konfiguration. Er findet ihn nie, weil er woanders
    # liegt -- beim Hoster, der gedrosselt hat oder ueberbucht ist.

    def messfenster():
        w = tk.Toplevel(fenster)
        w.title('Vermittler pruefen')
        w.configure(bg=GRUND)
        w.minsize(620, 600)
        r = tk.Frame(w, bg=GRUND, padx=24, pady=20)
        r.pack(fill='both', expand=True)

        tk.Label(r, text='Vermittler pruefen', bg=GRUND, fg=AKZENT,
                 font=SCHRIFT_GROSS, anchor='w').pack(fill='x')
        tk.Label(r, text='Der Vermittler bekommt genau die Aufgabe, die er im '
                         'Betrieb bekommt: eine Datei annehmen und wieder '
                         'herausgeben. Gemessen wird, wie lange er dafuer '
                         'braucht -- und ob das mehr ist als beim letzten Mal.',
                 bg=GRUND, fg=LEISE, font=SCHRIFT, anchor='w', justify='left',
                 wraplength=560).pack(fill='x', pady=(6, 14))

        tk.Label(r, text='Adresse des Vermittlers', bg=GRUND, fg=TEXT,
                 font=SCHRIFT, anchor='w').pack(fill='x')
        feld = tk.Entry(r, bg=FLAECHE, fg=TEXT, font=SCHRIFT, relief='flat',
                        insertbackground=AKZENT, highlightthickness=1,
                        highlightbackground=FLAECHE, highlightcolor=AKZENT)
        feld.pack(fill='x', pady=(4, 2), ipady=5)
        vorgabe = (einrichten._stand.get('webspace')
                   or einrichten._aus_agent_konfig().get('basis') or '')
        feld.insert(0, vorgabe)
        tk.Label(r, text='Vorbelegt ist der eingerichtete. Zum Vergleichen '
                         'eine andere Adresse eintragen -- etwa einen zweiten '
                         'Webspace, auf dem derselbe Vermittler liegt.',
                 bg=GRUND, fg=LEISE, font=SCHRIFT, anchor='w', justify='left',
                 wraplength=560).pack(fill='x', pady=(0, 12))

        # ---- Die eigene Leitung als Vergleichsgroesse
        #
        # OHNE SIE SAGT DIE MESSUNG NUR DIE HAELFTE. Sie misst, wie lange
        # der Vermittler braucht -- nicht, WORAN es liegt. Ein Anschluss mit
        # 20 Mbit/s hinauf kann nicht mehr hergeben, und dann ist ein
        # langsamer Rundlauf kein Mangel des Webspace, sondern die Wahrheit
        # ueber die eigene Leitung. Beides sieht gleich aus.
        #
        # Es steht hier als FELD und nicht als Messung: Nachmessen hiesse,
        # einen Dritten anzurufen -- der erfuehre die eigene IP, und es
        # kostete je Durchgang zweistellige Megabyte. Fuer die Frage "meine
        # Leitung oder der Hoster?" genuegt die Vertragsrate: Ob 2 von 20
        # ankommen oder 18 von 20, unterscheidet man auch so.
        leitung = einrichten.leitung_lesen()
        tk.Label(r, text='Deine Leitung laut Vertrag (Mbit/s)', bg=GRUND,
                 fg=TEXT, font=SCHRIFT, anchor='w').pack(fill='x')
        lz = tk.Frame(r, bg=GRUND)
        lz.pack(fill='x', pady=(4, 2))

        def zahlfeld(beschriftung, wert):
            tk.Label(lz, text=beschriftung, bg=GRUND, fg=LEISE,
                     font=SCHRIFT).pack(side='left')
            f = tk.Entry(lz, bg=FLAECHE, fg=TEXT, font=SCHRIFT, relief='flat',
                         width=7, insertbackground=AKZENT,
                         highlightthickness=1, highlightbackground=FLAECHE,
                         highlightcolor=AKZENT)
            f.pack(side='left', padx=(6, 18), ipady=4)
            if wert:
                f.insert(0, ('%g' % wert))
            return f

        feld_runter = zahlfeld('herunter', leitung.get('herunter_mbit'))
        feld_hoch = zahlfeld('hinauf', leitung.get('hinauf_mbit'))
        knopf(lz, 'Nachmessen', lambda: leitung_messen()).pack(side='left')

        herkunft = tk.Label(r, text='', bg=GRUND, fg=LEISE, font=SCHRIFT,
                            anchor='w', justify='left', wraplength=560)
        herkunft.pack(fill='x', pady=(0, 12))

        def herkunft_zeigen():
            """WOHER die Zahl stammt, gehoert danebengeschrieben.

            Ein gemessener Wert und ein getippter sehen im Feld gleich aus,
            verdienen aber nicht dasselbe Vertrauen -- und wer vor drei
            Monaten gemessen hat, soll das sehen, statt sich auf eine alte
            Zahl zu verlassen.
            """
            d = einrichten.leitung_lesen()
            if d.get('quelle') == 'gemessen':
                wo = d.get('ort') or d.get('knoten') or ''
                t = ('Gemessen am %s%s.'
                     % (time.strftime('%d.%m.%Y',
                                      time.localtime(d.get('zeit', 0))),
                        ' in ' + wo if wo else ''))
            elif d.get('hinauf_mbit') or d.get('herunter_mbit'):
                t = ('Von dir eingetragen. "Nachmessen" ermittelt die '
                     'wirklichen Werte -- die Vertragsrate stimmt oft nicht.')
            else:
                t = ('Freilassen, wenn du sie nicht weisst -- dann fehlt nur '
                     'der Satz, ob der Vermittler oder deine Leitung bremst.')
            herkunft.configure(text=t)

        herkunft_zeigen()

        urteil = tk.Label(r, text='', bg=GRUND, fg=LEISE, font=SCHRIFT,
                          anchor='w', justify='left', wraplength=560)
        urteil.pack(fill='x')

        tafel = tk.Frame(r, bg=GRUND)
        tafel.pack(fill='x', pady=(12, 0))
        felder = {}
        for spalte, (kennung, titel, unten) in enumerate((
            ('rundlauf', 'Rundlauf', '1 MB hin und zurueck'),
            ('arbeit', 'Arbeit', 'Ablegen + Abholen'),
            ('warten', 'Warten', 'auf die Abfragetakte'),
            ('umlauf', 'Umlauf', 'eine Anfrage'),
        )):
            tafel.columnconfigure(spalte, weight=1, uniform='messwerte')
            k = tk.Frame(tafel, bg=FLAECHE, padx=10, pady=10)
            k.grid(row=0, column=spalte, sticky='nsew',
                   padx=(0 if spalte == 0 else 6, 0))
            tk.Label(k, text=titel, bg=FLAECHE, fg=LEISE,
                     font=SCHRIFT).pack(anchor='w')
            wert = tk.Label(k, text='--', bg=FLAECHE, fg=AKZENT,
                            font=('TkFixedFont', 13, 'bold'))
            wert.pack(anchor='w', pady=(2, 0))
            klein = tk.Label(k, text=unten, bg=FLAECHE, fg=LEISE,
                             font=('TkFixedFont', 8))
            klein.pack(anchor='w')
            # Der Ausgangstext wandert mit: Beim naechsten Durchgang muss
            # auch die Kleinzeile zurueck. Sonst steht unter einem frisch
            # geleerten "--" noch der Wert von vorhin -- und der sieht aus
            # wie ein Messergebnis. Am 08.09.2026 genau so gesehen, als ein
            # abgeschalteter Vermittler "22.24 MB/s" darunter stehen hatte.
            felder[kennung] = (wert, klein, unten)

        text = tk.Text(r, height=9, bg=FLAECHE, fg=TEXT, font=SCHRIFT,
                       relief='flat', highlightthickness=0, wrap='word',
                       padx=10, pady=8)
        text.pack(fill='both', expand=True, pady=(12, 0))
        text.tag_configure('warn', foreground=WARN)
        text.tag_configure('gut', foreground=AKZENT)
        text.configure(state='disabled')

        leiste2 = tk.Frame(r, bg=GRUND)
        leiste2.pack(fill='x', pady=(14, 0))
        knopf(leiste2, 'Schliessen', w.destroy).pack(side='left')
        los = knopf(leiste2, 'Messen', lambda: messen(), haupt=True)
        los.pack(side='right')

        def schreib(zeilen):
            text.configure(state='normal')
            text.delete('1.0', 'end')
            for zeile, art in zeilen:
                text.insert('end', zeile + '\n\n', art)
            text.configure(state='disabled')

        def fertig(e):
            los.configure(state='normal', text='Nochmal messen')
            farben = {'gut': AKZENT, 'lahm': WARN, 'gedrosselt': WARN,
                      'krank': FEHLER, 'weg': FEHLER}
            koepfe = {
                'gut': 'Der Vermittler ist in Ordnung.',
                'lahm': 'Der Vermittler antwortet, aber langsam.',
                'gedrosselt': 'Der Vermittler ist deutlich langsamer als '
                              'frueher.',
                'krank': 'Der Vermittler antwortet, aber die Aufgabe ist '
                         'nicht durchgelaufen.',
                'weg': 'Der Vermittler ist nicht erreichbar.',
            }
            v = e.get('verdikt', 'weg')
            urteil.configure(text=koepfe.get(v, v), fg=farben.get(v, LEISE))

            def setz(kennung, gross, klein):
                felder[kennung][0].configure(text=gross)
                felder[kennung][1].configure(text=klein)

            if e.get('rundlauf_s'):
                setz('rundlauf', '%.1f s' % e['rundlauf_s'],
                     '%.1f MB Datei' % (e.get('datei_bytes', 0) / 1048576.0))
            if e.get('arbeit_s'):
                setz('arbeit', '%.1f s' % e['arbeit_s'],
                     '%d Stuecke, %s'
                     % (e.get('stuecke', 0),
                        einrichten._tempo(e.get('durchsatz_bps'), kurz=True)))
            if e.get('warten_agent_s') is not None:
                # Die zwei Wartezeiten getrennt benennen -- es sind zwei
                # verschiedene Takte, und nur der des Agenten laesst sich
                # ueberhaupt einstellen.
                setz('warten',
                     '%.1f s' % (e['warten_agent_s'] + e['warten_client_s']),
                     'Agent %.1f + Client %.1f'
                     % (e['warten_agent_s'], e['warten_client_s']))
            if 'umlauf_ms' in e:
                # Die Aufteilung nur zeigen, wenn sie aufgeht -- siehe
                # vermittler_messen(). Sonst nur der Gesamtwert; er ist der,
                # auf den es ankommt.
                setz('umlauf', '%.0f ms' % e['umlauf_ms'],
                     ('Netz %.1f + PHP %.1f'
                      % (e.get('tcp_ms') or 0, e['php_ms']))
                     if e.get('php_ms') else 'Netz und PHP zusammen')

            zeilen = [(s, 'warn') for s in e.get('saetze', [])]
            zeilen += [(s, 'warn') for s in e.get('hinweise', [])]
            if not zeilen:
                # Auch der gute Fall braucht einen Satz. Eine leere Flaeche
                # sieht aus wie ein halb fertiges Programm, nicht wie ein
                # Ergebnis.
                zeilen = [(
                    'Nichts zu beanstanden. Der Vermittler nimmt eine Datei '
                    'an und gibt sie in ordentlicher Zeit wieder heraus -- '
                    'laeuft AHPT trotzdem zaeh, liegt es nicht an ihm.',
                    'gut')]

            # WELCHE RICHTUNG BREMST -- das steht in den Zahlen schon
            # drin und war bisher nur nicht abzulesen. Genau danach sucht
            # aber, wer den Fehler eingrenzen will: Ein langsames Ablegen
            # zeigt auf die eigene Leitung hinauf oder auf den Webspace
            # beim Annehmen, ein langsames Zurueckholen auf die Ausgabe.
            if e.get('ablegen_s') and e.get('abholen_s'):
                hin, her = e['ablegen_s'], e['abholen_s']
                welche = ('Beide Richtungen sind gleich schnell.'
                          if 0.6 < hin / her < 1.7 else
                          'Das Ablegen bremst -- also die Leitung von hier '
                          'zum Webspace, oder er selbst beim Annehmen.'
                          if hin > her else
                          'Das Zurueckholen bremst -- also die Ausgabe des '
                          'Webspace.')
                zeilen.append((
                    'Aufgeteilt: Ablegen %.1f s, Zurueckholen %.1f s. %s'
                    % (hin, her, welche), 'gut'))

            # WAS DIE ZAHL BEDEUTET, muss danebenstehen. Sonst vergleicht
            # sie jemand mit dem Ergebnis eines DSL-Speedtests und haelt
            # seinen Webspace fuer kaputt: Der misst eine einzelne lange
            # Verbindung, hier zerfaellt dieselbe Datei in dutzende Stuecke
            # mit je einem eigenen Umlauf -- und wird durch Base64 auch noch
            # um ein Drittel dicker.
            if e.get('arbeit_s') and e.get('stuecke'):
                zeilen.append((
                    'Gemessen wird ein ECHTER Vorgang, kein Bandbreitentest: '
                    'Aus %.1f MB Datei werden durch Base64 %.1f MB auf der '
                    'Leitung, zerlegt in %d Stuecke mit je einem eigenen '
                    'Umlauf. Deshalb liegt der Wert weit unter dem, was ein '
                    'DSL-Speedtest derselben Leitung zeigt -- und deshalb '
                    'ist er der richtige.'
                    % (e.get('datei_bytes', 0) / 1048576.0,
                       e.get('leitung_bytes', 0) / 1048576.0,
                       e['stuecke']), 'gut'))
                zeilen.append((
                    'Hochgerechnet: eine Datei von 10 MB braucht auf diesem '
                    'Weg rund %.0f Sekunden. Die Wartezeit auf die '
                    'Abfragetakte (%.1f s) faellt dabei nur EINMAL an, nicht '
                    'je Megabyte.'
                    % (e['arbeit_s'] * (10 * 1048576.0 / max(1, e.get(
                           'datei_bytes', 1))) + e.get('warten_agent_s', 0)
                       + e.get('warten_client_s', 0),
                       e.get('warten_agent_s', 0) + e.get('warten_client_s', 0)),
                    'gut'))
            schreib(zeilen)

        # ------------------------------------------- Leitung nachmessen
        #
        # DIE GUI STARTET DAS EIGENSTAENDIGE PROGRAMM, sie uebernimmt seinen
        # Code nicht. Das ist der Unterschied, auf den es ankommt:
        # miss_leitung.py bleibt das einzige Stueck AHPT, das mit einem
        # Dritten redet, es bleibt einzeln aufrufbar, und wer es loescht
        # verliert nur diesen Knopf.
        #
        # DIE RUECKFRAGE MUSS TROTZDEM HIER STEHEN. Der Aufruf geht mit
        # --ja hinaus, also ohne die Rueckfrage der Konsolenfassung -- und
        # eine Einwilligung, die man umgeht, ist keine. Wer hier zustimmt,
        # hat dieselben Angaben gesehen wie dort.
        #
        # Und danach geht es von SELBST weiter zum Vermittlertest: Die
        # Leitung zu messen ist kein Selbstzweck, sondern der Anlauf. Wer
        # zwei Minuten auf eine Zahl gewartet hat, soll nicht noch einmal
        # einen Knopf suchen muessen.
        def leitung_messen():
            werkzeug = os.path.join(HIER, 'miss_leitung.py')
            if not os.path.isfile(werkzeug):
                urteil.configure(text='miss_leitung.py liegt nicht neben mir.',
                                 fg=FEHLER)
                return
            from tkinter import messagebox
            if not messagebox.askyesno(
                    'Leitung nachmessen',
                    'Dazu wird speed.cloudflare.com angerufen -- der einzige '
                    'fremde Rechner, mit dem AHPT je redet.\n\n'
                    'Er erfaehrt deine oeffentliche IP-Adresse und dass hier '
                    'gemessen wird. Sonst nichts: kein Name, nicht die '
                    'Adresse deines Webspace, kein Inhalt.\n\n'
                    'Es kostet je nach Leitung etwa 10 bis 200 MB Verkehr. '
                    'Am Handy-Tethering ist das Geld.\n\n'
                    'Danach laeuft der Vermittlertest automatisch weiter.\n\n'
                    'Jetzt messen?', parent=w, default='no'):
                return
            los.configure(state='disabled')
            urteil.configure(text='Leitung wird gemessen ...', fg=LEISE)
            schreib([('Der Speedtest laeuft. Das dauert etwa zwanzig '
                      'Sekunden.', 'gut')])

            def lauf():
                zeilen = []
                try:
                    p = subprocess.Popen(
                        [sys.executable, werkzeug, '--ja'], cwd=HIER,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1)
                except Exception as ex:
                    w.after(0, fehlschlag, 'Der Speedtest liess sich nicht '
                                           'starten: %s' % ex)
                    return
                for zeile in p.stdout:
                    zeile = zeile.rstrip()
                    zeilen.append(zeile)
                    del zeilen[:-25]
                    if zeile.strip():
                        w.after(0, urteil.configure,
                                {'text': zeile.strip(), 'fg': LEISE})
                if p.wait() != 0:
                    w.after(0, fehlschlag,
                            'Der Speedtest ist fehlgeschlagen. Die Werte '
                            'lassen sich von Hand eintragen.\n\n'
                            + '\n'.join(z for z in zeilen if z.strip()))
                    return
                w.after(0, leitung_uebernehmen)

            threading.Thread(target=lauf, daemon=True).start()

        def fehlschlag(text):
            los.configure(state='normal')
            urteil.configure(text='Leitung nicht gemessen.', fg=WARN)
            schreib([(text, 'warn')])

        def leitung_uebernehmen():
            """Felder nachfuehren und ohne Umweg weitermessen."""
            d = einrichten.leitung_lesen()
            for f, k in ((feld_runter, 'herunter_mbit'),
                         (feld_hoch, 'hinauf_mbit')):
                f.delete(0, 'end')
                if d.get(k):
                    f.insert(0, '%g' % d[k])
            herkunft_zeigen()
            los.configure(state='normal')
            messen()

        def messen():
            los.configure(state='disabled', text='Messen ...')
            urteil.configure(text='', fg=LEISE)
            for wert, klein, ausgang in felder.values():
                wert.configure(text='--')
                klein.configure(text=ausgang)
            schreib([('Es wird eine Datei von 1 MB abgelegt und wieder '
                      'zurueckgeholt -- genau so, wie AHPT es im Betrieb '
                      'tut. Auf einer langsamen Leitung dauert das eine '
                      'Weile.', 'gut')])
            adresse = feld.get().strip()
            # Vor dem Lauf sichern, nicht danach: vermittler_messen() liest
            # die Datei, nicht diese Felder.
            einrichten.leitung_schreiben(feld_hoch.get().strip().replace(',', '.'),
                                         feld_runter.get().strip().replace(',', '.'))

            def lauf():
                try:
                    e = einrichten.vermittler_messen(
                        adresse,
                        melde=lambda t: w.after(0, urteil.configure,
                                                {'text': t, 'fg': LEISE}))
                except einrichten.EinrichtenFehler as ex:
                    w.after(0, urteil.configure,
                            {'text': 'Messung nicht moeglich.', 'fg': FEHLER})
                    w.after(0, schreib, [(str(ex), 'warn')])
                    w.after(0, los.configure, {'state': 'normal',
                                               'text': 'Messen'})
                    return
                except Exception as ex:
                    w.after(0, urteil.configure,
                            {'text': 'Unerwarteter Fehler.', 'fg': FEHLER})
                    w.after(0, schreib, [('%s: %s' % (type(ex).__name__, ex),
                                          'warn')])
                    w.after(0, los.configure, {'state': 'normal',
                                               'text': 'Messen'})
                    return
                w.after(0, fertig, e)

            threading.Thread(target=lauf, daemon=True).start()

        schreib([('Auf "Messen" druecken. Es laeuft ein vollstaendiger '
                  'AHPT-Vorgang: eine Datei wird abgelegt und wieder '
                  'abgeholt, und dabei wird gestoppt, wie lange jeder '
                  'Abschnitt braucht.', 'gut')])
        feld.focus_set()

    # ------------------------------------------------- Assistent starten

    def assistent_starten():
        melde('starte den Assistenten ...')
        befehl = [sys.executable, os.path.join(HIER, 'einrichten.py')]
        if wahl.get() == 'hier':
            befehl.append('--nur-localhost')
        else:
            port, _ = einrichten.waehle_port(8771)
            if einrichten.firewall_lage(port)['zustand'] == 'zu':
                melde('Es kommt kein Port durch die Firewall. Der Assistent '
                      'laeuft deshalb nur hier an diesem Rechner.', WARN)
                befehl.append('--nur-localhost')
            else:
                befehl += ['--port', str(port)]
        try:
            p = subprocess.Popen(befehl, cwd=HIER, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 bufsize=1)
        except Exception as ex:
            melde('Der Assistent liess sich nicht starten: %s' % ex, FEHLER)
            return
        zustand['prozess'] = p

        def mitlesen():
            """Die Adresse aus der Ausgabe fischen -- und sonst den Grund.

            Das Token steht nur in dieser Ausgabe; der Assistent erzeugt es
            bei jedem Start neu und schreibt es nirgends hin. Bricht er ab,
            sagt er auf der Konsole genau warum ("Port belegt") -- diese
            Konsole sieht hier aber NIEMAND. Ein blosses "wurde beendet"
            liesse den Nutzer ratlos zurueck.
            """
            gefunden, letzte = None, []
            for zeile in p.stdout:
                letzte.append(zeile.rstrip())
                del letzte[:-12]
                if gefunden is None and 'http://' in zeile and '?t=' in zeile:
                    gefunden = zeile.strip()
                    fenster.after(0, assistent_laeuft, gefunden)
            if gefunden is None:
                text = '\n'.join(z for z in letzte if z.strip())
                fenster.after(0, melde,
                              'Der Assistent konnte nicht starten:', FEHLER)
                fenster.after(0, zeige_ausgabe,
                              text or 'keine Ausgabe', FEHLER, 7)
            else:
                fenster.after(0, zeichne)

        threading.Thread(target=mitlesen, daemon=True).start()

    def assistent_laeuft(url):
        melde('Der Assistent laeuft. Im Browser geht es weiter:', AKZENT)
        zeige_ausgabe(url, AKZENT, 2)
        einrichten._browser_oeffnen(url)

    def beenden():
        # NUR den Assistenten. Der Agent laeuft weiter -- wer sein Fenster
        # schliesst, will nicht seine Cloud abschalten.
        p = zustand.get('prozess')
        if p and p.poll() is None:
            p.terminate()
        fenster.destroy()

    # ------------------------------------------------------ Aufbau

    wahl = tk.StringVar(value='hier')
    autostart = tk.BooleanVar(value=autostart_an())

    def autostart_geaendert():
        autostart_setzen(autostart.get(), KONFIG)
        melde('Autostart ist %s.'
              % ('eingeschaltet' if autostart.get() else 'aus'), LEISE)

    def zeichne():
        leeren(inhalt)
        eingerichtet = os.path.isfile(KONFIG)

        if not eingerichtet:
            lage.configure(
                text='Noch nicht eingerichtet. Der Assistent fuehrt dich '
                     'durch die Schritte -- er laeuft im Browser, diese '
                     'Frage muss nur vorher geklaert sein:', fg=LEISE)
            for wert, titel, unten in (
                ('hier', 'Hier an diesem Rechner',
                 'Nichts muss durch eine Firewall, nichts geht durchs Netz.'),
                ('netz', 'Von einem anderen Geraet im Heimnetz',
                 'Zum Beispiel vom Laptop aus, waehrend der Rechner '
                 'woanders steht.'),
            ):
                kasten = tk.Frame(inhalt, bg=FLAECHE, padx=12, pady=10)
                kasten.pack(fill='x', pady=4)
                tk.Radiobutton(
                    kasten, text=titel, value=wert, variable=wahl,
                    bg=FLAECHE, fg=TEXT, selectcolor=GRUND,
                    activebackground=FLAECHE, activeforeground=AKZENT,
                    font=SCHRIFT, anchor='w', highlightthickness=0,
                    borderwidth=0).pack(fill='x')
                tk.Label(kasten, text=unten, bg=FLAECHE, fg=LEISE,
                         font=SCHRIFT, anchor='w', justify='left',
                         wraplength=460).pack(fill='x', padx=(24, 0))
            leiste = tk.Frame(inhalt, bg=GRUND)
            leiste.pack(fill='x', pady=(16, 0))
            knopf(leiste, 'Beenden', beenden).pack(side='left')
            knopf(leiste, 'Einrichtung starten', assistent_starten,
                  haupt=True).pack(side='right')
            return

        laeuft = agent_laeuft()
        lage.configure(
            text=('Der Agent laeuft. Deine Dateien sind von unterwegs '
                  'erreichbar.' if laeuft else
                  'Der Agent ist angehalten. Von unterwegs kommt gerade '
                  'niemand an deine Dateien.'),
            fg=AKZENT if laeuft else WARN)

        kasten = tk.Frame(inhalt, bg=FLAECHE, padx=14, pady=12)
        kasten.pack(fill='x')
        tk.Checkbutton(
            kasten, text='Beim Anmelden automatisch starten',
            variable=autostart, command=autostart_geaendert,
            bg=FLAECHE, fg=TEXT, selectcolor=GRUND,
            activebackground=FLAECHE, activeforeground=AKZENT,
            font=SCHRIFT, anchor='w', highlightthickness=0,
            borderwidth=0).pack(fill='x')
        tk.Label(kasten,
                 text='Ohne das ist AHPT nach jedem Neustart des Rechners '
                      'aus, bis du hier wieder auf Starten drueckst.',
                 bg=FLAECHE, fg=LEISE, font=SCHRIFT, anchor='w',
                 justify='left', wraplength=460).pack(fill='x', padx=(24, 0))

        pruef = tk.Frame(inhalt, bg=FLAECHE, padx=14, pady=12)
        pruef.pack(fill='x', pady=(8, 0))
        zeile = tk.Frame(pruef, bg=FLAECHE)
        zeile.pack(fill='x')
        knopf(zeile, 'Vermittler pruefen', messfenster).pack(side='left')
        tk.Label(zeile, text='  Antwortzeit und Tempo messen',
                 bg=FLAECHE, fg=TEXT, font=SCHRIFT).pack(side='left')
        tk.Label(pruef,
                 text='Wenn AHPT langsam geworden ist, liegt es meistens '
                      'nicht an dir: Freier Webspace wird gedrosselt oder ist '
                      'ueberbucht. Das sieht man ihm nicht an -- messen muss '
                      'man es.',
                 bg=FLAECHE, fg=LEISE, font=SCHRIFT, anchor='w',
                 justify='left', wraplength=460).pack(fill='x', pady=(8, 0))

        leiste = tk.Frame(inhalt, bg=GRUND)
        leiste.pack(fill='x', pady=(16, 0))
        knopf(leiste, 'Beenden', beenden).pack(side='left')
        if laeuft:
            knopf(leiste, 'Agent anhalten', agent_stoppen).pack(side='right')
        else:
            knopf(leiste, 'Agent starten', agent_starten,
                  haupt=True).pack(side='right')
        knopf(leiste, 'Einstellungen aendern', assistent_starten).pack(
            side='right', padx=(0, 8))

    zeichne()
    fenster.protocol('WM_DELETE_WINDOW', beenden)
    fenster.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
