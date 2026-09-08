#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
starten.py -- AHPT Cloud bedienen, ohne Terminal

SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 Manuel Person, InnoBytix-IT

WOZU
----
Zwei Dinge, die vorher nur ueber eine Konsole gingen:

  1. Den Einrichtungs-Assistenten ueberhaupt starten. Wer AHPT Cloud auf
     einem Linux Mint oder einem Windows-Rechner benutzt, hat mit einer
     Konsole nichts zu tun und soll auch nicht anfangen muessen.
  2. Den Agenten spaeter anhalten oder wieder starten. Das ging bisher GAR
     NICHT ueber die Oberflaeche: Der Assistent kennt zwar `stop` und
     `status`, aber die Seite ruft nur `start` auf. Wer den Agenten
     loswerden wollte, brauchte den Task-Manager.

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
Kein zweiter Assistent. Jeder EINRICHTUNGS-Schritt, den es hier gaebe,
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
    fenster.minsize(580, 400)

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
