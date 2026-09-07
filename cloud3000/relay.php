<?php
/**
 * relay.php -- AHPT/1, der inhaltsblinde Vermittler
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU
 * ----
 * Ein Heimserver hinter DS-Lite, CGNAT oder strenger Firewall ist von
 * aussen nicht erreichbar. Diese Datei macht einen gewoehnlichen Webspace
 * zum Treffpunkt: Der Besucher legt eine Frage ab, der Heimserver holt sie
 * und legt die Antwort ab. Der Heimserver baut jede Verbindung SELBST auf,
 * nach draussen. Er nimmt nie eine an.
 *
 * DAS KOSTENMODELL -- der Grund fuer den ganzen Aufbau
 * ----------------------------------------------------
 * Auf guenstigem Webspace ist LESEN unbegrenzt und AUSFUEHREN scharf
 * gedeckelt. Gemessen am 01./02.09.2026 gegen IONOS:
 *
 *   12 gleichzeitige Aufrufe eines PHP-Skripts      ->  7x 200, 5x 503
 *   12 gleichzeitige Aufrufe einer statischen Datei -> 12x 200
 *   20 gleichzeitige bedingte Abrufe (If-None-Match)-> 20x 304, 0 Bytes
 *   X-WS-RateLimit-Remaining waehrend der Messung   -> 999 (unberuehrt)
 *
 * Es ist keine Ratengrenze, sondern eine Grenze fuer gleichzeitig laufende
 * PHP-Prozesse, bei etwa sechs. Statische Dateien laufen daran vorbei.
 *
 * Daraus folgt alles -- nur das SCHREIBEN geht durch PHP:
 *
 *   Besucher legt Frage ab   -> PHP      (schreibt)
 *   Agent holt sie           -> statisch (kein PHP)
 *   Agent legt Antwort ab    -> PHP      (schreibt)
 *   Besucher holt sie        -> statisch (kein PHP)
 *
 * Zwei PHP-Aufrufe je Vorgang, beide kurz. Alles Warten ist umsonst.
 *
 * WAS DIESE FASSUNG ANDERS MACHT ALS tunnel.php
 * ----------------------------------------------
 * `tunnel.php` kennt kiwix: es prueft `typ` gegen suche/artikel und
 * `archiv` gegen allgemein/medizin. Diese Datei kennt gar nichts. Sie
 * traegt `dienst`, `aktion` und `daten` weiter, ohne sie zu deuten.
 *
 * DAS IST NUR HALB SO MUTIG, WIE ES KLINGT -- und die andere Haelfte ist
 * der Grund, warum es sicher bleibt: Es gibt zwei Sorten Dummheit, und nur
 * eine wird hier aufgegeben.
 *
 *   Der Vermittler ist dumm im Sinne von INHALTSBLIND. Das darf er
 *   verlieren -- er hat es nie gebraucht.
 *
 *   Der Agent ist dumm im Sinne von NICHT UEBERREDBAR. Das darf er
 *   niemals verlieren.
 *
 * Welche Dienste es gibt, steht ausschliesslich in der config.toml des
 * Agenten -- zu Hause, nicht hier und nicht im Netz. Von aussen kommt nur
 * die Auswahl daraus. Das ist die woertliche Verallgemeinerung von
 * "es reist niemals eine URL": Es reist niemals eine Faehigkeit, immer nur
 * ein Name aus einer Liste, die anderswo steht.
 *
 * Wer diesem Protokoll ein Feld hinzufuegt, in das eine Zieladresse passt,
 * hat AHPT in einen offenen Proxy ins Heimnetz verwandelt -- Drucker,
 * Router, NAS, bedienbar von der oeffentlichen Seite aus. Es gibt hier
 * kein solches Feld, und es darf nie eines geben.
 *
 * WAS DIESER WEG NICHT LEISTET -- zuerst lesen
 * ---------------------------------------------
 * ER IST OEFFENTLICH, UND ZWAR ZWANGSLAEUFIG. Der Agent muss die Frage ohne
 * PHP lesen koennen, sonst gibt es den Kostenvorteil nicht; also liegt sie
 * in einer statischen Datei; also kann jeder sie lesen, der die Marke aus
 * der Warteschlange nimmt. Dasselbe gilt fuer die Antwort.
 *
 * DIESE FASSUNG GEHOERT ZU AHPT PRIVAT und kennt deshalb ein zweites
 * Verfahren: `krypto: "noise_ik"`. Dann ist die Nutzlast EIN
 * undurchsichtiger Block -- Dienst, Aktion, Titel und Inhalt stecken darin
 * und sind hier nicht mehr sichtbar. Der Vermittler prueft dann nur noch
 * Form und Groesse, was folgerichtig ist: inhaltsblind war immer sein
 * Auftrag.
 *
 * Mit `krypto: "keine"` verhaelt sich diese Datei wie die oeffentliche
 * Fassung, und dann gilt unveraendert: UEBER DIESEN WEG REIST NICHTS, WAS
 * NICHT OEFFENTLICH SEIN DARF.
 *
 * Geschuetzt ist allein, WER fragt: Der Absenderkennwert steht gesalzen in
 * `relay_state.php`, nicht in der oeffentlichen Warteschlange. Ohne Salz
 * waere ein SHA-256 ueber eine IPv4 eine Adresse in Verkleidung -- 2^32
 * Moeglichkeiten sind in Sekunden durch.
 *
 * DIE VIER TRAGENDEN ENTSCHEIDUNGEN
 * ----------------------------------
 * 1. Es reist niemals eine Adresse, nur ein Name aus einer Liste, die zu
 *    Hause steht.
 * 2. Der Agent weist sich aus. Sonst koennte jeder eine Antwort
 *    einschleusen, und sie erschiene beim Besucher als echter Inhalt --
 *    schlimmer als keine Antwort, weil sie geglaubt wird.
 * 3. Deckel an jeder Stelle. Ohne Begrenzung braucht ein Fremder nebenbei
 *    das PHP-Kontingent auf und legt den ganzen Webspace lahm.
 * 4. Nur Schreiben durch PHP, nie Lesen. Wer eine Abhol-Aktion einbaut, hat
 *    den Aufbau nicht verstanden und verlegt das Warten auf den teuren Weg.
 *
 * DIE FALLE BEIM NACHBAUEN
 * -------------------------
 * NIE die Zeichenfolge Fragezeichen-Groesserzeichen in einen
 * Doppelstrich-Kommentar schreiben. Sie beendet den PHP-Modus auch dort.
 * Am 02.09.2026 ging so ein Kommentarrest als HTML hinaus, damit waren die
 * Kopfzeilen gesendet, und http_response_code() blieb wirkungslos -- JEDE
 * Antwort kam mit HTTP 200 zurueck, auch jede Ablehnung. In Blockkommentaren
 * wie diesem ist dieselbe Zeichenfolge harmlos.
 *
 * Gefunden hat es die Pruefliste, nicht das Auge. `tests/pruefe_relay_php.py`
 * sucht seither gezielt danach.
 *
 * DIE AUSLIEFERUNG IST NICHT LIVE, NUR WEIL SIE ANGEKOMMEN IST
 * --------------------------------------------------------------
 * Am 05.09.2026 lag die korrigierte Datei nachweislich byteidentisch auf
 * bplaced (per FTP direkt nachgelesen), und `ausliefern.sh` meldete jede
 * Nachkontrolle als "ok" -- trotzdem antwortete `relay.php` noch mit dem
 * ALTEN Verhalten. Weder ein erneuter Upload (neue Datei-Zeit) noch ein
 * atomarer FTP-Tausch (RNFR/RNTO auf einen frischen Dateinamen, also ein
 * neues Inode) hat es geloest. bplaced haelt den kompilierten PHP-Code
 * offenbar unabhaengig von Dateizeit und Inode vor, und ohne Shell-Zugriff
 * gibt es keinen Weg, das von aussen zu erzwingen.
 *
 * Die Lehre: Ausliefern und Nachkontrolle pruefen, DASS die Datei ankam --
 * nicht, dass PHP sie auch ausfuehrt. Wer eine Verhaltensaenderung
 * ausliefert (nicht nur eine neue Datei), muss die AENDERUNG SELBST gegen
 * den Live-Endpunkt nachmessen, nicht nur Selbsttest-Strukturfelder wie
 * `datei_da` oder `ablage_schreib`. Bleibt die alte Antwort bestehen, hilft
 * nur Geduld (der naechste Arbeiter-Neustart des Hosters) oder ein Eingriff
 * im bplaced-Kundenbereich selbst.
 */

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, X-AHPT-Auth');
header('Cache-Control: no-store');

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') { http_response_code(204); exit; }

// ---------------------------------------------------------------- Ablage
//
// ZUSTAND liegt oben (gesperrt), die PROJEKTION unten (oeffentlich lesbar).
// Wer beides in eine Datei legt, veroeffentlicht die Absender.
define('AHPT_VERSION', 1);
define('ABLAGE',       __DIR__ . '/ahpt');
define('SCHLANGE',     ABLAGE . '/warteschlange.json');

// BEIDE tragen die Endung .php und beginnen mit einer Zeile, die PHP sofort
// beendet.
//
// WARUM NICHT .txt/.json MIT .htaccess-SPERRE: Am 02.09.2026 beim ersten
// Hochladen gemessen -- der Uploader meldete die neue .htaccess zweimal mit
// gruenem Haken, auf dem Server lag weiter die alte. Nachweis:
// `peers_data.json` 403, `tunnel_state.json` 200, beide Namen in DERSELBEN
// FilesMatch-Regel.
//
// Ein Schutz, der davon abhaengt, dass eine Konfigurationsdatei ankommt, ist
// besonders tueckisch: ein ungeschuetztes Geheimnis funktioniert genauso gut
// wie ein geschuetztes. Nichts faellt auf.
//
// Eine .php-Datei kann der Server nicht ausliefern, er fuehrt sie aus. Sie
// endet in der ersten Zeile und gibt nichts aus. Das gilt auf Apache wie auf
// nginx und kann beim Hochladen nicht verlorengehen -- der Schutz IST die
// Datei. Die .htaccess-Regel bleibt als zweite Schranke.
define('ZUSTAND',     __DIR__ . '/relay_state.php');
define('TOKEN_DATEI', __DIR__ . '/relay_token.php');

// Der schliessende Tag MUSS hier stehen. Ohne ihn waere der angehaengte JSON
// PHP-Quelltext, die Datei liesse sich nicht uebersetzen, und ein Abruf
// erzeugte eine Fehlermeldung -- die womoeglich Dateiinhalt zeigt.
define('PHP_SCHUTZ', "<?php exit; ?>\n");

// ---------------------------------------------------------------- Deckel
define('MARKE_TTL',       120);    // s -- danach gilt eine Frage als verfallen
define('ANTWORT_TTL',     120);    // s -- danach wird eine Antwort weggeraeumt
define('MAX_OFFEN',        40);    // gleichzeitig offene Fragen insgesamt
// AHPT PRIVAT: 20 statt 5 wie in der oeffentlichen Fassung.
//
// Dort ist jeder Besucher ein Fremder, und fuenf Plaetze je Absender sind
// grosszuegig. Hier gibt es genau EINEN legitimen Nutzer -- und der bezahlt
// den engen Deckel doppelt:
//
//   * Ein Portal laedt beim Blaettern mehrere Ordner kurz hintereinander.
//   * ABGEWIESENE Fragen bleiben bis MARKE_TTL stehen. Der Agent antwortet
//     auf eine Frage, die er nicht entschluesseln kann, absichtlich NICHT --
//     die Marke belegt danach 120 Sekunden lang einen Platz.
//
// Am 03.09.2026 im Durchstich gemessen: Nach fuenf fehlgeschlagenen
// Versuchen war der eigene Zugang zwei Minuten lang gesperrt, mit der
// Meldung "Zu viele offene Fragen" -- die richtig ist und trotzdem in die
// Irre fuehrt.
//
// Das faire Verdraengen bleibt die eigentliche Schranke gegen Besetzen:
// Wer die meisten Plaetze haelt, verliert seinen aeltesten zuerst.
define('MAX_JE_IP',        20);    // gleichzeitig offene Fragen je Absender
define('MAX_FRAGE',      4096);    // Bytes -- Rumpf einer Frage
define('MAX_STUECK',    49152);    // Bytes -- Inhalt eines Stuecks
define('MAX_TEILE',       256);    // Stuecke je Antwort  (~12 MiB)

// Stuecke je FRAGE. Kleiner als bei der Antwort, und zwar mit Grund:
// Antwortstuecke legt der Agent ab, der sich ausweist. Fragestuecke legt
// JEDER ab, der die Adresse kennt -- der Vermittler kann Freund und Feind
// nicht unterscheiden, weil die Frage verschluesselt ist.
//
// 160 Stuecke sind rund 7,5 MiB Rohdaten, also etwa 5,6 MiB Datei nach der
// Base64-Aufblaehung. Das deckt Belege, Dokumente und Fotos ab. Mit
// MAX_JE_IP = 5 kann ein Absender damit hoechstens rund 38 MiB gleichzeitig
// belegen, und nach MARKE_TTL raeumt der Sammler alles wieder weg.
define('MAX_FRAGE_TEILE', 160);
define('MAX_RUMPF',     65536);    // Bytes -- harte Grenze fuer jeden Rumpf

/** Liest eine geschuetzte Datei und wirft die Schutzzeile weg. */
function lies_geschuetzt(string $pfad): string {
    $roh = @file_get_contents($pfad);
    if ($roh === false) return '';
    // Byte-Order-Mark wegwerfen. Kein Editor sollte einen setzen, aber wenn
    // doch, schlaegt der Vergleich unten fehl und die Datei gilt als leer --
    // ein Fehlschlag, dem man nichts ansieht.
    if (strncmp($roh, "\xEF\xBB\xBF", 3) === 0) $roh = substr($roh, 3);
    if (strncmp($roh, '<?php', 5) === 0) {
        // Zeilenende beliebig: LF, CRLF oder CR. Ein Uploader, der eine
        // .php-Datei als Text behandelt, wandelt sie um -- und wer nur nach
        // LF sucht, findet dann keines und liefert eine leere Zeichenkette
        // zurueck. Das Geheimnis waere still unbrauchbar.
        $nl = strcspn($roh, "\r\n");
        if ($nl >= strlen($roh)) return '';
        return ltrim(substr($roh, $nl), "\r\n");
    }
    return $roh;          // Altbestand ohne Schutzzeile
}

function antwort(array $d, int $code = 200): void {
    http_response_code($code);
    echo json_encode($d, JSON_UNESCAPED_UNICODE);
    exit;
}

/**
 * Geheimnis pruefen. Loopback zaehlt hier bewusst NICHT: Der Agent kommt per
 * Definition von aussen -- eine Loopback-Ausnahme waere eine Tuer ohne Nutzen.
 */
function agent_erlaubt(array $eingabe): bool {
    if (!is_file(TOKEN_DATEI)) return false;         // kein Geheimnis -> zu
    $soll = trim(lies_geschuetzt(TOKEN_DATEI));
    if ($soll === '' || strlen($soll) < 16) return false;
    $kopf = (string)($_SERVER['HTTP_X_AHPT_AUTH'] ?? '');
    if ($kopf !== '' && hash_equals($soll, $kopf)) return true;
    return hash_equals($soll, (string)($eingabe['token'] ?? ''));
}

function schreibe_atomar(string $ziel, string $inhalt): bool {
    $tmp = $ziel . '.' . bin2hex(random_bytes(4)) . '.tmp';
    if (@file_put_contents($tmp, $inhalt) === false) return false;
    if (!@rename($tmp, $ziel)) { @unlink($tmp); return false; }
    return true;
}

function ist_marke($m): bool {
    return is_string($m) && preg_match('/^[0-9a-f]{32}$/', $m) === 1;
}

/** dienst und aktion: Bezeichner, nie etwas Adressartiges. */
function ist_bezeichner($s): bool {
    return is_string($s) && preg_match('/^[a-z][a-z0-9_]{0,31}$/', $s) === 1;
}

/**
 * Wer fragt -- als NETZ, nicht als Adresse.
 *
 * IPv4 zaehlt voll. IPv6 wird auf das /64 gekuerzt, also auf die ersten
 * acht Bytes.
 *
 * WARUM: Die erste Fassung nahm REMOTE_ADDR unveraendert. Bei IPv6 bekommt
 * ein einzelner Anschluss aber regelmaessig ein ganzes /64 zugeteilt -- das
 * sind 2^64 Adressen, und jede davon galt als eigener Absender. MAX_JE_IP
 * war damit wirkungslos: Es brauchte kein Botnetz und keine Proxys, ein
 * Anschluss genuegte, um die Warteschlange zu fuellen.
 *
 * Dieselbe Zeile hatte die umgekehrte Schlagseite: Hinter CGNAT teilen sich
 * ECHTE Besucher eine IPv4 und bekamen zusammen fuenf Plaetze. Also zu
 * lasch gegen Angreifer und zu streng gegen genau die Zielgruppe, die
 * dieses Projekt bedienen will -- die sitzt per Definition hinter CGNAT.
 *
 * Das /64 ist die kleinste Einheit, die ein Anbieter zuteilt. Wer mehr
 * will, muss mehr Anschluesse haben, und das kostet.
 */
function absender_kennung(string $ip): string {
    if ($ip === '') return '?';
    $bin = @inet_pton($ip);
    if ($bin === false) return 'roh:' . $ip;         // unlesbar -> unveraendert
    if (strlen($bin) === 4) return 'v4:' . bin2hex($bin);
    if (strlen($bin) === 16) {
        // IPv4 im IPv6-Kleid (::ffff:1.2.3.4) ist EINE Adresse, kein Netz.
        // Wer die auf /64 kuerzt, wirft saemtliche IPv4-Besucher in einen
        // Topf -- und dann sperrt der erste Angreifer alle anderen aus.
        if (strncmp($bin, "\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff", 12) === 0) {
            return 'v4:' . bin2hex(substr($bin, 12));
        }
        return 'v6:' . bin2hex(substr($bin, 0, 8));  // /64
    }
    return 'roh:' . $ip;
}

/**
 * Ein Anzeigename, der zurueckgespiegelt wird -- also entschaerft.
 *
 * `titel` ist von aussen bestimmt: Bei einer Suche ist es der Suchbegriff,
 * bei einer Datei der angefragte Pfad. Er geht unveraendert an den Browser
 * zurueck. Schreibt ein Entwickler dort `innerHTML = a.titel`, hat ein
 * Angreifer Stored XSS mit frei gewaehltem Inhalt -- und er braucht dafuer
 * weder eine Datei noch ein Archiv, nur eine Frage.
 *
 * Ohne die spitzen Klammern laesst sich kein Tag oeffnen. Das MACHT
 * innerHTML NICHT SICHER -- `inhalt` bleibt beliebig, und das muss es auch,
 * sonst waere es keine Auslieferung mehr, sondern eine Verfaelschung. Es
 * nimmt der schaerfsten Kante die Spitze, mehr nicht.
 *
 * Der Agent tut dasselbe schon (handler/__init__.py). Zwei Schranken, weil
 * ein Agent mit gestohlenem Geheimnis nicht die erste bedienen wuerde.
 */
function sicherer_titel(string $t): string {
    // Ohne /u, absichtlich: Diese Bytes koennen in einer UTF-8-Folge nicht
    // vorkommen, und mit /u wuerde die Funktion bei unguelltigem UTF-8 null
    // zurueckgeben statt zu saeubern.
    $t = (string)preg_replace('/[\x00-\x1f\x7f<>]/', '', $t);
    if (strlen($t) > 240) {
        $t = substr($t, 0, 240);
        // Eine angeschnittene UTF-8-Folge am Ende wegwerfen -- hoechstens
        // vier Bytes, mehr ist eine Folge nie.
        for ($k = 0; $k < 4 && $t !== '' && @preg_match('//u', $t) !== 1; $k++) {
            $t = substr($t, 0, -1);
        }
    }
    return $t;
}

/**
 * Dateiname eines Stuecks.
 *
 * Die vier Zeichen am Ende sind KEIN Schmuck und keine Pruefsumme. Sie
 * verhindern, dass zwei benachbarte Stuecke sich um genau EIN Zeichen
 * unterscheiden -- denn genau dann greift mod_speling.
 *
 * Am 02.09.2026 gemessen: Apache haelt `a_<marke>.json` und `f_<marke>.json`
 * fuer einen Tippfehler und leitet per HTTP 301 um. Bei fortlaufend
 * nummerierten Stuecken (`_0`, `_1`, `_2`) waere die Lage dieselbe: Fehlt
 * Stueck 3, weil der Agent es gerade ablegt, kaeme statt 404 eine Umleitung
 * auf Stueck 2. `fetch` folgt ihr stillschweigend, und der Browser setzte
 * eine Datei zusammen, in der Stueck 2 zweimal steht -- ohne dass irgendwo
 * ein Fehler entstuende.
 *
 * Drei Schranken dagegen, weil eine zu wenig ist: dieser Name, die
 * Stuecknummer IM Inhalt (der Client prueft sie), und `CheckSpelling Off`
 * in der .htaccess. Die .htaccess ist die dritte, nicht die erste -- sie
 * muss ankommen, und das tut sie nachweislich nicht immer.
 */
function stueck_name(string $marke, int $teil): string {
    return 'antwort_' . $marke . '_' . $teil . '_'
         . substr(hash('sha256', $marke . '|' . $teil), 0, 4) . '.json';
}

/**
 * Dasselbe fuer Stuecke einer FRAGE (Hochladen).
 *
 * Eigener Namensstamm `fstueck_`, nicht `frage_`: Sonst laege
 * `frage_<marke>.json` genau eine Zeichenaenderung neben
 * `frage_<marke>_0_ab12.json`, und mod_speling haelt so etwas fuer einen
 * Tippfehler. Derselbe Grund, aus dem `frage_` und `antwort_` verschiedene
 * Staemme haben.
 */
function frage_stueck_name(string $marke, int $teil): string {
    return 'fstueck_' . $marke . '_' . $teil . '_'
         . substr(hash('sha256', $marke . '|f|' . $teil), 0, 4) . '.json';
}

/**
 * Alle Dateien einer Marke loeschen.
 *
 * $stuecke ist die Zahl der abgelegten Stueckdateien, nicht `teile` aus dem
 * Umschlag: Bei einer ungeteilten Antwort steht der Inhalt im Verzeichnis
 * selbst, und es gibt gar keine Stueckdateien.
 *
 * Die Zahl kommt aus dem Zustand, NICHT aus einem Verzeichnislisting.
 * `Options -Indexes` verhindert Listings, und das Aufraeumen darf sich nicht
 * auf etwas stuetzen, das gesperrt gehoert.
 */
function raeume_marke(string $marke, int $stuecke, int $fstuecke = 0): void {
    if (!ist_marke($marke)) return;                  // niemals ungeprueft
    @unlink(ABLAGE . '/frage_' . $marke . '.json');
    @unlink(ABLAGE . '/antwort_' . $marke . '.json');
    if ($stuecke > MAX_TEILE) $stuecke = MAX_TEILE;
    for ($i = 0; $i < $stuecke; $i++) {
        @unlink(ABLAGE . '/' . stueck_name($marke, $i));
    }
    // Beim Hochladen liegen zusaetzlich Fragestuecke. Wer die vergisst,
    // fuellt den Webspace mit Dateien, die in keiner Liste mehr stehen --
    // genau der Fehler, der in tunnel.php bei den Antworten steckte.
    if ($fstuecke > MAX_FRAGE_TEILE) $fstuecke = MAX_FRAGE_TEILE;
    for ($i = 0; $i < $fstuecke; $i++) {
        @unlink(ABLAGE . '/' . frage_stueck_name($marke, $i));
    }
}

/**
 * Zustand unter Sperre aendern, Verfallenes raeumen, Warteschlange neu
 * schreiben.
 *
 * ZWEI LISTEN, nicht eine -- und das ist eine Korrektur gegenueber
 * `tunnel.php`:
 *
 *   offen   gefragt, noch nicht beantwortet
 *   fertig  beantwortet, wartet auf Abholung
 *
 * In `tunnel.php` wird eine Marke beim Beantworten aus `offen` entfernt und
 * danach `antwort_<marke>.json` geschrieben. Ab da steht die Marke in keiner
 * Liste mehr -- der Sammler sieht sie nie wieder, und die Antwortdatei bleibt
 * fuer immer liegen. Geraeumt wird dort also nur, was NIEMAND beantwortet
 * hat; jeder erfolgreiche Vorgang hinterlaesst dauerhaft eine Datei. Im
 * Live-Lauf vom 02.09. fiel das nicht auf, weil dort `0 beantwortet` stand.
 *
 * WARUM NICHT BEIM ABHOLEN LOESCHEN: weil die Abholung statisch ist und PHP
 * sie nie sieht. Das ist kein Versaeumnis, sondern der Kern des Entwurfs.
 * Eine Ablaufzeit ist die einzige Handhabe, die es geben kann.
 *
 * Beide Dateien werden ueber eine Temporaerdatei umbenannt. `rename()` ist
 * auf demselben Dateisystem atomar -- ohne das liest der Agent frueher oder
 * spaeter eine halb geschriebene Datei und wirft sie weg, ohne dass es
 * jemand merkt.
 */
function zustand_aendern(callable $fn) {
    if (!is_dir(ABLAGE)) @mkdir(ABLAGE, 0755, true);
    if (!is_dir(ABLAGE)) return null;

    $sperre = @fopen(ZUSTAND . '.lock', 'c');
    if (!$sperre) return null;
    flock($sperre, LOCK_EX);

    $d = json_decode(lies_geschuetzt(ZUSTAND), true);
    if (!is_array($d)) $d = [];
    if (!isset($d['offen'])  || !is_array($d['offen']))  $d['offen']  = [];
    if (!isset($d['fertig']) || !is_array($d['fertig'])) $d['fertig'] = [];
    // Salz einmal je Installation.
    if (empty($d['salz'])) $d['salz'] = bin2hex(random_bytes(16));

    $jetzt = time();

    $behalten = [];
    foreach ($d['offen'] as $e) {
        if (!is_array($e) || !isset($e['marke'], $e['ts'])) continue;
        if (!ist_marke($e['marke'])) continue;
        if ($jetzt - (int)$e['ts'] > MARKE_TTL) {
            // `st` zaehlt die Stuecke, die der Agent schon abgelegt hatte,
            // bevor er stehenblieb. Ohne diesen Zaehler blieben sie liegen.
            raeume_marke((string)$e['marke'], (int)($e['st'] ?? 0),
                         (int)($e['fst'] ?? 0));
            continue;
        }
        $behalten[] = $e;
    }
    $d['offen'] = $behalten;

    $behalten = [];
    foreach ($d['fertig'] as $e) {
        if (!is_array($e) || !isset($e['marke'], $e['ts'])) continue;
        if (!ist_marke($e['marke'])) continue;
        if ($jetzt - (int)$e['ts'] > ANTWORT_TTL) {
            $t = (int)($e['teile'] ?? 1);
            raeume_marke((string)$e['marke'], $t > 1 ? $t : 0);
            continue;
        }
        $behalten[] = $e;
    }
    $d['fertig'] = $behalten;

    $ergebnis = $fn($d);
    $d['stand'] = $jetzt;
    // Fortlaufende Nummer jeder Aenderung. Sie steht in der oeffentlichen
    // Warteschlange, damit der Agent eine UEBERSEHENE Aenderung bemerken
    // kann -- siehe die lange Begruendung bei der Projektion unten.
    $d['folge'] = (int)($d['folge'] ?? 0) + 1;

    schreibe_atomar(ZUSTAND, PHP_SCHUTZ . json_encode($d, JSON_UNESCAPED_UNICODE));

    // Oeffentliche Projektion: nur Marke und Zeit, nur aus `offen`.
    // Kein Absender, kein Dienst, keine beantwortete Marke -- der Agent soll
    // nichts zweimal sehen.
    //
    // Eine Frage, deren Stuecke noch hochgeladen werden, steht NICHT drin.
    // Sonst holte der Agent sie, faende Luecken und antwortete auf eine
    // halbe Frage. Dieselbe Regel wie bei der Antwort: erst alle Stuecke,
    // dann sichtbar machen.
    $oeffentlich = [];
    foreach ($d['offen'] as $e) {
        if (!($e['bereit'] ?? true)) continue;
        $oeffentlich[] = ['marke' => $e['marke'], 'ts' => $e['ts']];
    }
    // Und die BEANTWORTETEN Marken -- nur die Marke, sonst nichts.
    //
    // Damit weiss ein Besucher, WANN seine Antwort bereitliegt, statt sie
    // im Takt zu erfragen und bis dahin lauter 404 zu bekommen. Das spart
    // nicht nur Abrufe, es macht den Weg ueberhaupt erst
    // ueber-Kreuz-tauglich: Am 03.09.2026 im Browser gemessen -- bplaced
    // liefert seine eigene 404-Seite aus einem anderen Verzeichnis aus, und
    // die traegt keine CORS-Kopfzeile. Ein 404 ohne CORS erreicht das
    // JavaScript nicht als 404, sondern als Netzfehler. Weder eine
    // FilesMatch-Regel noch ein eigenes ErrorDocument haben daran etwas
    // geaendert.
    //
    // KEIN NEUES LECK: Diese Marken standen vorher schon in `offen`, und
    // wer sie kennt, konnte die Antwortdatei ohnehin abrufen.
    $fertig = [];
    foreach (($d['fertig'] ?? []) as $e) {
        if (isset($e['marke'])) $fertig[] = $e['marke'];
    }
    // `folge` ist kein Schmuck. Am 02.09.2026 lokal gemessen:
    //
    // Apache bildet den ETag standardmaessig aus Aenderungszeit (in ganzen
    // SEKUNDEN) und Groesse. Zwei Warteschlangen mit je EINEM Eintrag sind
    // exakt gleich lang -- Marke und Zeitstempel haben feste Breite. Wird
    // eine Frage beantwortet und trifft in derselben Sekunde die naechste
    // ein, hat die neue Datei denselben ETag wie die alte, die der Agent
    // zuletzt geholt hat.
    //
    // Folge: Der Agent bekommt HTTP 304, uebersieht die Frage -- und weil
    // die Datei danach nicht mehr angefasst wird, bekommt er bei JEDEM
    // weiteren Abruf wieder 304. Die Frage bleibt bis zum Verfall
    // unbeantwortet, waehrend der Besucher wartet. Kein Fehler, keine
    // Meldung, nur Stille.
    //
    // Drei Schranken dagegen, weil eine zu wenig ist:
    //   1. `FileETag INode MTime Size` in der .htaccess. Jedes atomare
    //      rename() legt eine NEUE Datei an, also eine neue Inode-Nummer.
    //      Wirkt sofort und vollstaendig -- aber nur auf Apache, und nur
    //      wenn die .htaccess ankommt.
    //   2. Der Agent holt in Abstaenden UNBEDINGT, ohne If-None-Match.
    //      Traegt ohne jede Serverkonfiguration und kostet nur Bytes.
    //   3. Diese Nummer. Springt sie weiter, als der Agent gesehen hat,
    //      WEISS er, dass er etwas uebersehen hat, und sagt es. Aus einem
    //      stillen Fehlschlag wird ein gezaehlter.
    schreibe_atomar(SCHLANGE, json_encode(
        ['stand' => $jetzt, 'folge' => (int)$d['folge'],
         'offen' => $oeffentlich, 'fertig' => $fertig],
        JSON_UNESCAPED_UNICODE));

    flock($sperre, LOCK_UN);
    fclose($sperre);
    return $ergebnis;
}

/**
 * Umschlag bauen. Ein Ort, damit die Felder nie auseinanderlaufen.
 *
 * JSON_INVALID_UTF8_SUBSTITUTE ist kein Beiwerk: `json_encode` gibt bei
 * ungueltigem UTF-8 `false` zurueck, und `false` wird beim Schreiben zur
 * leeren Zeichenkette. Der Besucher bekaeme dann eine leere Antwortdatei --
 * ein Fehlschlag ohne Fehlermeldung, also genau die Sorte, gegen die hier
 * sonst ueberall Vorkehrungen stehen. Lieber ein Ersatzzeichen im Text als
 * eine Datei, die aussieht wie eine Antwort und keine ist.
 */
function umschlag(string $marke, int $teil, int $teile, $nutzlast,
                  string $krypto = 'keine'): string {
    $roh = json_encode([
        'v'        => AHPT_VERSION,
        'marke'    => $marke,
        'teil'     => $teil,
        'teile'    => $teile,
        'krypto'   => $krypto,
        'nutzlast' => $nutzlast,
    ], JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
    if ($roh !== false) return $roh;
    // Auch das noch fehlgeschlagen: dann eine gueltige, ehrliche Absage
    // statt einer leeren Datei. Ohne Verfahren, denn eine Absage des
    // VERMITTLERS kann er gar nicht verschluesseln -- er hat keinen
    // Schluessel, und das ist der Sinn der Sache. Der Client erkennt sie
    // daran, dass `krypto` "keine" sagt, wo er "noise_ik" erwartet.
    return '{"v":' . AHPT_VERSION . ',"marke":"' . $marke . '","teil":0,'
         . '"teile":1,"krypto":"keine","nutzlast":{"gefunden":false,'
         . '"titel":"","quelle":"","inhalt_typ":"text","inhalt":"",'
         . '"grund":"nicht darstellbar"}}';
}

// ---------------------------------------------------------------- Eingabe
$aktion = (string)($_GET['action'] ?? '');
$rumpf  = (string)file_get_contents('php://input');

// Vor dem Zerlegen begrenzen. Wer erst zerlegt und dann misst, hat die
// Arbeit schon getan, gegen die der Deckel schuetzen soll.
if (strlen($rumpf) > MAX_RUMPF) {
    antwort(['ok' => false, 'fehler' => 'Rumpf zu gross', 'grenze' => MAX_RUMPF], 413);
}
$eingabe = json_decode($rumpf, true);
if (!is_array($eingabe)) $eingabe = [];

// ZWEITE Fassung derselben Eingabe, diesmal mit Objekten statt Feldern.
//
// PHP unterscheidet nicht zwischen einem leeren Objekt und einer leeren
// Liste: json_decode('{}', true) ergibt [], und json_encode([]) ergibt
// wieder []. Wer die Nutzlast als Feld einliest und neu schreibt, macht aus
// {"daten":{}} also {"daten":[]}.
//
// Dasselbe trifft Objekte mit lauter Ziffernschluesseln: {"0":"a","1":"b"}
// wird zu ["a","b"].
//
// Am 02.09.2026 auf dem HomeServer gegen PHP 8.3 gemessen -- eine
// Auflistung ohne Parameter kam nie an, weil der Agent zu Recht ein Objekt
// erwartete und eine Liste bekam. Gegen die Python-Attrappe war der Fehler
// UNSICHTBAR, weil Python beides unterscheidet. Genau die Abdrift, vor der
// tests/attrappe_relay.py im Kopf warnt.
$roh_obj = json_decode($rumpf, false);

// Protokollfassung. Beim Selbsttest nicht verlangt -- er soll gerade dann
// noch antworten, wenn sonst nichts mehr passt.
if ($aktion !== 'selbsttest') {
    $v = $eingabe['v'] ?? null;
    // Typtolerant vergleichen: Jede bekannte Client-Fassung schickt eine
    // Ganzzahl, aber JSON unterscheidet nicht zwischen 1 und 1.0, und PHPs
    // "!==" wertet beides als verschieden -- nachgemessen am 05.09.2026:
    // ein zahlengleicher, aber anders typisierter Wert wurde abgewiesen,
    // obwohl die Fassung stimmte. Nur die FASSUNG zaehlt, nicht der
    // Zahlentyp.
    if (!is_numeric($v) || (int)$v !== AHPT_VERSION) {
        // Diagnose VOR der Ablehnung, mit eigenem Deckel: Ein abgewiesenes
        // "v" kann zwei ganz verschiedene Ursachen haben, die von aussen
        // gleich aussehen -- eine echte Fassungsabweichung, oder ein
        // unvollstaendig angekommener Rumpf (json_decode liefert dann
        // null, $eingabe wird zu [], $v damit still zu null). Ohne diese
        // Zeile sind beide Faelle nicht zu unterscheiden. TEMPORAER, bis
        // die Ursache der Stueck-Ausfaelle vom 05.09.2026 geklaert ist.
        $log = ABLAGE . '/protokollfehler.log';
        if (!is_file($log) || filesize($log) < 1_000_000) {
            @file_put_contents($log,
                date('c') . " aktion=$aktion rumpf_bytes=" . strlen($rumpf)
                . ' content_length=' . ($_SERVER['CONTENT_LENGTH'] ?? '?')
                . ' decode_fehler=' . (json_last_error() !== JSON_ERROR_NONE ? '1' : '0')
                . ' erhalten=' . substr(var_export($v, true), 0, 120)
                . ' typ=' . gettype($v) . "\n",
                FILE_APPEND);
        }
        antwort(['ok' => false, 'fehler' => 'Protokollfassung', 'erwartet' => AHPT_VERSION,
                 'erhalten' => $v], 400);
    }
    // Ein unbekanntes Verfahren wird ABGEWIESEN, nicht ignoriert. Wer es
    // ignoriert, reicht Rauschen als Klartext weiter -- oder umgekehrt.
    //
    // AHPT PRIVAT kennt zwei Werte:
    //
    //   "keine"     wie im oeffentlichen AHPT. Die Nutzlast ist
    //               {dienst, aktion, daten}, und der Vermittler prueft
    //               deren Form.
    //   "noise_ik"  Die Nutzlast ist EIN undurchsichtiger Block. Dienst und
    //               Aktion stecken darin und sind hier nicht mehr sichtbar.
    //
    // Dass der Vermittler dabei seine Formpruefung auf `dienst`/`aktion`
    // verliert, ist kein Verlust: Er war immer INHALTSBLIND, und diese
    // Pruefung schuetzte nur davor, dass die Werte in einen Dateinamen
    // ausbrechen -- was sie ohnehin nie tun, weil Dateinamen ausschliesslich
    // die Marke tragen.
    //
    // Stuenden Dienst und Aktion aussen, saehe der Webspace weiterhin, WAS
    // getan wird, auch wenn er den Inhalt nicht mehr lesen kann. Wer Dateien
    // abruft, verraet mit "dienst: dateien, aktion: hole" schon genug.
    $k = (string)($eingabe['krypto'] ?? 'keine');
    // Zwei Noise-Suiten, und der Grund ist der Browser: WebCrypto kennt
    // AES-GCM, aber KEIN ChaCha20-Poly1305. Der Kommandozeilen-Client nimmt
    // WireGuards Suite, das Portal nimmt AES-GCM. Beide sind gegen dieselben
    // offiziellen Testvektoren geprueft.
    if (!in_array($k, ['keine', 'noise_ik', 'noise_ik_aes'], true)) {
        antwort(['ok' => false, 'fehler' => 'Unbekanntes Verfahren: ' . $k,
                 'erlaubt' => ['keine', 'noise_ik', 'noise_ik_aes']], 400);
    }
}

/**
 * Prueft einen verschluesselten Block.
 *
 * Base64, damit er ohne Sonderbehandlung durch JSON passt. Geprueft wird
 * er trotzdem: Der Vermittler soll den Inhalt nicht VERSTEHEN -- das heisst
 * nicht, dass er alles annimmt. Auch ein undurchsichtiger Block hat eine
 * Form, und eine Form laesst sich pruefen, ohne etwas zu erfahren.
 */
function ist_chiffre($s, int $grenze): bool {
    return is_string($s) && $s !== '' && strlen($s) <= $grenze
           && preg_match('#^[A-Za-z0-9+/]+={0,2}$#', $s) === 1;
}

switch ($aktion) {

// ------------------------------------------ Besucher legt eine Frage ab
case 'frage':
    $n = $eingabe['nutzlast'] ?? null;
    if (!is_array($n)) {
        antwort(['ok' => false, 'fehler' => 'nutzlast fehlt'], 400);
    }
    // MARKE, wahlweise vom Absender vorgegeben -- fuer AHPT Cloud 3000, wo
    // dieselbe Marke einen Transportwechsel ueberleben muss (derselbe
    // logische Vorgang bleibt wiedererkennbar, auch wenn der zweite Versuch
    // ueber einen anderen Weg laeuft als der erste). Und ZWINGEND fuer
    // WebDAV: Dort gibt es keine Ablage, die eine Marke ERZEUGT -- ein PUT
    // braucht sie vorher.
    //
    // ALTE Clients senden gar keine -- dann bleibt es beim urspruenglichen
    // Verhalten (Zeile bei `$marke = bin2hex(...)` weiter unten): der
    // Vermittler erzeugt sie, wie eh und je.
    $marke_vorgabe = (string)($eingabe['marke'] ?? '');
    if ($marke_vorgabe !== '' && !ist_marke($marke_vorgabe)) {
        antwort(['ok' => false, 'fehler' => 'Ungueltige Marke'], 400);
    }
    // VERSCHLUESSELT: ein einziger undurchsichtiger Block, sonst nichts.
    //
    // Ab hier weiss der Vermittler nicht mehr, welcher Dienst gefragt ist
    // und was getan werden soll. Das ist keine Nachlaessigkeit, sondern der
    // erklaerte Zweck -- siehe die lange Begruendung oben bei `krypto`.
    // Wieviele Stuecke? 1 ist der Normalfall (eine Frage passt in eine
    // Nachricht). Mehr heisst HOCHLADEN: Dann kommt hier nur das Verzeichnis
    // an, die Stuecke folgen einzeln, und die Marke wird erst danach
    // sichtbar.
    $f_teile = $eingabe['teile'] ?? 1;
    if (!is_int($f_teile) || $f_teile < 1 || $f_teile > MAX_FRAGE_TEILE) {
        antwort(['ok' => false, 'fehler' => 'teile unplausibel',
                 'grenze' => MAX_FRAGE_TEILE], 400);
    }
    if ($f_teile > 1 && $k === 'keine') {
        // Ungestueckelt und unverschluesselt hochladen hiesse: Der Webspace
        // bekommt die Datei im Klartext zu sehen und behaelt sie minutenlang.
        antwort(['ok' => false,
                 'fehler' => 'Gestueckelte Fragen nur verschluesselt'], 400);
    }

    if ($k !== 'keine') {
        if ($f_teile > 1) {
            // Das Verzeichnis traegt noch keinen Inhalt -- der kommt in den
            // Stuecken.
            // Das Verzeichnis traegt noch keinen Inhalt -- der kommt in
            // den Stuecken. Die Stueckliste wird weiter unten nachgetragen,
            // sobald die Marke feststeht: Die Dateinamen haengen an ihr.
            $nutz = ['chiffre' => ''];
        } elseif (!ist_chiffre($n['chiffre'] ?? null, MAX_FRAGE)) {
            antwort(['ok' => false, 'fehler' => 'chiffre: Base64 erwartet',
                     'grenze' => MAX_FRAGE], 400);
        } else {
            $nutz = ['chiffre' => (string)$n['chiffre']];
        }
    } else {
    $dienst = $n['dienst'] ?? null;
    $akt    = $n['aktion'] ?? null;
    $daten  = $n['daten']  ?? null;

    // Weissliste der FORM, nicht des Sinns. Welche Dienste es gibt, weiss
    // diese Datei nicht und soll es nicht wissen -- das entscheidet der
    // Agent gegen seine eigene config.toml.
    //
    // Die Formregel steht trotzdem, und zwar aus einem anderen Grund: So
    // koennen `dienst` und `aktion` unter keinen Umstaenden in einen
    // Dateinamen, einen Pfad oder eine Kopfzeile ausbrechen. Sie erscheinen
    // ohnehin in keinem Dateinamen -- das ist die erste Schranke, das hier
    // die zweite.
    if (!ist_bezeichner($dienst)) {
        antwort(['ok' => false, 'fehler' => 'dienst: Bezeichner erwartet'], 400);
    }
    if (!ist_bezeichner($akt)) {
        antwort(['ok' => false, 'fehler' => 'aktion: Bezeichner erwartet'], 400);
    }
    // Aus der Objekt-Fassung, nicht aus der Feld-Fassung -- Begruendung oben
    // bei $roh_obj. Damit geht `daten` unveraendert wieder hinaus: Objekte
    // bleiben Objekte, Listen bleiben Listen, auch verschachtelt.
    $daten_obj = (is_object($roh_obj) && isset($roh_obj->nutzlast)
                  && is_object($roh_obj->nutzlast)
                  && isset($roh_obj->nutzlast->daten))
                 ? $roh_obj->nutzlast->daten : null;
    if (!is_array($daten) || !is_object($daten_obj)) {
        antwort(['ok' => false, 'fehler' => 'daten: Objekt erwartet'], 400);
    }

    $nutz = ['dienst' => $dienst, 'aktion' => $akt, 'daten' => $daten_obj];
    $roh  = json_encode($nutz, JSON_UNESCAPED_UNICODE);
    if ($roh === false || strlen($roh) > MAX_FRAGE) {
        antwort(['ok' => false, 'fehler' => 'Frage zu gross', 'grenze' => MAX_FRAGE], 400);
    }

    }   // Ende des unverschluesselten Zweigs

    $roh_ip = (string)($_SERVER['REMOTE_ADDR'] ?? '?');
    $ergebnis = zustand_aendern(function (array &$d) use ($nutz, $roh_ip, $k, $f_teile, $marke_vorgabe) {
        // Das NETZ, nicht die Adresse -- Begruendung bei absender_kennung().
        $wer = substr(hash('sha256', $d['salz'] . '|'
                                     . absender_kennung($roh_ip)), 0, 16);

        $meine = 0;
        foreach ($d['offen'] as $e) { if (($e['wer'] ?? '') === $wer) $meine++; }
        if ($meine >= MAX_JE_IP) {
            return ['ok' => false, 'fehler' => 'Zu viele offene Fragen', 'code' => 429];
        }

        // FAIRES VERDRAENGEN STATT ABWEISEN
        //
        // Die erste Fassung antwortete bei voller Schlange schlicht mit 503.
        // Das ist die Achillesferse jedes globalen Deckels: Wer zuerst da
        // ist, sperrt alle anderen aus. Mit MAX_OFFEN = 40 und MARKE_TTL =
        // 120 genuegen vierzig Anfragen alle zwei Minuten, um das ganze
        // System dauerhaft lahmzulegen -- ein paar Kilobyte Aufwand.
        //
        // Ein Rechenraetsel im Browser (Proof-of-Work) hilft dagegen NICHT:
        // Es verteuert die RATE, und dieser Angriff hat keine hohe Rate. Er
        // HAELT Plaetze. Vierzig Plaetze alle zwei Minuten kosten bei 100 ms
        // Rechenzeit ganze vier Sekunden -- das bremst niemanden, waehrend
        // ein altes Handy die 100 ms bei jeder Frage bezahlt.
        //
        // Also nicht den Platz verteuern, sondern ihn gerecht vergeben: Ist
        // die Schlange voll, wird nicht der Neuankoemmling abgewiesen,
        // sondern dem Absender mit den MEISTEN Plaetzen sein aeltester
        // genommen.
        //
        // Damit gilt: Wer genau einen Platz haelt, wird nie verdraengt,
        // solange irgendjemand zwei haelt. Ein Angreifer kann die Schlange
        // also nicht mehr besetzen, sondern hoechstens seinen Anteil daran
        // -- und der schrumpft, je mehr echte Besucher da sind.
        //
        // Halten alle genau einen Platz, ist die Schlange ehrlich voll. Dann
        // ist 503 die richtige Auskunft, und niemand wird verdraengt.
        if (count($d['offen']) >= MAX_OFFEN) {
            // WICHTIG: hier NICHT $k als Schleifenvariable verwenden. $k
            // traegt das Verfahren ("noise_ik" o.ae.) und ist von aussen in
            // diese Closure hineingereicht (siehe `use ($nutz, ..., $k, ...)`
            // oben). PHP kennt keinen Block-Scope -- ein `foreach` oder `if`
            // eroeffnet KEINEN neuen Gueltigkeitsbereich, nur eine Funktion
            // oder Closure tut das. Eine Schleifenvariable namens $k
            // ueberschreibt also dauerhaft das echte $k fuer den Rest DIESER
            // Closure, nicht nur fuer die Dauer der Schleife.
            //
            // Genau das geschah hier: Sobald die Warteschlange voll war UND
            // wirklich verdraengt wurde (nicht die beiden Faelle mit 503/429
            // vorher), stand in $k danach der "wer"-Wert des letzten
            // Eintrags -- ein 16-stelliger Hex-Hash statt "noise_ik". Der
            // Aufruf umschlag($marke, 0, $f_teile, $nutz, $k) weiter unten
            // schrieb diesen Muell als Verschluesselungsangabe der neuen
            // Frage auf die Ablage. Der Agent erkannte das Verfahren nicht,
            // lehnte die Frage kommentarlos ab, und der Besucher lief in
            // seinen Zeitablauf, ohne je zu erfahren warum. Am 03.09.2026
            // gefunden und mit einem isolierten PHP-Test bewiesen: PHP
            // ueberschreibt $k tatsaechlich ausserhalb der Schleife.
            $zaehlung = [];
            foreach ($d['offen'] as $e) {
                $absender = (string)($e['wer'] ?? '');
                $zaehlung[$absender] = ($zaehlung[$absender] ?? 0) + 1;
            }
            arsort($zaehlung);
            $vielste = (string)array_key_first($zaehlung);

            if ($zaehlung[$vielste] <= 1) {
                return ['ok' => false, 'fehler' => 'Vermittler ausgelastet',
                        'code' => 503];
            }
            if ($vielste === $wer) {
                // Ich bin selbst der Vielhalter. Dann trifft es mich.
                return ['ok' => false, 'fehler' => 'Zu viele offene Fragen',
                        'code' => 429];
            }

            $opfer_i = -1;
            foreach ($d['offen'] as $i => $e) {
                if ((string)($e['wer'] ?? '') !== $vielste) continue;
                if ($opfer_i < 0
                    || (int)$e['ts'] < (int)$d['offen'][$opfer_i]['ts']) {
                    $opfer_i = $i;
                }
            }
            if ($opfer_i < 0) {
                return ['ok' => false, 'fehler' => 'Vermittler ausgelastet',
                        'code' => 503];
            }
            $opfer = $d['offen'][$opfer_i];
            raeume_marke((string)$opfer['marke'], (int)($opfer['st'] ?? 0),
                         (int)($opfer['fst'] ?? 0));
            array_splice($d['offen'], $opfer_i, 1);
            // Gezaehlt, nicht verschwiegen: Der Zaehler steht im Selbsttest
            // und ist das Warnzeichen fuer genau diesen Angriff. Ein
            // Verdraengen ist kein Normalbetrieb.
            $d['verdraengt'] = (int)($d['verdraengt'] ?? 0) + 1;
        }

        if ($marke_vorgabe !== '') {
            // Vorgegeben -- nur ablehnen, wenn sie schon in Gebrauch ist.
            // Bei 128 Bit Zufall praktisch nie der Fall; trotzdem geprueft,
            // statt eine bestehende Frage/Antwort stillschweigend zu
            // ueberschreiben.
            foreach ($d['offen'] as $e) {
                if (($e['marke'] ?? '') === $marke_vorgabe) {
                    return ['ok' => false, 'fehler' => 'Marke bereits in Gebrauch',
                             'code' => 409];
                }
            }
            foreach ($d['fertig'] as $e) {
                if (($e['marke'] ?? '') === $marke_vorgabe) {
                    return ['ok' => false, 'fehler' => 'Marke bereits in Gebrauch',
                             'code' => 409];
                }
            }
            $marke = $marke_vorgabe;
        } else {
            $marke = bin2hex(random_bytes(16));    // 128 Bit, nicht erratbar
        }

        // Atomar, obwohl die Reihenfolge allein schon traegt: Die Marke
        // kommt erst danach in die Warteschlange, der Agent kann die Datei
        // also nie halb sehen. In `tunnel.php` ist genau das der Fall -- dort
        // wird die Fragedatei mit einfachem file_put_contents geschrieben,
        // und die Reihenfolge ist tragend, ohne irgendwo benannt zu sein.
        // Eine Annahme, die nur in der Reihenfolge steckt, geht beim naechsten
        // Umbau verloren.
        // Bei mehreren Stuecken traegt das Verzeichnis deren Dateinamen.
        // Sie werden erst hier gebildet, weil sie an der Marke haengen -- und
        // die entsteht eine Zeile weiter oben.
        if ($f_teile > 1) {
            $liste = [];
            for ($i = 0; $i < $f_teile; $i++) {
                $liste[] = ['teil' => $i, 'datei' => frage_stueck_name($marke, $i)];
            }
            $nutz['stuecke'] = $liste;
        }
        if (!schreibe_atomar(ABLAGE . '/frage_' . $marke . '.json',
                             umschlag($marke, 0, $f_teile, $nutz, $k))) {
            return ['ok' => false, 'fehler' => 'Ablage nicht schreibbar', 'code' => 500];
        }
        // `bereit` entscheidet, ob die Marke in der oeffentlichen
        // Warteschlange auftaucht. Bei einer gestueckelten Frage erst, wenn
        // alle Stuecke da sind -- sonst holte der Agent eine halbe Frage.
        $d['offen'][] = ['marke' => $marke, 'ts' => time(), 'wer' => $wer,
                         'st' => 0, 'fst' => 0,
                         'bereit' => ($f_teile === 1)];
        return ['ok' => true, 'marke' => $marke, 'teile' => $f_teile];
    });

    if ($ergebnis === null) {
        antwort(['ok' => false, 'fehler' => 'Ablage nicht schreibbar'], 500);
    }
    if (empty($ergebnis['ok'])) {
        antwort($ergebnis, (int)($ergebnis['code'] ?? 400));
    }
    antwort(['ok' => true, 'marke' => $ergebnis['marke'], 'ttl' => MARKE_TTL,
             'teile' => $ergebnis['teile'] ?? 1,
             'abholen' => 'ahpt/antwort_' . $ergebnis['marke'] . '.json']);

// ------------------------------ Besucher legt ein Stueck einer Frage ab
//
// DAS IST DER HOCHLADEWEG, und er ist der einzige Ort, an dem ein Besucher
// nennenswerte Datenmengen ablegen darf. Deshalb ist er enger gefasst als
// alles andere hier:
//
//   * nur zu einer Marke, die es GIBT und die NOCH NICHT BEREIT ist. Eine
//     fertige oder verfallene Marke nimmt nichts mehr an -- sonst liesse
//     sich eine bereits gestellte Frage nachtraeglich unterwandern.
//   * nur so viele Stuecke, wie das Verzeichnis angekuendigt hat.
//   * Groesse je Stueck gedeckelt, Zahl der Stuecke gedeckelt, und der
//     Sammler raeumt nach MARKE_TTL alles weg.
//
// Kein Ausweis: Der Besucher hat keinen und soll keinen haben. Die Schranke
// ist, dass er die Marke nur bekommt, wenn er sie sich gerade hat geben
// lassen -- und dass sie 120 Sekunden spaeter verfallen ist.
case 'frage_stueck':
    $marke = (string)($eingabe['marke'] ?? '');
    if (!ist_marke($marke)) {
        antwort(['ok' => false, 'fehler' => 'Ungueltige Marke'], 400);
    }
    $teil  = $eingabe['teil']  ?? null;
    $teile = $eingabe['teile'] ?? null;
    if (!is_int($teil) || !is_int($teile)
        || $teile < 2 || $teile > MAX_FRAGE_TEILE
        || $teil < 0 || $teil >= $teile) {
        antwort(['ok' => false, 'fehler' => 'teil/teile unplausibel',
                 'grenze' => MAX_FRAGE_TEILE], 400);
    }
    $inhalt = $eingabe['nutzlast'] ?? null;
    if (!ist_chiffre($inhalt, MAX_STUECK)) {
        antwort(['ok' => false, 'fehler' => 'nutzlast: Base64 erwartet',
                 'grenze' => MAX_STUECK], 400);
    }

    $stand = zustand_aendern(function (array &$d) use ($marke, $teil, $teile, $inhalt, $k) {
        $gefunden = false;
        foreach ($d['offen'] as &$e) {
            if (($e['marke'] ?? '') !== $marke) continue;
            // Eine bereits sichtbare Marke nimmt nichts mehr an.
            if ($e['bereit'] ?? true) return false;
            $gefunden = true;
            if ($teil + 1 > (int)($e['fst'] ?? 0)) $e['fst'] = $teil + 1;
            break;
        }
        unset($e);
        if (!$gefunden) return false;

        return schreibe_atomar(ABLAGE . '/' . frage_stueck_name($marke, $teil),
            umschlag($marke, $teil, $teile, $inhalt, $k)) ? true : null;
    });

    if ($stand === null)  antwort(['ok' => false, 'fehler' => 'Ablage nicht schreibbar'], 500);
    if ($stand === false) antwort(['ok' => false, 'fehler' => 'Marke unbekannt, verfallen oder schon fertig'], 404);
    antwort(['ok' => true, 'datei' => frage_stueck_name($marke, $teil)]);

// --------------------------- Besucher meldet: alle Stuecke sind abgelegt
//
// Erst hier wird die Marke in der Warteschlange sichtbar. Der Vermittler
// sieht vorher NACH, ob wirklich alle Stuecke da sind -- er verlaesst sich
// nicht auf die Zusage des Absenders. Eine Warteschlange, die auf Luecken
// zeigt, ist schlimmer als eine leere.
case 'frage_fertig':
    $marke = (string)($eingabe['marke'] ?? '');
    if (!ist_marke($marke)) {
        antwort(['ok' => false, 'fehler' => 'Ungueltige Marke'], 400);
    }
    $teile = $eingabe['teile'] ?? null;
    if (!is_int($teile) || $teile < 2 || $teile > MAX_FRAGE_TEILE) {
        antwort(['ok' => false, 'fehler' => 'teile unplausibel'], 400);
    }
    for ($i = 0; $i < $teile; $i++) {
        if (!is_file(ABLAGE . '/' . frage_stueck_name($marke, $i))) {
            antwort(['ok' => false, 'fehler' => 'Es fehlt ein Stueck',
                     'teil' => $i], 409);
        }
    }

    $stand = zustand_aendern(function (array &$d) use ($marke) {
        foreach ($d['offen'] as &$e) {
            if (($e['marke'] ?? '') !== $marke) continue;
            if ($e['bereit'] ?? true) return false;   // schon fertig gemeldet
            $e['bereit'] = true;
            // Die Uhr laeuft ab JETZT: Das Hochladen soll nicht von der
            // Bearbeitungsfrist abgehen.
            $e['ts'] = time();
            return true;
        }
        unset($e);
        return false;
    });
    if ($stand !== true) {
        antwort(['ok' => false, 'fehler' => 'Marke unbekannt, verfallen oder schon fertig'], 404);
    }
    antwort(['ok' => true, 'marke' => $marke, 'ttl' => MARKE_TTL,
             'abholen' => 'ahpt/antwort_' . $marke . '.json']);

// ------------------------------------------ Agent legt ein Stueck ab
//
// Stuecke kommen VOR dem Verzeichnis. Andersherum verwiese ein Verzeichnis
// auf Dateien, die es noch nicht gibt.
case 'stueck':
    if (!agent_erlaubt($eingabe)) {
        antwort(['ok' => false, 'fehler' => 'Geheimnis noetig'], 403);
    }
    $marke = (string)($eingabe['marke'] ?? '');
    if (!ist_marke($marke)) {
        antwort(['ok' => false, 'fehler' => 'Ungueltige Marke'], 400);
    }
    $teil  = $eingabe['teil']  ?? null;
    $teile = $eingabe['teile'] ?? null;
    if (!is_int($teil) || !is_int($teile)
        || $teile < 2 || $teile > MAX_TEILE || $teil < 0 || $teil >= $teile) {
        antwort(['ok' => false, 'fehler' => 'teil/teile unplausibel',
                 'grenze' => MAX_TEILE], 400);
    }
    $inhalt = $eingabe['nutzlast'] ?? null;
    if (!is_string($inhalt)) {
        antwort(['ok' => false, 'fehler' => 'nutzlast: Zeichenkette erwartet'], 400);
    }
    if (strlen($inhalt) > MAX_STUECK) {
        antwort(['ok' => false, 'fehler' => 'Stueck zu gross', 'grenze' => MAX_STUECK], 413);
    }

    $stand = zustand_aendern(function (array &$d) use ($marke, $teil, $teile, $inhalt, $k) {
        // Nur zu einer OFFENEN Marke. Eine beantwortete oder verfallene
        // Marke nimmt nichts mehr an -- sonst koennte man ein Verzeichnis
        // nachtraeglich unterwandern.
        $gefunden = false;
        foreach ($d['offen'] as &$e) {
            if (($e['marke'] ?? '') !== $marke) continue;
            $gefunden = true;
            if ($teil + 1 > (int)($e['st'] ?? 0)) $e['st'] = $teil + 1;
            break;
        }
        unset($e);
        if (!$gefunden) return false;

        return schreibe_atomar(ABLAGE . '/' . stueck_name($marke, $teil),
            umschlag($marke, $teil, $teile, $inhalt, $k)) ? true : null;
    });

    if ($stand === null)  antwort(['ok' => false, 'fehler' => 'Ablage nicht schreibbar'], 500);
    if ($stand === false) antwort(['ok' => false, 'fehler' => 'Marke unbekannt oder verfallen'], 404);
    antwort(['ok' => true, 'datei' => stueck_name($marke, $teil)]);

// ------------------------------------------ Agent legt die Antwort ab
case 'antwort':
    if (!agent_erlaubt($eingabe)) {
        antwort(['ok' => false, 'fehler' => 'Geheimnis noetig'], 403);
    }
    $marke = (string)($eingabe['marke'] ?? '');
    if (!ist_marke($marke)) {
        antwort(['ok' => false, 'fehler' => 'Ungueltige Marke'], 400);
    }
    $teile = $eingabe['teile'] ?? 1;
    if (!is_int($teile) || $teile < 1 || $teile > MAX_TEILE) {
        antwort(['ok' => false, 'fehler' => 'teile unplausibel', 'grenze' => MAX_TEILE], 400);
    }
    $n = $eingabe['nutzlast'] ?? null;
    if (!is_array($n)) {
        antwort(['ok' => false, 'fehler' => 'nutzlast fehlt'], 400);
    }

    // `titel` und `quelle` werden im Browser angezeigt und sind von aussen
    // bestimmt -- bei einer Suche ist der Titel der Suchbegriff. Der Agent
    // entschaerft sie schon; hier steht die zweite Schranke, weil ein Agent
    // mit gestohlenem Geheimnis die erste nicht bedienen wuerde.
    // `inhalt` bleibt unangetastet: Wer die Nutzlast saeubert, liefert nicht
    // mehr aus, sondern verfaelscht.
    // VERSCHLUESSELT: auch hier nur ein undurchsichtiger Block.
    //
    // `gefunden`, `titel` und `quelle` wandern mit HINEIN. Stuenden sie
    // aussen, verriete der Titel den Dateinamen und `gefunden` das Ergebnis
    // -- beides genau das, was verborgen bleiben soll. Ein Webspace, der
    // "gefunden: true, titel: gehaltsabrechnung.pdf" liest, braucht den
    // Inhalt nicht mehr.
    //
    // `sicherer_titel()` entfaellt damit fuer diesen Fall, und das ist
    // richtig: Es gibt hier keinen Titel mehr, den jemand ungeprueft
    // anzeigen koennte. Der Client entschluesselt und entschaerft selbst.
    if ($k !== 'keine') {
        $chiffre = $n['chiffre'] ?? null;
        if ($teile === 1 && !ist_chiffre($chiffre, MAX_STUECK)) {
            antwort(['ok' => false, 'fehler' => 'chiffre: Base64 erwartet',
                     'grenze' => MAX_STUECK], 400);
        }
        $nutz = ['chiffre' => $teile > 1 ? '' : (string)$chiffre];
    } else {
    $nutz = [
        'gefunden'   => (bool)($n['gefunden'] ?? true),
        'titel'      => sicherer_titel((string)($n['titel']  ?? '')),
        'quelle'     => sicherer_titel((string)($n['quelle'] ?? '')),
        'inhalt_typ' => (string)($n['inhalt_typ'] ?? 'text'),
        'inhalt'     => (string)($n['inhalt'] ?? ''),
    ];
    if (!in_array($nutz['inhalt_typ'], ['text', 'base64'], true)) {
        antwort(['ok' => false, 'fehler' => 'inhalt_typ: text oder base64'], 400);
    }
    if ($teile === 1 && strlen($nutz['inhalt']) > MAX_STUECK) {
        antwort(['ok' => false, 'fehler' => 'Antwort zu gross -- stueckeln',
                 'grenze' => MAX_STUECK], 413);
    }
    if ($teile > 1) {
        // Bei geteilter Antwort steht der Inhalt in den Stuecken, nicht hier.
        $nutz['inhalt'] = '';
    }
    }   // Ende des unverschluesselten Zweigs

    // Das Stueckverzeichnis gilt fuer beide Faelle gleichermassen.
    if ($teile > 1) {
        $liste = [];
        for ($i = 0; $i < $teile; $i++) {
            $liste[] = ['teil' => $i, 'datei' => stueck_name($marke, $i)];
        }
        $nutz['stuecke'] = $liste;
    }

    $stand = zustand_aendern(function (array &$d) use ($marke, $teile, $nutz, $k) {
        $neu = []; $treffer = false;
        foreach ($d['offen'] as $e) {
            if (($e['marke'] ?? '') === $marke) { $treffer = true; continue; }
            $neu[] = $e;
        }
        if (!$treffer) return 'unbekannt';          // unbekannt oder verfallen

        // Kein Verzeichnis auf fehlende Stuecke. Der Agent legt sie vorher
        // ab; wenn eines fehlt, hat er unterwegs aufgegeben -- und ein
        // Verzeichnis, das ins Leere zeigt, laesst den Besucher eine halbe
        // Datei zusammensetzen, ohne dass ein Fehler entsteht.
        if ($teile > 1) {
            for ($i = 0; $i < $teile; $i++) {
                if (!is_file(ABLAGE . '/' . stueck_name($marke, $i))) {
                    return 'stueck_fehlt:' . $i;
                }
            }
        }

        $d['offen'] = $neu;
        if (!schreibe_atomar(ABLAGE . '/antwort_' . $marke . '.json',
                             umschlag($marke, 0, $teile, $nutz, $k))) {
            return 'schreibfehler';
        }
        @unlink(ABLAGE . '/frage_' . $marke . '.json');
        // Ab hier wartet die Antwort auf Abholung -- und WIRD wieder
        // geraeumt, anders als in tunnel.php.
        $d['fertig'][] = ['marke' => $marke, 'ts' => time(), 'teile' => $teile];
        return 'ok';
    });

    if ($stand === null)          antwort(['ok' => false, 'fehler' => 'Ablage nicht schreibbar'], 500);
    if ($stand === 'unbekannt')   antwort(['ok' => false, 'fehler' => 'Marke unbekannt oder verfallen'], 404);
    if ($stand === 'schreibfehler') antwort(['ok' => false, 'fehler' => 'Ablage nicht schreibbar'], 500);
    if (is_string($stand) && strncmp($stand, 'stueck_fehlt:', 13) === 0) {
        antwort(['ok' => false, 'fehler' => 'Stueck fehlt', 'teil' => (int)substr($stand, 13)], 409);
    }
    antwort(['ok' => true, 'teile' => $teile]);

// ------------------------------------------ Diagnose
//
// Sagt, OB das Geheimnis lesbar ist, nie WELCHES. Herausgegeben werden nur
// Laengen und ein Fingerabdruck; daraus laesst sich ein 256-Bit-Zufallswert
// nicht zurueckrechnen.
//
// Es gibt sie, weil am 02.09.2026 beim ersten Live-Lauf das Geheimnis
// abgewiesen wurde und von aussen nicht zu unterscheiden war, WARUM: Datei
// nicht da? Nicht lesbar? Andere Zeilenenden? Falscher Wert? Ein Fehlschlag,
// der keine Auskunft gibt, kostet mehr als er schuetzt.
case 'selbsttest':
    $roh  = @file_get_contents(TOKEN_DATEI);
    $soll = trim(lies_geschuetzt(TOKEN_DATEI));
    // Nur lesen, nicht sperren: Der Selbsttest soll gerade dann noch
    // antworten, wenn sonst etwas klemmt -- eine Diagnose, die auf eine
    // Sperre wartet, ist keine.
    $zustand = json_decode(lies_geschuetzt(ZUSTAND), true);
    if (!is_array($zustand)) $zustand = [];
    $zle  = '?';
    if ($roh !== false) {
        if     (strpos($roh, "\r\n") !== false) $zle = 'CRLF';
        elseif (strpos($roh, "\n")   !== false) $zle = 'LF';
        elseif (strpos($roh, "\r")   !== false) $zle = 'CR';
        else                                    $zle = 'keines';
    }
    antwort([
        'ok'              => true,
        'protokoll'       => AHPT_VERSION,
        'datei_da'        => is_file(TOKEN_DATEI),
        'lesbar'          => $roh !== false,
        'roh_bytes'       => $roh === false ? 0 : strlen($roh),
        'beginnt_mit_php' => $roh !== false
                             && strncmp(ltrim($roh, "\xEF\xBB\xBF"), '<?php', 5) === 0,
        'zeilenende'      => $zle,
        'geheim_zeichen'  => strlen($soll),
        // `geheim_pruef` GIBT ES NICHT MEHR.
        //
        // Frueher stand hier substr(hash('sha256', $soll), 0, 16) -- gedacht
        // als Hilfe beim Einrichten: Man konnte vergleichen, ob Webspace und
        // Agent dasselbe Geheimnis haben, ohne es zu uebertragen.
        //
        // Es war aber OHNE JEDE ANMELDUNG abrufbar, und damit ein
        // Offline-Rateorakel: Wer ein Geheimnis raten will, kann seine
        // Kandidaten gegen diesen Wert pruefen -- milliardenfach je Sekunde,
        // ohne den Server anzufassen. Und wer es findet, kann gefaelschte
        // Antworten einschleusen, die der Besucher fuer echt haelt.
        //
        // Bei einem zufaelligen 64-Zeichen-Geheimnis ist das folgenlos. Aber
        // geprueft wird oben nur die LAENGE (mindestens 16 Zeichen), nicht
        // die Zufaelligkeit -- "sommer2026abcdef" kommt durch. Fuer so eines
        // waere der Wert hier das Ende.
        //
        // Die Einrichtungshilfe ist deshalb dorthin gewandert, wo sie
        // hingehoert: `ausliefern.sh` PRUEFT das Geheimnis, indem es sich
        // damit ausweist. Ein Test ist besser als ein Fingerabdruck.
        //
        // Am 03.09.2026 gefunden, beim Nachsehen, was die Seite oeffentlich
        // hergibt.
        'ablage_da'       => is_dir(ABLAGE),
        'ablage_schreib'  => is_dir(ABLAGE) && is_writable(ABLAGE),
        // Wie oft musste ein Platz verdraengt werden. Im Normalbetrieb 0.
        // Steigt der Wert, hat jemand versucht, die Warteschlange zu
        // besetzen -- das ist das einzige Warnzeichen fuer diesen Angriff,
        // und es soll ablesbar sein, ohne dass man auf den Webspace muss.
        // Was hier steht, verraet nichts, was die oeffentliche
        // Warteschlange nicht ohnehin zeigt.
        'verdraengt'      => (int)($zustand['verdraengt'] ?? 0),
        'offen'           => is_array($zustand['offen'] ?? null)
                             ? count($zustand['offen']) : 0,
        'wartet_auf_abholung' => is_array($zustand['fertig'] ?? null)
                             ? count($zustand['fertig']) : 0,
    ]);

default:
    antwort(['ok' => false, 'fehler' => 'Unbekannte Aktion: ' . $aktion,
             'aktionen' => ['frage', 'stueck', 'antwort', 'selbsttest'],
             'hinweis' => 'Abgeholt wird NICHT ueber diese Datei, sondern statisch: '
                        . 'ahpt/warteschlange.json (Agent) bzw. '
                        . 'ahpt/antwort_<marke>.json (Besucher). Das ist der ganze Sinn.'], 400);
}
