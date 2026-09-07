#!/bin/bash
# ausliefern.sh -- die drei Dateien auf den Webspace, und danach NACHMESSEN
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Manuel Person, InnoBytix-IT
#
# Aufruf:
#     bash ausliefern.sh <ftp-host> <fernordner> <https-basis> <quellordner> [pin-datei]
#
# Beispiel:
#     bash ausliefern.sh dein-webspace.example.com /www/ahpt \
#          https://dein-webspace.example.com/ahpt ~/ahpt-auslieferung \
#          ~/.ahpt/bplaced.pin
#
# WOZU DIE NACHKONTROLLE
# ----------------------
# Am 02.09.2026 meldete ein FTP-Programm eine neue `.htaccess` ZWEIMAL mit
# gruenem Haken und 7,41 KB -- auf dem Server lag weiter die alte. Dieselbe
# Runde hatte auch `tunnel.php` verschluckt. Nachweisbar wurde es erst so:
#
#     peers_data.json     403      alte Regel, wirkt
#     tunnel_state.json   200      neue Regel, wirkt NICHT
#
# Ein Auslieferungswerkzeug, das nur hochlaedt und "fertig" sagt, ist
# deshalb wertlos. Dieses hier misst hinterher ueber HTTPS nach, und zwar
# das, worauf es ankommt:
#
#     1. Antwortet relay.php ueberhaupt?
#     2. Liegt das Geheimnis da UND liefert es 0 Bytes aus?
#     3. Ist die Ablage beschreibbar?
#
# Erst wenn das stimmt, ist ausgeliefert.
#
# ZUGANGSDATEN
# ------------
# Kommen ausschliesslich aus `~/.netrc`. Dieses Skript liest sie nicht,
# gibt sie nicht aus und nimmt sie nicht als Argument entgegen -- ein
# Passwort auf der Kommandozeile steht in der Prozessliste und in der
# Verlaufsdatei der Shell.
#
#     printf 'machine HOST\nlogin BENUTZER\npassword GEHEIM\n' > ~/.netrc
#     chmod 600 ~/.netrc

set -u

HOST="${1:-}"
FERN="${2:-}"
BASIS="${3:-}"
QUELLE="${4:-}"
PINDATEI="${5:-}"

# TLS-Einstellungen fuer curl.
#
# `--ssl-reqd` allein ist der Normalfall: TLS erzwingen, Zertifikat gegen die
# Wurzelzertifikate des Systems pruefen. So soll es sein.
#
# Viele Hoster betreiben FTPS aber mit einem SELBSTSIGNIERTEN Zertifikat --
# bplaced etwa mit einem eigenen von 2021, ausgestellt auf "bplaced". Dann
# schlaegt die Pruefung fehl, und es gibt drei Auswege:
#
#   1. Klartext-FTP. Das Passwort reist offen mit. Nein.
#   2. `--insecure`. Verschluesselt, aber ohne zu pruefen MIT WEM -- ein
#      Zwischenknoten koennte sein eigenes Zertifikat vorzeigen und das
#      Passwort mitschreiben. Verschluesselung ohne Ausweis ist Theater.
#   3. Den oeffentlichen Schluessel FESTNAGELN. Dann ist die Gegenstelle
#      kryptografisch bestimmt, ohne dass ein Wurzelzertifikat noetig waere.
#
# Weg 3, und zwar als Datei mit dem Pin. Ihn einmal ermitteln:
#
#   echo | openssl s_client -connect HOST:21 -starttls ftp 2>/dev/null \
#     | openssl x509 -pubkey -noout | openssl pkey -pubin -outform der \
#     | openssl dgst -sha256 -binary | openssl base64
#
# Als "sha256//WERT" in eine Datei, und die hier uebergeben.
#
# WAS DAS NICHT LEISTET: Beim ERSTEN Ermitteln koennte schon jemand
# dazwischen sitzen -- der Pin waere dann seiner. Das ist Vertrauen beim
# ersten Kontakt. Ab da ist jeder spaetere Austausch ausgeschlossen, und
# genau das ist der Gewinn gegenueber `--insecure`, wo jedes Mal alles
# offen steht.
TLS=(--ssl-reqd)
if [ -n "$PINDATEI" ]; then
    if [ ! -r "$PINDATEI" ]; then
        echo "ABBRUCH: Pin-Datei $PINDATEI nicht lesbar."
        exit 2
    fi
    PIN=$(tr -d ' \r\n' < "$PINDATEI")
    case "$PIN" in
        sha256//*) ;;
        *) echo "ABBRUCH: Pin muss mit sha256// beginnen (ist: ${PIN:0:12}...)."; exit 2 ;;
    esac
    # `--insecure` schaltet Wurzel- und Namenspruefung ab, `--pinnedpubkey`
    # bleibt trotzdem wirksam -- nachgemessen am 02.09.2026: ein falscher
    # Pin wird mit `curl: (90) public key does not match` abgewiesen. Ohne
    # diese Gegenprobe waere der Pin womoeglich Zierde.
    TLS=(--ssl-reqd --insecure --pinnedpubkey "$PIN")
fi

if [ -z "$HOST" ] || [ -z "$FERN" ] || [ -z "$BASIS" ] || [ -z "$QUELLE" ]; then
    echo "Aufruf:"
    echo "  bash ausliefern.sh <ftp-host> <fernordner> <https-basis> <quellordner> [pin-datei]"
    echo ""
    echo "Beispiel:"
    echo "  bash ausliefern.sh dein-webspace.example.com /www/ahpt \\"
    echo "       https://dein-webspace.example.com/ahpt ~/ahpt-auslieferung \\"
    echo "       ~/.ahpt/bplaced.pin"
    exit 2
fi
BASIS="${BASIS%/}"
FERN="/${FERN#/}"

if [ ! -r "$HOME/.netrc" ]; then
    echo "ABBRUCH: ~/.netrc fehlt."
    echo "         Ohne sie muesste das Passwort auf die Kommandozeile -- und"
    echo "         damit in die Prozessliste und in den Shell-Verlauf."
    echo ""
    echo "  So anlegen, ohne dass es irgendwo mitgeschrieben wird:"
    echo "      read -rsp 'FTP-Passwort: ' P"
    echo "      printf 'machine $HOST\\nlogin BENUTZER\\npassword %s\\n' \"\$P\" > ~/.netrc"
    echo "      chmod 600 ~/.netrc; unset P"
    exit 2
fi

for f in relay.php .htaccess relay_token.php; do
    if [ ! -r "$QUELLE/$f" ]; then
        echo "ABBRUCH: $QUELLE/$f fehlt."
        exit 2
    fi
done

# Die Schutzzeile ist die erste Schranke des Geheimnisses. Fehlt sie, liefert
# der Server die Datei aus statt sie auszufuehren -- und ein ungeschuetztes
# Geheimnis funktioniert genauso gut wie ein geschuetztes. Nichts faellt auf.
if ! head -1 "$QUELLE/relay_token.php" | grep -q 'exit'; then
    echo "ABBRUCH: relay_token.php beginnt nicht mit der Schutzzeile."
    echo "         Erste Zeile muss sein:  <?php exit; ?>"
    exit 2
fi

echo ""
echo "AUSLIEFERN nach ftp://$HOST$FERN"
echo ""

fehler=0
hoch() {   # datei
    local f="$1"
    # --ftp-create-dirs legt fehlende Ordner an. --ssl-reqd erzwingt TLS:
    # ueber unverschluesseltes FTP reist das Passwort im Klartext, und mit
    # ihm koennte jeder Zwischenknoten relay_token.php austauschen.
    if curl -sS --netrc "${TLS[@]}" --ftp-create-dirs \
            -T "$QUELLE/$f" "ftp://$HOST$FERN/$f" 2>"/tmp/ausliefern_$$.err"; then
        printf '  %-24s hochgeladen\n' "$f"
    else
        printf '  %-24s FEHLGESCHLAGEN: %s\n' "$f" "$(tr -d '\n' < "/tmp/ausliefern_$$.err")"
        fehler=$((fehler + 1))
    fi
    rm -f "/tmp/ausliefern_$$.err"
}

# relay_token.php ZUERST, relay.php ZULETZT.
#
# Reihenfolge ist hier sicherheitstragend: Waere relay.php zuerst da und das
# Geheimnis noch nicht, stuende fuer die Dauer der Uebertragung ein Endpunkt
# offen, der Antworten ohne Ausweis annimmt -- agent_erlaubt() gibt bei
# fehlender Datei zwar false zurueck, aber verlassen sollte man sich auf
# eine Reihenfolge, nicht auf ein Zeitfenster.
hoch relay_token.php
hoch .htaccess
hoch relay.php

if [ "$fehler" -gt 0 ]; then
    echo ""
    echo "ERGEBNIS: $fehler Datei(en) nicht uebertragen. Nicht weitermessen."
    exit 1
fi

# --------------------------------------------------------- Nachkontrolle
echo ""
echo "NACHKONTROLLE ueber $BASIS"
echo ""

pruefe() {
    if [ "$2" = "1" ]; then
        printf '  %-46s ok\n' "$1"
    else
        printf '  %-46s FEHLSCHLAG%s\n' "$1" "${3:+  -- $3}"
        fehler=$((fehler + 1))
    fi
}

# Ein Abruf, der Code UND Groesse festhaelt.
#
# Der erste Entwurf dieser Datei mass nur `curl … | wc -c` und wertete
# 0 Bytes als "Geheimnis wird nicht ausgeliefert". Am 02.09.2026 gegen
# bplaced kam die Verbindung wegen eines selbstsignierten Zertifikats gar
# nicht zustande -- null Bytes, und die Pruefung meldete **ok**. Zwei
# Schranken standen damit auf gruen, ohne dass irgendetwas geprueft war.
#
# Eine fehlgeschlagene Verbindung ist kein bestandener Schutz. Sie ist
# ueberhaupt keine Messung, und genau das muss die Ausgabe sagen.
HCODE=""; HBYTES=0
abruf() {
    local tmp; tmp=$(mktemp)
    HCODE=$(curl -sS -o "$tmp" -w '%{http_code}' "$1" 2>/dev/null || echo 000)
    HBYTES=$(wc -c < "$tmp" | tr -d ' ')
    rm -f "$tmp"
}

S=$(curl -sS "$BASIS/relay.php?action=selbsttest" 2>/dev/null || true)
if [ -z "$S" ]; then
    pruefe "relay.php antwortet" 0 "keine Antwort -- alles Weitere nicht gemessen"
    echo ""
    echo "  Haeufige Ursachen: falsche Basis-Adresse, HTTPS mit einem"
    echo "  Zertifikat, dem curl nicht traut, oder die Datei ist gar nicht"
    echo "  angekommen. Erst das klaeren, dann erneut ausliefern."
    exit 1
fi
pruefe "relay.php antwortet" 1

feld() { printf '%s' "$S" | python3 -c "
import json,sys
try: print(json.load(sys.stdin).get(sys.argv[1], ''))
except Exception: print('')
" "$1"; }

pruefe "Geheimnisdatei ist da"     "$([ "$(feld datei_da)" = "True" ] && echo 1 || echo 0)"
pruefe "Geheimnis ist lesbar"      "$([ "$(feld lesbar)"   = "True" ] && echo 1 || echo 0)"
pruefe "Schutzzeile angekommen"    "$([ "$(feld beginnt_mit_php)" = "True" ] && echo 1 || echo 0)"
Z=$(feld geheim_zeichen)
pruefe "Geheimnis hat Inhalt"      "$([ "${Z:-0}" -ge 16 ] 2>/dev/null && echo 1 || echo 0)" "$Z Zeichen"

# Die Ablage entsteht erst mit der ersten Frage -- vorher ist
# `ablage_schreib` zu Recht false, und danach zu fragen bewiese nichts.
# Also eine Frage stellen und DANN nachsehen. Sie verfaellt von selbst.
curl -sS -o /dev/null -X POST "$BASIS/relay.php?action=frage" \
     -H 'Content-Type: application/json' \
     --data '{"v":1,"krypto":"keine","nutzlast":{"dienst":"auslieferung","aktion":"pruefung","daten":{}}}' \
     2>/dev/null || true
S=$(curl -sS "$BASIS/relay.php?action=selbsttest" 2>/dev/null || true)
pruefe "Ablage angelegt und beschreibbar" \
       "$([ "$(feld ablage_schreib)" = "True" ] && echo 1 || echo 0)" \
       "PHP darf im Zielordner nicht schreiben"

# STIMMT das Geheimnis? Nicht vergleichen -- ausprobieren.
#
# Frueher gab der Selbsttest einen Fingerabdruck des Geheimnisses aus, den
# man vergleichen konnte. Der war ohne Anmeldung abrufbar und damit ein
# Offline-Rateorakel (siehe relay.php). Jetzt weist sich dieses Skript
# stattdessen damit AUS -- das ist ohnehin die schaerfere Probe:
#
#   403  das Geheimnis passt NICHT
#   400  das Geheimnis passt, die Frage war nur absichtlich unsinnig
ANTW=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASIS/relay.php?action=antwort" \
       -H 'Content-Type: application/json' \
       -H "X-AHPT-Auth: $(tail -1 "$QUELLE/relay_token.php")" \
       --data '{"v":1,"krypto":"keine","marke":"00000000000000000000000000000000","teile":1,"nutzlast":{}}')
if [ "$ANTW" = "403" ]; then
    pruefe "Geheimnis stimmt ueberein" 0 "Vermittler weist es ab (403)"
elif [ "$ANTW" = "000" ]; then
    pruefe "Geheimnis stimmt ueberein" 0 "keine Verbindung -- NICHT gemessen"
else
    pruefe "Geheimnis stimmt ueberein" 1
fi

# Die eigentliche Probe: gibt der Server das Geheimnis heraus?
#
# Zwei Wege sind richtig und beide zaehlen:
#   403/404  -- die .htaccess sperrt (zweite Schranke)
#   200 mit 0 Bytes -- der Server FUEHRT die Datei AUS (erste Schranke)
# Falsch ist allein: 200 mit Inhalt. Und 000 heisst "nicht gemessen".
abruf "$BASIS/relay_token.php"
if [ "$HCODE" = "000" ]; then
    pruefe "relay_token.php gibt nichts heraus" 0 "keine Verbindung -- NICHT gemessen"
else
    ok=0
    case "$HCODE" in 403|404) ok=1 ;; 200) [ "$HBYTES" -eq 0 ] && ok=1 ;; esac
    pruefe "relay_token.php gibt nichts heraus" "$ok" "HTTP $HCODE, $HBYTES Bytes"
fi

abruf "$BASIS/relay_state.php"
if [ "$HCODE" = "000" ]; then
    pruefe "relay_state.php gibt nichts heraus" 0 "keine Verbindung -- NICHT gemessen"
else
    ok=0
    case "$HCODE" in 403|404) ok=1 ;; 200) [ "$HBYTES" -eq 0 ] && ok=1 ;; esac
    pruefe "relay_state.php gibt nichts heraus" "$ok" "HTTP $HCODE, $HBYTES Bytes"
fi

abruf "$BASIS/.htaccess"
if [ "$HCODE" = "000" ]; then
    pruefe "'.htaccess' nicht abrufbar" 0 "keine Verbindung -- NICHT gemessen"
else
    pruefe "'.htaccess' nicht abrufbar" \
           "$([ "$HCODE" != "200" ] && echo 1 || echo 0)" "HTTP $HCODE"
fi

echo ""
if [ "$fehler" -eq 0 ]; then
    echo "ERGEBNIS: ausgeliefert und nachgemessen."
    echo ""
    echo "  Naechster Schritt:"
    echo "      bash tests/durchstich.sh $BASIS ~/.ahpt/geheimnis"
else
    echo "ERGEBNIS: $fehler Beanstandung(en) -- NICHT in Betrieb nehmen."
    echo ""
    echo "  Der haeufigste Grund ist, dass eine Datei gar nicht angekommen"
    echo "  ist, obwohl das FTP-Programm Erfolg gemeldet hat. Genau dafuer"
    echo "  gibt es diese Nachkontrolle."
fi
exit "$([ "$fehler" -eq 0 ] && echo 0 || echo 1)"
