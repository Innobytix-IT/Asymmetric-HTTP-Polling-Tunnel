/*
 * NetzRahmungGeraetTest.kt -- dieselbe Frage, aber AUF dem Geraet
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WARUM ES DIESE DATEI ZWEIMAL GIBT
 * ----------------------------------
 * `kern/src/test/.../NetzRahmungTest.kt` stellt dieselben vier Rahmungen
 * auf der JVM -- und dort kommt alles vollstaendig an. Trotzdem fehlte am
 * 08.09.2026 auf dem Geraet das letzte Byte.
 *
 * Der Grund kann nur unterhalb des Kerns liegen: Unter Androids
 * `HttpURLConnection` steckt OkHttp, auf der JVM die Implementierung des
 * JDK. Es sind zwei verschiedene Programme hinter demselben Namen, und ein
 * Unterschied zwischen ihnen ist auf der JVM grundsaetzlich nicht zu sehen.
 *
 * Deshalb laeuft die Gegenstelle hier IM GERAET: ein Serversocket auf
 * 127.0.0.1, im selben Prozess. Kein Netz, kein Vermittler, kein WLAN --
 * nur die Frage, ob Androids Netzschicht den Koerper vollstaendig
 * herausgibt.
 *
 * ERGEBNIS: Sie tut es. Auf einem SM-G970F (Android 12) und im Emulator,
 * bei allen vier Rahmungen, und ueber die Netz-Nachbildung des Emulators
 * ebenso. Der Fehler von damals liegt also anderswo -- siehe OFFEN.md,
 * Punkt 1.
 */
package de.innobytix.ahpt

import androidx.test.platform.app.InstrumentationRegistry
import de.innobytix.ahpt.kern.HttpNetz
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeNotNull
import org.junit.Test
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

/** Ein Server, der GENAU die Bytes sendet, die man ihm vorgibt. */
private class RohServer(val antwort: () -> ByteArray) : AutoCloseable {
    private val dose = ServerSocket(0)
    val port: Int get() = dose.localPort

    init {
        thread(isDaemon = true) {
            while (!dose.isClosed) {
                val s = try { dose.accept() } catch (e: Exception) { break }
                thread(isDaemon = true) { bediene(s) }
            }
        }
    }

    private fun bediene(s: Socket) = s.use {
        val ein = s.getInputStream()
        val kopf = StringBuilder()
        while (!kopf.endsWith("\r\n\r\n")) {
            val b = ein.read()
            if (b < 0) return
            kopf.append(b.toChar())
        }
        s.getOutputStream().write(antwort())
        s.getOutputStream().flush()
        // Schliessen ohne Laengenangabe -- genau so beendet `php -S`.
    }

    override fun close() = dose.close()
}

/** 138 Zeichen, letztes ist die Klammer -- wie am 08.09.2026 gemessen. */
private val KOERPER = buildString {
    append("""{"ok":true,"marke":"add81a2f4c6b0e93","datei":"antwort_add81a""")
    while (length < 137) append('x')
    append('}')
}

class NetzRahmungGeraetTest {

    private fun pruefe(name: String, kopf: String, leib: ByteArray) {
        RohServer { "HTTP/1.1 200 OK\r\n$kopf\r\n".toByteArray() + leib }
            .use { srv ->
                val a = HttpNetz().hole("http://127.0.0.1:${srv.port}/antwort.json")
                assertEquals("$name: Zeichen angekommen",
                             KOERPER.length, a?.text?.length ?: -1)
                assertEquals(name, KOERPER, a?.text)
            }
    }

    private val leib get() = KOERPER.toByteArray(Charsets.UTF_8)

    @Test
    fun mitContentLength() =
        pruefe("Content-Length",
               "Content-Type: application/json\r\nContent-Length: 138\r\n", leib)

    @Test
    fun chunked() {
        val b = leib
        pruefe("chunked",
               "Content-Type: application/json\r\nTransfer-Encoding: chunked\r\n",
               "%x\r\n".format(b.size).toByteArray() + b + "\r\n0\r\n\r\n".toByteArray())
    }

    /** DER Fall aus OFFEN.md Punkt 1. */
    @Test
    fun nurVerbindungsabbau() =
        pruefe("Verbindungsabbau",
               "Content-Type: application/json\r\nConnection: close\r\n", leib)

    /**
     * Dieselbe Rahmung, aber ueber eine ECHTE Strecke statt ueber 127.0.0.1.
     *
     * Die anderen Pruefungen sprechen mit einem Serversocket im selben
     * Prozess -- dabei bleibt alles unterhalb von TCP aussen vor. Beim
     * Emulator ist das aber gerade die Schicht, die neu ist: Sein Netz ist
     * nachgebaut, und ein Verbindungsabbau muss durch diese Nachbildung
     * hindurch.
     *
     * Laeuft nur, wenn ein Ziel mitgegeben wird -- sonst wird sie
     * uebersprungen statt zu scheitern:
     *
     *   gradlew :app:connectedDebugAndroidTest      *     -Pandroid.testInstrumentationRunnerArguments.ziel=http://10.0.2.2:5177/antwort.json
     */
    @Test
    fun ueberEineEchteStrecke() {
        val ziel = InstrumentationRegistry.getArguments().getString("ziel")
        assumeNotNull(ziel)
        val a = HttpNetz().hole(ziel!!)
        assertEquals("Zeichen von $ziel", KOERPER.length, a?.text?.length ?: -1)
        assertEquals(KOERPER, a?.text)
    }

    @Test
    fun httpEinsNullOhneLaenge() {
        val b = leib
        RohServer {
            "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n".toByteArray() + b
        }.use { srv ->
            val a = HttpNetz().hole("http://127.0.0.1:${srv.port}/antwort.json")
            assertEquals("HTTP/1.0 ohne Laenge", KOERPER, a?.text)
        }
    }
}
