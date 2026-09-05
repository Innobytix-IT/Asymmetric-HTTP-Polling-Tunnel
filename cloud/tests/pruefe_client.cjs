/*
 * pruefe_client.cjs -- relay-client.js gegen einen laufenden Vermittler
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * Wird von durchstich_lokal.py gestartet und bekommt die Basis-Adresse als
 * Argument. Laeuft dort gegen eine ATTRAPPE -- was hier gruen wird, sagt
 * etwas ueber relay-client.js und nichts ueber relay.php.
 *
 * Geprueft wird vor allem das, was der Client als EINZIGER tut: das
 * Zusammensetzen gestueckelter Antworten und die Pruefung der Marken.
 * Genau dort saesse ein Fehler, den niemand als Fehler saehe -- eine
 * verfaelschte Datei sieht aus wie eine Datei.
 *
 * Aufruf:  node tests/pruefe_client.cjs http://127.0.0.1:8099
 */

'use strict';

const path = require('path');
const { AhptClient, AhptFehler } = require(
  path.join(__dirname, '..', 'relay-client.js'));

const basis = process.argv[2];
if (!basis) {
  console.error('Basis-Adresse fehlt.');
  process.exit(2);
}

let fehler = 0;
function pruefe(beschreibung, bedingung, hinweis) {
  const ok = !!bedingung;
  if (!ok) fehler++;
  console.log(beschreibung.padEnd(56) + (ok ? 'ok' : 'FEHLSCHLAG')
              + (!ok && hinweis ? '  -- ' + hinweis : ''));
}

(async () => {
  const relay = new AhptClient(basis, { wartezeit: 40000 });

  // 1 -- Auflisten, ungeteilt.
  const liste = await relay.frage('dateien', 'liste', {});
  pruefe('liste kommt an', liste.gefunden && typeof liste.text === 'string');
  let namen = [];
  try { namen = JSON.parse(liste.text).eintraege.map(e => e.name); } catch (e) {}
  pruefe('liste nennt die Dateien', namen.includes('klein.txt'), namen.join(','));

  // 2 -- Kleine Textdatei.
  const klein = await relay.frage('dateien', 'hole', { pfad: 'klein.txt' });
  pruefe('kleine Datei kommt als Text',
         klein.gefunden && typeof klein.text === 'string'
         && klein.text.indexOf('Massstab') >= 0);
  pruefe('kleine Datei traegt keine Bytes', klein.bytes === undefined);

  // 3 -- Grosse Binaerdatei. DAS ist der Teil, den nur der Client tut.
  const gross = await relay.frage('dateien', 'hole', { pfad: 'gross.png' });
  pruefe('grosse Datei kommt als Bytes',
         gross.gefunden && gross.bytes instanceof Uint8Array);
  pruefe('grosse Datei hat die richtige Laenge',
         gross.bytes && gross.bytes.length === 300000,
         gross.bytes ? String(gross.bytes.length) : 'keine');
  // Byte fuer Byte, gegen dieselbe Formel wie in durchstich_lokal.py.
  let gleich = !!gross.bytes;
  if (gross.bytes) {
    for (let i = 0; i < gross.bytes.length; i++) {
      if (gross.bytes[i] !== (i * 37 + 11) % 256) { gleich = false; break; }
    }
  }
  pruefe('grosse Datei ist Byte fuer Byte dieselbe', gleich);

  // 4 -- Text, der JSON aufblaeht.
  const boese = await relay.frage('dateien', 'hole', { pfad: 'boese.txt' });
  pruefe('JSON-aufblaehender Text kommt vollstaendig an',
         boese.gefunden && boese.text && boese.text.length === 120000,
         boese.text ? String(boese.text.length) : 'keiner');

  // 5 -- Angriffe kommen als "nichts gefunden" zurueck, nie als Inhalt.
  for (const [name, pfad] of [['Pfadwanderung', '../draussen.txt'],
                              ['absoluter Pfad', '/etc/passwd'],
                              ['versteckte Datei', '.geheim']]) {
    const a = await relay.frage('dateien', 'hole', { pfad: pfad });
    pruefe('angriff liefert nichts: ' + name,
           a.gefunden === false && a.text === undefined && a.bytes === undefined);
  }

  // 6 -- Formfehler weist schon der Vermittler ab, und der Client
  //      unterscheidet die Lagen, statt alles "Fehler" zu nennen.
  try {
    await relay.frage('Dateien', 'hole', { pfad: 'klein.txt' });
    pruefe('Grossbuchstabe im Dienst wird abgewiesen', false, 'ging durch');
  } catch (e) {
    pruefe('Grossbuchstabe im Dienst wird abgewiesen',
           e instanceof AhptFehler && e.art === 'abgewiesen', e.art);
  }

  // 7 -- Unbekannter Dienst: angenommen, aber nichts gefunden. Und der
  //      Client erfaehrt nicht, welche Dienste es gibt.
  const unb = await relay.frage('unbekannt', 'hole', { pfad: 'x' });
  pruefe('unbekannter Dienst liefert nichts', unb.gefunden === false);
  pruefe('unbekannter Dienst verraet keine Namen',
         JSON.stringify(unb).indexOf('dateien') < 0, JSON.stringify(unb));

  // 8 -- Abbruch ueber AbortSignal muss wirken, sonst haengt eine Seite,
  //      die der Nutzer laengst verlassen hat, weiter am Netz.
  const ac = new AbortController();
  setTimeout(() => ac.abort(), 60);
  try {
    await relay.frage('dateien', 'hole', { pfad: 'gross.png' }, ac.signal);
    pruefe('Abbruch wirkt', false, 'lief zu Ende');
  } catch (e) {
    pruefe('Abbruch wirkt', e.name === 'AbortError', e.name);
  }

  // 9 -- Der sichere Weg, etwas anzuzeigen. Kein DOM hier, aber zeige()
  //      braucht nur ein Objekt mit textContent -- und genau darauf kommt
  //      es an: Es darf NIE innerHTML anfassen.
  const el = { textContent: 'alt' };
  AhptClient.zeige(el, '<script>alert(1)</script>');
  pruefe('zeige() schreibt nach textContent',
         el.textContent === '<script>alert(1)</script>');
  pruefe('zeige() ruehrt innerHTML nicht an', el.innerHTML === undefined);
  pruefe('zeige() macht aus null einen leeren Text',
         AhptClient.zeige({ textContent: 'x' }, null).textContent === '');
  pruefe('zeige() macht aus einer Zahl Text',
         AhptClient.zeige({ textContent: '' }, 42).textContent === '42');
  try {
    AhptClient.zeige(null, 'x');
    pruefe('zeige() ohne Element bricht ab', false, 'ging durch');
  } catch (e) {
    pruefe('zeige() ohne Element bricht ab', e instanceof AhptFehler);
  }

  // 10 -- titel ist entschaerft, inhalt nicht. Der Suchbegriff kommt als
  //       titel zurueck -- hier ueber den Dateipfad, weil kein kiwix laeuft.
  const t = await relay.frage('dateien', 'liste', {});
  pruefe('titel traegt keine spitzen Klammern',
         typeof t.titel === 'string' && !/[<>]/.test(t.titel), t.titel);

  console.log('');
  console.log(fehler ? fehler + ' FEHLSCHLAG(E).' : 'alle bestanden.');
  process.exit(fehler ? 1 : 0);
})().catch(e => {
  console.error('ABBRUCH: ' + (e && e.stack ? e.stack : e));
  process.exit(2);
});
