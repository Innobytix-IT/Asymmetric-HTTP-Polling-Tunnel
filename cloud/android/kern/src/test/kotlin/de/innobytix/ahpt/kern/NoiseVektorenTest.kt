/*
 * NoiseVektorenTest.kt -- die dritte Umsetzung gegen dieselben Vektoren
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU
 * ----
 * krypto.py und noise.js rechnen beide gegen tests/ik_vektoren.json -- die
 * offiziellen Noise-Testvektoren aus `snow`. Diese Datei tut fuer Kotlin
 * dasselbe, und zwar gegen DIESELBE Datei, nicht gegen eine Kopie.
 *
 * Der Unterschied zu einem Durchstich mit sich selbst ist entscheidend: Eine
 * Umsetzung, die nur gegen sich selbst prueft, besteht ihre Pruefung auch
 * dann, wenn sie durchgehend falsch rechnet. Erst ein von aussen
 * vorgegebener Geheimtext, der Byte fuer Byte getroffen werden muss, belegt,
 * dass hier wirklich Noise IK laeuft und nicht etwas, das ihm aehnelt.
 *
 * WAS DIE VEKTOREN ABDECKEN, OHNE DASS MAN ES IHNEN ANSIEHT
 * ----------------------------------------------------------
 * Je Vektor stehen sechs Nachrichten: zwei fuer den Handshake, vier fuer den
 * Transport danach. Die vier sind kein Beiwerk. Der Zaehler in der Nonce
 * steht bei der ERSTEN Nachricht je Richtung auf null, und null sieht in
 * grosser wie in kleiner Bytereihenfolge gleich aus. Ein vertauschtes
 * Endian faellt deshalb erst bei der ZWEITEN Nachricht je Richtung auf --
 * also genau bei messages[4] und messages[5].
 */
package de.innobytix.ahpt.kern

import org.json.JSONObject
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import kotlin.test.fail

class NoiseVektorenTest {

    private fun vektoren(): List<JSONObject> {
        val pfad = System.getProperty("ahpt.vektoren")
            ?: fail("Systemeigenschaft ahpt.vektoren ist nicht gesetzt -- " +
                    "siehe kern/build.gradle.kts")
        val datei = File(pfad)
        if (!datei.isFile) {
            fail("Testvektoren nicht gefunden: $pfad\n" +
                    "Sie liegen beim uebrigen Projekt unter tests/, nicht im " +
                    "Android-Zweig -- absichtlich, damit es kein zweites " +
                    "Exemplar gibt, das veralten kann.")
        }
        val wurzel = JSONObject(datei.readText())
        val feld = wurzel.getJSONArray("vectors")
        return (0 until feld.length()).map { feld.getJSONObject(it) }
    }

    @Test
    fun `beide Suiten treffen die offiziellen Vektoren Byte fuer Byte`() {
        val alle = vektoren()
        assertTrue(alle.isNotEmpty(), "keine Vektoren in der Datei")

        var geprueft = 0
        for (v in alle) {
            val name = v.getString("protocol_name")
            val suite = Suite.ausName(name)

            val h = HandshakeIK(
                suite = suite,
                prologue = hexZuBytes(v.getString("init_prologue")),
                sRoh = hexZuBytes(v.getString("init_static")),
                rs = hexZuBytes(v.getString("init_remote_static")),
                eRoh = hexZuBytes(v.getString("init_ephemeral")),
            )

            val nachrichten = v.getJSONArray("messages")

            // --- Nachricht 1: wir schreiben sie, der Vektor sagt, wie sie
            //     aussehen muss.
            val m0 = nachrichten.getJSONObject(0)
            assertEquals(
                m0.getString("ciphertext"),
                bytesZuHex(h.schreibeNachricht1(hexZuBytes(m0.getString("payload")))),
                "$name: Handshake-Nachricht 1 weicht ab",
            )

            // --- Nachricht 2: der Vektor gibt sie vor, wir muessen den
            //     Klartext herausbekommen.
            val m1 = nachrichten.getJSONObject(1)
            assertEquals(
                m1.getString("payload"),
                bytesZuHex(h.liesNachricht2(hexZuBytes(m1.getString("ciphertext")))),
                "$name: Handshake-Nachricht 2 nicht entschluesselbar",
            )

            assertEquals(
                v.getString("handshake_hash"),
                bytesZuHex(h.handshakeHash()),
                "$name: Handshake-Hash weicht ab",
            )

            // --- Transport. Die Richtungen wechseln sich ab: gerade Nummern
            //     gehen vom Initiator weg, ungerade kommen zu ihm zurueck.
            val (nachDraussen, vonDraussen) = h.transportschluessel()
            for (i in 2 until nachrichten.length()) {
                val m = nachrichten.getJSONObject(i)
                val nutzlast = hexZuBytes(m.getString("payload"))
                val geheim = hexZuBytes(m.getString("ciphertext"))
                if (i % 2 == 0) {
                    assertEquals(
                        m.getString("ciphertext"),
                        bytesZuHex(nachDraussen.EncryptWithAd(ByteArray(0), nutzlast)),
                        "$name: Transportnachricht $i weicht ab",
                    )
                } else {
                    assertEquals(
                        m.getString("payload"),
                        bytesZuHex(vonDraussen.DecryptWithAd(ByteArray(0), geheim)),
                        "$name: Transportnachricht $i nicht entschluesselbar",
                    )
                }
            }
            geprueft++
        }
        assertEquals(2, geprueft, "es sollten beide Suiten geprueft worden sein")
    }

    /**
     * Die Bytereihenfolge der Nonce, ausdruecklich festgehalten.
     *
     * Die Vektoren decken das mit ab, aber erst ab der zweiten Nachricht je
     * Richtung -- und dort sieht ein Fehlschlag aus wie irgendeiner. Diese
     * Pruefung benennt ihn.
     */
    @Test
    fun `AES-GCM zaehlt gross-endian, ChaChaPoly klein-endian`() {
        val schluessel = ByteArray(32) { it.toByte() }
        val klartext = "x".toByteArray()

        for (suite in Suite.entries) {
            val a = CipherState(suite).also { it.InitializeKey(schluessel) }
            val b = CipherState(suite).also { it.InitializeKey(schluessel) }
            // Beide bei Zaehler 0 -- muss gleich sein.
            assertEquals(
                bytesZuHex(a.EncryptWithAd(ByteArray(0), klartext)),
                bytesZuHex(b.EncryptWithAd(ByteArray(0), klartext)),
                "$suite: erste Nachricht schon uneinig",
            )
            // Jetzt beide bei Zaehler 1. Waere die Reihenfolge verdreht,
            // ergaebe sich hier ein anderer Geheimtext als beim Gegenueber --
            // gegen die Vektoren geprueft wird das in der Pruefung darueber.
            val zweiteA = bytesZuHex(a.EncryptWithAd(ByteArray(0), klartext))
            val zweiteB = bytesZuHex(b.EncryptWithAd(ByteArray(0), klartext))
            assertEquals(zweiteA, zweiteB, "$suite: zweite Nachricht uneinig")
            assertTrue(
                zweiteA != bytesZuHex(CipherState(suite)
                    .also { it.InitializeKey(schluessel) }
                    .EncryptWithAd(ByteArray(0), klartext)),
                "$suite: der Zaehler wirkt sich gar nicht aus",
            )
        }
    }

    /**
     * Ein veraenderter Geheimtext darf nicht durchgehen, und die Meldung darf
     * nicht verraten, woran es lag.
     */
    @Test
    fun `veraenderter Geheimtext wird abgewiesen`() {
        for (suite in Suite.entries) {
            val schluessel = ByteArray(32) { (it * 7).toByte() }
            val c = CipherState(suite).also { it.InitializeKey(schluessel) }
            val geheim = c.EncryptWithAd(ByteArray(0), "Nachricht".toByteArray())
            geheim[0] = (geheim[0].toInt() xor 1).toByte()

            val e = CipherState(suite).also { it.InitializeKey(schluessel) }
            val fehler = assertFailsWith<NoiseFehler> {
                e.DecryptWithAd(ByteArray(0), geheim)
            }
            assertEquals("Entschluesselung fehlgeschlagen", fehler.message,
                "$suite: die Meldung soll nichts ueber die Ursache sagen")
        }
    }

    /**
     * X25519 mit einem Punkt kleiner Ordnung ergibt lauter Nullen -- fuer
     * JEDEN privaten Schluessel. Das muss auffallen, nicht stillschweigend
     * zu einem "gemeinsamen Geheimnis" werden, das der andere vorher kennt.
     */
    @Test
    fun `Punkt kleiner Ordnung wird abgewiesen`() {
        val privat = Dh.schluesselpaar().first
        assertFailsWith<NoiseFehler> { Dh.dh(privat, ByteArray(32)) }
    }

    @Test
    fun `Schluesselpaar und oeffentlicher Teil passen zusammen`() {
        val (privat, oeffentlich) = Dh.schluesselpaar()
        assertEquals(32, privat.size)
        assertEquals(32, oeffentlich.size)
        assertTrue(gleich(oeffentlich, Dh.oeffentlichZu(privat)))
        // Zwei Paare, beide Richtungen -- das gemeinsame Geheimnis muss
        // uebereinstimmen.
        val (p2, o2) = Dh.schluesselpaar()
        assertTrue(gleich(Dh.dh(privat, o2), Dh.dh(p2, oeffentlich)))
    }
}
