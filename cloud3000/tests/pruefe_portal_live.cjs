/*
 * pruefe_portal_live.cjs -- das Portal gegen den LAUFENDEN Betrieb
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU -- und wie es sich von pruefe_portal.cjs unterscheidet
 * -----------------------------------------------------------
 * `pruefe_portal.cjs` laeuft gegen eine Attrappe mit bekannten Testdateien.
 * Es darf deshalb wissen, dass dort `scan.png` mit 300000 Bytes liegt.
 *
 * Diese Datei laeuft gegen den ECHTEN Webspace und den ECHTEN Agenten. Dort
 * weiss niemand, was im Freigabeordner liegt -- und eine Pruefung, die
 * bestimmte Dateien voraussetzt, wuerde bei jedem Nutzer anders fehlschlagen.
 *
 * Deshalb prueft sie nur, was IMMER gelten muss, und bringt sich ihre
 * Testdatei selbst mit: hochladen, zurueckholen, vergleichen, aufraeumen.
 * Das ist der Rundlauf, auf den es ankommt -- ueber einen echten Webspace,
 * durch echtes PHP, zu einem echten Agenten und zurueck.
 *
 * Aufruf:
 *     node tests/pruefe_portal_live.cjs <basis> <privat-hex> <agent-pub-hex>
 */

'use strict';

const path = require('path');
const N = require(path.join(__dirname, '..', 'portal', 'noise.js'));
for (const k of Object.keys(N)) global[k] = N[k];
const P = require(path.join(__dirname, '..', 'portal', 'ahpt.js'));

let gesamt = 0, fehler = 0;
function pruefe(text, bedingung, hinweis) {
  gesamt++;
  const ok = !!bedingung;
  if (!ok) fehler++;
  console.log('  ' + text.padEnd(52) + (ok ? 'ok' : 'FEHLSCHLAG')
              + (!ok && hinweis ? '  -- ' + hinweis : ''));
  return ok;
}

const [basis, privHex, agentHex] = process.argv.slice(2);
const MARKE = 'portal_live_' + Date.now() + '.txt';

(async () => {
  const portal = new P.AhptPortal(basis, N.hexZuBytes(privHex),
                                  N.hexZuBytes(agentHex));
  portal.frist = 60000;

  console.log('');
  console.log('PORTAL GEGEN DEN LAUFENDEN BETRIEB');
  console.log('   ' + basis);
  console.log('');

  const t0 = Date.now();
  const d = await portal.liste('');
  pruefe('Auflistung kommt an', Array.isArray(d.eintraege),
         JSON.stringify(d).slice(0, 60));
  console.log('    (' + (d.eintraege || []).length + ' Eintraege, '
              + (Date.now() - t0) + ' ms fuer den ganzen Umlauf)');

  // Eine Datei, die gross genug ist, um gestueckelt zu werden -- sonst
  // prueft der Rundlauf den interessanten Fall gar nicht.
  const gross = new Uint8Array(180000);
  for (let i = 0; i < gross.length; i++) gross[i] = (i * 131 + 17) % 256;

  let stuecke = 0;
  const t1 = Date.now();
  const a = await portal.lege(MARKE, gross,
                              s => { if (s.art === 'hoch') stuecke = s.gesamt; });
  pruefe('Hochladen durch den echten Webspace', a.abgelegt === MARKE,
         JSON.stringify(a));
  pruefe('dabei wurde gestueckelt', stuecke > 1, 'Stuecke=' + stuecke);
  console.log('    (' + stuecke + ' Stuecke, ' + (Date.now() - t1) + ' ms)');

  const t2 = Date.now();
  const zurueck = await portal.hole(MARKE);
  let gleich = zurueck.bytes.length === gross.length;
  for (let i = 0; gleich && i < gross.length; i++) {
    if (zurueck.bytes[i] !== gross[i]) gleich = false;
  }
  pruefe('Rundlauf: Byte fuer Byte dieselbe Datei', gleich,
         zurueck.bytes.length + ' statt ' + gross.length);
  console.log('    (' + (Date.now() - t2) + ' ms fuer das Zurueckholen)');

  // Die Schranken gelten auch hier -- gegen echtes PHP, nicht gegen eine
  // Attrappe.
  const klein = new TextEncoder().encode('x');
  for (const [boese, was] of [['../draussen.txt', 'Pfadwanderung'],
                              ['.bashrc', 'versteckte Datei']]) {
    let abgewiesen = false;
    try { await portal.lege(boese, klein); } catch (e) { abgewiesen = true; }
    pruefe('abgewiesen: ' + was, abgewiesen);
  }

  console.log('');
  console.log('  ' + gesamt + ' Pruefungen, '
              + (fehler ? fehler + ' FEHLSCHLAG(E).' : 'alle bestanden.'));
  console.log('');
  console.log('  Aufraeumen: ' + MARKE + ' liegt jetzt im Freigabeordner');
  console.log('  und kann von Hand geloescht werden -- ueber diesen Weg gibt');
  console.log('  es kein Loeschen, und das ist Absicht.');
  process.exit(fehler ? 1 : 0);
})().catch(e => {
  console.log('');
  console.log('  ABBRUCH: ' + (e && e.message ? e.message : e));
  process.exit(2);
});
