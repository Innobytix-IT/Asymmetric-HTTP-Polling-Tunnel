/*
 * Schluesselspeicher.kt -- wo der private Schluessel liegt, und warum dort
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * DER UNTERSCHIED ZUM PORTAL
 * ---------------------------
 * Das Portal legt den privaten Schluessel in `localStorage` ab. Es sagt das
 * dem Nutzer auch -- in index.html steht der Hinweis, auf einem fremden
 * Rechner sei das bedenklich. Es hat aber keine Wahl: Etwas Besseres gibt es
 * im Browser nicht.
 *
 * Hier gibt es etwas Besseres. Der Ablauf ist zweistufig:
 *
 *   1. Im Android-Schluesselspeicher liegt ein AES-Schluessel. Er wird DORT
 *      erzeugt und verlaesst ihn nie -- auf Geraeten mit sicherem Element
 *      liegt er in eigener Hardware, und selbst das Betriebssystem bekommt
 *      ihn nicht zu sehen, sondern nur Rechenergebnisse.
 *   2. Der private Noise-Schluessel wird damit verschluesselt und liegt nur
 *      in dieser Form in den Einstellungen.
 *
 * Was das bringt: Wer sich die Dateien der App beschafft -- ueber ein
 * Sicherungswerkzeug, ein entsperrtes Geraet, einen Fehler in einer anderen
 * App --, findet dort Rauschen. Zum Entschluesseln braeuchte er den
 * Schluessel aus dem Speicher, und den kann er nicht herauskopieren.
 *
 * WARUM DER NOISE-SCHLUESSEL NICHT SELBST IM SPEICHER LIEGT
 * ---------------------------------------------------------
 * Der Android-Schluesselspeicher kennt X25519 nicht als Schluesselart, die
 * man fuer ein Diffie-Hellman heranziehen koennte. Er kann also AES und
 * Signaturen, aber nicht das, was Noise braucht. Der Umweg ueber einen
 * AES-Umschlag ist deshalb kein Kompromiss aus Bequemlichkeit, sondern der
 * einzige Weg, der die Hardware ueberhaupt einbezieht.
 */
package de.innobytix.ahpt

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import de.innobytix.ahpt.kern.Dh
import de.innobytix.ahpt.kern.bytesZuHex
import de.innobytix.ahpt.kern.hexZuBytes
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private const val SPEICHER = "AndroidKeyStore"
private const val ALIAS = "ahpt_umschlag"
private const val EINSTELLUNGEN = "ahpt"

private const val S_PRIVAT = "privat_verschluesselt"
private const val S_BASIS = "basis"
private const val S_AGENT = "agent_oeffentlich"

class Schluesselspeicher(context: Context) {

    private val e = context.getSharedPreferences(EINSTELLUNGEN, Context.MODE_PRIVATE)

    /* -------------------------------------------------- Der Umschlag */

    private fun umschlagSchluessel(): SecretKey {
        val ks = KeyStore.getInstance(SPEICHER).apply { load(null) }
        (ks.getEntry(ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }

        val bau = KeyGenParameterSpec.Builder(
            ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            // Kein Entsperren je Zugriff. Das waere sicherer, machte aber
            // jedes Blaettern im Dateiverzeichnis zu einer Abfrage -- und
            // eine Schranke, die staendig im Weg steht, schaltet der Nutzer
            // irgendwann ab. Der Schluessel bleibt trotzdem im Speicher
            // gebunden und ist nicht auslesbar.
            .setUserAuthenticationRequired(false)
            .build()

        val g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, SPEICHER)
        g.init(bau)
        return g.generateKey()
    }

    private fun verschluessele(klar: ByteArray): String {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, umschlagSchluessel())
        val geheim = c.doFinal(klar)
        // Der Zufallsvektor gehoert dazu und ist kein Geheimnis -- er steht
        // vorne, damit beim Lesen nichts erraten werden muss.
        return Base64.encodeToString(c.iv + geheim, Base64.NO_WRAP)
    }

    private fun entschluessele(b64: String): ByteArray {
        val roh = Base64.decode(b64, Base64.NO_WRAP)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(
            Cipher.DECRYPT_MODE, umschlagSchluessel(),
            GCMParameterSpec(128, roh, 0, 12),
        )
        return c.doFinal(roh, 12, roh.size - 12)
    }

    /* ------------------------------------------------- Nach aussen */

    val eingerichtet: Boolean
        get() = hatSchluessel && basis.isNotEmpty() && agentHex.isNotEmpty()

    /**
     * Gibt es schon ein Schluesselpaar?
     *
     * Beim Koppeln wird genau danach gefragt, bevor ein neues erzeugt wird:
     * Ein zweites Mal erzeugen macht die bisherige Paarung still ungueltig,
     * und der Agent wuerde die App danach abweisen, ohne dass jemand wuesste
     * warum.
     */
    val hatSchluessel: Boolean
        get() = e.contains(S_PRIVAT)

    var basis: String
        get() = e.getString(S_BASIS, "") ?: ""
        set(v) = e.edit().putString(S_BASIS, v.trim().trimEnd('/')).apply()

    var agentHex: String
        get() = e.getString(S_AGENT, "") ?: ""
        set(v) = e.edit().putString(S_AGENT, v.trim().lowercase()).apply()

    /** Der private Schluessel, entschluesselt. Nur so lange halten wie noetig. */
    fun privat(): ByteArray {
        val g = e.getString(S_PRIVAT, null)
            ?: throw IllegalStateException("Es ist noch kein Schluessel erzeugt.")
        return entschluessele(g)
    }

    fun agent(): ByteArray = hexZuBytes(agentHex)

    /** Der eigene oeffentliche Teil -- der gehoert in die clients-Liste. */
    fun eigenerOeffentlicherHex(): String = bytesZuHex(Dh.oeffentlichZu(privat()))

    /**
     * Ein neues Schluesselpaar erzeugen.
     *
     * Ein NEUES macht die bisherige Paarung ungueltig: Der Agent kennt nur
     * den alten oeffentlichen Teil und wuerde den neuen abweisen. Deshalb
     * fragt die Oberflaeche vorher nach.
     */
    fun erzeugeNeuenSchluessel(): String {
        val (privat, _) = Dh.schluesselpaar()
        e.edit().putString(S_PRIVAT, verschluessele(privat)).apply()
        return eigenerOeffentlicherHex()
    }

    /** Alles loeschen -- auch den Umschlag im Schluesselspeicher. */
    fun vergissAlles() {
        e.edit().clear().apply()
        runCatching {
            KeyStore.getInstance(SPEICHER).apply { load(null) }.deleteEntry(ALIAS)
        }
    }
}
