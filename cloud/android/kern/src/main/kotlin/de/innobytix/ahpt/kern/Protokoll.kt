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
    Netz, Abgewiesen, Umleitung, Krypto, Zeit, ZuGross, Leer, Geaendert, Pruefsumme,
    Abgebrochen, Sonstiges
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

    /**
     * Stueck soundso EINER Nachricht -- nicht Block soundso einer Datei.
     *
     * WOZU DAS NOETIG WURDE
     * ---------------------
     * Ein Block ist bis zu 4 MiB gross, und eine Datei darunter ist damit
     * EIN Block. Gemeldet wurde bisher erst, wenn er ganz durch war: Auf dem
     * Bildschirm stand von Anfang bis Ende "0 B von 4,1 MB", und dann war es
     * fertig. Dabei zerfaellt so ein Block sehr wohl in rund neunzig Stuecke
     * zu 48 KiB, jedes mit eigenem Abruf -- es gab also die ganze Zeit etwas
     * zu berichten, es fragte nur niemand danach.
     *
     * EIGENER TYP UND NICHT `Hoch`: Den gibt es schon fuer die Bloecke einer
     * Datei. Beides unter demselben Namen zu melden hiesse, dass der
     * Empfaenger "3 von 90" und "1 von 2" nicht auseinanderhalten kann --
     * und der Balken sprang entsprechend.
     */
    data class Stueck(val getan: Int, val gesamt: Int, val hinauf: Boolean) : Fortschritt
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

    /**
     * Die Abschnitte eines Vorgangs, in Millisekunden.
     *
     * `warten` ist der wertvolle Wert: die Zeit, bis der Agent die Frage
     * bemerkt UND beantwortet hat. Der Test auf dem Rechner des Agenten muss
     * diesen Anteil aus dem eingestellten Abfragetakt SCHAETZEN -- hier wird
     * er gemessen, denn hier steht die Uhr am richtigen Ende.
     */
    class Zeiten {
        var frageMs: Long = 0
        var wartenMs: Long = 0
        var holenMs: Long = 0
        var gesamtMs: Long = 0
        var abrufe: Int = 0
        var eintraege: Int = 0
        internal var bereit: Long = 0
    }

    /**
     * Die Verbindung pruefen -- vom CLIENT aus, nicht vom Agenten.
     *
     * WARUM DAS HIER STEHEN MUSS
     * ---------------------------
     * Der Vermittlertest in starten.py laeuft auf dem Rechner des Agenten und
     * spielt beide Rollen. Ehrlich misst er damit die Strecke Agent <->
     * Webspace. Die andere Haelfte -- Webspace <-> DIESES Geraet -- sieht er
     * prinzipiell nicht, denn dort steht er nicht. Und genau die spuert der
     * Anwender, wenn er im Mobilfunk oder in einem fremden WLAN sitzt.
     *
     * Hier sitzt der Client. Er ist zugelassen, also stellt er eine ECHTE
     * Frage und laesst die Uhr mitlaufen -- ohne Fuellstoff, ohne Sonderweg,
     * ohne einen Endpunkt, den es sonst nicht gaebe.
     *
     * Gemessen wird die ANTWORTZEIT, nicht der Durchsatz: Eine Auflistung ist
     * klein. Wieviel durch die Leitung passt, zeigt das naechste
     * Herunterladen einer richtigen Datei.
     */
    fun messeVerbindung(pfad: String = ""): Zeiten {
        val z = Zeiten()
        val t0 = jetzt()
        val antwort = frage("dateien", "liste", JSONObject().put("pfad", pfad),
                            null, z)
        z.eintraege = antwort.optJSONArray("eintraege")?.length() ?: 0
        z.gesamtMs = jetzt() - t0
        return z
    }

    /** Ein vollstaendiger Vorgang: fragen, warten, Antwort auspacken.
     *
     * `zeiten` ist freiwillig. Wird eines uebergeben, traegt dieser Vorgang
     * seine Abschnitte darin ein -- ohne dass am Ablauf etwas anders liefe.
     * Genau das macht die Verbindungspruefung glaubwuerdig: Sie misst den
     * ECHTEN Vorgang, sie baut ihn nicht nach. Eine Nachbildung haette die
     * Fehler nicht, die man sucht.
     */
    fun frage(
        dienst: String,
        aktion: String,
        daten: JSONObject,
        melde: FortschrittMelder? = null,
        zeiten: Zeiten? = null,
        abbruch: Abbruch? = null,
    ): JSONObject {
        abbruch.pruefe()
        val begonnen = jetzt()
        val sitzung = HandshakeIK(Suite.ChaChaPoly, AHPT_PROLOG, privat, agent)
        val klartext = JSONObject()
            .put("dienst", dienst)
            .put("aktion", aktion)
            .put("daten", daten)
            .toString().toByteArray(Charsets.UTF_8)
        val chiffre = b64(sitzung.schreibeNachricht1(klartext))

        val marke = if (chiffre.length > MAX_FRAGE) {
            hochladen(chiffre, melde, abbruch)
        } else {
            sende("frage", JSONObject()
                .put("v", AHPT_VERSION)
                .put("krypto", AHPT_VERFAHREN)
                .put("nutzlast", JSONObject().put("chiffre", chiffre)))
                .optString("marke")
        }
        if (marke.length != 32) throw AhptFehler("Vermittler gab keine gueltige Marke")

        zeiten?.frageMs = jetzt() - begonnen
        val umschlag = warte(marke, melde, zeiten, abbruch)
        val ergebnis = auspacken(marke, umschlag, sitzung, melde, abbruch)
        if (zeiten != null) {
            zeiten.holenMs = jetzt() - zeiten.bereit
            zeiten.gesamtMs = jetzt() - begonnen
        }
        return ergebnis
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
    private fun hochladen(
        chiffre: String,
        melde: FortschrittMelder?,
        abbruch: Abbruch? = null,
    ): String {
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
            // Hier auszusteigen kostet nichts: Die Marke wird erst durch
            // `frage_fertig` sichtbar. Was liegen bleibt, sieht der Agent
            // also nie, und der Vermittler raeumt es nach MARKE_TTL weg.
            abbruch.pruefe()
            val von = i * stueckgroesse
            val bis = minOf(chiffre.length, von + stueckgroesse)
            sende("frage_stueck", JSONObject()
                .put("v", AHPT_VERSION)
                .put("krypto", AHPT_VERFAHREN)
                .put("marke", marke)
                .put("teil", i)
                .put("teile", teile)
                .put("nutzlast", chiffre.substring(von, bis)))
            melde?.invoke(Fortschritt.Stueck(i + 1, teile, hinauf = true))
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
    private fun warte(
        marke: String,
        melde: FortschrittMelder?,
        zeiten: Zeiten? = null,
        abbruch: Abbruch? = null,
    ): JSONObject {
        val bis = jetzt() + fristMs
        val begonnen = jetzt()
        var abstand = 350L
        var abrufe = 0
        while (jetzt() < bis) {
            // Die WICHTIGSTE der drei Stellen: Hier steht der Anwender vor
            // "Warte auf den Agenten ...", und hier drueckt er ab. Die Frage
            // liegt dann schon beim Vermittler -- der Agent arbeitet sie zu
            // Ende und legt eine Antwort hin, die niemand abholt. Sie
            // verfaellt nach ANTWORT_TTL. Das ist der Preis, und er ist
            // kleiner als eine Minute Warten auf einen Abbruch.
            abbruch.pruefe()
            val q = holeJson("warteschlange.json")
            abrufe++
            val fertig = q?.optJSONArray("fertig")
            if (fertig != null && (0 until fertig.length()).any { fertig.optString(it) == marke }) {
                // Der Zeitpunkt, an dem die Antwort BEREITLAG. Alles davor
                // ist Warten auf den Agenten, alles danach die Leitung
                // hierher -- und die zwei zu trennen ist der Sinn der Sache.
                if (zeiten != null) {
                    zeiten.wartenMs = jetzt() - begonnen
                    zeiten.abrufe = abrufe
                    zeiten.bereit = jetzt()
                }
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

    private fun auspacken(
        marke: String,
        u: JSONObject,
        sitzung: HandshakeIK,
        melde: FortschrittMelder? = null,
        abbruch: Abbruch? = null,
    ): JSONObject {
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
            stuecke(marke, teile,
                    u.optJSONObject("nutzlast")?.optJSONArray("stuecke"), melde,
                    abbruch)
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

    private fun stuecke(
        marke: String,
        teile: Int,
        liste: JSONArray?,
        melde: FortschrittMelder? = null,
        abbruch: Abbruch? = null,
    ): String {
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
            // Hier ist die Stelle, an der die Wartezeit vergeht: Ein Block
            // von 4 MiB zerfaellt in rund neunzig solcher Abrufe. Wer hier
            // nichts meldet, laesst den Bildschirm die ganze Zeit "0 B"
            // zeigen -- und das sieht aus wie haengengeblieben.
            melde?.invoke(Fortschritt.Stueck(i + 1, teile, hinauf = false))
            // Und hier auch, aus demselben Grund wie oben: Ein Block von
            // 4 MiB sind rund neunzig Abrufe. Erst am Blockende zu fragen
            // hiesse, dass "Abbrechen" bis zu einer Minute lang nichts tut
            // -- und was nichts tut, drueckt der Anwender wieder und wieder.
            abbruch.pruefe()
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


/* ------------------------------------------------------------- Abbruch */

/**
 * Ein Vorgang, den der Anwender abbrechen kann.
 *
 * WARUM EIN RUECKRUF UND NICHT DIE KOROUTINE
 * -------------------------------------------
 * Dieser Kern ist bewusst frei von Android und von Koroutinen -- er laeuft
 * genauso in einem gewoehnlichen JVM-Test. Ein `job.cancel()` haette hier
 * ohnehin nichts ausgerichtet: Die Uebertragung steckt in blockierenden
 * Lesevorgaengen, und Koroutinen brechen nur an Aussetzpunkten ab.
 *
 * WO GEFRAGT WIRD, UND WARUM UEBERALL
 * ------------------------------------
 * Zuerst nur zwischen den Bloecken -- das war zu selten. Ein Block sind
 * 4 MiB, und am 08.09.2026 sah das auf dem Geraet so aus: Druecken bei
 * 2,4 MB, und bis genau 4,0 MB geschah nichts. Der Anwender drueckt dann
 * wieder, und wieder, denn ein Knopf ohne Wirkung ist ein kaputter Knopf.
 *
 * Gefragt wird deshalb an vier Stellen. Alle vier hinterlassen nichts
 * Halbes -- nur etwas Liegengebliebenes, das der Vermittler wegraeumt:
 *
 * | Stelle                    | was liegen bleibt         | Frist       |
 * |---------------------------|---------------------------|-------------|
 * | zwischen den Bloecken     | nichts                    | --          |
 * | Frage hinauf, je Stueck   | unsichtbare Teilfrage     | MARKE_TTL   |
 * | Warten auf den Agenten    | Antwort ohne Abholer      | ANTWORT_TTL |
 * | Antwort herunter, je St.  | der Rest der Antwort      | ANTWORT_TTL |
 *
 * GENAU GENOMMEN raeumt er es beim NAECHSTEN zustandsaendernden Zugriff,
 * der nach Ablauf der Frist kommt -- der Sammler haengt in `relay.php` an
 * `zustand_aendern()`, nicht an einer Uhr. `selbsttest` raeumt nicht, und
 * das Pollen auch nicht: Es liest `warteschlange.json` statisch, ohne
 * `relay.php` ueberhaupt anzufassen. Nach einem Abbruch kann also eine
 * abgelaufene Antwort noch eine Weile in `wartet_auf_abholung` stehen --
 * am 08.09.2026 nachgesehen und genau so vorgefunden. Sie verschwindet,
 * sobald wieder jemand etwas fragt.
 *
 * Genau dieselbe Lage entsteht, wenn die App abstuerzt oder das Netz
 * wegbricht. Dafuer wirkt "Abbrechen" jetzt innerhalb eines Stueckes statt
 * innerhalb eines Blocks.
 */
fun interface Abbruch {
    /** true heisst: der Anwender will nicht mehr. */
    fun gewuenscht(): Boolean
}

internal fun Abbruch?.pruefe() {
    if (this != null && gewuenscht()) {
        throw AhptFehler("Abgebrochen.", Fehlerart.Abgebrochen)
    }
}
