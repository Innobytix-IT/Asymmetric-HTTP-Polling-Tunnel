/*
 * pruefe_portal.cjs -- das Portal-JavaScript gegen den ECHTEN Agenten
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU -- und warum das die wichtigste der drei Krypto-Pruefungen ist
 * -------------------------------------------------------------------
 * `pruefe_krypto.py` zeigt: krypto.py trifft die Spezifikation.
 * `pruefe_noise_js.cjs` zeigt: noise.js trifft die Spezifikation.
 *
 * Beides zusammen bedeutet NOCH NICHT, dass sie miteinander reden koennen.
 * Zwei Umsetzungen koennen jede fuer sich richtig sein und trotzdem
 * aneinander vorbeilaufen -- etwa wenn eine Seite den Prologue anders
 * bildet, das Verfahren anders benennt oder die Nutzlast anders verpackt.
 * Das steht in keinem Testvektor, weil es nicht die Kryptografie betrifft,
 * sondern ihre Verwendung.
 *
 * Diese Datei fuehrt deshalb den echten Browser-Client gegen den echten
 * Python-Agenten: derselbe Quelltext, den der Browser laedt, gegen dasselbe
 * Programm, das zu Hause laeuft.
 *
 * Aufruf (wird von tests/durchstich_privat.py gestartet):
 *     node tests/pruefe_portal.cjs <basis> <client-privat-hex> <agent-pub-hex>
 */

'use strict';

const path = require('path');

const N = require(path.join(__dirname, '..', 'portal', 'noise.js'));
// Das Portal setzt voraus, dass noise.js im selben Namensraum liegt -- im
// Browser tut es das, weil beide Dateien per <script> geladen werden.
for (const k of Object.keys(N)) global[k] = N[k];
const P = require(path.join(__dirname, '..', 'portal', 'ahpt.js'));

let gesamt = 0, fehler = 0;
function pruefe(text, bedingung, hinweis) {
  gesamt++;
  const ok = !!bedingung;
  if (!ok) fehler++;
  console.log('  ' + text.padEnd(56) + (ok ? 'ok' : 'FEHLSCHLAG')
              + (!ok && hinweis ? '  -- ' + hinweis : ''));
  return ok;
}

const [basis, privHex, agentHex] = process.argv.slice(2);

(async () => {
  const portal = new P.AhptPortal(basis, N.hexZuBytes(privHex),
                                  N.hexZuBytes(agentHex));
  portal.frist = 40000;

  console.log('');
  console.log('PORTAL (Browser-Quelltext gegen den echten Agenten)');
  console.log('');

  // 1 -- Auflisten
  const d = await portal.liste('');
  const namen = (d.eintraege || []).map(e => e.name);
  pruefe('Auflistung kommt an', namen.length > 0, JSON.stringify(namen));
  pruefe('Auflistung nennt die vorhandenen Dateien',
         namen.includes('gehaltsabrechnung.txt') && namen.includes('scan.png'),
         JSON.stringify(namen));
  pruefe('Ordner sind als Ordner gekennzeichnet',
         (d.eintraege || []).some(e => e.art === 'ordner'));

  // 2 -- Holen, klein und gross
  const klein = await portal.hole('gehaltsabrechnung.txt');
  pruefe('kleine Datei kommt unverfaelscht an',
         new TextDecoder().decode(klein.bytes).includes('Kontonummer'));

  const gross = await portal.hole('scan.png');
  let stimmt = gross.bytes.length === 300000;
  for (let i = 0; stimmt && i < gross.bytes.length; i++) {
    if (gross.bytes[i] !== (i * 37 + 11) % 256) stimmt = false;
  }
  pruefe('grosse Datei ist Byte fuer Byte dieselbe', stimmt,
         gross.bytes.length + ' Bytes');

  // 3 -- Hochladen, klein und gross (letzteres gestueckelt)
  const inhalt = new TextEncoder().encode('Aus dem Portal hochgeladen.');
  const a1 = await portal.lege('aus_portal.txt', inhalt);
  pruefe('kleine Datei wird hochgeladen', a1.abgelegt === 'aus_portal.txt',
         JSON.stringify(a1));

  const grossHoch = new Uint8Array(250000);
  for (let i = 0; i < grossHoch.length; i++) grossHoch[i] = (i * 53 + 29) % 256;
  let stuecke = 0;
  const a2 = await portal.lege('unter/aus_portal_gross.png', grossHoch,
                               s => { if (s.art === 'hoch') stuecke = s.gesamt; });
  pruefe('grosse Datei wird gestueckelt hochgeladen',
         a2.abgelegt === 'unter/aus_portal_gross.png' && stuecke > 1,
         JSON.stringify(a2) + ' Stuecke=' + stuecke);
  pruefe('Fortschritt meldet mehr als ein Stueck', stuecke > 1, 'Stuecke=' + stuecke);

  // 4 -- Zurueckholen, was das Portal selbst hochgeladen hat. DAS ist die
  //      eigentliche Rundprobe: hoch und wieder herunter, ueber zwei
  //      verschiedene Umsetzungen derselben Spezifikation.
  const zurueck = await portal.hole('unter/aus_portal_gross.png');
  let rund = zurueck.bytes.length === grossHoch.length;
  for (let i = 0; rund && i < grossHoch.length; i++) {
    if (zurueck.bytes[i] !== grossHoch[i]) rund = false;
  }
  pruefe('hochgeladene Datei kommt Byte fuer Byte zurueck', rund,
         zurueck.bytes.length + ' statt ' + grossHoch.length);

  // 5 -- Ordner anlegen
  const o = await portal.neuerOrdner('aus_portal_ordner');
  pruefe('Ordner wird angelegt', o.angelegt === 'aus_portal_ordner',
         JSON.stringify(o));
  const d2 = await portal.liste('');
  pruefe('neuer Ordner erscheint in der Auflistung',
         (d2.eintraege || []).some(e => e.name === 'aus_portal_ordner'
                                        && e.art === 'ordner'));

  // 6 -- Nicht ueberschreiben
  const a3 = await portal.lege('aus_portal.txt', inhalt);
  pruefe('zweite Datei gleichen Namens ueberschreibt nicht',
         a3.abgelegt === 'aus_portal (2).txt', JSON.stringify(a3));

  // 7 -- Die Schranken gelten auch fuer das Portal
  for (const [boese, was] of [['../draussen.txt', 'Pfadwanderung'],
                              ['.bashrc', 'versteckte Datei'],
                              ['schad.exe', 'gesperrte Endung']]) {
    let abgewiesen = false;
    try { await portal.lege(boese, inhalt); }
    catch (e) { abgewiesen = (e.art === 'leer'); }
    pruefe('Portal darf nicht schreiben: ' + was, abgewiesen);
  }

  // 8 -- Ein Portal mit falschem Agentenschluessel bekommt nichts.
  const fremd = await N.schluesselpaar();
  const falsch = new P.AhptPortal(basis, N.hexZuBytes(privHex),
                                  fremd.oeffentlich);
  falsch.frist = 6000;
  let geflogen = false;
  try { await falsch.liste(''); } catch (e) { geflogen = (e.art === 'zeit'); }
  pruefe('falscher Agentenschluessel: keine Antwort', geflogen);

  console.log('');
  console.log('  ' + gesamt + ' Pruefungen, '
              + (fehler ? fehler + ' FEHLSCHLAG(E).' : 'alle bestanden.'));
  process.exit(fehler ? 1 : 0);
})().catch(e => {
  console.log('');
  console.log('  ABBRUCH: ' + (e && e.stack ? e.stack : e));
  process.exit(2);
});
