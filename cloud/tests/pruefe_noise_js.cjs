/*
 * pruefe_noise_js.cjs -- rechnet portal/noise.js gegen die offiziellen
 *                        Testvektoren nach
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU
 * ----
 * Dieselbe Begruendung wie bei `pruefe_krypto.py`: Der Unterschied zwischen
 * "selbst ausgedacht" und "selbst umgesetzt" ist dieser Abgleich. Stimmt
 * jeder Geheimtext Byte fuer Byte mit dem ueberein, was andere Umsetzungen
 * derselben Spezifikation erzeugen, dann ist es dieselbe Spezifikation.
 *
 * WARUM IN NODE UND NICHT IM BROWSER
 * -----------------------------------
 * Node 19+ bringt dieselbe WebCrypto mit -- geprueft am 03.09.2026 gegen
 * Node 22: X25519 vorhanden, PKCS8-Rahmen identisch. Damit laeuft die
 * Pruefung bei jedem Durchstich mit, statt auf jemanden zu warten, der eine
 * Seite im Browser oeffnet. Ein Test, den man von Hand starten muss, wird
 * irgendwann nicht mehr gestartet.
 *
 * Aufruf:
 *     node tests/pruefe_noise_js.cjs
 */

'use strict';

const fs = require('fs');
const path = require('path');

const HIER = __dirname;
const N = require(path.join(HIER, '..', 'portal', 'noise.js'));

let gesamt = 0, fehler = 0;

function pruefe(text, bedingung, hinweis) {
  gesamt++;
  const ok = !!bedingung;
  if (!ok) fehler++;
  console.log('  ' + text.padEnd(56) + (ok ? 'ok' : 'FEHLSCHLAG')
              + (!ok && hinweis ? '  -- ' + hinweis : ''));
  return ok;
}

const h = N.hexZuBytes;
const x = N.bytesZuHex;

(async () => {
  const daten = JSON.parse(
    fs.readFileSync(path.join(HIER, 'ik_vektoren.json'), 'utf8'));
  const v = daten.vectors.find(
    e => e.protocol_name === 'Noise_IK_25519_AESGCM_SHA256');
  if (!v) {
    console.log('ABBRUCH: kein AESGCM-Vektor in ik_vektoren.json.');
    process.exit(2);
  }

  console.log('');
  console.log('TESTVEKTOREN   ' + daten.quelle);
  console.log('');
  console.log(v.protocol_name);
  console.log('');

  const verf = await N.kryptoVerfuegbar();
  pruefe('WebCrypto kann, was gebraucht wird', verf.ok, verf.grund);

  // Vorprobe: Der dem Initiator bekannte Schluessel MUSS der oeffentliche
  // Teil des Antwortenden sein. Stimmt das nicht, prueft der Rest Unsinn.
  const rPub = await N.oeffentlichZu(h(v.resp_static));
  pruefe('Vorprobe: bekannter Schluessel passt zum Antwortenden',
         x(rPub) === v.init_remote_static,
         x(rPub) + ' statt ' + v.init_remote_static);

  // Nur die INITIATOR-Seite: Das Portal ist immer der Initiator, und was es
  // nicht tut, soll es auch nicht koennen. Die Antwortenden-Seite steckt in
  // krypto.py und ist dort gegen dieselben Vektoren geprueft.
  const ini = await N.HandshakeIK.neu(
    h(v.init_prologue || ''), h(v.init_static),
    h(v.init_remote_static), h(v.init_ephemeral));

  const m1 = await ini.schreibeNachricht1(h(v.messages[0].payload));
  pruefe('Nachricht 1, Geheimtext stimmt Byte fuer Byte',
         x(m1) === v.messages[0].ciphertext,
         m1.length + ' statt ' + (v.messages[0].ciphertext.length / 2) + ' Bytes');

  const zurueck = await ini.liesNachricht2(h(v.messages[1].ciphertext));
  pruefe('Nachricht 2, Klartext wird zurueckgewonnen',
         x(zurueck) === v.messages[1].payload);

  pruefe('Handshake-Hash stimmt mit dem Vektor',
         x(ini.handshakeHash()) === v.handshake_hash,
         x(ini.handshakeHash()));

  // Transportnachrichten -- HIER faellt eine falsche Byte-Reihenfolge der
  // Nonce auf, und nirgends sonst: Bis hierhin ist der Zaehler null, und
  // null ist in beiden Reihenfolgen dasselbe.
  const [c1, c2] = await ini.transportschluessel();
  for (let nr = 2; nr < v.messages.length; nr++) {
    const vomInitiator = (nr % 2 === 0);
    const m = v.messages[nr];
    const leer = new Uint8Array(0);
    if (vomInitiator) {
      const c = await c1.EncryptWithAd(leer, h(m.payload));
      pruefe('Transportnachricht ' + (nr + 1) + ' (Portal -> Agent) stimmt',
             x(c) === m.ciphertext);
    } else {
      const p = await c2.DecryptWithAd(leer, h(m.ciphertext));
      pruefe('Transportnachricht ' + (nr + 1) + ' (Agent -> Portal) stimmt',
             x(p) === m.payload);
    }
  }

  // ------------------------------------------------------------ Angriffe
  console.log('');
  console.log('ANGRIFFE');
  console.log('');

  // Ein veraendertes Byte in Nachricht 2 muss auffallen.
  const ini2 = await N.HandshakeIK.neu(
    h(v.init_prologue || ''), h(v.init_static),
    h(v.init_remote_static), h(v.init_ephemeral));
  await ini2.schreibeNachricht1(h(v.messages[0].payload));
  const kaputt = h(v.messages[1].ciphertext);
  kaputt[kaputt.length - 1] ^= 0x01;
  let geflogen = false;
  try { await ini2.liesNachricht2(kaputt); } catch (e) { geflogen = true; }
  pruefe('veraendertes Byte wird abgewiesen', geflogen, 'ging durch');

  // Ein falscher Agentenschluessel: Der Handshake laeuft durch (der
  // Initiator merkt es nicht beim Schreiben), aber Nachricht 2 passt nicht.
  const fremd = await N.schluesselpaar();
  const ini3 = await N.HandshakeIK.neu(
    h(v.init_prologue || ''), h(v.init_static), fremd.oeffentlich,
    h(v.init_ephemeral));
  await ini3.schreibeNachricht1(new Uint8Array([1, 2, 3]));
  geflogen = false;
  try { await ini3.liesNachricht2(h(v.messages[1].ciphertext)); }
  catch (e) { geflogen = true; }
  pruefe('Antwort zu falschem Schluessel wird abgewiesen', geflogen, 'ging durch');

  // Zwei Laeufe mit derselben Frage ergeben verschiedene Geheimtexte --
  // sonst waere von aussen erkennbar, wann dasselbe gefragt wird.
  const a = await N.HandshakeIK.neu(N.AHPT_PROLOG, h(v.init_static),
                                    h(v.init_remote_static));
  const b = await N.HandshakeIK.neu(N.AHPT_PROLOG, h(v.init_static),
                                    h(v.init_remote_static));
  const ca = await a.schreibeNachricht1(new TextEncoder().encode('gleich'));
  const cb = await b.schreibeNachricht1(new TextEncoder().encode('gleich'));
  pruefe('gleiche Frage ergibt verschiedene Geheimtexte', x(ca) !== x(cb));

  // Schluesselverwaltung: Rundlauf ueber roh -> oeffentlich.
  const p = await N.schluesselpaar();
  const wieder = await N.oeffentlichZu(p.roh);
  pruefe('roher privater Schluessel ergibt denselben oeffentlichen',
         x(wieder) === x(p.oeffentlich));

  console.log('');
  console.log('ERGEBNIS: ' + gesamt + ' Pruefungen, '
              + (fehler ? fehler + ' FEHLSCHLAG(E).' : 'alle bestanden.'));
  if (!fehler) {
    console.log('');
    console.log('  Damit spricht das Portal dieselbe Sprache wie krypto.py,');
    console.log('  und beide sind gegen fremde Vektoren geprueft.');
  }
  process.exit(fehler ? 1 : 0);
})().catch(e => {
  console.log('');
  console.log('ABBRUCH: ' + (e && e.stack ? e.stack : e));
  process.exit(2);
});
