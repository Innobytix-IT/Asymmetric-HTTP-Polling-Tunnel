/*
 * relay-client.js -- AHPT/1 im Browser
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * Ohne Abhaengigkeiten, ohne Bauschritt. Eine Datei einbinden, fertig:
 *
 *     const relay = new AhptClient('https://example.de/ahpt');
 *     const a = await relay.frage('wiki', 'suche', { begriff: 'Wasser' });
 *     if (a.gefunden) console.log(a.text);
 *
 * WAS DIESE DATEI TUT
 * -------------------
 *   1. Frage per POST an relay.php ablegen  -- ein PHP-Aufruf
 *   2. auf antwort_<marke>.json warten      -- statisch, KEIN PHP
 *   3. bei geteilter Antwort die Stuecke holen und zusammensetzen
 *
 * Schritt 2 und 3 laufen ueber gewoehnliche Dateien. Das ist der ganze
 * Sinn des Aufbaus: Warten kostet nichts. Wer hier auf die Idee kommt,
 * eine Abhol-Aktion in relay.php zu bauen, verlegt das Warten auf den
 * teuren Weg und hebt den Entwurf auf.
 *
 * VIER SCHRANKEN GEGEN EINE STILLE VERFAELSCHUNG
 * ----------------------------------------------
 * Am 02.09.2026 auf IONOS gemessen: `mod_speling` haelt zwei Dateinamen,
 * die sich um EIN Zeichen unterscheiden, fuer einen Tippfehler und leitet
 * per HTTP 301 um. Die Abfrage nach der ANTWORT landete bei der FRAGE.
 * `fetch` folgt so einer Umleitung stillschweigend -- der Besucher haette
 * "hat geantwortet, nichts gefunden" gelesen, eine Auskunft, die es nie
 * gab.
 *
 * Dagegen steht hier:
 *
 *   1. redirect: 'error' bei JEDEM statischen Abruf. Eine Umleitung ist
 *      dann keine stille Umleitung mehr, sondern ein Fehler.
 *   2. Die Marke IM Inhalt wird gegen die erwartete geprueft.
 *   3. Bei Stuecken zusaetzlich `teil` und `teile`.
 *   4. Stueck-Dateinamen werden aus dem Verzeichnis GELESEN, nie geraten --
 *      und sie tragen vier abgeleitete Zeichen, damit benachbarte Stuecke
 *      nicht eine Zeichenaenderung auseinanderliegen.
 *
 * Dazu `CheckSpelling Off` in der .htaccess -- als fuenfte, nicht als
 * erste: Eine .htaccess muss ankommen, und das tut sie nachweislich nicht
 * immer.
 *
 * WAS DIESE DATEI NICHT TUT
 * -------------------------
 * Sie haengt nichts in die Seite. `a.text` ist reiner Text, `a.bytes` ist
 * ein Uint8Array. Wer daraus innerHTML macht, traegt fremden Inhalt als
 * Markup in seine Seite -- und der Weg ist oeffentlich, jeder kann in die
 * Warteschlange schreiben.
 *
 * Das ist kein theoretischer Einwand. `a.titel` ist bei einer Suche der
 * SUCHBEGRIFF, also frei waehlbar; ein Angreifer braucht weder eine Datei
 * noch ein Archiv, nur eine Frage. Vermittler und Agent werfen dort die
 * spitzen Klammern heraus, aber `a.text` bleibt beliebig und muss es auch
 * -- eine gesaeuberte Nutzlast waere keine Auslieferung mehr, sondern eine
 * Verfaelschung.
 *
 * Deshalb gibt es `AhptClient.zeige(element, text)`: derselbe Einzeiler wie
 * innerHTML, nur richtig. Verbieten laesst sich innerHTML nicht -- aber der
 * bequeme Weg soll der sichere sein.
 *
 *     AhptClient.zeige(document.getElementById('ergebnis'), a.text);
 *
 * UND DAS WICHTIGSTE
 * ------------------
 * DER WEG IST OEFFENTLICH, UND ZWAR ZWANGSLAEUFIG. Frage und Antwort
 * liegen als statische Dateien auf dem Webspace, weil der Agent sie ohne
 * PHP lesen koennen muss -- sonst gaebe es den Kostenvorteil nicht. Jeder,
 * der die Marke aus der Warteschlange nimmt, kann beides lesen.
 *
 * Ueber diesen Weg reist nichts, was nicht oeffentlich sein darf.
 */

'use strict';

class AhptFehler extends Error {
  constructor(nachricht, art) {
    super(nachricht);
    this.name = 'AhptFehler';
    this.art = art || 'unbekannt';
  }
}

class AhptClient {

  /**
   * @param {string} basis    Verzeichnis, in dem relay.php liegt.
   * @param {object} [optionen]
   *        wartezeit    ms, wie lange insgesamt auf eine Antwort gewartet wird
   *        abstand      ms, erster Abstand zwischen zwei Abrufen
   *        abstandMax   ms, groesster Abstand
   */
  constructor(basis, optionen) {
    if (typeof basis !== 'string' || !basis) {
      throw new AhptFehler('basis fehlt', 'konfig');
    }
    const o = optionen || {};
    this.basis      = basis.replace(/\/+$/, '');
    this.wartezeit  = o.wartezeit  || 120000;
    this.abstand    = o.abstand    || 300;
    this.abstandMax = o.abstandMax || 1500;
  }

  /**
   * Stellt eine Frage und wartet auf die Antwort.
   *
   * @param {string} dienst  Name aus der config.toml des Agenten.
   * @param {string} aktion  eine seiner freigegebenen Aktionen.
   * @param {object} daten   die Parameter -- der Handler prueft sie.
   * @param {AbortSignal} [signal]
   * @returns {Promise<{gefunden, titel, quelle, text?, bytes?, marke, dauer}>}
   */
  async frage(dienst, aktion, daten, signal) {
    const t0 = Date.now();
    const marke = await this.stelleFrage(dienst, aktion, daten, signal);
    const antwort = await this.holeAntwort(marke, signal);
    antwort.marke = marke;
    antwort.dauer = Date.now() - t0;
    return antwort;
  }

  /** Legt die Frage ab und gibt die Marke zurueck. Der einzige PHP-Aufruf. */
  async stelleFrage(dienst, aktion, daten, signal) {
    const r = await fetch(this.basis + '/relay.php?action=frage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // Auch hier: eine Umleitung waere ein Fehler, keine Umleitung.
      redirect: 'error',
      signal: signal,
      body: JSON.stringify({
        v: 1,
        krypto: 'keine',
        nutzlast: { dienst: dienst, aktion: aktion, daten: daten || {} }
      })
    });

    let d = {};
    try { d = await r.json(); } catch (e) { /* faellt unten auf */ }

    if (!r.ok || !d.ok) {
      // Die Lagen bleiben unterscheidbar. "Ausgelastet" und "abgewiesen"
      // sind verschiedene Auskuenfte, und die eine als die andere
      // auszugeben kostet den Aufrufer die richtige Reaktion.
      const art = r.status === 429 ? 'zu_viele'
                : r.status === 503 ? 'ausgelastet'
                : r.status === 413 ? 'zu_gross'
                : 'abgewiesen';
      throw new AhptFehler(d.fehler || ('HTTP ' + r.status), art);
    }
    if (!/^[0-9a-f]{32}$/.test(d.marke || '')) {
      throw new AhptFehler('Vermittler gab keine gueltige Marke', 'protokoll');
    }
    return d.marke;
  }

  /** Wartet statisch auf antwort_<marke>.json. Kein PHP, kein Kontingent. */
  async holeAntwort(marke, signal) {
    const bis = Date.now() + this.wartezeit;
    let abstand = this.abstand;

    while (Date.now() < bis) {
      const u = this.basis + '/ahpt/antwort_' + marke + '.json';
      const d = await this._holeJson(u, signal, true);
      if (d) {
        this._pruefeUmschlag(d, marke, 0);
        const n = d.nutzlast || {};
        const teile = d.teile || 1;
        const inhalt = teile > 1
          ? await this._holeStuecke(marke, teile, n.stuecke, signal)
          : (n.inhalt || '');
        return this._auspacken(n, inhalt);
      }
      await this._warte(abstand, signal);
      // Langsam laenger warten. Der erste Umlauf dauert typisch unter zwei
      // Sekunden; danach lohnt haeufiges Fragen nicht mehr.
      abstand = Math.min(this.abstandMax, Math.round(abstand * 1.35));
    }
    throw new AhptFehler('Zeit abgelaufen -- keine Antwort binnen '
                         + (this.wartezeit / 1000) + ' s', 'zeitablauf');
  }

  /** Holt alle Stuecke und setzt sie zusammen. */
  async _holeStuecke(marke, teile, liste, signal) {
    if (!Array.isArray(liste) || liste.length !== teile) {
      throw new AhptFehler('Verzeichnis nennt ' + (liste ? liste.length : 0)
                           + ' Stuecke, angekuendigt sind ' + teile,
                           'protokoll');
    }
    const teil = new Array(teile);
    for (let i = 0; i < teile; i++) {
      const e = liste[i];
      // Der Dateiname wird GELESEN, nie gebaut. Er traegt vier abgeleitete
      // Zeichen, damit zwei benachbarte Stuecke nicht eine Zeichenaenderung
      // auseinanderliegen -- sonst haelt mod_speling sie fuer Tippfehler.
      if (!e || typeof e.datei !== 'string'
          || !/^antwort_[0-9a-f]{32}_\d+_[0-9a-f]{4}\.json$/.test(e.datei)) {
        throw new AhptFehler('Stueck ' + i + ': unbrauchbarer Dateiname',
                             'protokoll');
      }
      const d = await this._holeJson(this.basis + '/ahpt/' + e.datei,
                                     signal, false);
      this._pruefeUmschlag(d, marke, e.teil);
      if (d.teile !== teile) {
        throw new AhptFehler('Stueck ' + i + ' nennt ' + d.teile
                             + ' Stuecke statt ' + teile, 'protokoll');
      }
      if (typeof d.nutzlast !== 'string') {
        throw new AhptFehler('Stueck ' + i + ' traegt keinen Text',
                             'protokoll');
      }
      teil[e.teil] = d.nutzlast;
    }
    for (let i = 0; i < teile; i++) {
      if (typeof teil[i] !== 'string') {
        throw new AhptFehler('Stueck ' + i + ' fehlt', 'protokoll');
      }
    }
    return teil.join('');
  }

  /**
   * Prueft den Umschlag.
   *
   * Eine unbekannte Fassung wird ABGEWIESEN, nicht gedeutet -- wer raet,
   * zeigt irgendwann etwas Falsches an und merkt es nicht.
   */
  _pruefeUmschlag(d, marke, teil) {
    if (!d || typeof d !== 'object') {
      throw new AhptFehler('Antwort ist kein Objekt', 'protokoll');
    }
    if (d.v !== 1) {
      throw new AhptFehler('Protokollfassung ' + d.v + ', erwartet 1',
                           'protokoll');
    }
    if ((d.krypto || 'keine') !== 'keine') {
      throw new AhptFehler('Unbekanntes Verfahren: ' + d.krypto, 'protokoll');
    }
    // DIE Pruefung gegen eine stille Umleitung.
    if (d.marke !== marke) {
      throw new AhptFehler(
        'Marke weicht ab (erwartet ' + marke + ', erhalten ' + d.marke
        + '). Das deutet auf eine Umleitung hin -- CheckSpelling Off?',
        'umleitung');
    }
    if (typeof teil === 'number' && d.teil !== teil) {
      throw new AhptFehler('Stuecknummer weicht ab (erwartet ' + teil
                           + ', erhalten ' + d.teil + ')', 'umleitung');
    }
  }

  /** Macht aus der Nutzlast das, was der Aufrufer bekommt. */
  _auspacken(n, inhalt) {
    const a = {
      gefunden: !!n.gefunden,
      titel:    n.titel  || '',
      quelle:   n.quelle || ''
    };
    if (!a.gefunden) {
      a.grund = n.grund || '';
      return a;
    }
    if (n.inhalt_typ === 'base64') {
      a.bytes = this._vonBase64(inhalt);
    } else {
      // Reiner Text. Bewusst NICHT in die Seite gehaengt -- wer daraus
      // innerHTML macht, traegt fremden Inhalt als Markup in seine Seite.
      a.text = inhalt;
    }
    return a;
  }

  /**
   * Text sicher in ein Element schreiben. Immer textContent, nie innerHTML.
   *
   * Der ganze Zweck ist Bequemlichkeit: Ein Entwickler, der schnell etwas
   * anzeigen will, greift zu dem, was am kuerzesten ist. Wenn das
   * `innerHTML` ist, wird es `innerHTML`. Also gibt es hier etwas, das
   * genauso kurz und richtig ist.
   *
   *     AhptClient.zeige(document.getElementById('ergebnis'), a.text);
   *
   * @param {Element} element  wohin
   * @param {*} text           was -- alles andere als Zeichenkette wird
   *                           dazu gemacht, null und undefined zu ''
   * @returns {Element} dasselbe Element
   */
  static zeige(element, text) {
    if (!element || typeof element.textContent === 'undefined') {
      throw new AhptFehler('zeige(): kein Element', 'konfig');
    }
    element.textContent = (text === null || text === undefined)
      ? '' : String(text);
    return element;
  }

  _vonBase64(s) {
    const roh = atob(s);
    const b = new Uint8Array(roh.length);
    for (let i = 0; i < roh.length; i++) b[i] = roh.charCodeAt(i);
    return b;
  }

  /**
   * Statischer Abruf.
   *
   * @param {boolean} darfFehlen  bei true ist HTTP 404 kein Fehler, sondern
   *        "noch nicht da" -- die Antwortdatei entsteht erst, wenn der Agent
   *        geantwortet hat.
   */
  async _holeJson(url, signal, darfFehlen) {
    let r;
    try {
      // redirect: 'error' ist hier sicherheitstragend, nicht Vorsicht:
      // Ohne das folgt fetch einer 301 stillschweigend, und mod_speling
      // schiebt einem eine fremde Datei unter.
      r = await fetch(url, { redirect: 'error', cache: 'no-store',
                             signal: signal });
    } catch (e) {
      if (e && e.name === 'AbortError') throw e;
      throw new AhptFehler('Abruf fehlgeschlagen (Umleitung? Netz?): '
                           + e.message, 'umleitung');
    }
    if (r.status === 404 && darfFehlen) return null;
    if (!r.ok) {
      throw new AhptFehler('HTTP ' + r.status + ' bei ' + url, 'abruf');
    }
    try {
      return await r.json();
    } catch (e) {
      throw new AhptFehler('Antwort ist kein JSON: ' + url, 'protokoll');
    }
  }

  _warte(ms, signal) {
    return new Promise((fertig, fehler) => {
      const t = setTimeout(fertig, ms);
      if (signal) {
        signal.addEventListener('abort', () => {
          clearTimeout(t);
          const e = new Error('abgebrochen');
          e.name = 'AbortError';
          fehler(e);
        }, { once: true });
      }
    });
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { AhptClient, AhptFehler };
}
