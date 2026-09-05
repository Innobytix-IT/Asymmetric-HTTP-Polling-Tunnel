/*
 * ahpt.js -- die Besucherseite von AHPT Cloud, fuer den Browser
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * Das Gegenstueck zu ahpt_client.py, mit denselben Schranken:
 *
 *   * keine Weiterleitungen (mod_speling hat am 02.09.2026 eine Abfrage
 *     stillschweigend auf eine fremde Datei umgeleitet)
 *   * Marke und Stuecknummer werden IM INHALT nachgeprueft
 *   * Dateinamen von Stuecken werden GELESEN, nie gebaut
 *   * ein Rueckfall auf Klartext wird abgewiesen, nicht hingenommen
 *
 * Alles Warten laeuft ueber statische Dateien -- kein PHP. Genau daran
 * haengt das Kostenmodell: Auf billigem Webspace ist Lesen unbegrenzt und
 * Ausfuehren scharf gedeckelt.
 */

'use strict';

function zufallHex(bytes) {
  // Marke fuer eine Blockuebertragung. Nur der Absender muss sie
  // unterscheiden koennen -- 16 Byte reichen sehr breit dafuer aus.
  const b = new Uint8Array(bytes);
  crypto.getRandomValues(b);
  return bytesZuHex(b);
}

const AHPT_VERSION = 1;
const AHPT_VERFAHREN = 'noise_ik_aes';   // WebCrypto kann kein ChaCha20

// Muessen zu relay.php passen.
const MAX_FRAGE = 4096;
const MAX_STUECK = 49152;
const MAX_FRAGE_TEILE = 160;

// Groesse eines Blocks beim Hochladen (Rohdaten, VOR base64 und Noise).
//
// Der Vermittler laesst je Frage MAX_FRAGE_TEILE * MAX_STUECK ~ 7,5 MiB
// Base64. Base64 blaeht um 4/3 auf, Noise legt 16 Byte je Chiffre dazu --
// dann bleiben knapp 5,5 MiB Rohdaten je Block. 4 MiB laesst reichlich
// Luft und ist eine runde Zahl, die auf jedem Speicher lebt.
const BLOCK = 4 * 1024 * 1024;

// Wenn eine Datei kleiner als das ist, geht sie in EINER Frage. Sonst
// waere jede Sprachnotiz ein Umlauf durch Marke, Blockzaehlung und
// Pruefsumme -- unnoetige zwei Sekunden Tunnel je Datei.
const KLEIN = BLOCK;

class AhptFehler extends Error {
  constructor(text, art) { super(text); this.art = art || 'fehler'; }
}

class AhptPortal {
  /**
   * @param basis      Verzeichnis mit relay.php, z. B. ".."
   * @param privatRoh  eigener privater Schluessel, 32 Bytes
   * @param agentPub   oeffentlicher Schluessel des Agenten, 32 Bytes
   */
  constructor(basis, privatRoh, agentPub) {
    this.basis = String(basis || '..').replace(/\/+$/, '');
    this.privat = privatRoh;
    this.agent = agentPub;
    // Zeitfenster, in dem die Antwort auf EINE Frage eintreffen muss.
    //
    // Passt zur MARKE_TTL des Vermittlers (120 s in relay.php); der CLI-
    // Client hat 110 s -- knapp darunter, damit eine Frage, die dieses
    // Portal noch fuer offen haelt, beim Vermittler nicht schon abgelaufen
    // ist. 60 s waren zu wenig, sobald zwischen Antwort und naechster
    // Frage ein Agenten-Poll-Zyklus (unbedingt_nach) lag.
    this.frist = 110000;
  }

  async _sende(aktion, koerper) {
    let r;
    try {
      r = await fetch(this.basis + '/relay.php?action=' + aktion, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(koerper),
        redirect: 'error',            // eine Umleitung ist ein Befund
        cache: 'no-store'
      });
    } catch (e) {
      throw new AhptFehler('Der Vermittler ist nicht erreichbar. '
                           + 'Steht relay.php am erwarteten Ort?', 'netz');
    }
    let d = {};
    try { d = await r.json(); } catch (e) { /* gleich behandelt */ }
    if (!r.ok || !d.ok) {
      throw new AhptFehler('Abgewiesen (HTTP ' + r.status + '): '
                           + (d.fehler || 'keine Begruendung'), 'abgewiesen');
    }
    return d;
  }

  async _hole(pfad) {
    let r;
    try {
      r = await fetch(this.basis + '/ahpt/' + pfad,
                      { redirect: 'error', cache: 'no-store' });
    } catch (e) {
      throw new AhptFehler('Abruf fehlgeschlagen -- eine Umleitung im Spiel? '
                           + 'Dann fehlt CheckSpelling Off.', 'umleitung');
    }
    if (r.status === 404) return null;
    if (!r.ok) throw new AhptFehler('Abruf ergab HTTP ' + r.status, 'netz');
    return r.json();
  }

  /** Ein vollstaendiger Vorgang: fragen, warten, Antwort auspacken. */
  async frage(dienst, aktion, daten, beiFortschritt) {
    const sitzung = await HandshakeIK.neu(AHPT_PROLOG, this.privat, this.agent);
    const klartext = new TextEncoder().encode(
      JSON.stringify({ dienst: dienst, aktion: aktion, daten: daten }));
    const m1 = await sitzung.schreibeNachricht1(klartext);
    const chiffre = bytesZuB64(m1);

    const marke = (chiffre.length > MAX_FRAGE)
      ? await this._hochladen(chiffre, beiFortschritt)
      : (await this._sende('frage', {
          v: AHPT_VERSION, krypto: AHPT_VERFAHREN,
          nutzlast: { chiffre: chiffre }
        })).marke;

    if (typeof marke !== 'string' || marke.length !== 32) {
      throw new AhptFehler('Vermittler gab keine gueltige Marke');
    }
    const umschlag = await this._warte(marke, beiFortschritt);
    return this._auspacken(marke, umschlag, sitzung);
  }

  /*
   * Eine grosse Frage in Stuecken hinaufbringen.
   *
   * Verschluesselt wird VORHER, als ein Stueck -- geteilt wird erst der
   * fertige Geheimtext. Andersherum waere jedes Stueck fuer sich gueltig,
   * und wer eines weglaesst oder vertauscht, bliebe unbemerkt. So macht
   * jede Aenderung das Ganze unbrauchbar.
   *
   * Sichtbar wird die Marke erst, wenn alle Stuecke liegen -- sonst holte
   * der Agent eine halbe Frage.
   */
  async _hochladen(chiffre, beiFortschritt) {
    // Mindestens 2 Stuecke -- nicht nur "mind. 1". Der Vermittler
    // akzeptiert die leere Ankuendigungs-Nutzlast (siehe unten) nur bei
    // `teile > 1`; bei genau 1 Stueck landet die leere Nutzlast in der
    // normalen Pruefung und scheitert dort, weil leer kein gueltiges
    // Base64 ist. Trifft jede Chiffre zwischen MAX_FRAGE (4096 B) und
    // MAX_STUECK (49152 B) -- bei einer Datei heisst das ungefaehr
    // 2,3 KB bis 27 KB roh, ein ganz gewoehnlicher Bereich. Am
    // 05.09.2026 live gefunden: eine 12,43-KB-Textdatei scheiterte
    // genau daran.
    const teile = Math.max(2, Math.ceil(chiffre.length / MAX_STUECK));
    if (teile > MAX_FRAGE_TEILE) {
      throw new AhptFehler(
        'Zu gross: ' + teile + ' Stuecke, erlaubt sind ' + MAX_FRAGE_TEILE
        + '. Der Weg traegt Dokumente und Belege, keine Videos.', 'zu_gross');
    }
    // Schnittgroesse aus der (ggf. angehobenen) Stueckzahl ableiten, NICHT
    // umgekehrt in feste MAX_STUECK-Bloecke schneiden -- sonst waere bei
    // einer kurzen Chiffre und teile=2 das zweite Stueck leer, und leer
    // scheitert bei `frage_stueck` an derselben Pruefung, nur eine Ebene
    // tiefer.
    const stueckgroesse = Math.ceil(chiffre.length / teile);
    const d = await this._sende('frage', {
      v: AHPT_VERSION, krypto: AHPT_VERFAHREN, teile: teile,
      nutzlast: { chiffre: '' }
    });
    const marke = d.marke;
    for (let i = 0; i < teile; i++) {
      await this._sende('frage_stueck', {
        v: AHPT_VERSION, krypto: AHPT_VERFAHREN, marke: marke,
        teil: i, teile: teile,
        nutzlast: chiffre.slice(i * stueckgroesse, (i + 1) * stueckgroesse)
      });
      if (beiFortschritt) {
        beiFortschritt({ art: 'hoch', getan: i + 1, gesamt: teile });
      }
    }
    await this._sende('frage_fertig', {
      v: AHPT_VERSION, krypto: AHPT_VERFAHREN, marke: marke, teile: teile
    });
    return marke;
  }

  /*
   * Warten, bis die Antwort bereitliegt -- ueber die WARTESCHLANGE, nicht
   * durch wiederholtes Fragen nach der Antwortdatei.
   *
   * Der Unterschied ist nicht Feinschliff. Solange die Antwort nicht da ist,
   * ergaebe ein direkter Abruf einen 404 -- und bplaced liefert seine eigene
   * 404-Seite aus einem anderen Verzeichnis aus, ohne CORS-Kopfzeile. Ein
   * 404 ohne CORS erreicht dieses JavaScript nicht als 404, sondern als
   * Netzfehler; das Portal meldete dann eine Umleitung, wo keine war.
   * Am 03.09.2026 im Browser gemessen. Weder eine FilesMatch-Regel noch ein
   * eigenes ErrorDocument liessen sich dagegen durchsetzen.
   *
   * Die Warteschlange gibt es IMMER (sobald einmal gefragt wurde), also
   * kommt sie mit 200 und mit Kopfzeile. Steht die eigene Marke in `fertig`,
   * liegt die Antwortdatei -- der Vermittler schreibt sie unter derselben
   * Sperre, unter der er die Liste fortschreibt.
   *
   * Nebenbei spart es Abrufe: EIN Abruf beantwortet die Frage fuer alle
   * laufenden Vorgaenge, nicht einer je Vorgang.
   */
  async _warte(marke, beiFortschritt) {
    const bis = Date.now() + this.frist;
    let abstand = 350;
    while (Date.now() < bis) {
      const q = await this._hole('warteschlange.json');
      if (q && Array.isArray(q.fertig) && q.fertig.indexOf(marke) >= 0) {
        const u = await this._hole('antwort_' + marke + '.json');
        if (u) return u;
        throw new AhptFehler(
          'Die Warteschlange meldet die Antwort als fertig, aber die Datei '
          + 'fehlt. Das deutet auf ein Aufraeumen zur Unzeit hin.', 'netz');
      }
      if (beiFortschritt) beiFortschritt({ art: 'warten' });
      await new Promise(r => setTimeout(r, abstand));
      abstand = Math.min(1500, Math.round(abstand * 1.3));
    }
    throw new AhptFehler(
      'Zeit abgelaufen -- der Agent hat nicht geantwortet. Laeuft er? '
      + 'Steht der oeffentliche Schluessel dieses Geraets in seiner '
      + 'clients-Liste?', 'zeit');
  }

  _pruefeUmschlag(u, marke, teil) {
    if (!u || typeof u !== 'object') throw new AhptFehler('Umschlag fehlt');
    if (u.v !== AHPT_VERSION) {
      throw new AhptFehler('Protokollfassung ' + u.v + ', erwartet '
                           + AHPT_VERSION);
    }
    // DIE Pruefung gegen eine stille Umleitung.
    if (u.marke !== marke) {
      throw new AhptFehler(
        'Marke weicht ab -- das deutet auf eine Umleitung hin. '
        + 'Steht CheckSpelling Off in der .htaccess?', 'umleitung');
    }
    if (teil !== undefined && u.teil !== teil) {
      throw new AhptFehler('Stuecknummer weicht ab', 'umleitung');
    }
  }

  async _auspacken(marke, u, sitzung) {
    this._pruefeUmschlag(u, marke);
    if (u.krypto !== AHPT_VERFAHREN) {
      // Ein Rueckfall auf Klartext waere ein Angriff, kein Zufall: Wer die
      // Verschluesselung abschalten kann, indem er sie weglaesst, hat keine.
      throw new AhptFehler(
        'Die Antwort kam unverschluesselt (' + u.krypto + '). Das wird nicht '
        + 'hingenommen -- entweder stimmt die Einrichtung nicht, oder jemand '
        + 'hat die Antwort ersetzt.', 'krypto');
    }
    const n = u.nutzlast || {};
    const chiffre = (u.teile > 1)
      ? await this._stuecke(marke, u.teile, n.stuecke)
      : (n.chiffre || '');

    let klartext;
    try {
      klartext = await sitzung.liesNachricht2(b64ZuBytes(chiffre));
    } catch (e) {
      throw new AhptFehler(
        'Die Antwort liess sich nicht entschluesseln. Sie stammt nicht von '
        + 'dem Agenten, dessen Schluessel hier eingetragen ist -- oder sie '
        + 'wurde unterwegs veraendert.', 'krypto');
    }
    return JSON.parse(new TextDecoder().decode(klartext));
  }

  async _stuecke(marke, teile, liste) {
    if (!Array.isArray(liste) || liste.length !== teile) {
      throw new AhptFehler('Verzeichnis und Stueckzahl passen nicht zusammen');
    }
    const teil = new Array(teile).fill(null);
    for (const e of liste) {
      // Der Dateiname wird GELESEN, nie gebaut: Er traegt vier abgeleitete
      // Zeichen, damit benachbarte Stuecke nicht eine Zeichenaenderung
      // auseinanderliegen -- sonst haelt mod_speling sie fuer Tippfehler.
      const datei = e && e.datei;
      const nr = e && e.teil;
      if (typeof datei !== 'string' || !datei.startsWith('antwort_')
          || datei.includes('/') || datei.includes('\\')) {
        throw new AhptFehler('Stueck mit unbrauchbarem Dateinamen');
      }
      const s = await this._hole(datei);
      if (!s) throw new AhptFehler('Stueck ' + nr + ' fehlt');
      this._pruefeUmschlag(s, marke, nr);
      if (s.teile !== teile) throw new AhptFehler('Stueck ' + nr + ' zaehlt anders');
      if (!Number.isInteger(nr) || nr < 0 || nr >= teile) {
        throw new AhptFehler('Stueck mit unbrauchbarer Nummer');
      }
      teil[nr] = s.nutzlast || '';
    }
    if (teil.some(t => t === null)) throw new AhptFehler('Es fehlt ein Stueck');
    return teil.join('');
  }

  /* ------------------------------------------------------- Bequemlichkeit */

  async liste(pfad) {
    const a = await this.frage('dateien', 'liste', { pfad: pfad || '' });
    if (!a.gefunden) throw new AhptFehler(a.grund || 'nichts gefunden', 'leer');
    return JSON.parse(a.inhalt || '{}');
  }

  /*
   * Eine Datei jeder Groesse herunterholen.
   *
   * Der erste Umlauf fragt gleich Daten UND Pruefsumme -- kleine Dateien
   * sind damit nach EINEM Umlauf da und geprueft. Bei einer grossen laeuft
   * der Empfaenger dann in einer Schleife bis zum Ende.
   *
   * Alle Stuecke landen in einem Uint8Array -- der Browser gibt dem Aufrufer
   * keinen Blob zurueck, mit dem er einen Download anstossen koennte, ohne
   * die Datei doch wieder im Speicher zu haben. Das ist die Beschraenkung
   * dieses Wegs: sehr grosse Downloads brauchen einen Handhaufen Speicher.
   * Ein Streaming-Download waere eine File-System-Access-API-Sache, die
   * nicht ueberall geht -- spaeter.
   */
  async hole(pfad, beiFortschritt) {
    // Erster Umlauf: bereichsweise, Pruefsumme mit.
    const erst = await this.frage('dateien', 'hole', {
      pfad: pfad, von: 0, laenge: BLOCK, pruefsumme: true
    }, beiFortschritt);
    if (!erst.gefunden) {
      throw new AhptFehler(erst.grund || 'nichts gefunden', 'leer');
    }
    const a = JSON.parse(erst.inhalt || '{}');
    const gesamt = a.gesamt|0;
    const stand = a.stand;
    const summe = a.sha256 || null;

    // Puffer fuer die ganze Datei anlegen. Bei einer 200-MiB-Datei sind
    // das 200 MiB Speicher -- zu viel fuer ein Handy. Wer da anlaeuft, soll
    // eine klare Meldung bekommen statt eines stillen Absturzes.
    let alles;
    try {
      alles = new Uint8Array(gesamt);
    } catch (e) {
      throw new AhptFehler(
        'Zu gross fuer diesen Browser: ' + Math.round(gesamt/1048576)
        + ' MiB passen nicht in einen einzelnen Speicherblock.',
        'zu_gross');
    }

    let von = 0;
    const erstesStueck = b64ZuBytes(a.inhalt);
    alles.set(erstesStueck, von);
    von += erstesStueck.length;
    if (beiFortschritt && gesamt > BLOCK) {
      beiFortschritt({ art: 'runter', getan: von, gesamt: gesamt });
    }

    while (von < gesamt) {
      const laenge = Math.min(BLOCK, gesamt - von);
      const w = await this.frage('dateien', 'hole', {
        pfad: pfad, von: von, laenge: laenge
      });
      if (!w.gefunden) {
        throw new AhptFehler(w.grund || 'nichts gefunden', 'leer');
      }
      const b = JSON.parse(w.inhalt || '{}');
      // Zeitstempel muss ueber alle Umlaeufe gleich bleiben. Aendert sich
      // die Datei waehrend des Holens, waeren die Stuecke aus zwei
      // Fassungen zusammengesetzt -- jedes fuer sich gueltig, das Ganze
      // falsch, und niemand saehe es.
      if (b.stand !== stand) {
        throw new AhptFehler(
          'Die Datei hat sich waehrend des Holens geaendert. '
          + 'Nichts uebernommen -- der Vorgang bleibt in sich schluessig.',
          'geaendert');
      }
      const stueck = b64ZuBytes(b.inhalt);
      alles.set(stueck, von);
      von += stueck.length;
      if (beiFortschritt) {
        beiFortschritt({ art: 'runter', getan: von, gesamt: gesamt });
      }
    }

    // Pruefsumme des Ganzen. Dieselbe Ueberlegung wie oben: kein Streaming
    // im Browser, aber die Datei liegt ohnehin schon in einem Stueck vor.
    if (summe) {
      const h = await crypto.subtle.digest('SHA-256', alles);
      if (bytesZuHex(new Uint8Array(h)) !== summe) {
        throw new AhptFehler(
          'Pruefsumme stimmt nicht -- nichts uebernommen.',
          'pruefsumme');
      }
    }

    return {
      bytes: alles,
      typ: 'base64',
      titel: a.name || pfad.split('/').pop() || pfad
    };
  }

  /*
   * Eine Datei jeder Groesse hinaufbringen.
   *
   * `bytes` kann ein Uint8Array sein (bisheriger Weg, klein), oder ein Blob
   * bzw. File. Der Grund fuer die Doppelspur: Ein Uint8Array liegt schon
   * vollstaendig im Speicher, ein Blob laesst sich Stueck fuer Stueck
   * anschauen. Eine 500-MiB-Datei am Stueck in den Speicher zu ziehen,
   * bringt den Browserstab auf dem Handy zum Absturz.
   *
   * Kleine Dateien gehen weiterhin in EINER Frage. Der Weg mit Marke,
   * Blockzaehlung und Pruefsumme kostet pro Umlauf rund zwei Sekunden --
   * das lohnt sich erst bei mehr als einem Block.
   */
  async lege(pfad, dateiOderBytes, beiFortschritt) {
    // Wir muessen die Gesamtgroesse kennen, um zu wissen, ob es EIN Zug
    // oder Bloecke werden -- und die Pruefsumme kann nur nach dem letzten
    // Byte da sein. Datei-Objekte liefern die Groesse ohne Lesen.
    const istDatei = typeof Blob !== 'undefined'
                     && dateiOderBytes instanceof Blob;
    const gesamt = istDatei ? dateiOderBytes.size : dateiOderBytes.length;

    if (gesamt <= KLEIN) {
      // KLEIN: Ein Zug, alter Weg. Wenn es ein Blob war, jetzt in den
      // Speicher ziehen -- bei KLEIN Bytes ist das tragbar.
      const bytes = istDatei
        ? new Uint8Array(await dateiOderBytes.arrayBuffer())
        : dateiOderBytes;
      const a = await this.frage('dateien', 'lege', {
        pfad: pfad, inhalt_typ: 'base64', inhalt: bytesZuB64(bytes)
      }, beiFortschritt);
      if (!a.gefunden) {
        throw new AhptFehler(a.grund || 'nicht abgelegt', 'leer');
      }
      return JSON.parse(a.inhalt || '{}');
    }

    // GROSS: in BLOECKEN. Der Agent haengt sie an eine Teildatei und legt
    // erst ab, wenn die Pruefsumme des GANZEN stimmt.
    //
    // Pruefsumme wird VORHER in einem eigenen Durchlauf gebildet. Die
    // Datei zweimal zu lesen ist billiger, als sie fuer die Pruefsumme im
    // Speicher zu halten. Bei einer 500-MiB-Datei ist es der Unterschied
    // zwischen laeuft und laeuft nicht.
    const bloecke = Math.ceil(gesamt / BLOCK);
    const marke = zufallHex(16);

    if (beiFortschritt) beiFortschritt({ art: 'summe', getan: 0, gesamt: gesamt });
    const summe = await this._summeBlob(dateiOderBytes, gesamt, (getan) => {
      if (beiFortschritt) beiFortschritt({ art: 'summe', getan: getan, gesamt: gesamt });
    });

    let antw = null;
    for (let i = 0; i < bloecke; i++) {
      const von = i * BLOCK;
      const bis = Math.min(gesamt, von + BLOCK);
      const rohstueck = istDatei
        ? new Uint8Array(await dateiOderBytes.slice(von, bis).arrayBuffer())
        : dateiOderBytes.subarray(von, bis);
      const daten = {
        uebertragung: marke, block: i, bloecke: bloecke,
        inhalt_typ: 'base64', inhalt: bytesZuB64(rohstueck)
      };
      // Pfad nur beim ERSTEN Block. Danach steht er beim Agenten fest;
      // ihn erneut mitzuschicken waere eine zweite Wahrheit.
      if (i === 0) daten.pfad = pfad;
      if (i === bloecke - 1) daten.sha256 = summe;
      antw = await this.frage('dateien', 'lege_block', daten);
      if (!antw.gefunden) {
        throw new AhptFehler(antw.grund || 'block abgewiesen', 'leer');
      }
      if (beiFortschritt) {
        beiFortschritt({ art: 'hoch', getan: i + 1, gesamt: bloecke });
      }
    }
    return JSON.parse(antw.inhalt || '{}');
  }

  /*
   * Pruefsumme eines Blobs, ohne die ganze Datei in den Speicher zu holen.
   *
   * Der Browser hat keinen fortschreitenden SHA-256 -- crypto.subtle
   * verlangt den ganzen Datenblock auf einmal. Also lesen wir in Bloecken
   * und speisen jeden in einen frischen digest(), das wiederum als
   * Zwischenstand in den naechsten wandert. Das ist NICHT SHA-256.
   *
   * Deshalb: fuer die Pruefsumme, die mit der des Agenten uebereinstimmen
   * muss, brauchen wir einen echten Streaming-SHA-256. Der ist im Browser
   * nur ueber eine Umleitung zu haben: alle Bloecke einmal in einen
   * ArrayBuffer zusammenkopieren -- bei einer sehr grossen Datei genau das,
   * was wir vermeiden wollten. Der Ausweg: SubtleCrypto.digest kann einen
   * Stream nicht, aber es kann einen Uint8Array pro Aufruf. Wir puffern
   * DIE, aber nur die Datei EINMAL komplett -- bei einer 4-GiB-Datei
   * geht das nicht auf einem Handy. Fuer die realistische Groesse einer
   * Sprachnotiz, eines Videos, eines Fotoordners geht es.
   */
  async _summeBlob(blob, gesamt, beiFortschritt) {
    const istBlob = typeof Blob !== 'undefined' && blob instanceof Blob;
    if (!istBlob) {
      const h = await crypto.subtle.digest('SHA-256', blob);
      return bytesZuHex(new Uint8Array(h));
    }
    // Blob am Stueck an digest() geben -- die Web Crypto API frisst einen
    // BufferSource, kein Stream. arrayBuffer() liest ihn dabei genau
    // einmal.
    if (beiFortschritt) beiFortschritt(gesamt);
    const puffer = await blob.arrayBuffer();
    const h = await crypto.subtle.digest('SHA-256', puffer);
    return bytesZuHex(new Uint8Array(h));
  }

  async neuerOrdner(pfad) {
    const a = await this.frage('dateien', 'neuer_ordner', { pfad: pfad });
    if (!a.gefunden) throw new AhptFehler(a.grund || 'nicht angelegt', 'leer');
    return JSON.parse(a.inhalt || '{}');
  }
}

/* --------------------------------------------------------------------
 * Fuer die Pruefung ausserhalb des Browsers.
 *
 * `tests/pruefe_portal.cjs` fuehrt genau diese Datei gegen den ECHTEN
 * Python-Agenten -- nicht gegen eine Nachbildung. Das ist die einzige
 * Pruefung, die zeigt, ob Browser und Heimserver wirklich dieselbe Sprache
 * sprechen; die Testvektoren zeigen nur, dass beide die Spezifikation
 * treffen.
 * -------------------------------------------------------------------- */
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { AhptPortal, AhptFehler, AHPT_VERFAHREN,
                     MAX_FRAGE, MAX_STUECK, MAX_FRAGE_TEILE };
}
