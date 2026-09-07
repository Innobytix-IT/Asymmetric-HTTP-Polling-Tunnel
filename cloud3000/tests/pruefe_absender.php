<?php
/**
 * pruefe_absender.php -- prueft absender_kennung() gegen echtes PHP
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WARUM ES DIESE DATEI GIBT
 * -------------------------
 * `absender_kennung()` entscheidet, wer als derselbe Absender gilt. Daran
 * haengen MAX_JE_IP und das faire Verdraengen -- also die einzige Schranke
 * gegen Queue-Jamming. Ungeprueft duerfte sie nicht bleiben.
 *
 * Ueber HTTP laesst sie sich nicht messen: Ein Testlauf gegen `php -S`
 * kommt immer von 127.0.0.1. Man kann REMOTE_ADDR nicht waehlen, ohne eine
 * Testklappe in den Vermittler zu bauen -- und eine Testklappe in genau der
 * Funktion, die Absender unterscheidet, waere die Schwachstelle selbst.
 *
 * Deshalb wird die Funktion hier AUS relay.php HERAUSGESCHNITTEN und
 * ausgefuehrt. Geprueft wird damit der echte Quelltext, nicht eine zweite
 * Fassung davon -- an zwei Fassungen derselben Sache sind in diesem Projekt
 * schon mehrere Fehler gestorben.
 *
 * Aufruf:  php tests/pruefe_absender.php
 */

declare(strict_types=1);

$quelle = @file_get_contents(__DIR__ . '/../relay.php');
if ($quelle === false) {
    fwrite(STDERR, "ABBRUCH: relay.php nicht lesbar.\n");
    exit(2);
}

// Von "function absender_kennung" bis zur ersten schliessenden Klammer, die
// allein am Zeilenanfang steht. Das passt, solange Funktionen im Quelltext
// nicht eingerueckt stehen -- was sie dort nicht tun.
// `\r?` an beiden Enden ist kein Uebereifer: Genau daran ist diese Datei am
// 02.09.2026 zuerst gescheitert. relay.php war beim Bearbeiten auf einem
// Windows-Rechner still zu CRLF geworden, und `\n\}\n` traf `\r\n}\r\n`
// nicht. Die Pruefung meldete daraufhin, die Funktion sei nicht auffindbar
// -- richtig gemeldet, aber die Ursache lag zwei Ebenen tiefer.
if (!preg_match('/\r?\nfunction absender_kennung\(.*?\r?\n\}\r?\n/s',
                $quelle, $treffer)) {
    fwrite(STDERR, "ABBRUCH: absender_kennung() liess sich nicht aus relay.php\n"
                 . "         herausloesen. Wurde sie umbenannt oder eingerueckt?\n"
                 . "         Dann prueft diese Datei nichts -- und das muss\n"
                 . "         auffallen, statt als Erfolg durchzugehen.\n");
    exit(2);
}
eval($treffer[0]);

$faelle = [
    // Eingabe                 erwartet                        warum
    ['1.2.3.4',                'v4:01020304',                  'IPv4 zaehlt voll'],
    ['255.255.255.255',        'v4:ffffffff',                  'IPv4 Randwert'],
    ['127.0.0.1',              'v4:7f000001',                  'Loopback'],
    ['::ffff:1.2.3.4',         'v4:01020304',                  'IPv4 im IPv6-Kleid bleibt eine Adresse'],
    ['::ffff:9.9.9.9',         'v4:09090909',                  'dito, anderer Wert'],
    ['2001:db8:1:2::1',        'v6:20010db800010002',          'IPv6 auf /64'],
    ['2001:db8:1:2::ffff',     'v6:20010db800010002',          'gleiches /64 -> gleicher Absender'],
    ['2001:db8:1:2:aaaa:bbbb:cccc:dddd', 'v6:20010db800010002', 'gleiches /64, voll ausgeschrieben'],
    ['2001:db8:1:3::1',        'v6:20010db800010003',          'anderes /64 -> anderer Absender'],
    ['::1',                    'v6:0000000000000000',          'IPv6-Loopback'],
    ['',                       '?',                            'leer'],
    ['kaputt',                 'roh:kaputt',                   'unlesbar bleibt unveraendert'],
];

$fehler = 0;
echo "\nABSENDER-KENNUNG (aus relay.php herausgeloest, echtes PHP)\n\n";
foreach ($faelle as [$eingabe, $soll, $warum]) {
    $ist = absender_kennung($eingabe);
    $ok  = ($ist === $soll);
    printf("  %-48s %s%s\n", $warum, $ok ? 'ok' : 'FEHLSCHLAG',
           $ok ? '' : sprintf('  -- %s ergab %s, erwartet %s',
                              var_export($eingabe, true), $ist, $soll));
    $fehler += $ok ? 0 : 1;
}

// Die zwei Eigenschaften, auf die es ankommt -- gesondert benannt, damit
// eine Aenderung nicht nur eine Zeile der Tabelle umwirft, sondern die
// Aussage.
$paare = [
    ['ein /64 ist EIN Absender',
     absender_kennung('2001:db8:aa:bb::1') === absender_kennung('2001:db8:aa:bb::2')],
    ['zwei /64 sind ZWEI Absender',
     absender_kennung('2001:db8:aa:bb::1') !== absender_kennung('2001:db8:aa:bc::1')],
    ['zwei IPv4 bleiben zwei Absender',
     absender_kennung('1.2.3.4') !== absender_kennung('1.2.3.5')],
    ['IPv4 faellt nicht mit IPv4-im-IPv6-Kleid zusammen -- sondern trifft es',
     absender_kennung('1.2.3.4') === absender_kennung('::ffff:1.2.3.4')],
    ['zwei IPv4 im IPv6-Kleid bleiben zwei Absender',
     absender_kennung('::ffff:1.2.3.4') !== absender_kennung('::ffff:1.2.3.5')],
];
echo "\n";
foreach ($paare as [$was, $gilt]) {
    printf("  %-48s %s\n", $was, $gilt ? 'ok' : 'FEHLSCHLAG');
    $fehler += $gilt ? 0 : 1;
}

echo "\n" . ($fehler === 0
    ? "  alle bestanden.\n"
    : "  $fehler FEHLSCHLAG(E).\n");
exit($fehler === 0 ? 0 : 1);
