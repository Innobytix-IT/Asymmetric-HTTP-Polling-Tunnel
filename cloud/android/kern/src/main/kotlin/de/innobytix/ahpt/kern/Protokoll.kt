/*
 * Protokoll.kt -- die Besucherseite von AHPT Cloud, fuer Android
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * Das Gegenstueck zu ahpt_client.py und ahpt.js, mit denselben Schranken:
 *
 *   * keine Weiterleitungen (mod_speling hat am 02.09.2026 eine Abfrage
 *     stillschweigend auf eine fremde Datei umgeleitet)
 *   * Marke und Stuecknummer werden IM INHALT nachgeprueft
 *   * Dateinamen von Stuecken werden GELESEN, nie gebaut
 *   * ein Rueckfall auf Klartext wird abgewiesen, nicht hingenommen
 *
 * Alles Warten laeuft ueber statische Dateien -- kein PHP. Genau daran haengt
 * das Kostenmodell: Auf billigem Webspace ist Lesen unbegrenzt und Ausfuehren
 * scharf gedeckelt.
 *
 * WAS HIER ANDERS IST ALS IM PORTAL, UND WARUM
 * ---------------------------------------------
 * Das Portal spricht `noise_ik_aes`, weil WebCrypto kein ChaCha20-Poly1305
 * kennt. Diese App spricht `noise_ik` -- dieselbe Suite wie der
 * Kommandozeilen-Client. Der Agent nimmt beide an und antwortet in
 * derselben, in der gefragt wurde.
 *
 * Zwei weitere Unterschiede sind keine Geschmacksfrage, sondern heben
 * Grenzen auf, an denen der Browser haengt:
 *
 *   * Die Pruefsumme wird STREAMEND gebildet. `crypto.subtle.digest` im
 *     Browser verlangt den ganzen Datenblock auf einmal; ahpt.js muss die
 *     Datei deshalb einmal vollstaendig in den Speicher ziehen und schreibt
 *     selbst dazu, dass das bei einer sehr grossen Datei auf einem Handy
 *     nicht aufgeht. MessageDigest kann fortschreiten.
 *   * Beim Holen wird Block fuer Block in den Zielstrom geschrieben, statt
 *     die ganze Datei in einem Feld zu sammeln. Damit haengt die Groesse am
 *     freien Speicherplatz, nicht am Arbeitsspeicher.
 */
package de.innobytix.ahpt.kern

import org.json.JSONArray
import org.json.JSONObject
import java.security.SecureRandom
import java.util.Base64

const val AHPT_VERSION = 1

/** ChaChaPoly -- dieselbe Suite wie ahpt_client.py. */
const val AHPT_VERFAHREN = "noise_ik"

// Muessen zu relay.php passen.
const val MAX_FRAGE = 4096
const val MAX_STUECK = 49152
const val MAX_FRAGE_TEILE = 160

/**
 * Groesse eines Blocks beim Uebertragen (Rohdaten, VOR base64 und Noise).
 *
 * Der Vermittler laesst je Frage MAX_FRAGE_TEILE * MAX_STUECK ~ 7,5 MiB
 * Base64. Base64 blaeht um 4/3 auf, Noise legt 16 Byte je Chiffre dazu --
 * dann bleiben knapp 5,5 MiB Rohdaten je Block. 4 MiB laesst reichlich Luft.
 */
const val BLOCK = 4 * 1024 * 1024

/** Darunter geht eine Datei in EINER Frage, ohne Marke und Blockzaehlung. */
const val KLEIN = BLOCK

enum class Fehlerart {
    Netz, Abgewiesen, Umleitung, Krypto, Zeit, ZuGross, Leer, Geaendert, Pruefsumme, Sonstiges
}

class AhptFehler(
    text: String,
    val art: Fehlerart = Fehlerart.Sonstiges,
) : Exception(text)

/** Meldungen ueber den Fortschritt eines laufenden Vorgangs. */
sealed interface Fortschritt {
    data object Warten : Fortschritt
    data class Hoch(val getan: Int, val gesamt: Int) : Fortschritt
    data class Runter(val getan: Long, val gesamt: Long) : Fortschritt
    data class Summe(val getan: Long, val gesamt: Long) : Fortschritt
}

typealias FortschrittMelder = (Fortschritt) -> Unit

private val zufall = SecureRandom()

internal fun zufallHex(bytes: Int): String =
    bytesZuHex(ByteArray(bytes).also { zufall.nextBytes(it) })

internal fun b64(b: ByteArray): String = Base64.getEncoder().encodeToString(b)

internal fun entB64(s: String): ByteArray = try {
    Base64.getDecoder().decode(s)
} catch (e: IllegalArgumentException) {
    throw AhptFehler("Antwort ist kein gueltiges Base64", Fehlerart.Krypto)
}

/**
 * Ein Vorgang gegen den Vermittler.
 *
 * Blockierend. Die Nebenlaeufigkeit gehoert in die App-Schicht (ein
 * Dispatcher, ein WorkManager) -- hier waere sie eine zweite Sache, die
 * mitgeprueft werden muesste, ohne dass der Kern etwas davon haette.
 */
class AhptClient(
    basis: String,
    private val privat: ByteArray,
    private val agent: ByteArray,
    private val netz: Netz = HttpNetz(),
    /**
     * Zeitfenster, in dem die Antwort auf EINE Frage eintreffen muss.
     *
     * Passt zur MARKE_TTL des Vermittlers (120 s in relay.php); der
     * Kommandozeilen-Client hat 110 s -- knapp darunter, damit eine Frage,
     * die dieser Client noch fuer offen haelt, beim Vermittler nicht schon
     * abgelaufen ist. 60 s waren zu wenig, sobald zwischen Antwort und
     * naechster Frage ein Agenten-Poll-Zyklus lag.
     */
    private val fristMs: Long = 110_000,
    private val schlaf: (Long) -> Unit = { Thread.sleep(it) },
    private val jetzt: () -> Long = { System.currentTimeMillis() },
) {
    private val basis = basis.trimEnd('/')

    /* ------------------------------------------------------------ Umlauf */

    /** Ein vollstaendiger Vorgang: fragen, warten, Antwort auspacken. */
    fun frage(
        dienst: String,
        aktion: String,
        daten: JSONObject,
        melde: FortschrittMelder? = null,
    ): JSONObject {
        val sitzung = HandshakeIK(Suite.ChaChaPoly, AHPT_PROLOG, privat, agent)
        val klartext = JSONObject()
            .put("dienst", dienst)
            .put("aktion", aktion)
            .put("daten", daten)
            .toString().toByteArray(Charsets.UTF_8)
        val chiffre = b64(sitzung.schreibeNachricht1(klartext))

        val marke = if (chiffre.length > MAX_FRAGE) {
            hochladen(chiffre, melde)
        } else {
            sende("frage", JSONObject()
                .put("v", AHPT_VERSION)
                .put("krypto", AHPT_VERFAHREN)
                .put("nutzlast", JSONObject().put("chiffre", chiffre)))
                .optString("marke")
        }
        if (marke.length != 32) throw AhptFehler("Vermittler gab keine gueltige Marke")

        return auspacken(marke, warte(marke, melde), sitzung)
    }

    /**
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
    private fun hochladen(chiffre: String, melde: FortschrittMelder?): String {
        // Mindestens 2 Stuecke -- nicht nur "mind. 1". Der Vermittler nimmt
        // die leere Ankuendigungs-Nutzlast nur bei `teile > 1` an; bei genau
        // einem Stueck landet sie in der normalen Pruefung und scheitert
        // dort, weil leer kein gueltiges Base64 ist. Trifft jede Chiffre
        // zwischen MAX_FRAGE und MAX_STUECK -- am 05.09.2026 live gefunden,
        // eine 12,43-KB-Textdatei scheiterte genau daran.
        val teile = maxOf(2, (chiffre.length + MAX_STUECK - 1) / MAX_STUECK)
        if (teile > MAX_FRAGE_TEILE) {
            throw AhptFehler(
                "Zu gross: $teile Stuecke, erlaubt sind $MAX_FRAGE_TEILE. " +
                        "Der Weg traegt Dokumente und Belege, keine Videos.",
                Fehlerart.ZuGross,
            )
        }
        // Schnittgroesse aus der (ggf. angehobenen) Stueckzahl ableiten,
        // NICHT umgekehrt in feste MAX_STUECK-Bloecke schneiden -- sonst
        // waere bei einer kurzen Chiffre und teile=2 das zweite Stueck leer,
        // und leer scheitert eine Ebene tiefer an derselben Pruefung.
        val stueckgroesse = (chiffre.length + teile - 1) / teile
        val marke = sende("frage", JSONObject()
            .put("v", AHPT_VERSION)
            .put("krypto", AHPT_VERFAHREN)
            .put("teile", teile)
            .put("nutzlast", JSONObject().put("chiffre", "")))
            .optString("marke")

        for (i in 0 until teile) {
            val von = i * stueckgroesse
            val bis = minOf(chiffre.length, von + stueckgroesse)
            sende("frage_stueck", JSONObject()
                .put("v", AHPT_VERSION)
                .put("krypto", AHPT_VERFAHREN)
                .put("marke", marke)
                .put("teil", i)
                .put("teile", teile)
                .put("nutzlast", chiffre.substring(von, bis)))
            melde?.invoke(Fortschritt.Hoch(i + 1, teile))
        }
        sende("frage_fertig", JSONObject()
            .put("v", AHPT_VERSION)
            .put("krypto", AHPT_VERFAHREN)
            .put("marke", marke)
            .put("teile", teile))
        return marke
    }

    /**
     * Warten, bis die Antwort bereitliegt -- ueber die WARTESCHLANGE, nicht
     * durch wiederholtes Fragen nach der Antwortdatei.
     *
     * Der Unterschied ist nicht Feinschliff. Solange die Antwort nicht da
     * ist, ergaebe ein direkter Abruf einen 404 -- und bplaced liefert seine
     * eigene 404-Seite aus einem anderen Verzeichnis aus, ohne CORS-Kopfzeile.
     * Im Browser kam ein solcher 404 nicht als 404 an, sondern als Netzfehler
     * (03.09.2026 gemessen). Hier faellt das CORS-Thema zwar weg, aber der
     * andere Grund bleibt: EIN Abruf beantwortet die Frage fuer alle
     * laufenden Vorgaenge, nicht einer je Vorgang.
     */
    private fun warte(marke: String, melde: FortschrittMelder?): JSONObject {
        val bis = jetzt() + fristMs
        var abstand = 350L
        while (jetzt() < bis) {
            val q = holeJson("warteschlange.json")
            val fertig = q?.optJSONArray("fertig")
            if (fertig != null && (0 until fertig.length()).any { fertig.optString(it) == marke }) {
                return holeJson("antwort_$marke.json") ?: throw AhptFehler(
                    "Die Warteschlange meldet die Antwort als fertig, aber die " +
                            "Datei fehlt. Das deutet auf ein Aufraeumen zur Unzeit hin.",
                    Fehlerart.Netz,
                )
            }
            melde?.invoke(Fortschritt.Warten)
            schlaf(abstand)
            abstand = minOf(1500L, (abstand * 13) / 10)
        }
        throw AhptFehler(
            "Zeit abgelaufen -- der Agent hat nicht geantwortet. Laeuft er? " +
                    "Steht der oeffentliche Schluessel dieses Geraets in seiner " +
                    "clients-Liste?",
            Fehlerart.Zeit,
        )
    }

    private fun pruefeUmschlag(u: JSONObject, marke: String, teil: Int? = null) {
        if (u.optInt("v", -1) != AHPT_VERSION) {
            throw AhptFehler("Protokollfassung ${u.opt("v")}, erwartet $AHPT_VERSION")
        }
        // DIE Pruefung gegen eine stille Umleitung.
        if (u.optString("marke") != marke) {
            throw AhptFehler(
                "Marke weicht ab -- das deutet auf eine Umleitung hin. " +
                        "Steht CheckSpelling Off in der .htaccess?",
                Fehlerart.Umleitung,
            )
        }
        if (teil != null && u.optInt("teil", -1) != teil) {
            throw AhptFehler("Stuecknummer weicht ab", Fehlerart.Umleitung)
        }
    }

    private fun auspacken(marke: String, u: JSONObject, sitzung: HandshakeIK): JSONObject {
        pruefeUmschlag(u, marke)
        val krypto = u.optString("krypto")
        if (krypto != AHPT_VERFAHREN) {
            // Ein Rueckfall auf Klartext waere ein Angriff, kein Zufall: Wer
            // die Verschluesselung abschalten kann, indem er sie weglaesst,
            // hat keine.
            throw AhptFehler(
                "Die Antwort kam nicht in der erwarteten Verschluesselung " +
                        "($krypto statt $AHPT_VERFAHREN). Das wird nicht hingenommen " +
                        "-- entweder stimmt die Einrichtung nicht, oder jemand hat " +
                        "die Antwort ersetzt.",
                Fehlerart.Krypto,
            )
        }
        val teile = u.optInt("teile", 1)
        val chiffre = if (teile > 1) {
            stuecke(marke, teile, u.optJSONObject("nutzlast")?.optJSONArray("stuecke"))
        } else {
            u.optJSONObject("nutzlast")?.optString("chiffre") ?: ""
        }

        val klartext = try {
            sitzung.liesNachricht2(entB64(chiffre))
        } catch (e: Exception) {
            throw AhptFehler(
                "Die Antwort liess sich nicht entschluesseln. Sie stammt nicht " +
                        "von dem Agenten, dessen Schluessel hier eingetragen ist -- " +
                        "oder sie wurde unterwegs veraendert.",
                Fehlerart.Krypto,
            )
        }
        return JSONObject(String(klartext, Charsets.UTF_8))
    }

    private fun stuecke(marke: String, teile: Int, liste: JSONArray?): String {
        if (liste == null || liste.length() != teile) {
            throw AhptFehler("Verzeichnis und Stueckzahl passen nicht zusammen")
        }
        val teil = arrayOfNulls<String>(teile)
        for (i in 0 until liste.length()) {
            val e = liste.optJSONObject(i)
                ?: throw AhptFehler("Stueck ohne Angaben")
            // Der Dateiname wird GELESEN, nie gebaut: Er traegt vier
            // abgeleitete Zeichen, damit benachbarte Stuecke nicht eine
            // Zeichenaenderung auseinanderliegen -- sonst haelt mod_speling
            // sie fuer Tippfehler.
            val datei = e.optString("datei")
            val nr = e.optInt("teil", -1)
            if (!datei.startsWith("antwort_") || datei.contains('/') || datei.contains('\\')) {
                throw AhptFehler("Stueck mit unbrauchbarem Dateinamen")
            }
            if (nr < 0 || nr >= teile) throw AhptFehler("Stueck mit unbrauchbarer Nummer")
            val s = holeJson(datei) ?: throw AhptFehler("Stueck $nr fehlt")
            pruefeUmschlag(s, marke, nr)
            if (s.optInt("teile", -1) != teile) throw AhptFehler("Stueck $nr zaehlt anders")
            teil[nr] = s.optString("nutzlast")
        }
        if (teil.any { it == null }) throw AhptFehler("Es fehlt ein Stueck")
        return teil.joinToString("")
    }

    /* ------------------------------------------------------------- Netz */

    private fun sende(aktion: String, koerper: JSONObject): JSONObject {
        val a = netz.sende("$basis/relay.php?action=$aktion", koerper.toString())
        val d = try {
            JSONObject(a.text)
        } catch (e: Exception) {
            JSONObject()
        }
        if (a.kode !in 200..299 || !d.optBoolean("ok")) {
            throw AhptFehler(
                "Abgewiesen (HTTP ${a.kode}): " +
                        d.optString("fehler").ifEmpty { "keine Begruendung" },
                Fehlerart.Abgewiesen,
            )
        }
        return d
    }

    private fun holeJson(pfad: String): JSONObject? {
        val a = netz.hole("$basis/ahpt/$pfad") ?: return null
        if (a.kode !in 200..299) {
            throw AhptFehler("Abruf ergab HTTP ${a.kode}", Fehlerart.Netz)
        }
        return try {
            JSONObject(a.text)
        } catch (e: Exception) {
            throw AhptFehler("Abruf lieferte kein JSON: $pfad", Fehlerart.Netz)
        }
    }
}
