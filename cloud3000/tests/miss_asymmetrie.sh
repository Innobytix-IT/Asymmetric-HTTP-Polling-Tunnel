#!/bin/bash
# miss_asymmetrie.sh -- traegt das Muster auf DIESEM Webspace?
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Manuel Person, InnoBytix-IT
#
# Aufruf:
#     bash tests/miss_asymmetrie.sh https://example.de/ahpt
#
# WOZU
# ----
# AHPT beruht auf einer einzigen gemessenen Eigenschaft billiger Webspaces:
#
#     LESEN ist unbegrenzt, AUSFUEHREN ist scharf gedeckelt.
#
# Gemessen am 01./02.09.2026 gegen IONOS:
#
#     12 gleichzeitige Aufrufe eines PHP-Skripts      ->  7x 200, 5x 503
#     12 gleichzeitige Aufrufe einer statischen Datei -> 12x 200
#     20 gleichzeitige bedingte Abrufe                -> 20x 304, 0 Bytes
#     Laufzeit 304                                    ->  75-99 ms
#     Laufzeit PHP                                    -> 123-1638 ms
#
# Ist das auf einem anderen Webspace NICHT so, traegt der ganze Entwurf dort
# nicht -- und das sollte man frueh wissen statt spaet. Vor allem:
#
#     OHNE ETags pollt der Agent jedes Mal die volle Datei. Dann kostet das
#     Warten wieder etwas, und der einzige Grund fuer AHPT ist weg.
#
# Diese Datei misst und URTEILT NICHT. Sie gibt Zahlen aus; die Bewertung
# steht darunter in Klartext. Ein Webspace ist kein Pruefling, der besteht
# oder durchfaellt -- er ist geeignet oder nicht.
#
# Die Messung ist bewusst kurz: rund 45 Anfragen in wenigen Sekunden. Das
# ist normaler Webverkehr, keine Last.

set -u

U="${1:-}"
if [ -z "$U" ]; then
    echo "Aufruf: bash tests/miss_asymmetrie.sh https://example.de/ahpt"
    exit 2
fi
U="${U%/}"

N_PHP=12
N_STATISCH=12
N_BEDINGT=20

# ------------------------------------------------------------- Werkzeug

gleichzeitig() {   # anzahl url [zusatz-header]  -> "code laufzeit" je Zeile
    local n="$1" url="$2" kopf="${3:-}"
    local d i
    d=$(mktemp -d)
    for i in $(seq 1 "$n"); do
        if [ -n "$kopf" ]; then
            curl -s -o /dev/null -w '%{http_code} %{time_total}\n' \
                 -H "$kopf" "$url" > "$d/$i" 2>/dev/null &
        else
            curl -s -o /dev/null -w '%{http_code} %{time_total}\n' \
                 "$url" > "$d/$i" 2>/dev/null &
        fi
    done
    wait
    cat "$d"/* 2>/dev/null
    rm -rf "$d"
}

zaehle() { grep -c "^$1 " || true; }

spanne() {   # aus "code laufzeit"-Zeilen die Laufzeitspanne in ms
    awk '{ms=$2*1000; if(min==""||ms<min)min=ms; if(ms>max)max=ms}
         END{if(min=="")print "-"; else printf "%.0f-%.0f ms", min, max}'
}

echo ""
echo "ASYMMETRIE-MESSUNG   $U"
echo ""

# --------------------------------------------- Eine statische Datei erzeugen
#
# `warteschlange.json` entsteht erst mit der ersten Frage. Der Vermittler ist
# inhaltsblind, nimmt also jede formgerechte Frage an -- der Agent wird sie
# spaeter mit "dienst unbekannt" beantworten, und das ist hier egal. Wir
# brauchen nur die Datei.
curl -s -o /dev/null -X POST "$U/relay.php?action=frage" \
     -H 'Content-Type: application/json' \
     --data '{"v":1,"krypto":"keine","nutzlast":{"dienst":"messung","aktion":"messung","daten":{}}}'

STATISCH="$U/ahpt/warteschlange.json"
KOPF=$(curl -s -D - -o /dev/null "$STATISCH" | tr -d '\r')
CODE=$(printf '%s' "$KOPF" | awk 'NR==1{print $2}')
if [ "${CODE:-}" != "200" ]; then
    echo "  ABBRUCH: $STATISCH nicht abrufbar (HTTP ${CODE:-?})."
    echo "           Ohne eine statische Datei laesst sich nichts vergleichen."
    exit 2
fi
ETAG=$(printf '%s' "$KOPF" | awk 'tolower($1)=="etag:"{print $2}')

# --------------------------------------------------------------- 1. PHP
#
# `selbsttest` aendert keinen Zustand -- deshalb ist er gleichzeitig
# gefahrlos aufrufbar. Eine Frage waere es nicht: die schriebe unter Sperre.
PHP_ERG=$(gleichzeitig "$N_PHP" "$U/relay.php?action=selbsttest")
PHP_200=$(printf '%s\n' "$PHP_ERG" | zaehle 200)
PHP_503=$(printf '%s\n' "$PHP_ERG" | zaehle 503)
PHP_ZEIT=$(printf '%s\n' "$PHP_ERG" | spanne)

printf '  %-42s %s\n' "$N_PHP gleichzeitige PHP-Aufrufe" \
       "${PHP_200}x 200, ${PHP_503}x 503   (${PHP_ZEIT})"

# ---------------------------------------------------------- 2. Statisch
ST_ERG=$(gleichzeitig "$N_STATISCH" "$STATISCH")
ST_200=$(printf '%s\n' "$ST_ERG" | zaehle 200)
ST_ZEIT=$(printf '%s\n' "$ST_ERG" | spanne)

printf '  %-42s %s\n' "$N_STATISCH gleichzeitige statische Abrufe" \
       "${ST_200}x 200   (${ST_ZEIT})"

# ----------------------------------------------------------- 3. Bedingt
if [ -n "$ETAG" ]; then
    BD_ERG=$(gleichzeitig "$N_BEDINGT" "$STATISCH" "If-None-Match: $ETAG")
    BD_304=$(printf '%s\n' "$BD_ERG" | zaehle 304)
    BD_200=$(printf '%s\n' "$BD_ERG" | zaehle 200)
    BD_ZEIT=$(printf '%s\n' "$BD_ERG" | spanne)
    BYTES=$(curl -s -H "If-None-Match: $ETAG" "$STATISCH" | wc -c)
    printf '  %-42s %s\n' "$N_BEDINGT gleichzeitige bedingte Abrufe" \
           "${BD_304}x 304, ${BD_200}x 200   (${BD_ZEIT})"
    printf '  %-42s %s\n' "Rumpf einer 304-Antwort" "$BYTES Bytes"
else
    printf '  %-42s %s\n' "bedingte Abrufe" "KEIN ETag -- nicht messbar"
fi

# ------------------------------------------------------------- Bewertung

echo ""
echo "BEWERTUNG"
echo ""

if [ -z "$ETAG" ]; then
    echo "  KEIN ETag. Das ist der harte Ausschluss."
    echo "  Der Agent muesste die Warteschlange jedes Mal vollstaendig laden."
    echo "  Das Warten kostet dann Bandbreite statt nichts, und der einzige"
    echo "  Grund fuer AHPT faellt weg. Vor dem Betrieb klaeren, ob sich"
    echo "  ETags einschalten lassen (FileETag MTime Size in der .htaccess)."
elif [ "${BD_304:-0}" -lt "$N_BEDINGT" ]; then
    echo "  ETag vorhanden, aber nur ${BD_304} von ${N_BEDINGT} Abrufen ergaben 304."
    echo "  Nachsehen, ob ein Zwischenspeicher oder eine Weiterleitung"
    echo "  dazwischenfunkt."
else
    echo "  ETags wirken: alle bedingten Abrufe ergaben 304 mit null Bytes."
    echo "  Das Warten kostet hier tatsaechlich nichts."
fi

echo ""
if [ "${PHP_503:-0}" -gt 0 ]; then
    echo "  Die Ausfuehrung ist gedeckelt (${PHP_503} von ${N_PHP} abgewiesen),"
    echo "  das Lesen nicht (${ST_200} von ${N_STATISCH} durchgelassen)."
    echo "  Das ist genau die Asymmetrie, auf der AHPT beruht."
elif [ "${ST_200:-0}" -eq "$N_STATISCH" ] && [ "${PHP_200:-0}" -eq "$N_PHP" ]; then
    echo "  Beides ging durch -- die Prozessgrenze wurde bei ${N_PHP}"
    echo "  gleichzeitigen Aufrufen nicht erreicht. Das ist kein Widerspruch"
    echo "  zum Entwurf, nur eine groszuegigere Grenze als bei IONOS."
    echo "  AHPT traegt hier ebenfalls; der Vorsprung ist nur kleiner."
else
    echo "  Ungewoehnliches Bild -- die Zahlen oben von Hand ansehen."
fi

echo ""
echo "  Zum Vergleich IONOS, 01./02.09.2026:"
echo "    12 PHP gleichzeitig -> 7x 200, 5x 503     (123-1638 ms)"
echo "    12 statisch         -> 12x 200"
echo "    20 bedingt          -> 20x 304, 0 Bytes   (75-99 ms)"
