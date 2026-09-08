/*
 * Modell.kt -- der Zustand der App und was ihn aendert
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * Der Kern (`:kern`) ist blockierend gebaut -- absichtlich, damit er sich
 * ohne Geraet pruefen laesst. Die Nebenlaeufigkeit steht deshalb hier: jeder
 * Vorgang laeuft auf einem eigenen Faden, und die Oberflaeche sieht nur den
 * Zustand.
 */
package de.innobytix.ahpt

import android.app.Application
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.innobytix.ahpt.kern.AhptClient
import de.innobytix.ahpt.kern.BLOCK
import de.innobytix.ahpt.kern.AhptFehler
import de.innobytix.ahpt.kern.Fehlerart
import de.innobytix.ahpt.kern.Fortschritt
import de.innobytix.ahpt.kern.Quelle
import de.innobytix.ahpt.kern.hole
import de.innobytix.ahpt.kern.lege
import de.innobytix.ahpt.kern.liste
import de.innobytix.ahpt.kern.neuerOrdner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.InputStream

data class Eintrag(val name: String, val istOrdner: Boolean, val bytes: Long?)

data class Meldung(
    val text: String,
    val schlimm: Boolean = false,
    /** Wenn gesetzt: Die Meldung bietet an, diese Datei zu oeffnen. */
    val oeffnen: Uri? = null,
    val oeffnenName: String = "",
)

/**
 * Eine laufende Uebertragung -- alles, was der Bildschirm darueber sagen soll.
 *
 * WARUM DAS NEBEN `fortschritt` STEHT UND IHN NICHT ERSETZT
 * ----------------------------------------------------------
 * Der Kern meldet EINEN Fortschritt, und der wechselt die Bedeutung: Erst
 * `Summe` (Pruefsumme der eigenen Datei), dann `Hoch` (Block soundso), und
 * zwischendurch `Warten` (der Agent hat noch nicht geantwortet). Wer nur den
 * letzten Wert anzeigt, verliert bei jedem `Warten` die Blockzahl -- der
 * Balken springt dann auf unbestimmt zurueck.
 *
 * Hier bleibt deshalb BEIDES stehen: der Stand in Bytes, der nur waechst,
 * und daneben die Phase, die sich aendern darf.
 */
data class Transfer(
    val hinauf: Boolean,
    val name: String,
    val phase: String,
    val getan: Long = 0,
    val gesamt: Long = 0,
    /** Als der erste Fortschritt kam -- nicht als der Vorgang begann. */
    val gemessenAb: Long = 0,
    val gemessenAbBytes: Long = 0,
    val jetzt: Long = 0,
    /**
     * Was durch ABGESCHLOSSENE Bloecke schon sicher steht.
     *
     * Die Stueckmeldungen beziehen sich immer auf den laufenden Block, nie
     * auf die ganze Datei. Ohne diesen Bezugspunkt muesste man sie entweder
     * ignorieren -- dann steht der Balken bei einer 4-MiB-Datei minutenlang
     * still -- oder auf das Ganze beziehen, und dann springt er bei jedem
     * Blockwechsel zurueck. Mit ihm gehen beide zusammen.
     */
    val basis: Long = 0,
) {
    val anteil: Float? get() = if (gesamt > 0) (getan.toFloat() / gesamt) else null

    /**
     * Geschaetzte Restzeit in Sekunden, oder null.
     *
     * Gemessen wird ab dem ERSTEN Fortschritt, nicht ab dem Start: Davor
     * liegen Handschlag und Pruefsumme, und die verzerren die Rate so stark,
     * dass die erste Schaetzung sonst um ein Vielfaches danebenliegt.
     *
     * Erst ab einer Sekunde und ab 1 % -- vorher ist jede Hochrechnung
     * geraten, und eine Zahl, die von 40 Minuten auf 20 Sekunden springt,
     * ist schlechter als keine.
     */
    val restSekunden: Long?
        get() {
            val dauer = (jetzt - gemessenAb) / 1000.0
            val bytes = getan - gemessenAbBytes
            if (gesamt <= 0 || dauer < 1.0 || bytes <= 0) return null
            if (getan.toDouble() / gesamt < 0.01) return null
            val rate = bytes / dauer
            return ((gesamt - getan) / rate).toLong().coerceAtMost(99 * 3600)
        }
}

data class Zustand(
    val eingerichtet: Boolean = false,
    val pfad: String = "",
    val eintraege: List<Eintrag> = emptyList(),
    val laedt: Boolean = false,
    val meldung: Meldung? = null,
    val fortschritt: Fortschritt? = null,
    /** Laeuft gerade eine Uebertragung? Dann zeigt die App einen Dialog. */
    val transfer: Transfer? = null,
    /* Eine Datei liegt bereit und soll SOFORT angezeigt werden.
     *
     * Das Modell kann keine fremde Anzeige starten -- dafuer braucht es
     * einen Zusammenhang, und der gehoert der Oberflaeche. Also legt es die
     * Adresse hier ab, die Oberflaeche sieht sie, oeffnet, und meldet sich
     * mit `oeffnenErledigt()` zurueck. Ohne das Zuruecksetzen oeffnete sich
     * die Datei bei jedem Neuzeichnen wieder. */
    val oeffneJetzt: Uri? = null,
    val oeffneName: String = "",
    /** Hinweise des Handlers, warum die Liste kuerzer sein kann als der Ordner. */
    val hinweis: String? = null,
    /* Die Einrichtungswerte stehen HIER und nicht nur im Speicher.
     *
     * Vorher las die Einrichtungsseite sie einmal beim Aufbau in ein
     * `remember` -- und zeigte danach unveraendert weiter, was beim Aufbau
     * galt. Nach einem Kopplungsvorgang stand dort "noch kein Schluessel",
     * obwohl gerade einer erzeugt worden war. Am 07.09.2026 beim ersten
     * Scan auf echter Hardware aufgefallen. */
    val basis: String = "",
    val agentHex: String = "",
    val eigenerHex: String = "",
)

class Modell(app: Application) : AndroidViewModel(app) {

    val speicher = Schluesselspeicher(app)

    private val _zustand = MutableStateFlow(Zustand(eingerichtet = speicher.eingerichtet))
    val zustand = _zustand.asStateFlow()

    /**
     * Laufende Nummer je Ansichtswechsel.
     *
     * Zwei Vorgaenge koennen sich ueberholen: Waehrend ein Hochladen laeuft
     * und danach die Liste nachzieht, kann der Nutzer laengst eine Ebene
     * hoeher sein. Dann setzt der langsamere Vorgang die Liste des ALTEN
     * Ordners unter den Titel des neuen -- und ein Klick auf einen Eintrag
     * baut daraus einen Pfad, den es nicht gibt. Am 07.09.2026 im Emulator
     * genau so aufgetreten, als Hochladen und Zurueckgehen zusammenfielen.
     *
     * Wer den Zustand setzen will, muss die Nummer nennen, mit der er
     * gestartet ist. Stimmt sie nicht mehr, hat ihn jemand ueberholt, und
     * sein Ergebnis wird verworfen statt angezeigt.
     */
    private var ansichtNr = 0

    private fun client() = AhptClient(
        basis = speicher.basis,
        privat = speicher.privat(),
        agent = speicher.agent(),
    )

    init {
        lieseEinrichtung()
    }

    fun pruefeEinrichtung() = lieseEinrichtung()

    /** Den angezeigten Zustand mit dem Speicher gleichziehen. */
    fun lieseEinrichtung() {
        val eigener = runCatching { speicher.eigenerOeffentlicherHex() }.getOrDefault("")
        _zustand.update {
            it.copy(
                eingerichtet = speicher.eingerichtet,
                basis = speicher.basis,
                agentHex = speicher.agentHex,
                eigenerHex = eigener,
            )
        }
    }

    /** Adresse und Agentenschluessel von Hand uebernehmen. */
    fun uebernimm(basis: String, agentHex: String) {
        speicher.basis = basis
        speicher.agentHex = agentHex
        lieseEinrichtung()
    }

    fun erzeugeSchluessel() {
        speicher.erzeugeNeuenSchluessel()
        lieseEinrichtung()
    }

    fun melde(text: String, schlimm: Boolean = false,
              oeffnen: Uri? = null, oeffnenName: String = "") {
        _zustand.update {
            it.copy(meldung = Meldung(text, schlimm, oeffnen, oeffnenName))
        }
    }

    fun meldungWeg() = _zustand.update { it.copy(meldung = null) }

    /* ------------------------------------------------------------ Vorgaenge */

    /* ------------------------------------------------- Uebertragungen */

    /**
     * NUR EINE UEBERTRAGUNG ZUR ZEIT, und das ist keine Bequemlichkeit.
     *
     * Zwei gleichzeitige Vorgaenge teilen sich die Warteschlange des
     * Vermittlers (MAX_JE_IP) und die Bandbreite -- beide werden dadurch
     * langsamer, und beide melden Fortschritt in dasselbe Feld. Auf dem
     * Bildschirm sprang der Balken dann zwischen zwei Dateien hin und her.
     */
    @Volatile
    private var abbruchGewuenscht = false
    private val laeuftUebertragung = java.util.concurrent.atomic.AtomicBoolean(false)

    /** Der Anwender will nicht mehr. Wirkt zwischen zwei Bloecken. */
    fun brichAb() {
        abbruchGewuenscht = true
        _zustand.update {
            it.copy(transfer = it.transfer?.copy(phase = "Wird abgebrochen ..."))
        }
    }

    /**
     * Meldet den Fortschritt in den Transferzustand.
     *
     * Der Kern kennt drei Arten, und sie bedeuten Verschiedenes -- siehe
     * `Transfer`. `Warten` aendert NUR die Phase: Der Balken soll seinen
     * Stand behalten, statt bei jeder Wartezeit auf unbestimmt
     * zurueckzuspringen.
     */
    private fun melde(f: Fortschritt) {
        val nun = System.currentTimeMillis()
        _zustand.update { z ->
            val t = z.transfer ?: return@update z.copy(fortschritt = f)
            val neu = when (f) {
                is Fortschritt.Warten -> t.copy(
                    phase = if (t.hinauf) "Warte auf den Agenten ..."
                    else "Warte auf den Agenten ...", jetzt = nun)
                is Fortschritt.Summe -> t.copy(
                    phase = "Pruefsumme bilden", getan = f.getan,
                    gesamt = f.gesamt, jetzt = nun)
                is Fortschritt.Hoch -> {
                    // Bloecke in Bytes umrechnen, damit Balken und Restzeit
                    // dieselbe Groesse benutzen wie beim Herunterladen.
                    val b = if (f.gesamt > 0)
                        t.gesamt * f.getan / f.gesamt else t.getan
                    t.copy(phase = "Block ${f.getan} von ${f.gesamt}",
                           getan = b, basis = b, jetzt = nun)
                }
                is Fortschritt.Runter -> t.copy(
                    phase = "Wird geholt", getan = f.getan,
                    basis = f.getan, gesamt = f.gesamt, jetzt = nun)
                // Stuecke EINER Nachricht. Hier vergeht bei einer Datei
                // unter 4 MiB die gesamte Zeit -- sie ist dann ein einziger
                // Block, und `Runter` kommt erst, wenn er ganz durch ist.
                //
                // Der Balken darf davon aber nur profitieren, wenn die
                // Datei WIRKLICH in einen Block passt: Sonst waeren "37 von
                // 90" die Stuecke des laufenden Blocks, und die auf die
                // ganze Datei zu beziehen liesse den Balken bei jedem
                // Blockwechsel zurueckspringen.
                is Fortschritt.Stueck -> {
                    // Innerhalb des LAUFENDEN Blocks umrechnen, nicht auf
                    // die ganze Datei: Der Block reicht von `basis` bis
                    // hoechstens BLOCK weiter.
                    val spanne = minOf(BLOCK.toLong(), t.gesamt - t.basis)
                        .coerceAtLeast(0)
                    t.copy(
                        phase = "Stueck ${f.getan} von ${f.gesamt}",
                        getan = if (f.gesamt > 0 && spanne > 0)
                            t.basis + spanne * f.getan / f.gesamt else t.getan,
                        jetzt = nun)
                }
            }
            // Der Messpunkt fuer die Restzeit wird beim ERSTEN echten
            // Fortschritt gesetzt -- siehe Transfer.restSekunden.
            val gesetzt = if (neu.gemessenAb == 0L && neu.getan > 0)
                neu.copy(gemessenAb = nun, gemessenAbBytes = neu.getan) else neu
            z.copy(fortschritt = f, transfer = gesetzt)
        }
    }

    /**
     * Wie `vorgang`, nur mit Transferzustand, Abbruch und Einzelsperre.
     */
    private fun uebertragung(hinauf: Boolean, name: String, gesamt: Long,
                             was: suspend () -> Unit) {
        if (!laeuftUebertragung.compareAndSet(false, true)) {
            melde("Es laeuft schon eine Uebertragung. Erst die abwarten oder " +
                  "abbrechen -- zwei gleichzeitig machen beide langsamer.",
                  schlimm = true)
            return
        }
        abbruchGewuenscht = false
        _zustand.update {
            it.copy(meldung = null, transfer = Transfer(
                hinauf = hinauf, name = name,
                phase = if (hinauf) "Wird vorbereitet" else "Wird angefragt",
                gesamt = gesamt, jetzt = System.currentTimeMillis()))
        }
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { was() }
            } catch (e: AhptFehler) {
                if (e.art == Fehlerart.Abgebrochen) {
                    melde("\"$name\" abgebrochen. Nichts uebernommen.")
                } else {
                    melde(e.message ?: "Der Vorgang ist fehlgeschlagen.",
                          schlimm = true)
                }
            } catch (e: Exception) {
                melde("Unerwartet: ${e.message ?: e.javaClass.simpleName}",
                      schlimm = true)
            } finally {
                laeuftUebertragung.set(false)
                abbruchGewuenscht = false
                _zustand.update {
                    it.copy(transfer = null, fortschritt = null, laedt = false)
                }
            }
        }
    }

    /**
     * Jeder Vorgang laeuft nach demselben Muster: Ladeanzeige an, Arbeit auf
     * einem Hintergrundfaden, Fehler in eine Meldung uebersetzen. Ein
     * Vorgang, der still scheitert, ist schlimmer als einer, der gar nicht
     * erst laeuft -- deshalb faengt der `catch` hier alles, nicht nur
     * AhptFehler.
     */
    private fun vorgang(was: suspend () -> Unit) {
        viewModelScope.launch {
            _zustand.update { it.copy(laedt = true, meldung = null) }
            try {
                withContext(Dispatchers.IO) { was() }
            } catch (e: AhptFehler) {
                melde(e.message ?: "Der Vorgang ist fehlgeschlagen.", schlimm = true)
            } catch (e: AhptKopplungsFehler) {
                // Eigene Klasse, weil die Kopplung nicht zum Protokoll gehoert
                // -- aber genauso ein ERWARTETER Fall. Ohne diesen Zweig landet
                // sie im Auffangnetz darunter und bekommt "Unerwartet:" davor,
                // obwohl die Meldung genau sagt, was zu tun ist.
                melde(e.message ?: "Die Kopplung ist fehlgeschlagen.", schlimm = true)
            } catch (e: Exception) {
                melde("Unerwartet: ${e.message ?: e.javaClass.simpleName}", schlimm = true)
            } finally {
                _zustand.update { it.copy(laedt = false, fortschritt = null) }
            }
        }
    }

    fun lade(pfad: String = _zustand.value.pfad): Unit {
        val meine = ++ansichtNr
        vorgang { zeigeListe(pfad, meine) }
    }

    /**
     * Die Verbindung pruefen -- von HIER aus, wo das Geraet steht.
     *
     * Der Vermittlertest auf dem Rechner des Agenten misst die Strecke Agent
     * <-> Webspace. Die andere Haelfte -- Webspace <-> dieses Handy -- kann
     * er prinzipiell nicht sehen, und genau die spuert man unterwegs im
     * Mobilfunk. Gemessen wird mit einer ECHTEN Frage ueber den ganzen Weg,
     * nicht mit einem Sonderaufruf.
     */
    fun pruefeVerbindung() = vorgang {
        val z = client().messeVerbindung(_zustand.value.pfad)
        val umbruch = "\n"
        melde(
            "Ein vollstaendiger Vorgang ueber den ganzen Weg -- dieses Geraet, " +
                "Vermittler, Agent und zurueck -- hat " +
                "%.1f s gebraucht.".format(z.gesamtMs / 1000.0) +
                umbruch + umbruch +
                "Frage ablegen: ${z.frageMs} ms" + umbruch +
                "Warten auf den Agenten: ${z.wartenMs} ms " +
                "(${z.abrufe} Abfrage${if (z.abrufe == 1) "" else "n"})" + umbruch +
                "Antwort holen: ${z.holenMs} ms" + umbruch + umbruch +
                "Gemessen wird die Antwortzeit, nicht der Durchsatz -- eine " +
                "Auflistung ist klein. Ist dieser Wert gut und AHPT trotzdem " +
                "zaeh, liegt es nicht an der Strecke zu diesem Geraet.")
    }

    /**
     * Die Liste eines Ordners holen und anzeigen -- wenn wir noch dran sind.
     */
    private suspend fun zeigeListe(pfad: String, meine: Int) {
        val a = client().liste(pfad)
        if (meine != ansichtNr) return          // jemand war schneller
        val feld = a.optJSONArray("eintraege")
        val liste = buildList {
            for (i in 0 until (feld?.length() ?: 0)) {
                val o = feld!!.getJSONObject(i)
                add(Eintrag(
                    name = o.optString("name"),
                    istOrdner = o.optString("art") == "ordner",
                    bytes = if (o.has("bytes")) o.optLong("bytes") else null,
                ))
            }
        }.sortedWith(compareByDescending<Eintrag> { it.istOrdner }.thenBy { it.name.lowercase() })

        // Ohne diese Hinweise ist "der Ordner ist leer" nicht von "hier ist
        // alles gesperrt" zu unterscheiden.
        val hinweise = buildList {
            if (a.has("gekappt")) add("nur die ersten ${a.optInt("gekappt")} Eintraege")
            if (a.optInt("versteckt", 0) > 0) add("${a.optInt("versteckt")} versteckte")
            if (a.optInt("gefiltert", 0) > 0) add("${a.optInt("gefiltert")} nach Endung gesperrt")
        }
        _zustand.update {
            it.copy(
                pfad = pfad,
                eintraege = liste,
                hinweis = hinweise.takeIf { h -> h.isNotEmpty() }?.joinToString(", "),
            )
        }
    }

    /**
     * Einrichten aus einem Kopplungscode.
     *
     * Reihenfolge ist wichtig: erst die Adresse und der Agentenschluessel,
     * dann der eigene Schluessel, DANN die Rueckmeldung. Wer sich anmeldet,
     * bevor er weiss wohin, hat einen Schluessel beim Agenten liegen, der zu
     * nichts gehoert.
     */
    fun koppeln(rohQr: String, geraetename: String) = vorgang {
        val d = Kopplungsdaten.lies(rohQr)
        speicher.basis = d.basis
        speicher.agentHex = d.agentHex
        if (!speicher.hatSchluessel) speicher.erzeugeNeuenSchluessel()
        // Vor der Rueckmeldung nachziehen: Schlaegt die fehl, hat der Nutzer
        // trotzdem schon Adresse, Agentenschluessel und seinen eigenen
        // Schluessel vor sich -- und kann von Hand weitermachen, statt vor
        // einer Seite zu stehen, die so aussieht, als sei nichts passiert.
        lieseEinrichtung()
        val name = meldeBeimAssistenten(d, speicher.eigenerOeffentlicherHex(), geraetename)
        lieseEinrichtung()
        val meine = ++ansichtNr
        zeigeListe("", meine)
        melde("Gekoppelt als \"$name\". Der Agent laesst dieses Geraet jetzt zu.")
    }

    /**
     * Einrichten aus der Verbindungsdatei des Assistenten.
     *
     * Anders als beim Kopplungscode meldet sich das Geraet danach NICHT von
     * selbst an -- die Datei traegt kein Token. Deshalb bleibt die
     * Einrichtungsseite offen und die Meldung sagt, was noch fehlt, statt
     * so zu tun, als sei man fertig.
     */
    fun ladeVerbindungsdatei(quelle: Uri) = vorgang {
        val roh = getApplication<Application>().contentResolver
            .openInputStream(quelle)?.use { it.readBytes().toString(Charsets.UTF_8) }
            ?: throw AhptKopplungsFehler("Die Datei liess sich nicht oeffnen.")
        val v = Verbindungsdatei.lies(roh)
        speicher.basis = v.basis
        speicher.agentHex = v.agentHex
        if (!speicher.hatSchluessel) speicher.erzeugeNeuenSchluessel()
        lieseEinrichtung()
        melde(
            "Adresse und Agentenschluessel uebernommen. Es fehlt noch der " +
                    "Rueckweg: Der Schluessel dieses Geraets muss in die " +
                    "clients-Liste des Agenten -- unten kopieren und im " +
                    "Assistenten eintragen.",
        )
    }

    fun hinein(ordner: String) =
        lade(if (_zustand.value.pfad.isEmpty()) ordner else "${_zustand.value.pfad}/$ordner")

    fun hinauf() = lade(_zustand.value.pfad.substringBeforeLast('/', ""))

    fun ordnerAnlegen(name: String) = vorgang {
        val p = _zustand.value.pfad
        client().neuerOrdner(if (p.isEmpty()) name else "$p/$name")
        melde("Ordner \"$name\" angelegt.")
        zeigeListe(p, ansichtNr)
    }

    /**
     * Herunterladen direkt in das vom Nutzer gewaehlte Ziel.
     *
     * Der Strom geht Block fuer Block dorthin -- nichts sammelt sich im
     * Arbeitsspeicher an. Genau daran haengt der Unterschied zum Portal, das
     * die ganze Datei in EIN Feld legen muss.
     */
    fun holeNach(name: String, ziel: Uri, bytes: Long = 0) =
            uebertragung(hinauf = false, name = name, gesamt = bytes) {
        val p = _zustand.value.pfad
        val voll = if (p.isEmpty()) name else "$p/$name"
        val loeser = getApplication<Application>().contentResolver
        try {
            val e = loeser.openOutputStream(ziel)?.use { aus ->
                client().hole(voll, aus, { f -> melde(f) }, { abbruchGewuenscht })
            } ?: throw AhptFehler("Das Ziel liess sich nicht oeffnen.")
            // Mit Angebot zum Oeffnen. Eine geholte Datei, die man erst im
            // Dateimanager suchen muss, ist eine halb erledigte Aufgabe.
            melde(
                "\"${e.name}\" geholt (${lesbar(e.bytes)})" +
                        if (e.summeGeprueft) ", Pruefsumme stimmt." else ".",
                oeffnen = ziel, oeffnenName = e.name,
            )
        } catch (e: Throwable) {
            // Die halbe Datei wieder wegraeumen.
            //
            // Ohne das bleibt liegen, was bis zum Abbruch geschrieben wurde
            // -- im schlimmsten Fall null Bytes unter dem richtigen Namen,
            // und die sieht im Dateimanager aus wie eine Datei. Am
            // 07.09.2026 genau so gefunden: ein PDF mit 0 Bytes im
            // Downloads-Ordner, das niemand als Fehlschlag erkannt haette.
            //
            // Ein Loeschen, das selbst scheitert, darf den eigentlichen
            // Fehler nicht verdecken -- deshalb runCatching.
            runCatching { DocumentsContract.deleteDocument(loeser, ziel) }
            throw e
        }
    }


    /**
     * Eine Datei holen und gleich anzeigen lassen.
     *
     * WARUM IN DEN ZWISCHENSPEICHER UND NICHT IN DIE ABLAGE
     * ------------------------------------------------------
     * Wer nur hineinsehen will, will keine Datei behalten. Landete jede
     * Vorschau im Download-Ordner, saehe der nach einer Woche aus wie ein
     * Papierkorb -- und die Sachen, die man wirklich aufheben wollte, gingen
     * darin unter. Der Zwischenspeicher raeumt sich selbst, wenn der Platz
     * knapp wird.
     *
     * Wer die Datei behalten will, nimmt "Speichern unter". Das ist der
     * Unterschied, den die Auswahl beim Antippen anbietet.
     */
    fun oeffneVorschau(name: String, bytes: Long) =
            uebertragung(hinauf = false, name = name, gesamt = bytes) {
        val app = getApplication<Application>()
        val ordner = java.io.File(app.cacheDir, "vorschau")
        ordner.mkdirs()
        // Die vorige Vorschau weg. Sie hat ihren Zweck erfuellt, und zwei
        // Fassungen derselben Datei nebeneinander stiften nur Verwirrung --
        // besonders wenn sich die Datei auf dem Server geaendert hat.
        ordner.listFiles()?.forEach { runCatching { it.delete() } }

        val sicher = name.substringAfterLast('/').substringAfterLast('\\')
        val datei = java.io.File(ordner, sicher)
        val p = _zustand.value.pfad
        val voll = if (p.isEmpty()) name else "$p/$name"
        try {
            datei.outputStream().use { aus ->
                client().hole(voll, aus, { f -> melde(f) }, { abbruchGewuenscht })
            }
        } catch (e: Throwable) {
            // Eine halbe Datei anzuzeigen waere schlimmer als keine: Das
            // fremde Programm meldet dann "beschaedigt", und der Anwender
            // sucht den Fehler in seiner Datei statt in der Uebertragung.
            runCatching { datei.delete() }
            throw e
        }
        val u = androidx.core.content.FileProvider.getUriForFile(
            app, app.packageName + ".dateien", datei)
        _zustand.update { it.copy(oeffneJetzt = u, oeffneName = sicher) }
    }

    /** Die Oberflaeche hat geoeffnet -- den Wunsch zuruecksetzen. */
    fun oeffnenErledigt() =
        _zustand.update { it.copy(oeffneJetzt = null, oeffneName = "") }

    fun legeAb(quelle: Uri) {
        val app = getApplication<Application>()
        val name = dateiname(quelle) ?: "unbenannt"
        val groesse = dateigroesse(quelle) ?: 0L
        uebertragung(hinauf = true, name = name, gesamt = groesse) {
            legeAbIntern(quelle, app, name, groesse)
        }
    }

    private suspend fun legeAbIntern(quelle: Uri, app: Application,
                                     name: String, groesse: Long) {
        if (groesse <= 0L) {
            throw AhptFehler("Die Groesse der Datei liess sich nicht bestimmen.")
        }
        val p = _zustand.value.pfad
        val ziel = if (p.isEmpty()) name else "$p/$name"

        val q = object : Quelle {
            override val groesse = groesse
            override fun oeffne(): InputStream =
                app.contentResolver.openInputStream(quelle)
                    ?: throw AhptFehler("Die Datei liess sich nicht oeffnen.")
        }
        val a = client().lege(ziel, q, { f -> melde(f) }, { abbruchGewuenscht })
        // Ueberschrieben wird nie -- gibt es den Namen schon, zaehlt der
        // Agent hoch. Wer das verschweigt, laesst den Nutzer glauben, er habe
        // eine aeltere Fassung ersetzt.
        val abgelegt = a.optString("abgelegt")
        if (abgelegt.isNotEmpty() && abgelegt != ziel) {
            melde(
                "\"$name\" abgelegt als \"${abgelegt.substringAfterLast('/')}\" " +
                        "-- unter dem urspruenglichen Namen lag schon etwas. " +
                        "Ueberschrieben wird nie.",
            )
        } else {
            melde("\"$name\" abgelegt (${lesbar(groesse)}).")
        }
        zeigeListe(p, ansichtNr)
    }

    /* ------------------------------------------------------------ Werkzeug */

    private fun dateiname(u: Uri): String? =
        getApplication<Application>().contentResolver
            .query(u, null, null, null, null)?.use { c ->
                val i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (i >= 0 && c.moveToFirst()) c.getString(i) else null
            }

    private fun dateigroesse(u: Uri): Long? =
        getApplication<Application>().contentResolver
            .query(u, null, null, null, null)?.use { c ->
                val i = c.getColumnIndex(OpenableColumns.SIZE)
                if (i >= 0 && c.moveToFirst() && !c.isNull(i)) c.getLong(i) else null
            }
}

fun lesbar(b: Long): String = when {
    b < 1024 -> "$b B"
    b < 1024 * 1024 -> "%.1f KB".format(b / 1024.0)
    b < 1024L * 1024 * 1024 -> "%.1f MB".format(b / 1048576.0)
    else -> "%.2f GB".format(b / 1073741824.0)
}
