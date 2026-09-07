/*
 * Kopplung.kt -- Einrichten per QR-Code, ohne Abtippen
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU
 * ----
 * Ein Geraet einzurichten hiess bisher: die Adresse des Vermittlers und den
 * oeffentlichen Schluessel des Agenten abtippen (64 Hexzeichen), dann den
 * eigenen Schluessel zurueck zum Server tragen. Dreimal Gelegenheit, sich zu
 * vertippen, und jeder Vertipper endet in "Zeit abgelaufen" statt in einer
 * Meldung, die sagt was los ist.
 *
 * Der Einrichtungs-Assistent (einrichten.py) zeigt stattdessen einen
 * QR-Code. Darin steht alles fuer die eine Richtung -- und zusaetzlich die
 * Adresse des Assistenten samt Token, damit diese App die ANDERE Richtung
 * selbst erledigen kann.
 *
 * WAS DABEI NICHT UEBER DEN CODE GEHT
 * ------------------------------------
 * Der private Schluessel. Er entsteht hier auf dem Geraet, liegt im
 * Android-Schluesselspeicher und verlaesst ihn nie. Zurueck zum Assistenten
 * geht nur der OEFFENTLICHE Teil -- derselbe Wert, den man sonst abgetippt
 * haette.
 *
 * WARUM MEHRERE ADRESSEN
 * ----------------------
 * Der Assistent nennt jede Adresse, unter der er zu erreichen ist. Ueber
 * WLAN ist das eine andere als ueber ein USB-Kabel mit eingeschaltetem
 * Tethering, und welcher Weg gerade steht, weiss er beim Anzeigen des Codes
 * noch nicht. Also probiert diese Seite sie der Reihe nach durch.
 */
package de.innobytix.ahpt

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

data class Kopplungsdaten(
    val basis: String,
    val agentHex: String,
    val token: String,
    val adressen: List<String>,
) {
    companion object {
        /**
         * Den Inhalt eines Kopplungscodes lesen.
         *
         * Wirft mit einer Meldung, die sagt WAS fehlt. Ein gescannter Code,
         * der einfach "ungueltig" heisst, laesst den Nutzer raten, ob er den
         * falschen Code erwischt hat oder ob etwas kaputt ist.
         */
        fun lies(roh: String): Kopplungsdaten {
            val o = try {
                JSONObject(roh)
            } catch (e: Exception) {
                throw AhptKopplungsFehler(
                    "Das ist kein AHPT-Kopplungscode. Der Assistent zeigt ihn " +
                            "unter \"Weiteres Geraet hinzufuegen\".",
                )
            }
            val basis = o.optString("b")
            val agent = o.optString("a").lowercase()
            val token = o.optString("t")
            val adressen = o.optJSONArray("h")

            if (basis.isEmpty()) throw AhptKopplungsFehler(
                "Im Code fehlt die Adresse des Vermittlers.")
            if (!Regex("[0-9a-f]{64}").matches(agent)) throw AhptKopplungsFehler(
                "Im Code fehlt der Schluessel des Agenten, oder er ist unvollstaendig.")
            if (token.isEmpty()) throw AhptKopplungsFehler(
                "Im Code fehlt das Zugangs-Token des Assistenten.")

            return Kopplungsdaten(
                basis = basis.trimEnd('/'),
                agentHex = agent,
                token = token,
                adressen = (0 until (adressen?.length() ?: 0))
                    .mapNotNull { adressen?.optString(it) }
                    .filter { it.isNotEmpty() },
            )
        }
    }
}

class AhptKopplungsFehler(meldung: String) : Exception(meldung)

/**
 * Den eigenen oeffentlichen Schluessel beim Assistenten anmelden.
 *
 * Probiert alle Adressen aus dem Code durch und nimmt die erste, die
 * antwortet. Schlaegt keine an, sagt die Meldung WARUM das meist passiert --
 * die Antwort ist fast immer "die beiden Geraete sind nicht im selben Netz".
 */
fun meldeBeimAssistenten(
    daten: Kopplungsdaten,
    eigenerSchluesselHex: String,
    geraetename: String,
): String {
    if (daten.adressen.isEmpty()) throw AhptKopplungsFehler(
        "Im Code steht keine Adresse des Assistenten.")

    val koerper = JSONObject()
        .put("schluessel", eigenerSchluesselHex)
        .put("geraet", geraetename)
        .toString().toByteArray(Charsets.UTF_8)

    val gruende = mutableListOf<String>()
    for (adresse in daten.adressen) {
        val v = try {
            (URL("http://$adresse/api/koppeln?t=${daten.token}")
                .openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                instanceFollowRedirects = false
                connectTimeout = 4_000
                readTimeout = 8_000
                setRequestProperty("Content-Type", "application/json")
            }
        } catch (e: Exception) {
            gruende += "$adresse: ${e.message}"
            continue
        }
        try {
            v.outputStream.use { it.write(koerper) }
            val kode = v.responseCode
            val text = (if (kode in 200..299) v.inputStream else v.errorStream)
                ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (kode in 200..299) {
                return try {
                    JSONObject(text).optString("geraet").ifEmpty { geraetename }
                } catch (e: Exception) {
                    geraetename
                }
            }
            // Ein ANTWORTENDER Assistent, der ablehnt, ist etwas anderes als
            // einer, den wir nicht erreichen: Weitersuchen waere sinnlos, und
            // seine Begruendung ist die brauchbarste Meldung, die wir haben.
            val grund = try {
                JSONObject(text).optString("fehler")
            } catch (e: Exception) {
                ""
            }
            throw AhptKopplungsFehler(
                grund.ifEmpty { "Der Assistent hat abgelehnt (HTTP $kode)." })
        } catch (e: IOException) {
            gruende += "$adresse: ${e.message ?: "keine Verbindung"}"
        } finally {
            v.disconnect()
        }
    }
    throw AhptKopplungsFehler(
        "Der Assistent war unter keiner der Adressen erreichbar " +
                "(${daten.adressen.joinToString(", ")}). Meist heisst das: Handy " +
                "und Rechner haengen nicht im selben Netz. Entweder beide ins " +
                "gleiche WLAN, oder das Handy per USB anschliessen und dort " +
                "USB-Tethering einschalten.",
    )
}
