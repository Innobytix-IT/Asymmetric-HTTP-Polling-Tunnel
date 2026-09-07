#!/bin/bash
# durchstich.sh -- der ECHTE Durchstich: Besucher -> relay.php -> Agent ->
#                  Handler -> zurueck. Gegen echtes PHP, nicht gegen eine
#                  Attrappe.
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Manuel Person, InnoBytix-IT
#
# Aufruf:
#     bash tests/durchstich.sh
#         gegen lokales php -S. Das Geheimnis erzeugt der Test selbst.
#
#     bash tests/durchstich.sh https://example.de/ahpt ~/.ahpt/geheimnis
#         gegen einen echten Webspace. Die Geheimnisdatei ist PFLICHT und
#         muss dasselbe Geheimnis enthalten wie relay_token.php dort.
#
# WAS DIESER TEST KANN UND WAS NICHT
# ----------------------------------
# Gegen `php -S` misst er echtes PHP: Syntax, Kopfzeilen, Sperren, atomares
# Umbenennen, die Deckel. Das ist deutlich mehr als die Attrappe.
#
# Er misst NICHT:
#   - ETags und damit HTTP 304. Der eingebaute PHP-Server sendet keine.
#     Die ganze Kostenrechnung von AHPT haengt daran -- sie ist hier also
#     nicht geprueft, sondern nur gegen echtes Apache.
#   - mod_speling. Der eingebaute Server kennt es nicht. Genau dieser Fehler
#     hat am 02.09.2026 den ersten Live-Lauf gekostet.
#   - Die Prozessgrenze und damit HTTP 503.
#
# Gegen einen echten Webspace (erstes Argument) misst er all das mit.
# DANN ist der Durchstich vollstaendig -- und nur dann.
#
# Was ein Testaufbau nicht hat, kann er nicht messen.

set -u

HIER="$(cd "$(dirname "$0")" && pwd)"
WURZEL="$(dirname "$HIER")"
EXTERN="${1:-}"
TOKENDATEI="${2:-}"
PORT=8093
fehler=0
pruefungen=0

pruefe() {   # beschreibung bedingung [hinweis]
    pruefungen=$((pruefungen + 1))
    if [ "$2" = "1" ]; then
        printf '  %-56s ok\n' "$1"
    else
        printf '  %-56s FEHLSCHLAG%s\n' "$1" "${3:+  -- $3}"
        fehler=$((fehler + 1))
    fi
}

jsonfeld() {  # feld  <  json auf stdin
    python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(''); raise SystemExit
v = d
for t in sys.argv[1].split('.'):
    if isinstance(v, dict): v = v.get(t, '')
    else: v = ''
print(v if not isinstance(v, (dict, list)) else json.dumps(v))
" "$1"
}

# ---------------------------------------------------------------- Aufbau

B=$(mktemp -d -t ahpt_durchstich_XXXXXX)
trap 'kill ${PHP:-} ${AG:-} 2>/dev/null; rm -rf "$B"' EXIT

mkdir -p "$B/web" "$B/freigabe/unter"
echo 'Ein kurzer Text mit Umlauten: Groesse, Fuesse, Massstab.' > "$B/freigabe/klein.txt"
python3 -c "
import sys
sys.stdout.buffer.write(bytes((i*37+11) % 256 for i in range(300000)))
" > "$B/freigabe/gross.png"
echo 'DARF NIE HERAUS' > "$B/draussen.txt"

# Das Geheimnis.
#
# Gegen den eigenen php -S erzeugt der Test es selbst und legt es dort
# gleich mit ab. Gegen einen ECHTEN Webspace geht das nicht: Dort liegt
# `relay_token.php` schon, und es kennt nur, wer es hingelegt hat. Ein
# selbst erzeugtes Geheimnis passte nicht -- der Agent bekaeme auf jede
# Ablage ein 403, und der Test meldete lauter Fehlschlaege im Code, wo
# keine sind.
#
# Deshalb ist die Geheimnisdatei beim externen Lauf PFLICHT. Sie wird nur
# gelesen, nie verschickt und nie ausgegeben.
if [ -n "$EXTERN" ]; then
    if [ -z "$TOKENDATEI" ] || [ ! -r "$TOKENDATEI" ]; then
        echo "ABBRUCH: Fuer einen Lauf gegen einen echten Webspace fehlt die"
        echo "         Geheimnisdatei. Sie muss DASSELBE Geheimnis enthalten,"
        echo "         das dort in relay_token.php steht (ohne die Schutzzeile)."
        echo ""
        echo "  Aufruf:  bash tests/durchstich.sh https://example.de/ahpt ~/.ahpt/geheimnis"
        echo ""
        echo "         Ohne sie wuerde jede Ablage mit 403 abgewiesen und der"
        echo "         Test meldete Fehler im Code, wo keine sind."
        exit 2
    fi
    TOK=$(tr -d '\r\n' < "$TOKENDATEI")
    if [ "${#TOK}" -lt 16 ]; then
        echo "ABBRUCH: Geheimnis zu kurz (${#TOK} Zeichen, mindestens 16)."
        exit 2
    fi
else
    TOK=$(python3 -c "import secrets;print(secrets.token_hex(32))")
fi
echo "$TOK" > "$B/geheimnis"

# Diese beiden brauchen keinen Server -- nur relay.php und PHP. Sie laufen
# deshalb in BEIDEN Faellen, sonst bliebe beim externen Lauf ausgerechnet
# die Pruefung der Absender-Einteilung aus.
if command -v php >/dev/null; then
    php -l "$WURZEL/relay.php" || { echo "ABBRUCH: relay.php ist kein gueltiges PHP."; exit 2; }
    python3 "$HIER/pruefe_relay_php.py" "$WURZEL/relay.php" | sed 's/^/  /'
    pruefungen=$((pruefungen + 1))
    php "$HIER/pruefe_absender.php" || fehler=$((fehler + 1))
else
    echo "  HINWEIS: kein php auf diesem Rechner -- php -l und die"
    echo "           Absender-Pruefung entfallen. Das ist kein Bestanden."
fi

if [ -z "$EXTERN" ]; then
    command -v php >/dev/null || {
        echo "ABBRUCH: kein php gefunden."
        echo "         Ohne PHP kann dieser Test nicht messen, was er messen soll."
        echo "         Fuer eine Pruefung ohne PHP: python3 tests/durchstich_lokal.py"
        echo "         (die laeuft gegen eine Attrappe und beweist nichts ueber relay.php)"
        exit 2
    }
    # Der Port MUSS uns gehoeren. Am 02.09.2026 hielt ein anderer Testaufbau
    # den Port; php -S startete nicht, die Anfragen liefen gegen den fremden
    # Server -- und das Skript meldete Fehlschlaege im Code, wo keine waren.
    # Ein Messaufbau muss beweisen, dass er misst.
    if (ss -tln 2>/dev/null || netstat -an 2>/dev/null) | grep -q "[:.]$PORT[ 	]"; then
        echo "ABBRUCH: Port $PORT ist belegt -- dieser Lauf wuerde einen FREMDEN"
        echo "         Server messen. Erst aufraeumen."
        exit 2
    fi

    cp "$WURZEL/relay.php" "$B/web/"
    printf '<?php exit; ?>\n%s\n' "$TOK" > "$B/web/relay_token.php"

    PHP_CLI_SERVER_WORKERS=4 php -S 127.0.0.1:$PORT -t "$B/web" > "$B/php.log" 2>&1 &
    PHP=$!
    sleep 1.2
    U="http://127.0.0.1:$PORT"
    echo ""
    echo "Gegen echtes PHP auf $U"
    echo "  ACHTUNG: kein ETag, kein mod_speling, kein 503 -- siehe Kopf dieser Datei."
else
    U="${EXTERN%/}"
    echo ""
    echo "Gegen $U   (echter Webspace -- vollstaendige Messung)"
fi

# Agent
cat > "$B/config.json" <<KONFIG
{ "relay": { "basis": "$U", "geheimnis_datei": "$B/geheimnis",
             "poll_abstand": 0.5, "unbedingt_nach": 5 },
  "dienst": [ { "name": "dateien", "art": "datei", "wurzel": "$B/freigabe",
                "aktionen": ["liste", "hole"], "endungen": ["txt", "png"] } ] }
KONFIG

(cd "$WURZEL" && python3 relay_agent.py --konfig "$B/config.json") > "$B/agent.log" 2>&1 &
AG=$!
sleep 3
echo ""
echo "=== Agent-Start ==="
sed 's/^/  /' "$B/agent.log"

# --------------------------------------------------------------- Besucher

besuch() {   # dienst aktion daten-json [v] [krypto]  -> setzt $CODE $MARKE
    local rumpf
    rumpf=$(python3 -c "
import json,sys
print(json.dumps({'v': int(sys.argv[4]), 'krypto': sys.argv[5],
                  'nutzlast': {'dienst': sys.argv[1], 'aktion': sys.argv[2],
                               'daten': json.loads(sys.argv[3])}}))
" "$1" "$2" "$3" "${4:-1}" "${5:-keine}")
    local aus
    aus=$(curl -s -w '\n%{http_code}' -X POST "$U/relay.php?action=frage" \
          -H 'Content-Type: application/json' --data "$rumpf")
    CODE=$(printf '%s' "$aus" | tail -1)
    MARKE=$(printf '%s' "$aus" | sed '$d' | jsonfeld marke)
}

hole() {     # marke frist -> setzt $NUTZ (JSON der Nutzlast, Stuecke vereint)
    NUTZ=$(python3 - "$U" "$1" "${2:-30}" <<'PY'
import json, sys, time, urllib.error, urllib.request
basis, marke, frist = sys.argv[1], sys.argv[2], float(sys.argv[3])
bis = time.time() + frist
while time.time() < bis:
    try:
        with urllib.request.urlopen('%s/ahpt/antwort_%s.json' % (basis, marke),
                                    timeout=10) as r:
            u = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            time.sleep(0.3); continue
        print(json.dumps({'fehler': 'HTTP %s' % e.code})); raise SystemExit
    assert u.get('v') == 1, 'Fassung'
    assert u.get('marke') == marke, 'Marke weicht ab -- Umleitung?'
    n, teile = u.get('nutzlast', {}), u.get('teile', 1)
    if teile > 1:
        text = []
        for i, e in enumerate(n.get('stuecke', [])):
            with urllib.request.urlopen('%s/ahpt/%s' % (basis, e['datei']),
                                        timeout=10) as r:
                s = json.loads(r.read().decode('utf-8'))
            assert s.get('marke') == marke, 'Stueck %d: fremde Marke' % i
            assert s.get('teil') == i,      'Stueck %d: falsche Nummer' % i
            text.append(s['nutzlast'])
        n = dict(n); n['inhalt'] = ''.join(text)
    n['_teile'] = teile
    print(json.dumps(n)); raise SystemExit
print(json.dumps({'fehler': 'keine Antwort binnen %ss' % frist}))
PY
)
}

feld() { printf '%s' "$NUTZ" | jsonfeld "$1"; }

echo ""
echo "DURCHSTICH"
echo ""

# 1 -- Selbsttest sagt, OB das Geheimnis lesbar ist
S=$(curl -s "$U/relay.php?action=selbsttest")
pruefe "selbsttest antwortet"        "$([ -n "$S" ] && echo 1 || echo 0)"
pruefe "selbsttest findet das Geheimnis" \
       "$([ "$(printf '%s' "$S" | jsonfeld geheim_zeichen)" = "64" ] && echo 1 || echo 0)" \
       "$(printf '%s' "$S" | jsonfeld geheim_zeichen) Zeichen"
pruefe "selbsttest gibt das Geheimnis NICHT heraus" \
       "$(printf '%s' "$S" | grep -qF "$TOK" && echo 0 || echo 1)"

# 2 -- relay_token.php liefert nichts.
#
#      relay_state.php wird erst NACH dem ersten Vorgang geprueft (Nr. 13):
#      Vorher gibt es die Datei gar nicht, und dann misst man die 404-Seite
#      des Servers statt der Schutzzeile. Am 02.09.2026 genau so passiert --
#      gemeldet wurden 548 Bytes, gemessen war eine Fehlerseite.
#
#      Eine Pruefung, die nicht messen kann, was sie messen soll, muss das
#      sagen und nicht urteilen.
N=$(curl -s "$U/relay_token.php" | wc -c)
pruefe "relay_token.php liefert 0 Bytes" "$([ "$N" -eq 0 ] && echo 1 || echo 0)" "$N Bytes"

# 3 -- Es gibt KEINE Abhol-Aktion. Das ist der ganze Entwurf.
C=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$U/relay.php?action=abholen" \
    -H 'Content-Type: application/json' --data '{"v":1,"krypto":"keine"}')
pruefe "keine Abhol-Aktion (HTTP 400)" "$([ "$C" = "400" ] && echo 1 || echo 0)" "HTTP $C"

# 4 -- Ablegen ohne Geheimnis wird abgewiesen
C=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$U/relay.php?action=antwort" \
    -H 'Content-Type: application/json' \
    --data '{"v":1,"krypto":"keine","marke":"00000000000000000000000000000000","nutzlast":{}}')
pruefe "Antwort ohne Geheimnis abgewiesen (403)" "$([ "$C" = "403" ] && echo 1 || echo 0)" "HTTP $C"

# 5 -- Umschlag: unbekannte Fassung und unbekanntes Verfahren
besuch dateien liste '{}' 2 keine
pruefe "unbekannte Protokollfassung abgewiesen" "$([ "$CODE" = "400" ] && echo 1 || echo 0)" "HTTP $CODE"
besuch dateien liste '{}' 1 x25519
pruefe "unbekanntes Verfahren abgewiesen" "$([ "$CODE" = "400" ] && echo 1 || echo 0)" "HTTP $CODE"

# 5b -- Regression 05.09.2026: "v":1.0 ist zahlengleich mit der Fassung 1,
#       nur anders typisiert. PHPs "!==" hielt das fuer eine falsche
#       Fassung, bis genau das echte Stueck-Uploads scheitern liess. Der
#       "besuch"-Helfer zwingt v ueber int() immer auf eine Ganzzahl, kann
#       diesen Fall also nicht auslösen -- deshalb hier ein roher Aufruf.
C=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$U/relay.php?action=frage" \
    -H 'Content-Type: application/json' \
    --data '{"v":1.0,"krypto":"keine","nutzlast":{"dienst":"dateien","aktion":"liste","daten":{}}}')
pruefe "zahlengleiche Fassung 1.0 wird angenommen" "$([ "$C" = "200" ] && echo 1 || echo 0)" "HTTP $C"

# 6 -- Formfehler beim Dienstnamen
for D in Dateien 'da.tei' 'a/b' ''; do
    besuch "$D" hole '{}'
    pruefe "Dienstname abgewiesen: '${D:-(leer)}'" \
           "$([ "$CODE" = "400" ] && echo 1 || echo 0)" "HTTP $CODE"
done

# 7 -- Auflisten
besuch dateien liste '{}'
pruefe "Frage wird angenommen" "$([ "$CODE" = "200" ] && echo 1 || echo 0)" "HTTP $CODE"
hole "$MARKE"
pruefe "Auflistung kommt an" "$([ "$(feld gefunden)" = "True" ] && echo 1 || echo 0)" "$(feld fehler)"
pruefe "Auflistung nennt klein.txt" \
       "$(printf '%s' "$NUTZ" | grep -q 'klein.txt' && echo 1 || echo 0)"
# An die vorige Bedingung GEKOPPELT: Eine leere Antwort enthaelt draussen.txt
# auch nicht und bestuende diese Pruefung, ohne dass irgendetwas geprueft
# waere. Am 02.09.2026 genau so geschehen -- sie stand auf "ok", waehrend die
# Auflistung in Wahrheit gar nicht ankam.
pruefe "Auflistung zeigt draussen.txt NICHT" \
       "$(printf '%s' "$NUTZ" | grep -q 'klein.txt' \
          && ! printf '%s' "$NUTZ" | grep -q draussen && echo 1 || echo 0)"

# 8 -- Kleine Datei, ungeteilt
besuch dateien hole '{"pfad":"klein.txt"}'
hole "$MARKE"
pruefe "kleine Datei kommt an" \
       "$(printf '%s' "$NUTZ" | grep -q Massstab && echo 1 || echo 0)"
pruefe "kleine Datei bleibt ungeteilt" "$([ "$(feld _teile)" = "1" ] && echo 1 || echo 0)"

# 9 -- Grosse Datei, gestueckelt. Der neue Teil.
besuch dateien hole '{"pfad":"gross.png"}'
hole "$MARKE" 60
T=$(feld _teile)
pruefe "grosse Datei wird gestueckelt" "$([ "${T:-1}" -gt 1 ] && echo 1 || echo 0)" "teile=$T"
GLEICH=$(printf '%s' "$NUTZ" | python3 -c "
import base64, json, sys
n = json.load(sys.stdin)
roh = base64.b64decode(n.get('inhalt', ''))
soll = bytes((i*37+11) % 256 for i in range(300000))
print(1 if roh == soll else 0)
")
pruefe "grosse Datei ist Byte fuer Byte dieselbe" "$GLEICH"

# 10 -- Angriffe
for P in '../draussen.txt' 'unter/../../draussen.txt' '/etc/passwd' '.geheim'; do
    besuch dateien hole "$(python3 -c "import json,sys;print(json.dumps({'pfad':sys.argv[1]}))" "$P")"
    if [ "$CODE" = "200" ]; then
        hole "$MARKE"
        pruefe "Angriff abgewiesen: $P" \
               "$([ "$(feld gefunden)" = "False" ] && echo 1 || echo 0)"
    else
        pruefe "Angriff abgewiesen: $P" 1
    fi
done

# 11 -- Unbekannter Dienst: angenommen, aber nichts gefunden
besuch unbekannt hole '{"pfad":"x"}'
hole "$MARKE"
pruefe "unbekannter Dienst liefert nichts" \
       "$([ "$(feld gefunden)" = "False" ] && echo 1 || echo 0)"
pruefe "unbekannter Dienst verraet keine Namen" \
       "$(printf '%s' "$NUTZ" | grep -q dateien && echo 0 || echo 1)"

# 12 -- `daten` bleibt ein OBJEKT, auch leer und auch mit Ziffernschluesseln.
#
# PHP unterscheidet nicht zwischen leerem Objekt und leerer Liste. Wer die
# Nutzlast als Feld einliest und neu schreibt, macht aus {"daten":{}} ein
# {"daten":[]}, und der Agent weist es zu Recht ab. Dasselbe gilt fuer
# {"0":"a"} -- daraus wird ["a"].
#
# Am 02.09.2026 gegen PHP 8.3 gefunden. Gegen die Python-Attrappe war es
# UNSICHTBAR, weil Python beides unterscheidet.
besuch dateien liste '{}'
hole "$MARKE"
pruefe "leeres daten-Objekt kommt als Objekt an" \
       "$([ "$(feld gefunden)" = "True" ] && echo 1 || echo 0)" "$(feld grund)"
besuch dateien hole '{"0":"x","1":"y","pfad":"klein.txt"}'
hole "$MARKE"
pruefe "daten mit Ziffernschluesseln bleibt ein Objekt" \
       "$(printf '%s' "$NUTZ" | grep -q Massstab && echo 1 || echo 0)" "$(feld grund)"

# 13 -- relay_state.php, jetzt wo es die Datei wirklich gibt.
C13=$(curl -s -o /dev/null -w '%{http_code}' "$U/relay_state.php")
if [ "$C13" = "404" ]; then
    pruefe "relay_state.php liefert 0 Bytes" 0 "Datei gibt es nicht -- nichts gemessen"
else
    N=$(curl -s "$U/relay_state.php" | wc -c)
    pruefe "relay_state.php liefert 0 Bytes" "$([ "$N" -eq 0 ] && echo 1 || echo 0)" "$N Bytes"
fi

# 13a -- NUR gegen einen echten Webspace.
#
# Das sind die drei Dinge, die `php -S` nicht hat -- und genau die drei, die
# im Betrieb zugeschlagen haben. Alles davor liesse sich auch lokal messen;
# dies hier ist der Grund, warum es diesen Lauf ueberhaupt gibt.
if [ -n "$EXTERN" ]; then
    echo ""
    echo "ECHTER WEBSPACE -- was php -S nicht messen kann"
    echo ""

    # (1) ETag und HTTP 304. DIE Zahl, um die es beim ganzen Entwurf geht:
    #     Im Live-Lauf vom 02.09.2026 waren 264 von 270 Abrufen 304 -- null
    #     Bytes, kein PHP. Ohne das kostet jedes Warten wieder etwas, und
    #     der ganze Aufbau ist hinfaellig.
    ETAG=$(curl -s -D - -o /dev/null "$U/ahpt/warteschlange.json" \
           | tr -d '\r' | awk 'tolower($1)=="etag:"{print $2}')
    pruefe "Webspace sendet einen ETag" \
           "$([ -n "$ETAG" ] && echo 1 || echo 0)" \
           "keiner -- dann kostet jedes Warten die ganze Datei"
    if [ -n "$ETAG" ]; then
        C=$(curl -s -o /dev/null -w '%{http_code}' \
            -H "If-None-Match: $ETAG" "$U/ahpt/warteschlange.json")
        pruefe "bedingter Abruf antwortet 304" \
               "$([ "$C" = "304" ] && echo 1 || echo 0)" "HTTP $C"
        N=$(curl -s -H "If-None-Match: $ETAG" "$U/ahpt/warteschlange.json" | wc -c)
        pruefe "304 traegt null Bytes" \
               "$([ "$N" -eq 0 ] && echo 1 || echo 0)" "$N Bytes"
    fi

    # (2) mod_speling. Am 02.09.2026 leitete es die Abfrage nach der ANTWORT
    #     stillschweigend auf die FRAGE um. Hier wird gezielt ein Name
    #     abgefragt, der genau EIN Zeichen neben einer vorhandenen Datei
    #     liegt. Richtig ist 404. Kommt 301, ist mod_speling aktiv und
    #     `CheckSpelling Off` in der .htaccess nicht angekommen.
    besuch dateien hole '{"pfad":"klein.txt"}'
    hole "$MARKE"
    C=$(curl -s -o /dev/null -w '%{http_code}' "$U/ahpt/antwort_${MARKE}.jsom")
    pruefe "ein Zeichen daneben ergibt 404, keine Umleitung" \
           "$([ "$C" = "404" ] && echo 1 || echo 0)" \
           "HTTP $C -- bei 301 fehlt CheckSpelling Off"

    # (3) Verzeichnislisting. Die Marken sind nicht erratbar -- ein Listing
    #     macht das Raten unnoetig und zeigt jede offene Frage auf einen Blick.
    C=$(curl -s -o /dev/null -w '%{http_code}' "$U/ahpt/")
    pruefe "kein Verzeichnislisting" \
           "$([ "$C" != "200" ] && echo 1 || echo 0)" "HTTP $C"

    # (4) Und die Gegenprobe zum Kostenmodell: Wie oft musste verdraengt
    #     werden? Im Normalbetrieb 0.
    V=$(curl -s "$U/relay.php?action=selbsttest" | jsonfeld verdraengt)
    pruefe "keine Verdraengung noetig gewesen" \
           "$([ "${V:-0}" = "0" ] && echo 1 || echo 0)" "verdraengt=$V"

    # (5) Traegt das Muster auf DIESEM Webspace ueberhaupt? Das ist keine
    #     Pruefung mit ok und Fehlschlag, sondern eine Messung -- ein
    #     Webspace besteht nicht, er ist geeignet oder nicht. Deshalb ein
    #     eigenes Werkzeug, das Zahlen ausgibt statt zu urteilen.
    bash "$HIER/miss_asymmetrie.sh" "$U"
fi

# 14 -- Der Agent hat keinen Fehler gezaehlt
pruefe "Agent meldet keinen Fehler" \
       "$(grep -qiE 'FEHLER|NICHT ABGELEGT|UEBERSEHEN' "$B/agent.log" && echo 0 || echo 1)" \
       "$(grep -iE 'FEHLER|NICHT ABGELEGT|UEBERSEHEN' "$B/agent.log" | head -1)"

echo ""
echo "=== Agent (letzte 12 Zeilen) ==="
tail -12 "$B/agent.log" | sed 's/^/  /'

echo ""
echo "ERGEBNIS: $pruefungen Pruefungen, $fehler Fehlschlag(e)."
if [ -z "$EXTERN" ]; then
    echo ""
    echo "  Gegen php -S. NICHT geprueft: ETag/304, mod_speling, 503."
    echo "  Das sind genau die drei, die im Betrieb zugeschlagen haben."
    echo "  Vollstaendig wird die Messung erst mit:"
    echo "      bash tests/durchstich.sh https://example.de/ahpt ~/.ahpt/geheimnis"
else
    echo ""
    echo "  Gegen einen echten Webspace. ETag/304, mod_speling und das"
    echo "  Verzeichnislisting sind damit gemessen."
    echo ""
    echo "  Weiterhin NICHT geprueft: das Verhalten an der Prozessgrenze"
    echo "  (HTTP 503) -- dafuer braeuchte es gleichzeitige Last, und die"
    echo "  gehoert nicht in einen Durchstich."
fi
exit $([ "$fehler" -eq 0 ] && echo 0 || echo 1)
