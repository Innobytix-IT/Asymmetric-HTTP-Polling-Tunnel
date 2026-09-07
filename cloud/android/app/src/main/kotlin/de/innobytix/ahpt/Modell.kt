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
import de.innobytix.ahpt.kern.AhptFehler
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

data class Meldung(val text: String, val schlimm: Boolean = false)

data class Zustand(
    val eingerichtet: Boolean = false,
    val pfad: String = "",
    val eintraege: List<Eintrag> = emptyList(),
    val laedt: Boolean = false,
    val meldung: Meldung? = null,
    val fortschritt: Fortschritt? = null,
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

    fun melde(text: String, schlimm: Boolean = false) {
        _zustand.update { it.copy(meldung = Meldung(text, schlimm)) }
    }

    fun meldungWeg() = _zustand.update { it.copy(meldung = null) }

    /* ------------------------------------------------------------ Vorgaenge */

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
    fun holeNach(name: String, ziel: Uri) = vorgang {
        val p = _zustand.value.pfad
        val voll = if (p.isEmpty()) name else "$p/$name"
        val loeser = getApplication<Application>().contentResolver
        try {
            val e = loeser.openOutputStream(ziel)?.use { aus ->
                client().hole(voll, aus) { f ->
                    _zustand.update { it.copy(fortschritt = f) }
                }
            } ?: throw AhptFehler("Das Ziel liess sich nicht oeffnen.")
            melde(
                "\"${e.name}\" geholt (${lesbar(e.bytes)})" +
                        if (e.summeGeprueft) ", Pruefsumme stimmt." else ".",
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

    fun legeAb(quelle: Uri) = vorgang {
        val app = getApplication<Application>()
        val name = dateiname(quelle) ?: "unbenannt"
        val groesse = dateigroesse(quelle)
            ?: throw AhptFehler("Die Groesse der Datei liess sich nicht bestimmen.")
        val p = _zustand.value.pfad
        val ziel = if (p.isEmpty()) name else "$p/$name"

        val q = object : Quelle {
            override val groesse = groesse
            override fun oeffne(): InputStream =
                app.contentResolver.openInputStream(quelle)
                    ?: throw AhptFehler("Die Datei liess sich nicht oeffnen.")
        }
        val a = client().lege(ziel, q) { f ->
            _zustand.update { it.copy(fortschritt = f) }
        }
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
