/*
 * NetzRahmungTest.kt -- kommt der Koerper VOLLSTAENDIG an?
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU
 * ----
 * Am 08.09.2026 im Emulator gemessen: Der Vermittler sendet 138 Byte, die
 * App liest 137. Das letzte Zeichen -- die schliessende Klammer -- fehlte,
 * das JSON war unbrauchbar, und auf dem Schirm stand "Abgewiesen (HTTP
 * 200): keine Begruendung".
 *
 * Der Verdacht galt der RAHMUNG, nicht der Menge: Fuer erzeugte Ausgabe
 * sendet `php -S` weder `Content-Length` noch `Transfer-Encoding`, es
 * schliesst nur die Verbindung. bplaced dagegen rahmt `chunked`, und dort
 * lief alles. Ein Fehler, der von der Gegenstelle abhaengt, gehoert in
 * einen Test mit einer Gegenstelle, die man selbst schreibt -- deshalb
 * hier ein echter Serversocket statt einer Attrappe.
 *
 * DER VERDACHT HAT SICH NICHT BESTAETIGT. Alle vier Rahmungen kommen hier
 * vollstaendig an, und auf dem Geraet ebenso (siehe
 * `app/src/androidTest/.../NetzRahmungGeraetTest`). Was die 137 Byte
 * verursacht hat, ist offen -- siehe OFFEN.md, Punkt 1.
 *
 * Die Pruefung bleibt trotzdem stehen: Sie kostet nichts und deckt eine
 * Klasse von Fehlern ab, die man sonst erst im Betrieb bemerkt. Der
 * Koerper ist absichtlich derselbe wie damals: 138 Zeichen, letztes
 * Zeichen eine Klammer.
 */
package de.innobytix.ahpt.kern

import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * Ein Server, der GENAU die Bytes sendet, die man ihm vorgibt.
 *
 * Bewusst kein fertiger Testserver: Jeder davon rahmt nach eigenem
 * Gutduenken, und die Rahmung ist hier der Gegenstand der Pruefung.
 */
private class RohServer(val antwort: (String) -> ByteArray) : AutoCloseable {
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
        // Die Anfrage bis zur Leerzeile lesen. Weiter nicht: Ein POST
        // brauchte hier seinen Koerper, und den will keine dieser
        // Pruefungen sehen.
        val ein = s.getInputStream()
        val kopf = StringBuilder()
        while (!kopf.endsWith("\r\n\r\n")) {
            val b = ein.read()
            if (b < 0) return
            kopf.append(b.toChar())
        }
        val weg = kopf.lineSequence().first().split(" ").getOrElse(1) { "/" }
        s.getOutputStream().write(antwort(weg))
        s.getOutputStream().flush()
        // Kein shutdownOutput, kein Warten: schliessen. Genau so beendet
        // `php -S` seine Antwort.
    }

    override fun close() = dose.close()
}

/** 138 Zeichen, letztes ist die Klammer -- wie am 08.09.2026 gemessen. */
private val KOERPER = buildString {
    append("""{"ok":true,"marke":"add81a2f4c6b0e93","datei":"antwort_add81a""")
    while (length < 137) append('x')
    append('}')
}

class NetzRahmungTest {

    private fun pruefe(kopfzeilen: String) {
        val leib = KOERPER.toByteArray(Charsets.UTF_8)
        RohServer { ("HTTP/1.1 200 OK\r\n$kopfzeilen\r\n").toByteArray() + leib }
            .use { srv ->
                val a = HttpNetz().hole("http://127.0.0.1:${srv.port}/antwort.json")
                assertEquals(138, KOERPER.length, "der Pruefkoerper selbst")
                assertEquals(KOERPER.length, a?.text?.length ?: -1,
                             "Zeichen angekommen bei: $kopfzeilen")
                assertEquals(KOERPER, a?.text)
            }
    }

    @Test
    fun `mit Content-Length kommt alles an`() =
        pruefe("Content-Type: application/json\r\nContent-Length: 138\r\n")

    @Test
    fun `chunked kommt alles an`() {
        val leib = KOERPER.toByteArray(Charsets.UTF_8)
        val brocken = "%x\r\n".format(leib.size).toByteArray() + leib +
                "\r\n0\r\n\r\n".toByteArray()
        RohServer {
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n".toByteArray() +
                "Transfer-Encoding: chunked\r\n\r\n".toByteArray() + brocken
        }.use { srv ->
            val a = HttpNetz().hole("http://127.0.0.1:${srv.port}/antwort.json")
            assertEquals(KOERPER, a?.text)
        }
    }

    @Test
    fun `nur Verbindungsabbau als Rahmung -- der damals Verdaechtige`() =
        pruefe("Content-Type: application/json\r\nConnection: close\r\n")

    @Test
    fun `HTTP-1_0 ohne jede Laengenangabe`() {
        val leib = KOERPER.toByteArray(Charsets.UTF_8)
        RohServer {
            "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n"
                .toByteArray() + leib
        }.use { srv ->
            val a = HttpNetz().hole("http://127.0.0.1:${srv.port}/antwort.json")
            assertEquals(KOERPER, a?.text)
        }
    }
}
