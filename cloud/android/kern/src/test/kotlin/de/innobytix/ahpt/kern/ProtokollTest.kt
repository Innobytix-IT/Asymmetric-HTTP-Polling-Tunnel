/*
 * ProtokollTest.kt -- die Schranken gegen eine boeswillige Gegenstelle
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU
 * ----
 * Ein Durchstich gegen den echten Agenten zeigt, dass beide Seiten dieselbe
 * Sprache sprechen. Er kann aber NICHT zeigen, dass die Schranken halten --
 * dafuer muesste der Agent sich falsch verhalten, und das tut er nicht.
 *
 * Hier steht deshalb das Gegenstueck: eine Gegenstelle, die genau das tut,
 * was ein Vermittler tun koennte, dem man nicht traut. Jede dieser Pruefungen
 * gehoert zu einer Zeile im Protokollkern, und jede wuerde ohne diese Zeile
 * durchgehen.
 */
package de.innobytix.ahpt.kern

import org.json.JSONArray
import org.json.JSONObject
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * Eine Gegenstelle, die sich nach Vorgabe verhaelt.
 *
 * `antwortBauer` bekommt die Marke und liefert den Umschlag, den der Client
 * unter `antwort_<marke>.json` vorfinden soll -- oder `null`, damit er
 * vergeblich wartet.
 */
private class Attrappe(
    val antwortBauer: (String) -> JSONObject?,
    val stueckDateien: Map<String, JSONObject> = emptyMap(),
    /** Meldet die Warteschlange die Marke ueberhaupt als fertig? */
    val meldetFertig: Boolean = true,
) : Netz {
    val gesendet = mutableListOf<Pair<String, JSONObject>>()
    var marke = "a".repeat(32)

    override fun sende(adresse: String, koerper: String): NetzAntwort {
        val aktion = adresse.substringAfter("action=")
        gesendet += aktion to JSONObject(koerper)
        return NetzAntwort(200, JSONObject()
            .put("ok", true).put("marke", marke).toString())
    }

    override fun hole(adresse: String): NetzAntwort? {
        val name = adresse.substringAfterLast('/')
        if (name == "warteschlange.json") {
            val fertig = if (meldetFertig) JSONArray().put(marke) else JSONArray()
            return NetzAntwort(200, JSONObject().put("fertig", fertig).toString())
        }
        stueckDateien[name]?.let { return NetzAntwort(200, it.toString()) }
        if (name == "antwort_$marke.json") {
            val u = antwortBauer(marke) ?: return null
            return NetzAntwort(200, u.toString())
        }
        return null
    }
}

class ProtokollTest {

    private val privat = ByteArray(32) { (it + 1).toByte() }
    private val agent = Dh.oeffentlichZu(ByteArray(32) { (it + 99).toByte() })

    private fun client(netz: Netz, fristMs: Long = 5_000) = AhptClient(
        basis = "http://beispiel.example/ahpt",
        privat = privat,
        agent = agent,
        netz = netz,
        fristMs = fristMs,
        schlaf = { },                       // im Test wird nicht gewartet
        jetzt = { zeit += 400; zeit },      // die Uhr laeuft mit den Abrufen
    )

    private var zeit = 0L

    private fun umschlag(marke: String) = JSONObject()
        .put("v", AHPT_VERSION)
        .put("marke", marke)
        .put("krypto", AHPT_VERFAHREN)
        .put("teile", 1)
        .put("nutzlast", JSONObject().put("chiffre", ""))

    /**
     * Die Pruefung gegen eine stille Umleitung.
     *
     * mod_speling hat am 02.09.2026 eine Abfrage auf eine FREMDE Datei
     * umgeleitet. Der Umschlag sah gueltig aus -- er gehoerte nur zu einer
     * anderen Frage. Ohne diese Pruefung faellt das nirgends auf.
     */
    @Test
    fun `Umschlag mit fremder Marke wird abgewiesen`() {
        val a = Attrappe({ umschlag("b".repeat(32)) })
        val f = assertFailsWith<AhptFehler> {
            client(a).frage("dateien", "liste", JSONObject())
        }
        assertEquals(Fehlerart.Umleitung, f.art)
    }

    /**
     * Ein Rueckfall auf Klartext ist ein Angriff, kein Zufall: Wer die
     * Verschluesselung abschalten kann, indem er sie weglaesst, hat keine.
     */
    @Test
    fun `unverschluesselte Antwort wird abgewiesen`() {
        val a = Attrappe({ umschlag(it).put("krypto", "keine") })
        val f = assertFailsWith<AhptFehler> {
            client(a).frage("dateien", "liste", JSONObject())
        }
        assertEquals(Fehlerart.Krypto, f.art)
    }

    /** Auch die andere Suite ist nicht dieselbe Suite. */
    @Test
    fun `Antwort in fremder Suite wird abgewiesen`() {
        val a = Attrappe({ umschlag(it).put("krypto", "noise_ik_aes") })
        val f = assertFailsWith<AhptFehler> {
            client(a).frage("dateien", "liste", JSONObject())
        }
        assertEquals(Fehlerart.Krypto, f.art)
    }

    /**
     * Stueckdateinamen werden GELESEN, nie gebaut -- aber gelesen heisst
     * nicht ungeprueft. Ein Name mit Pfadanteil wuerde den Abruf aus dem
     * Ablageverzeichnis herausfuehren.
     */
    @Test
    fun `Stueck mit Pfad im Dateinamen wird abgewiesen`() {
        for (boese in listOf("antwort_../../geheim.json", "antwort_a\\b.json", "beliebig.json")) {
            val a = Attrappe({
                umschlag(it).put("teile", 2).put("nutzlast", JSONObject()
                    .put("stuecke", JSONArray()
                        .put(JSONObject().put("datei", boese).put("teil", 0))
                        .put(JSONObject().put("datei", "antwort_x.json").put("teil", 1))))
            })
            val f = assertFailsWith<AhptFehler>("$boese haette abgewiesen werden muessen") {
                client(a).frage("dateien", "liste", JSONObject())
            }
            assertTrue(f.message!!.contains("Dateinamen") || f.message!!.contains("Nummer"))
        }
    }

    @Test
    fun `Stueckverzeichnis mit falscher Laenge wird abgewiesen`() {
        val a = Attrappe({
            umschlag(it).put("teile", 3).put("nutzlast", JSONObject()
                .put("stuecke", JSONArray()
                    .put(JSONObject().put("datei", "antwort_x.json").put("teil", 0))))
        })
        assertFailsWith<AhptFehler> { client(a).frage("dateien", "liste", JSONObject()) }
    }

    /** Ein Stueck, das eine andere Marke traegt als der Umschlag. */
    @Test
    fun `Stueck mit fremder Marke wird abgewiesen`() {
        val marke = "a".repeat(32)
        val stueck = JSONObject()
            .put("v", AHPT_VERSION)
            .put("marke", "c".repeat(32))
            .put("teil", 0).put("teile", 2).put("nutzlast", "AA==")
        val a = Attrappe(
            antwortBauer = {
                umschlag(it).put("teile", 2).put("nutzlast", JSONObject()
                    .put("stuecke", JSONArray()
                        .put(JSONObject().put("datei", "antwort_s0.json").put("teil", 0))
                        .put(JSONObject().put("datei", "antwort_s1.json").put("teil", 1))))
            },
            stueckDateien = mapOf("antwort_s0.json" to stueck),
        )
        val f = assertFailsWith<AhptFehler> {
            client(a).frage("dateien", "liste", JSONObject())
        }
        assertEquals(Fehlerart.Umleitung, f.art)
    }

    @Test
    fun `bleibt die Antwort aus, endet es in einer Zeitueberschreitung`() {
        val a = Attrappe({ null }, meldetFertig = false)
        val f = assertFailsWith<AhptFehler> {
            client(a, fristMs = 3_000).frage("dateien", "liste", JSONObject())
        }
        assertEquals(Fehlerart.Zeit, f.art)
    }

    /**
     * Der andere Fall, und er sieht von aussen gleich aus: Die Warteschlange
     * meldet die Antwort als fertig, aber die Datei ist nicht da. Das ist
     * KEINE Zeitueberschreitung -- es deutet auf ein Aufraeumen zur Unzeit
     * hin, und wer das als "der Agent antwortet nicht" meldet, schickt die
     * Fehlersuche in die falsche Richtung.
     */
    @Test
    fun `fertig gemeldet, aber Datei fehlt -- das ist kein Zeitproblem`() {
        val a = Attrappe({ null })
        val f = assertFailsWith<AhptFehler> {
            client(a).frage("dateien", "liste", JSONObject())
        }
        assertEquals(Fehlerart.Netz, f.art)
        assertTrue(f.message!!.contains("Aufraeumen"))
    }

    /**
     * Die Stueckelung beim Hochladen.
     *
     * Am 05.09.2026 live gefunden: Eine Chiffre zwischen MAX_FRAGE (4096) und
     * MAX_STUECK (49152) ergab bei naiver Rechnung EIN Stueck -- und der
     * Vermittler nimmt die leere Ankuendigungs-Nutzlast nur bei `teile > 1`
     * an. Eine 12,43-KB-Textdatei scheiterte genau daran. Deshalb mindestens
     * zwei, und die Schnittgroesse aus der Stueckzahl abgeleitet, damit kein
     * Stueck leer bleibt.
     */
    @Test
    fun `Stueckelung nimmt mindestens zwei Stuecke und laesst keines leer`() {
        val a = Attrappe({ null })
        // Frist sehr kurz: Uns interessiert nur, WAS gesendet wurde.
        runCatching {
            client(a, fristMs = 1).frage("dateien", "lege", JSONObject()
                .put("inhalt", "x".repeat(20_000)))
        }
        val stuecke = a.gesendet.filter { it.first == "frage_stueck" }
        assertTrue(stuecke.size >= 2, "es muessen mindestens zwei Stuecke sein")
        for ((_, k) in stuecke) {
            assertTrue(k.getString("nutzlast").isNotEmpty(), "ein Stueck war leer")
        }
        assertEquals(
            stuecke.size, a.gesendet.first { it.first == "frage" }.second.getInt("teile"),
            "die angekuendigte Stueckzahl passt nicht zu den gesendeten",
        )
        assertEquals(1, a.gesendet.count { it.first == "frage_fertig" })
        // Die Ankuendigung traegt eine LEERE Chiffre -- der Vermittler nimmt
        // sie nur so an.
        assertEquals(
            "", a.gesendet.first { it.first == "frage" }
                .second.getJSONObject("nutzlast").getString("chiffre"),
        )
    }

    /** Kleine Fragen gehen ohne Stueckelung, in einem Zug. */
    @Test
    fun `kleine Frage geht ungestueckelt`() {
        val a = Attrappe({ null })
        runCatching { client(a, fristMs = 1).frage("dateien", "liste", JSONObject()) }
        assertEquals(0, a.gesendet.count { it.first == "frage_stueck" })
        assertEquals(1, a.gesendet.count { it.first == "frage" })
        assertTrue(
            a.gesendet.first().second.getJSONObject("nutzlast")
                .getString("chiffre").isNotEmpty(),
        )
    }

    /** Jede Frage traegt Fassung und Verfahren -- der Vermittler prueft beides. */
    @Test
    fun `jede Sendung nennt Fassung und Verfahren`() {
        val a = Attrappe({ null })
        runCatching {
            client(a, fristMs = 1).frage("dateien", "lege", JSONObject()
                .put("inhalt", "x".repeat(20_000)))
        }
        assertTrue(a.gesendet.isNotEmpty())
        for ((aktion, k) in a.gesendet) {
            assertEquals(AHPT_VERSION, k.getInt("v"), "$aktion ohne Fassung")
            assertEquals(AHPT_VERFAHREN, k.getString("krypto"), "$aktion ohne Verfahren")
        }
    }
}
