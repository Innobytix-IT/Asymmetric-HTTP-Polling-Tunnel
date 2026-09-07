/*
 * noise.js -- Noise IK im Browser, nur mit WebCrypto
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU
 * ----
 * Das Gegenstueck zu krypto.py, damit das Portal dieselbe Sprache spricht
 * wie der Kommandozeilen-Client. Ohne Bibliothek, ohne Bauschritt -- eine
 * Datei, die der Browser direkt laedt.
 *
 * WARUM AES-GCM UND NICHT ChaCha20-Poly1305
 * ------------------------------------------
 * WebCrypto kennt kein ChaCha20-Poly1305. Es gaebe zwei Auswege: eine
 * WASM-Bibliothek einbinden (eine Abhaengigkeit, die man pruefen muesste)
 * oder die andere Suite nehmen, die WebCrypto beherrscht.
 *
 * Hier steht die zweite: `Noise_IK_25519_AESGCM_SHA256`. Das ist eine
 * regulaere Noise-Suite, gegen dieselben offiziellen Testvektoren geprueft
 * wie die ChaCha-Variante -- siehe `pruefe_noise.html`, die genau das im
 * Browser nachrechnet.
 *
 * Der Agent nimmt beide an und antwortet in derselben, die er bekommen hat.
 *
 * WAS DIESE DATEI NICHT LEISTET -- BITTE LESEN
 * ---------------------------------------------
 * Sie kommt vom Webspace. Der Hoster koennte sie austauschen und damit auch
 * den Schluessel, gegen den verschluesselt wird. Gegen einen BOESWILLIGEN
 * HOSTER schuetzt ein Portal auf seinem eigenen Server also nicht -- das
 * kann es nicht, egal wie gut die Kryptografie ist.
 *
 * Wogegen es sehr wohl schuetzt, und das ist der eigentliche Zweck: gegen
 * JEDEN ANDEREN. Ohne Verschluesselung kann jeder im Internet die
 * Warteschlange abrufen, die Marken nehmen und Fragen wie Antworten
 * mitlesen. Genau das ist damit zu.
 *
 * Wer auch dem Hoster nicht traut, nimmt den Kommandozeilen-Client oder
 * legt diese Seite als Datei auf den eigenen Rechner. Dann ist der Webspace
 * nur noch Briefkasten.
 *
 * DIE ENGLISCHEN NAMEN
 * --------------------
 * MixKey, MixHash, EncryptAndHash, Split heissen wie in der Spezifikation,
 * damit man Zeile fuer Zeile vergleichen kann. Uebersetzte Namen waeren
 * hier keine Sorgfalt, sondern eine zusaetzliche Fehlerquelle.
 */

'use strict';

const AHPT_PROLOG = new TextEncoder().encode('AHPT-Privat/1');

/* ---------------------------------------------------------- Werkzeug */

function hexZuBytes(h) {
  h = (h || '').trim().toLowerCase().replace(/[^0-9a-f]/g, '');
  if (h.length % 2) throw new Error('Hexwert hat ungerade Laenge');
  const b = new Uint8Array(h.length / 2);
  for (let i = 0; i < b.length; i++) b[i] = parseInt(h.substr(i * 2, 2), 16);
  return b;
}

function bytesZuHex(b) {
  return Array.from(b).map(x => x.toString(16).padStart(2, '0')).join('');
}

function bytesZuB64(b) {
  let s = '';
  const CH = 0x8000;                       // in Haeppchen, sonst Stapelfehler
  for (let i = 0; i < b.length; i += CH) {
    s += String.fromCharCode.apply(null, b.subarray(i, i + CH));
  }
  return btoa(s);
}

function b64ZuBytes(s) {
  const roh = atob(s);
  const b = new Uint8Array(roh.length);
  for (let i = 0; i < roh.length; i++) b[i] = roh.charCodeAt(i);
  return b;
}

function verkette(...teile) {
  let n = 0;
  for (const t of teile) n += t.length;
  const r = new Uint8Array(n);
  let i = 0;
  for (const t of teile) { r.set(t, i); i += t.length; }
  return r;
}

function gleich(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i];
  return d === 0;
}

/* ------------------------------------------------------- Grundrechnung */

async function sha256(daten) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', daten));
}

async function hmacSha256(schluessel, daten) {
  const k = await crypto.subtle.importKey(
    'raw', schluessel, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return new Uint8Array(await crypto.subtle.sign('HMAC', k, daten));
}

/*
 * Die HKDF-Variante der NOISE-Spezifikation.
 *
 * ACHTUNG: Das ist NICHT WebCryptos HKDF. Noise verkettet HMAC-Aufrufe in
 * einer eigenen Form (jeder Ausgang geht in den naechsten ein), ohne
 * `info`-Feld. Wer hier die eingebaute HKDF benutzt, bekommt andere
 * Schluessel -- und merkt es erst, wenn die Testvektoren nicht mehr stimmen.
 * Genau dafuer gibt es sie.
 */
async function noiseHkdf(ck, ikm, anzahl) {
  const temp = await hmacSha256(ck, ikm);
  const o1 = await hmacSha256(temp, new Uint8Array([1]));
  if (anzahl === 1) return [o1];
  const o2 = await hmacSha256(temp, verkette(o1, new Uint8Array([2])));
  if (anzahl === 2) return [o1, o2];
  const o3 = await hmacSha256(temp, verkette(o2, new Uint8Array([3])));
  return [o1, o2, o3];
}

/* ------------------------------------------------------------- X25519 */

// WebCrypto nimmt einen privaten X25519-Schluessel nicht als 32 rohe Bytes
// entgegen -- nur als PKCS8 oder JWK. Diese 16 Bytes sind der feste
// PKCS8-Rahmen fuer X25519; danach folgt der rohe Schluessel.
const PKCS8_X25519 = new Uint8Array([
  0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06,
  0x03, 0x2b, 0x65, 0x6e, 0x04, 0x22, 0x04, 0x20]);

async function privatImportieren(rohe32) {
  if (rohe32.length !== 32) throw new Error('privater Schluessel: 32 Bytes erwartet');
  return crypto.subtle.importKey(
    'pkcs8', verkette(PKCS8_X25519, rohe32),
    { name: 'X25519' }, false, ['deriveBits']);
}

async function oeffentlichImportieren(rohe32) {
  if (rohe32.length !== 32) throw new Error('oeffentlicher Schluessel: 32 Bytes erwartet');
  return crypto.subtle.importKey('raw', rohe32, { name: 'X25519' }, true, []);
}

async function dh(privatKey, oeffentlichRoh) {
  const pub = await oeffentlichImportieren(oeffentlichRoh);
  return new Uint8Array(await crypto.subtle.deriveBits(
    { name: 'X25519', public: pub }, privatKey, 256));
}

/** Neues Schluesselpaar. Rueckgabe: {privat: CryptoKey, roh, oeffentlich}. */
async function schluesselpaar() {
  const p = await crypto.subtle.generateKey({ name: 'X25519' }, true,
                                            ['deriveBits']);
  const oeff = new Uint8Array(await crypto.subtle.exportKey('raw', p.publicKey));
  const pkcs8 = new Uint8Array(await crypto.subtle.exportKey('pkcs8', p.privateKey));
  return {
    privat: p.privateKey,
    roh: pkcs8.slice(PKCS8_X25519.length),   // die 32 Bytes am Ende
    oeffentlich: oeff
  };
}

/** Zu einem privaten Rohschluessel den oeffentlichen Teil bestimmen. */
async function oeffentlichZu(rohe32) {
  // WebCrypto kann aus einem PKCS8-Import den oeffentlichen Teil nicht
  // herausgeben. Der Umweg: als JWK importieren geht nur mit bekanntem `x`.
  // Also rechnen wir ihn: X25519 mit dem Basispunkt.
  const BASIS = new Uint8Array(32); BASIS[0] = 9;
  const k = await privatImportieren(rohe32);
  return dh(k, BASIS);
}

/* --------------------------------------------------------- CipherState */

class CipherState {
  constructor() { this.k = null; this.n = 0n; }

  InitializeKey(k) { this.k = k; this.n = 0n; }
  HasKey() { return this.k !== null; }

  // 96 Bit: 32 Bit Null, dann der Zaehler.
  //
  // AES-GCM verlangt BIG ENDIAN -- ChaCha20-Poly1305 verlangt little.
  // Das ist keine Schlamperei der Spezifikation, sondern folgt den
  // jeweiligen Originalarbeiten. Wer beides gleich behandelt, baut etwas,
  // das mit sich selbst funktioniert und mit keiner anderen Umsetzung. Der
  // Fehler faellt erst bei der ZWEITEN Nachricht je Richtung auf, weil
  // null in beiden Reihenfolgen dasselbe ist.
  _nonce() {
    const iv = new Uint8Array(12);
    const dv = new DataView(iv.buffer);
    dv.setBigUint64(4, this.n, false);      // false = big endian
    return iv;
  }

  async _key() {
    return crypto.subtle.importKey('raw', this.k, { name: 'AES-GCM' },
                                   false, ['encrypt', 'decrypt']);
  }

  async EncryptWithAd(ad, klartext) {
    if (this.k === null) return klartext;
    const c = new Uint8Array(await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: this._nonce(), additionalData: ad, tagLength: 128 },
      await this._key(), klartext));
    this.n += 1n;
    return c;
  }

  async DecryptWithAd(ad, geheim) {
    if (this.k === null) return geheim;
    let p;
    try {
      p = new Uint8Array(await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: this._nonce(), additionalData: ad, tagLength: 128 },
        await this._key(), geheim));
    } catch (e) {
      // Absichtlich wortkarg: Eine Meldung, die zwischen "falscher
      // Schluessel" und "veraendert" unterscheidet, ist ein Auskunftsdienst
      // fuer den, der es versucht.
      throw new Error('Entschluesselung fehlgeschlagen');
    }
    this.n += 1n;
    return p;
  }
}

/* ------------------------------------------------------ SymmetricState */

class SymmetricState {
  static async neu(protokollName) {
    const s = new SymmetricState();
    const name = new TextEncoder().encode(protokollName);
    // Ist der Name hoechstens so lang wie der Hash, wird er mit Nullen
    // aufgefuellt statt gehasht. Unserer ist genau 28 Zeichen lang.
    if (name.length <= 32) {
      s.h = new Uint8Array(32);
      s.h.set(name, 0);
    } else {
      s.h = await sha256(name);
    }
    s.ck = s.h.slice();
    s.cs = new CipherState();
    return s;
  }

  async MixKey(ikm) {
    const [ck, tempK] = await noiseHkdf(this.ck, ikm, 2);
    this.ck = ck;
    this.cs.InitializeKey(tempK);
  }

  async MixHash(daten) { this.h = await sha256(verkette(this.h, daten)); }

  async EncryptAndHash(klartext) {
    const c = await this.cs.EncryptWithAd(this.h, klartext);
    await this.MixHash(c);
    return c;
  }

  async DecryptAndHash(geheim) {
    // Gehasht wird der GEHEIMTEXT, nicht der Klartext -- sonst haetten beide
    // Seiten verschiedene Hashes, sobald ein Feld unverschluesselt bleibt.
    const p = await this.cs.DecryptWithAd(this.h, geheim);
    await this.MixHash(geheim);
    return p;
  }

  async Split() {
    const [t1, t2] = await noiseHkdf(this.ck, new Uint8Array(0), 2);
    const c1 = new CipherState(); c1.InitializeKey(t1);
    const c2 = new CipherState(); c2.InitializeKey(t2);
    return [c1, c2];
  }
}

/* ---------------------------------------------------------- HandshakeIK
 *
 *   IK:
 *     <- s
 *     ...
 *     -> e, es, s, ss
 *     <- e, ee, se
 *
 * Der Browser ist immer der Initiator: Er kennt den statischen Schluessel
 * des Agenten, weil du ihn von Hand eingetragen hast.
 */

const PROTOKOLL_NAME = 'Noise_IK_25519_AESGCM_SHA256';

class HandshakeIK {
  /**
   * @param prologue  bindet den Handshake an dieses Protokoll
   * @param sRoh      eigener privater Schluessel, 32 rohe Bytes
   * @param rs        oeffentlicher Schluessel des Agenten, 32 rohe Bytes
   * @param eRoh      fluechtiger Schluessel -- nur fuer Testvektoren
   */
  static async neu(prologue, sRoh, rs, eRoh) {
    const h = new HandshakeIK();
    h.ss = await SymmetricState.neu(PROTOKOLL_NAME);
    await h.ss.MixHash(prologue);
    h.sRoh = sRoh;
    h.s = await privatImportieren(sRoh);
    h.sPub = await oeffentlichZu(sRoh);
    h.rs = rs;
    h.re = null;
    h.fertig = false;
    if (eRoh) {
      h.eRoh = eRoh;
      h.e = await privatImportieren(eRoh);
      h.ePub = await oeffentlichZu(eRoh);
    }
    // Vornachricht "<- s": Der statische Schluessel des Antwortenden ist dem
    // Initiator schon bekannt und geht in den Hash ein.
    await h.ss.MixHash(rs);
    return h;
  }

  async schreibeNachricht1(nutzlast) {
    if (!this.e) {
      const p = await schluesselpaar();
      this.e = p.privat; this.ePub = p.oeffentlich; this.eRoh = p.roh;
    }
    let puffer = this.ePub;
    await this.ss.MixHash(this.ePub);                       // e
    await this.ss.MixKey(await dh(this.e, this.rs));        // es
    puffer = verkette(puffer, await this.ss.EncryptAndHash(this.sPub));  // s
    await this.ss.MixKey(await dh(this.s, this.rs));        // ss
    puffer = verkette(puffer, await this.ss.EncryptAndHash(nutzlast));
    return puffer;
  }

  async liesNachricht2(nachricht) {
    if (nachricht.length < 32 + 16) throw new Error('Nachricht 2 zu kurz');
    this.re = nachricht.slice(0, 32);
    await this.ss.MixHash(this.re);                         // e
    await this.ss.MixKey(await dh(this.e, this.re));        // ee
    await this.ss.MixKey(await dh(this.s, this.re));        // se
    const klartext = await this.ss.DecryptAndHash(nachricht.slice(32));
    this.fertig = true;
    return klartext;
  }

  handshakeHash() { return this.ss.h; }

  async transportschluessel() {
    if (!this.fertig) throw new Error('Handshake noch nicht abgeschlossen');
    return this.ss.Split();
  }
}

/* --------------------------------------------------------- Verfuegbarkeit */

/**
 * Kann dieser Browser, was wir brauchen?
 *
 * X25519 in WebCrypto ist noch nicht ueberall da. Lieber EINMAL klar sagen,
 * dass es nicht geht, als bei jedem Klick eine unverstaendliche Fehlermeldung
 * zu erzeugen.
 */
async function kryptoVerfuegbar() {
  if (typeof window !== 'undefined' && !window.isSecureContext) {
    return { ok: false, grund: 'Die Seite laeuft nicht in einem sicheren ' +
             'Kontext. WebCrypto gibt es nur ueber https oder auf localhost.' };
  }
  if (typeof crypto === 'undefined' || !crypto.subtle) {
    return { ok: false, grund: 'Dieser Browser hat kein WebCrypto.' };
  }
  try {
    await crypto.subtle.generateKey({ name: 'X25519' }, true, ['deriveBits']);
  } catch (e) {
    return { ok: false, grund: 'Dieser Browser kann kein X25519. ' +
             'Noetig sind Chrome 133+, Firefox 132+ oder Safari 17.4+.' };
  }
  return { ok: true };
}

/* --------------------------------------------------------------------
 * Fuer die Pruefung ausserhalb des Browsers.
 *
 * `tests/pruefe_noise_js.cjs` rechnet diese Datei gegen dieselben
 * offiziellen Testvektoren nach wie krypto.py. Ohne diesen Block muesste
 * der Test den Quelltext auswerten -- und dann prueft er eine Kopie, nicht
 * das Original.
 *
 * Im Browser ist `module` nicht definiert; der Block tut dort nichts.
 * -------------------------------------------------------------------- */
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    HandshakeIK, CipherState, SymmetricState, noiseHkdf, schluesselpaar,
    oeffentlichZu, privatImportieren, dh, sha256, hmacSha256,
    hexZuBytes, bytesZuHex, bytesZuB64, b64ZuBytes, verkette, gleich,
    kryptoVerfuegbar, AHPT_PROLOG, PROTOKOLL_NAME
  };
}
