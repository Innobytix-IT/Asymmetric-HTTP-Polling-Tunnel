/*
 * Netz.kt -- der Weg zum Vermittler, und nichts weiter
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WARUM DAS EINE EIGENE SCHNITTSTELLE IST
 * ----------------------------------------
 * Damit sich das Protokoll ohne Netz pruefen laesst. Die Schranken, an denen
 * es haengt -- Marke gegenpruefen, Stueckdateinamen nicht selbst bauen, kein
 * Rueckfall auf Klartext -- lassen sich nur dann ernsthaft pruefen, wenn man
 * dem Client eine BOESWILLIGE Gegenstelle vorsetzen kann. Gegen einen echten
 * Agenten geht das nicht: Der verhaelt sich richtig.
 *
 * WARUM HttpURLConnection UND NICHT OkHttp
 * -----------------------------------------
 * Eine Abhaengigkeit weniger, und auf Android liegt unter
 * HttpURLConnection ohnehin OkHttp. Was hier zaehlt, ist nicht Bequemlichkeit,
 * sondern die Kontrolle ueber Umleitungen -- und die ist unten ausdruecklich
 * ausgeschaltet, nicht bloss nicht eingeschaltet.
 */
package de.innobytix.ahpt.kern

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Was von einem Abruf ankommt. `null` als Ergebnis heisst: HTTP 404. */
data class NetzAntwort(val kode: Int, val text: String)

interface Netz {
    /** POST mit JSON-Koerper. */
    fun sende(adresse: String, koerper: String): NetzAntwort

    /** GET. Gibt `null` zurueck, wenn es die Datei (noch) nicht gibt. */
    fun hole(adresse: String): NetzAntwort?
}

class HttpNetz(
    private val zeitLimitMs: Int = 30_000,
    private val kennung: String = "AHPT-Android/1",
) : Netz {

    override fun sende(adresse: String, koerper: String): NetzAntwort {
        val v = oeffne(adresse)
        v.requestMethod = "POST"
        v.doOutput = true
        v.setRequestProperty("Content-Type", "application/json")
        try {
            v.outputStream.use { it.write(koerper.toByteArray(Charsets.UTF_8)) }
            return lies(v, adresse)!!
        } catch (e: IOException) {
            throw AhptFehler(
                "Der Vermittler ist nicht erreichbar. Steht relay.php am " +
                        "erwarteten Ort?", Fehlerart.Netz,
            )
        } finally {
            v.disconnect()
        }
    }

    override fun hole(adresse: String): NetzAntwort? {
        val v = oeffne(adresse)
        v.requestMethod = "GET"
        try {
            return lies(v, adresse)
        } catch (e: IOException) {
            throw AhptFehler("Abruf fehlgeschlagen: ${e.message}", Fehlerart.Netz)
        } finally {
            v.disconnect()
        }
    }

    private fun oeffne(adresse: String): HttpURLConnection {
        val v = URL(adresse).openConnection() as HttpURLConnection
        // Eine Umleitung ist hier ein BEFUND, keine Bequemlichkeit. Am
        // 02.09.2026 hat mod_speling eine Abfrage stillschweigend auf eine
        // fremde Datei umgeleitet -- wer Umleitungen folgt, bekommt dann
        // einen gueltig aussehenden Umschlag, der zu einer anderen Frage
        // gehoert. Die Marke im Inhalt faengt das ab; hier faellt es schon
        // eine Ebene frueher auf.
        v.instanceFollowRedirects = false
        v.connectTimeout = zeitLimitMs
        v.readTimeout = zeitLimitMs
        v.setRequestProperty("User-Agent", kennung)
        v.setRequestProperty("Cache-Control", "no-store")
        return v
    }

    private fun lies(v: HttpURLConnection, adresse: String): NetzAntwort? {
        val kode = v.responseCode
        if (kode == HttpURLConnection.HTTP_NOT_FOUND) return null
        if (kode in 300..399) {
            throw AhptFehler(
                "Der Vermittler hat umgeleitet (HTTP $kode). Fehlt " +
                        "CheckSpelling Off in der .htaccess?", Fehlerart.Umleitung,
            )
        }
        val strom = if (kode in 200..299) v.inputStream else v.errorStream
        val text = strom?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
        return NetzAntwort(kode, text)
    }
}
