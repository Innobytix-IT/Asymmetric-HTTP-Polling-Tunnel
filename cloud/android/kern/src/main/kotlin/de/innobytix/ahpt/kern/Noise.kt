/*
 * Noise.kt -- Noise IK fuer Android, dritte Umsetzung
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU
 * ----
 * Das Gegenstueck zu krypto.py und noise.js, damit die App dieselbe Sprache
 * spricht wie der Kommandozeilen-Client und das Portal. Sie ist die DRITTE
 * Umsetzung desselben Verfahrens -- und wie die beiden anderen wird sie gegen
 * tests/ik_vektoren.json nachgerechnet, Byte fuer Byte. Eine Kryptografie,
 * die nur mit sich selbst funktioniert, faellt genau dabei auf.
 *
 * WARUM BEIDE SUITEN, ANDERS ALS IM PORTAL
 * -----------------------------------------
 * noise.js kann nur AES-GCM, weil WebCrypto kein ChaCha20-Poly1305 kennt.
 * Diese Einschraenkung gibt es hier nicht, also stehen beide zur Verfuegung:
 *
 *   Noise_IK_25519_ChaChaPoly_SHA256   wie ahpt_client.py
 *   Noise_IK_25519_AESGCM_SHA256       wie das Portal
 *
 * Die App spricht ChaChaPoly, also dieselbe wie der Kommandozeilen-Client.
 * AES-GCM ist trotzdem umgesetzt, und zwar nicht auf Vorrat: Nur so lassen
 * sich BEIDE Testvektoren nachrechnen, und ein Fehler in der gemeinsamen
 * Grundrechnung faellt dann zweimal auf statt einmal.
 *
 * WARUM DIE UNTERE SCHICHT VON BOUNCYCASTLE
 * ------------------------------------------
 * Android bringt selbst eine alte, beschnittene BouncyCastle-Fassung mit. Wer
 * einen zweiten Provider registriert, bekommt ein Verhalten, das vom Geraet
 * abhaengt -- und Fehler, die sich auf einem Geraet nicht zeigen.
 * org.bouncycastle.crypto.* und .math.ec.* melden sich nirgends an; sie
 * rechnen nur. Damit ist das Ergebnis auf jedem Geraet dasselbe.
 *
 * DIE ENGLISCHEN NAMEN
 * --------------------
 * MixKey, MixHash, EncryptAndHash, Split heissen wie in der Spezifikation,
 * damit man Zeile fuer Zeile mit ihr und mit den beiden anderen Umsetzungen
 * vergleichen kann. Uebersetzte Namen waeren hier keine Sorgfalt, sondern
 * eine zusaetzliche Fehlerquelle.
 */
package de.innobytix.ahpt.kern

import org.bouncycastle.crypto.digests.SHA256Digest
import org.bouncycastle.crypto.engines.AESEngine
import org.bouncycastle.crypto.macs.HMac
import org.bouncycastle.crypto.modes.ChaCha20Poly1305
import org.bouncycastle.crypto.modes.GCMBlockCipher
import org.bouncycastle.crypto.params.AEADParameters
import org.bouncycastle.crypto.params.KeyParameter
import org.bouncycastle.math.ec.rfc7748.X25519
import java.security.SecureRandom

/** Bindet den Handshake an DIESES Protokoll -- muss beim Agenten gleich sein. */
val AHPT_PROLOG: ByteArray = "AHPT-Privat/1".toByteArray(Charsets.UTF_8)

class NoiseFehler(meldung: String) : Exception(meldung)

/* ------------------------------------------------------------- Werkzeug */

fun hexZuBytes(h: String): ByteArray {
    val s = h.trim().lowercase().filter { it in "0123456789abcdef" }
    if (s.length % 2 != 0) throw NoiseFehler("Hexwert hat ungerade Laenge")
    return ByteArray(s.length / 2) {
        ((Character.digit(s[it * 2], 16) shl 4) or
                Character.digit(s[it * 2 + 1], 16)).toByte()
    }
}

fun bytesZuHex(b: ByteArray): String = b.joinToString("") { "%02x".format(it) }

fun verkette(vararg teile: ByteArray): ByteArray {
    val r = ByteArray(teile.sumOf { it.size })
    var i = 0
    for (t in teile) {
        t.copyInto(r, i)
        i += t.size
    }
    return r
}

/**
 * Vergleich in gleichbleibender Zeit.
 *
 * Ein Vergleich, der beim ersten Unterschied abbricht, verraet ueber seine
 * Laufzeit, WIE WEIT zwei Werte uebereinstimmen. Wer raten darf und die Zeit
 * messen kann, raet damit Stelle fuer Stelle statt auf einen Schlag.
 */
fun gleich(a: ByteArray, b: ByteArray): Boolean {
    if (a.size != b.size) return false
    var d = 0
    for (i in a.indices) d = d or (a[i].toInt() xor b[i].toInt())
    return d == 0
}

/* -------------------------------------------------------- Grundrechnung */

fun sha256(daten: ByteArray): ByteArray {
    val d = SHA256Digest()
    d.update(daten, 0, daten.size)
    return ByteArray(d.digestSize).also { d.doFinal(it, 0) }
}

fun hmacSha256(schluessel: ByteArray, daten: ByteArray): ByteArray {
    val m = HMac(SHA256Digest())
    m.init(KeyParameter(schluessel))
    m.update(daten, 0, daten.size)
    return ByteArray(m.macSize).also { m.doFinal(it, 0) }
}

/**
 * Die HKDF-Variante der NOISE-Spezifikation.
 *
 * ACHTUNG: Das ist NICHT die uebliche HKDF. Noise verkettet HMAC-Aufrufe in
 * einer eigenen Form -- jeder Ausgang geht in den naechsten ein --, und es
 * gibt kein `info`-Feld. Wer hier eine fertige HKDF einsetzt, bekommt andere
 * Schluessel und merkt es erst, wenn die Testvektoren nicht mehr stimmen.
 * Genau dafuer gibt es sie.
 */
fun noiseHkdf(ck: ByteArray, ikm: ByteArray, anzahl: Int): List<ByteArray> {
    val temp = hmacSha256(ck, ikm)
    val o1 = hmacSha256(temp, byteArrayOf(1))
    if (anzahl == 1) return listOf(o1)
    val o2 = hmacSha256(temp, verkette(o1, byteArrayOf(2)))
    if (anzahl == 2) return listOf(o1, o2)
    val o3 = hmacSha256(temp, verkette(o2, byteArrayOf(3)))
    return listOf(o1, o2, o3)
}

/* --------------------------------------------------------------- X25519 */

private val zufall = SecureRandom()

object Dh {
    /** Oeffentlicher Teil zu einem privaten Rohschluessel. */
    fun oeffentlichZu(privat32: ByteArray): ByteArray {
        pruefe32(privat32, "privater Schluessel")
        return ByteArray(32).also { X25519.scalarMultBase(privat32, 0, it, 0) }
    }

    /** Gemeinsames Geheimnis aus eigenem privaten und fremdem oeffentlichen. */
    fun dh(privat32: ByteArray, oeffentlich32: ByteArray): ByteArray {
        pruefe32(privat32, "privater Schluessel")
        pruefe32(oeffentlich32, "oeffentlicher Schluessel")
        val r = ByteArray(32)
        // Den Rueckgabewert zu verwerfen waere falsch: X25519 meldet mit
        // `false` einen Punkt kleiner Ordnung. Das Ergebnis waere dann lauter
        // Nullen, und zwar fuer JEDEN privaten Schluessel -- ein Gegenueber
        // koennte damit ein "gemeinsames Geheimnis" erzwingen, das es vorher
        // kennt.
        if (!X25519.calculateAgreement(privat32, 0, oeffentlich32, 0, r, 0)) {
            throw NoiseFehler("X25519: unbrauchbarer oeffentlicher Schluessel")
        }
        return r
    }

    /** Neues Schluesselpaar: (privat, oeffentlich). */
    fun schluesselpaar(): Pair<ByteArray, ByteArray> {
        val privat = ByteArray(32).also { zufall.nextBytes(it) }
        return privat to oeffentlichZu(privat)
    }

    private fun pruefe32(b: ByteArray, was: String) {
        if (b.size != 32) throw NoiseFehler("$was: 32 Bytes erwartet, nicht ${b.size}")
    }
}

/* ---------------------------------------------------------------- Suite */

enum class Suite(val protokollName: String) {
    ChaChaPoly("Noise_IK_25519_ChaChaPoly_SHA256"),
    AesGcm("Noise_IK_25519_AESGCM_SHA256");

    companion object {
        fun ausName(name: String): Suite =
            entries.firstOrNull { it.protokollName == name }
                ?: throw NoiseFehler("unbekannte Suite: $name")
    }
}

/* ---------------------------------------------------------- CipherState */

class CipherState(private val suite: Suite) {
    private var k: ByteArray? = null
    private var n: Long = 0

    fun InitializeKey(schluessel: ByteArray?) {
        k = schluessel
        n = 0
    }

    fun HasKey(): Boolean = k != null

    /**
     * 96 Bit: 32 Bit Null, dann der Zaehler.
     *
     * AES-GCM verlangt BIG ENDIAN, ChaCha20-Poly1305 LITTLE ENDIAN. Das ist
     * keine Schlamperei der Spezifikation, sondern folgt den jeweiligen
     * Originalarbeiten. Wer beides gleich behandelt, baut etwas, das mit sich
     * selbst funktioniert und mit keiner anderen Umsetzung. Der Fehler faellt
     * erst bei der ZWEITEN Nachricht je Richtung auf, weil null in beiden
     * Reihenfolgen dasselbe ist -- und bis dahin sieht alles gut aus.
     */
    private fun nonce(): ByteArray {
        val iv = ByteArray(12)
        for (i in 0 until 8) {
            val b = ((n ushr (8 * i)) and 0xff).toByte()
            if (suite == Suite.AesGcm) iv[11 - i] = b else iv[4 + i] = b
        }
        return iv
    }

    private fun lauf(verschluesseln: Boolean, ad: ByteArray, ein: ByteArray): ByteArray {
        val schluessel = k ?: return ein
        val p = AEADParameters(KeyParameter(schluessel), 128, nonce(), ad)
        val c = if (suite == Suite.AesGcm)
            GCMBlockCipher.newInstance(AESEngine.newInstance())
        else
            ChaCha20Poly1305()
        c.init(verschluesseln, p)
        val aus = ByteArray(c.getOutputSize(ein.size))
        val geschrieben = c.processBytes(ein, 0, ein.size, aus, 0)
        c.doFinal(aus, geschrieben)
        return aus
    }

    fun EncryptWithAd(ad: ByteArray, klartext: ByteArray): ByteArray {
        if (k == null) return klartext
        return lauf(true, ad, klartext).also { n++ }
    }

    fun DecryptWithAd(ad: ByteArray, geheim: ByteArray): ByteArray {
        if (k == null) return geheim
        val p = try {
            lauf(false, ad, geheim)
        } catch (e: Exception) {
            // Absichtlich wortkarg: Eine Meldung, die zwischen "falscher
            // Schluessel" und "veraendert" unterscheidet, ist ein
            // Auskunftsdienst fuer den, der es versucht.
            throw NoiseFehler("Entschluesselung fehlgeschlagen")
        }
        n++
        return p
    }
}

/* ------------------------------------------------------- SymmetricState */

class SymmetricState(private val suite: Suite) {
    var h: ByteArray
        private set
    private var ck: ByteArray
    private val cs = CipherState(suite)

    init {
        val name = suite.protokollName.toByteArray(Charsets.UTF_8)
        // Ist der Name hoechstens so lang wie der Hash, wird er mit Nullen
        // aufgefuellt statt gehasht -- so steht es in der Spezifikation.
        h = if (name.size <= 32) ByteArray(32).also { name.copyInto(it) } else sha256(name)
        ck = h.copyOf()
    }

    fun MixKey(ikm: ByteArray) {
        val (neuCk, tempK) = noiseHkdf(ck, ikm, 2)
        ck = neuCk
        cs.InitializeKey(tempK)
    }

    fun MixHash(daten: ByteArray) {
        h = sha256(verkette(h, daten))
    }

    fun EncryptAndHash(klartext: ByteArray): ByteArray =
        cs.EncryptWithAd(h, klartext).also { MixHash(it) }

    fun DecryptAndHash(geheim: ByteArray): ByteArray {
        // Gehasht wird der GEHEIMTEXT, nicht der Klartext -- sonst haetten
        // beide Seiten verschiedene Hashes, sobald ein Feld unverschluesselt
        // bleibt.
        val p = cs.DecryptWithAd(h, geheim)
        MixHash(geheim)
        return p
    }

    fun Split(): Pair<CipherState, CipherState> {
        val (t1, t2) = noiseHkdf(ck, ByteArray(0), 2)
        return CipherState(suite).also { it.InitializeKey(t1) } to
                CipherState(suite).also { it.InitializeKey(t2) }
    }
}

/* ----------------------------------------------------------- HandshakeIK
 *
 *   IK:
 *     <- s
 *     ...
 *     -> e, es, s, ss
 *     <- e, ee, se
 *
 * Die App ist immer der Initiator: Sie kennt den statischen Schluessel des
 * Agenten, weil du ihn von Hand eingetragen hast. Die Gegenrichtung
 * (Responder) ist deshalb NICHT umgesetzt -- sie liefe hier nie, und
 * unbenutzter Code an einer Sicherheitsschranke wird auch nicht mitgeprueft.
 */
class HandshakeIK(
    suite: Suite,
    prologue: ByteArray,
    /** Eigener privater Schluessel, 32 rohe Bytes. */
    private val sRoh: ByteArray,
    /** Oeffentlicher Schluessel des Agenten, 32 rohe Bytes. */
    private val rs: ByteArray,
    /** Fluechtiger Schluessel -- nur fuer die Testvektoren vorzugeben. */
    eRoh: ByteArray? = null,
) {
    private val ss = SymmetricState(suite)
    private val sPub = Dh.oeffentlichZu(sRoh)
    private var e: ByteArray? = eRoh
    private var fertig = false

    init {
        ss.MixHash(prologue)
        // Vornachricht "<- s": Der statische Schluessel des Antwortenden ist
        // dem Initiator schon bekannt und geht in den Hash ein.
        ss.MixHash(rs)
    }

    fun schreibeNachricht1(nutzlast: ByteArray): ByteArray {
        val eigenesE = e ?: Dh.schluesselpaar().first.also { e = it }
        val ePub = Dh.oeffentlichZu(eigenesE)
        ss.MixHash(ePub)                                   // e
        ss.MixKey(Dh.dh(eigenesE, rs))                     // es
        val s = ss.EncryptAndHash(sPub)                    // s
        ss.MixKey(Dh.dh(sRoh, rs))                         // ss
        return verkette(ePub, s, ss.EncryptAndHash(nutzlast))
    }

    fun liesNachricht2(nachricht: ByteArray): ByteArray {
        if (nachricht.size < 32 + 16) throw NoiseFehler("Nachricht 2 zu kurz")
        val eigenesE = e ?: throw NoiseFehler("Nachricht 1 wurde nie geschrieben")
        val re = nachricht.copyOfRange(0, 32)
        ss.MixHash(re)                                     // e
        ss.MixKey(Dh.dh(eigenesE, re))                     // ee
        ss.MixKey(Dh.dh(sRoh, re))                         // se
        val klartext = ss.DecryptAndHash(nachricht.copyOfRange(32, nachricht.size))
        fertig = true
        return klartext
    }

    fun handshakeHash(): ByteArray = ss.h

    /** Erst nach dem Handshake: die beiden Transportschluessel. */
    fun transportschluessel(): Pair<CipherState, CipherState> {
        if (!fertig) throw NoiseFehler("Handshake noch nicht abgeschlossen")
        return ss.Split()
    }
}
