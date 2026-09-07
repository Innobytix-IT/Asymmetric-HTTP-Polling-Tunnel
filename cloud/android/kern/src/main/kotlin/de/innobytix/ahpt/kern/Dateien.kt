/*
 * Dateien.kt -- liste, hole, lege, neuer_ordner
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WAS HIER BESSER GEHT ALS IM BROWSER
 * ------------------------------------
 * ahpt.js muss beim Hochladen die ganze Datei einmal in den Speicher ziehen,
 * weil `crypto.subtle.digest` keinen fortschreitenden SHA-256 kennt -- der
 * Kommentar dort sagt selbst, dass das bei einer sehr grossen Datei auf einem
 * Handy nicht aufgeht. Beim Herunterladen dasselbe in der anderen Richtung:
 * alle Stuecke landen in EINEM Uint8Array.
 *
 * Hier laeuft beides streamend. Damit haengt die Groesse am freien
 * Speicherplatz statt am Arbeitsspeicher -- und das ist auf einem Telefon der
 * Unterschied zwischen laeuft und laeuft nicht.
 */
package de.innobytix.ahpt.kern

import org.json.JSONObject
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest

/**
 * Etwas, das sich hochladen laesst.
 *
 * `oeffne()` muss jedes Mal einen Strom VON VORNE liefern: einmal fuer die
 * Pruefsumme, einmal fuer die Bloecke. Die Datei zweimal zu lesen ist
 * billiger, als sie fuer die Pruefsumme im Speicher zu halten.
 */
interface Quelle {
    val groesse: Long
    fun oeffne(): InputStream
}

/** Was beim Holen herauskam. Der Inhalt ging in den Zielstrom. */
data class HoleErgebnis(val name: String, val bytes: Long, val summeGeprueft: Boolean)

fun AhptClient.liste(pfad: String = ""): JSONObject {
    val a = frage("dateien", "liste", JSONObject().put("pfad", pfad))
    return inhaltOderFehler(a, "nichts gefunden")
}

fun AhptClient.neuerOrdner(pfad: String): JSONObject {
    val a = frage("dateien", "neuer_ordner", JSONObject().put("pfad", pfad))
    return inhaltOderFehler(a, "nicht angelegt")
}

/**
 * Eine Datei jeder Groesse herunterholen, Block fuer Block in den Zielstrom.
 *
 * Der erste Umlauf fragt gleich Daten UND Pruefsumme -- kleine Dateien sind
 * damit nach EINEM Umlauf da und geprueft.
 */
fun AhptClient.hole(
    pfad: String,
    ziel: OutputStream,
    melde: FortschrittMelder? = null,
): HoleErgebnis {
    val erst = inhaltOderFehler(
        frage("dateien", "hole", JSONObject()
            .put("pfad", pfad)
            .put("von", 0)
            .put("laenge", BLOCK)
            .put("pruefsumme", true), melde),
        "nichts gefunden",
    )
    val gesamt = erst.optLong("gesamt")
    val stand = erst.opt("stand")
    val summe = erst.optString("sha256").ifEmpty { null }
    val digest = MessageDigest.getInstance("SHA-256")

    var von = 0L
    entB64(erst.optString("inhalt")).let {
        ziel.write(it); digest.update(it); von += it.size
    }
    if (gesamt > BLOCK) melde?.invoke(Fortschritt.Runter(von, gesamt))

    while (von < gesamt) {
        val laenge = minOf(BLOCK.toLong(), gesamt - von).toInt()
        val w = inhaltOderFehler(
            frage("dateien", "hole", JSONObject()
                .put("pfad", pfad).put("von", von).put("laenge", laenge)),
            "nichts gefunden",
        )
        // Der Zeitstempel muss ueber alle Umlaeufe gleich bleiben. Aendert
        // sich die Datei waehrend des Holens, waeren die Stuecke aus zwei
        // Fassungen zusammengesetzt -- jedes fuer sich gueltig, das Ganze
        // falsch, und niemand saehe es.
        if (w.opt("stand") != stand) {
            throw AhptFehler(
                "Die Datei hat sich waehrend des Holens geaendert. Nichts " +
                        "uebernommen -- der Vorgang bleibt in sich schluessig.",
                Fehlerart.Geaendert,
            )
        }
        entB64(w.optString("inhalt")).let {
            ziel.write(it); digest.update(it); von += it.size
        }
        melde?.invoke(Fortschritt.Runter(von, gesamt))
    }
    ziel.flush()

    if (summe != null && bytesZuHex(digest.digest()) != summe) {
        throw AhptFehler(
            "Pruefsumme stimmt nicht -- die Datei ist unterwegs beschaedigt " +
                    "worden oder wurde veraendert.",
            Fehlerart.Pruefsumme,
        )
    }
    return HoleErgebnis(
        name = erst.optString("name").ifEmpty { pfad.substringAfterLast('/') },
        bytes = von,
        summeGeprueft = summe != null,
    )
}

/**
 * Eine Datei jeder Groesse hinaufbringen.
 *
 * Kleine Dateien gehen in EINER Frage. Der Weg mit Marke, Blockzaehlung und
 * Pruefsumme kostet je Umlauf rund zwei Sekunden -- das lohnt erst ab mehr
 * als einem Block.
 */
fun AhptClient.lege(
    pfad: String,
    quelle: Quelle,
    melde: FortschrittMelder? = null,
): JSONObject {
    val gesamt = quelle.groesse

    if (gesamt <= KLEIN) {
        val bytes = quelle.oeffne().use { it.readBytes() }
        return inhaltOderFehler(
            frage("dateien", "lege", JSONObject()
                .put("pfad", pfad)
                .put("inhalt_typ", "base64")
                .put("inhalt", b64(bytes)), melde),
            "nicht abgelegt",
        )
    }

    // GROSS: in BLOECKEN. Der Agent haengt sie an eine Teildatei und legt
    // erst ab, wenn die Pruefsumme des GANZEN stimmt.
    melde?.invoke(Fortschritt.Summe(0, gesamt))
    val summe = quelle.oeffne().use { strom ->
        val d = MessageDigest.getInstance("SHA-256")
        val puffer = ByteArray(64 * 1024)
        var gelesen = 0L
        while (true) {
            val n = strom.read(puffer)
            if (n < 0) break
            d.update(puffer, 0, n)
            gelesen += n
            melde?.invoke(Fortschritt.Summe(gelesen, gesamt))
        }
        bytesZuHex(d.digest())
    }

    val bloecke = ((gesamt + BLOCK - 1) / BLOCK).toInt()
    val marke = zufallHex(16)
    var antwort: JSONObject? = null

    quelle.oeffne().use { strom ->
        for (i in 0 until bloecke) {
            val laenge = minOf(BLOCK.toLong(), gesamt - i.toLong() * BLOCK).toInt()
            val roh = strom.lies(laenge)
            val daten = JSONObject()
                .put("uebertragung", marke)
                .put("block", i)
                .put("bloecke", bloecke)
                .put("inhalt_typ", "base64")
                .put("inhalt", b64(roh))
            // Pfad nur beim ERSTEN Block. Danach steht er beim Agenten fest;
            // ihn erneut mitzuschicken waere eine zweite Wahrheit.
            if (i == 0) daten.put("pfad", pfad)
            if (i == bloecke - 1) daten.put("sha256", summe)
            antwort = inhaltOderFehler(
                frage("dateien", "lege_block", daten), "block abgewiesen",
            )
            melde?.invoke(Fortschritt.Hoch(i + 1, bloecke))
        }
    }
    return antwort ?: throw AhptFehler("kein Block uebertragen")
}

/* ------------------------------------------------------------- Werkzeug */

/**
 * Die Antwort des Agenten auspacken.
 *
 * Sie traegt `gefunden` als Wahrheitswert und `inhalt` als Zeichenkette, in
 * der noch einmal JSON steckt. Das ist keine Doppelung ohne Grund: Der Kern
 * des Agenten ist inhaltsblind, `inhalt` gehoert dem Handler -- der Kern
 * reicht es durch, ohne es zu lesen.
 */
private fun inhaltOderFehler(a: JSONObject, vorgabe: String): JSONObject {
    if (!a.optBoolean("gefunden")) {
        throw AhptFehler(a.optString("grund").ifEmpty { vorgabe }, Fehlerart.Leer)
    }
    val roh = a.optString("inhalt").ifEmpty { "{}" }
    return try {
        JSONObject(roh)
    } catch (e: Exception) {
        throw AhptFehler("Antwort des Handlers ist kein JSON")
    }
}

/**
 * Genau `laenge` Bytes lesen.
 *
 * `read` darf jederzeit weniger liefern, als gewuenscht ist -- ohne dass
 * etwas fehlt. Wer das uebersieht, schickt kurze Bloecke, und die Pruefsumme
 * am Ende passt nicht mehr; der Fehler zeigt sich dann weit weg von seiner
 * Ursache. `readNBytes` gaebe es fertig, aber erst ab Android 13.
 */
private fun InputStream.lies(laenge: Int): ByteArray {
    val b = ByteArray(laenge)
    var gefuellt = 0
    while (gefuellt < laenge) {
        val n = read(b, gefuellt, laenge - gefuellt)
        if (n < 0) throw AhptFehler("Quelle endete frueher als angekuendigt")
        gefuellt += n
    }
    return b
}
