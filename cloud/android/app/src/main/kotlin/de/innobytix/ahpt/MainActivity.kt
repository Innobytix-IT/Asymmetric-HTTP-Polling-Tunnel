/*
 * MainActivity.kt -- die Oberflaeche
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * Zwei Bildschirme, mehr braucht es nicht: einrichten und Dateien. Das
 * Portal hat dieselben zwei, nur als eine Seite mit einem Umschalter.
 */
package de.innobytix.ahpt

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.MimeTypeMap
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import de.innobytix.ahpt.kern.Fortschritt

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AhptGestaltung { Rahmen() }
        }
    }
}

@Composable
private fun Rahmen(modell: Modell = viewModel()) {
    val z by modell.zustand.collectAsState()
    var zeigeEinrichtung by remember { mutableStateOf(!z.eingerichtet) }

    LaunchedEffect(z.eingerichtet) {
        if (z.eingerichtet && z.eintraege.isEmpty()) modell.lade("")
    }

    if (zeigeEinrichtung || !z.eingerichtet) {
        Einrichtung(modell, kannZurueck = z.eingerichtet) { zeigeEinrichtung = false }
    } else {
        Dateien(modell) { zeigeEinrichtung = true }
    }
}

/* ------------------------------------------------------------ Einrichtung */

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Einrichtung(modell: Modell, kannZurueck: Boolean, fertig: () -> Unit) {
    val ctx = LocalContext.current
    val z by modell.zustand.collectAsState()
    // Die Felder muessen tippbar bleiben, sollen aber nachziehen, wenn sich
    // der gespeicherte Wert aendert -- etwa nach einem Kopplungsvorgang.
    // Deshalb der Zustandswert als Schluessel: Aendert er sich, faengt das
    // Feld mit dem neuen Wert neu an.
    var basis by remember(z.basis) { mutableStateOf(z.basis) }
    var agent by remember(z.agentHex) { mutableStateOf(z.agentHex) }
    val eigener = z.eigenerHex
    var frageNeuerSchluessel by remember { mutableStateOf(false) }

    // Der Scanner kommt von ZXing und bringt seine eigene Ansicht mit, samt
    // Nachfrage nach der Kamera-Erlaubnis. `contents` ist null, wenn der
    // Nutzer abbricht -- das ist kein Fehler und wird still uebergangen.
    val scanner = rememberLauncherForActivityResult(ScanContract()) { ergebnis ->
        ergebnis.contents?.let { modell.koppeln(it, android.os.Build.MODEL ?: "Handy") }
    }

    // Der zweite Weg: die Verbindungsdatei des Assistenten. Sie braucht
    // weder Kamera noch gemeinsames Netz -- sie kommt notfalls per USB-Kabel
    // in den Download-Ordner. Dasselbe, was das Portal im Browser kann.
    val dateiWaehler = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri: Uri? -> uri?.let { modell.ladeVerbindungsdatei(it) } }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Einrichtung") },
                navigationIcon = {
                    if (kannZurueck) IconButton(onClick = fertig) {
                        Icon(Icons.Default.ArrowBack, "Zurueck")
                    }
                },
            )
        },
    ) { pad ->
        Column(
            Modifier.padding(pad).padding(16.dp).fillMaxSize()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            // Meldungen stehen OBEN. Vorher standen sie ganz unten vor dem
            // Uebernehmen-Knopf -- wer eine falsche Datei laedt, muss dann
            // erst scrollen, um zu erfahren warum nichts passiert ist.
            z.meldung?.let { m ->
                Surface(
                    color = if (m.schlimm) MaterialTheme.colorScheme.errorContainer
                    else MaterialTheme.colorScheme.secondaryContainer,
                    shape = MaterialTheme.shapes.small,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(m.text, Modifier.weight(1f),
                             style = MaterialTheme.typography.bodySmall)
                        TextButton(onClick = { modell.meldungWeg() }) { Text("OK") }
                    }
                }
            }

            Card {
                Column(
                    Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("Schnellster Weg: koppeln",
                         style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Auf dem Rechner den Einrichtungs-Assistenten oeffnen, " +
                                "dort \"Weiteres Geraet hinzufuegen\" waehlen und den " +
                                "angezeigten Code abfotografieren. Adresse und " +
                                "Schluessel kommen dann von selbst, und dieses Geraet " +
                                "meldet sich beim Agenten an.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Button(
                        onClick = {
                            scanner.launch(ScanOptions().apply {
                                setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                                setPrompt("Kopplungscode des Assistenten abfotografieren")
                                setBeepEnabled(false)
                                setOrientationLocked(false)
                            })
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Default.QrCodeScanner, null)
                        Spacer(Modifier.width(8.dp))
                        Text("Code abfotografieren")
                    }
                    Text(
                        "Beide Geraete muessen dafuer im selben Netz sein -- gleiches " +
                                "WLAN, oder Handy per USB anschliessen und dort " +
                                "USB-Tethering einschalten.",
                        style = MaterialTheme.typography.bodySmall,
                    )

                    HorizontalDivider()

                    Text(
                        "Ohne Kamera oder ohne gemeinsames Netz: die " +
                                "Verbindungsdatei aus dem Assistenten laden. Sie darf " +
                                "auch per USB-Kabel in den Download-Ordner gelegt " +
                                "werden. Der eigene Schluessel muss dann von Hand zum " +
                                "Agenten.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    OutlinedButton(
                        onClick = {
                            dateiWaehler.launch(arrayOf("application/json", "*/*"))
                        },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Default.FileOpen, null)
                        Spacer(Modifier.width(8.dp))
                        Text("Verbindungsdatei laden")
                    }
                }
            }

            HorizontalDivider()
            Text("Oder von Hand", style = MaterialTheme.typography.titleMedium)

            OutlinedTextField(
                value = basis, onValueChange = { basis = it },
                label = { Text("Adresse des Vermittlers") },
                placeholder = { Text("http://beispiel.example/ahpt") },
                supportingText = { Text("Das Verzeichnis, in dem relay.php liegt.") },
                singleLine = true, modifier = Modifier.fillMaxWidth(),
            )

            OutlinedTextField(
                value = agent, onValueChange = { agent = it },
                label = { Text("Oeffentlicher Schluessel des Agenten") },
                supportingText = {
                    Text(
                        "64 Hexzeichen, aus der Startausgabe des Agenten. Von Hand " +
                                "uebertragen -- niemals ueber den Vermittler: Was dort " +
                                "liegt, kann der Hoster austauschen.",
                    )
                },
                modifier = Modifier.fillMaxWidth(),
            )

            HorizontalDivider()

            Text("Der Schluessel dieses Geraets", style = MaterialTheme.typography.titleMedium)
            if (eigener.isEmpty()) {
                Text(
                    "Noch keiner erzeugt. Er entsteht auf diesem Geraet und " +
                            "verlaesst es nicht -- er liegt verschluesselt im " +
                            "Android-Schluesselspeicher.",
                    style = MaterialTheme.typography.bodySmall,
                )
                Button(onClick = { modell.erzeugeSchluessel() }) {
                    Text("Schluessel erzeugen")
                }
            } else {
                Card {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            eigener, fontFamily = FontFamily.Monospace,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(onClick = {
                                val cb = ctx.getSystemService(Context.CLIPBOARD_SERVICE)
                                        as ClipboardManager
                                cb.setPrimaryClip(ClipData.newPlainText("AHPT", eigener))
                                modell.melde("Schluessel kopiert.")
                            }) { Text("Kopieren") }
                            TextButton(onClick = { frageNeuerSchluessel = true }) {
                                Text("Neu erzeugen")
                            }
                        }
                    }
                }
                Text(
                    "Dieser oeffentliche Teil gehoert in die clients-Liste des " +
                            "Agenten. Ohne ihn dort weist er jede Frage ab.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }

            Spacer(Modifier.height(8.dp))

            Button(
                onClick = {
                    modell.uebernimm(basis, agent)
                    if (modell.speicher.eingerichtet) { modell.lade(""); fertig() }
                    else modell.melde(
                        "Es fehlt noch etwas: Adresse, Agentenschluessel oder " +
                                "der eigene Schluessel.", schlimm = true,
                    )
                },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Uebernehmen") }
        }
    }

    if (frageNeuerSchluessel) {
        AlertDialog(
            onDismissRequest = { frageNeuerSchluessel = false },
            title = { Text("Neuen Schluessel erzeugen?") },
            text = {
                Text(
                    "Ein NEUER macht die bisherige Paarung ungueltig: Der Agent " +
                            "kennt nur den alten oeffentlichen Teil und wuerde diese " +
                            "App danach abweisen, bis du den neuen dort eingetragen " +
                            "hast.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    modell.erzeugeSchluessel()
                    frageNeuerSchluessel = false
                }) { Text("Erzeugen") }
            },
            dismissButton = {
                TextButton(onClick = { frageNeuerSchluessel = false }) { Text("Abbrechen") }
            },
        )
    }
}

/* ---------------------------------------------------------------- Dateien */

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Dateien(modell: Modell, zurEinrichtung: () -> Unit) {
    val z by modell.zustand.collectAsState()
    var neuerOrdner by remember { mutableStateOf(false) }
    var holeName by remember { mutableStateOf<String?>(null) }
    var holeBytes by remember { mutableStateOf(0L) }
    var wahlFuer by remember { mutableStateOf<Eintrag?>(null) }
    val zusammenhang = LocalContext.current

    val waehleQuelle = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri: Uri? -> uri?.let { modell.legeAb(it) } }

    val waehleZiel = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/octet-stream"),
    ) { uri: Uri? ->
        val n = holeName
        if (uri != null && n != null) modell.holeNach(n, uri, holeBytes)
        holeName = null
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        if (z.pfad.isEmpty()) "AHPT Cloud" else z.pfad,
                        maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    if (z.pfad.isNotEmpty()) IconButton(onClick = { modell.hinauf() }) {
                        Icon(Icons.Default.ArrowBack, "Eine Ebene hoeher")
                    }
                },
                actions = {
                    // Die Verbindung von HIER aus messen. Der Test auf dem
                    // Rechner des Agenten sieht die Strecke hierher nicht --
                    // dort steht er nicht, und genau die spuert man
                    // unterwegs im Mobilfunk.
                    IconButton(onClick = { modell.pruefeVerbindung() }) {
                        Icon(Icons.Default.NetworkCheck, "Verbindung pruefen")
                    }
                    IconButton(onClick = { modell.lade() }) {
                        Icon(Icons.Default.Refresh, "Neu laden")
                    }
                    IconButton(onClick = { neuerOrdner = true }) {
                        Icon(Icons.Default.CreateNewFolder, "Neuer Ordner")
                    }
                    IconButton(onClick = zurEinrichtung) {
                        Icon(Icons.Default.Settings, "Einrichtung")
                    }
                },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { waehleQuelle.launch(arrayOf("*/*")) },
                icon = { Icon(Icons.Default.Upload, null) },
                text = { Text("Hochladen") },
            )
        },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {

            // Der Fortschritt steht OBEN und bleibt stehen. Im Portal stand er
            // zwischen Werkzeugleiste und Liste und scrollte weg -- am
            // 06.09.2026 geaendert, hier gleich richtig.
            // Waehrend einer Uebertragung uebernimmt der Dialog. Beides
            // gleichzeitig waere doppelt gemoppelt, und der duenne Balken
            // unter dem Titel war genau das, was niemandem etwas sagte.
            if (z.transfer == null) {
                z.fortschritt?.let { FortschrittBalken(it) }
                if (z.laedt && z.fortschritt == null) {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                }
            }

            z.meldung?.let { m ->
                Surface(
                    color = if (m.schlimm) MaterialTheme.colorScheme.errorContainer
                    else MaterialTheme.colorScheme.secondaryContainer,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(m.text, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                        // Eine geholte Datei, die man erst im Dateimanager
                        // suchen muss, ist eine halb erledigte Aufgabe.
                        m.oeffnen?.let { u ->
                            TextButton(onClick = {
                                oeffneDatei(zusammenhang, u, m.oeffnenName)
                                    ?.let { modell.melde(it, schlimm = true) }
                            }) { Text("Oeffnen") }
                        }
                        TextButton(onClick = { modell.meldungWeg() }) { Text("OK") }
                    }
                }
            }

            z.hinweis?.let {
                Text(
                    "Nicht alles gezeigt: $it",
                    Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                    style = MaterialTheme.typography.bodySmall,
                )
            }

            if (z.eintraege.isEmpty() && !z.laedt) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("Hier liegt nichts.", style = MaterialTheme.typography.bodyMedium)
                }
            }

            LazyColumn(
                Modifier.fillMaxSize(),
                // Platz fuer den Hochladen-Knopf. Ohne das verdeckt er den
                // letzten Eintrag vollstaendig -- die Datei ist dann weder
                // zu sehen noch anzutippen. Am 07.09.2026 beim ersten
                // Durchstich gegen den echten Agenten aufgefallen.
                contentPadding = PaddingValues(bottom = 88.dp),
            ) {
                items(z.eintraege, key = { it.name }) { e ->
                    ListItem(
                        headlineContent = { Text(e.name) },
                        supportingContent = e.bytes?.let { { Text(lesbar(it)) } },
                        leadingContent = {
                            Icon(
                                if (e.istOrdner) Icons.Default.Folder
                                else Icons.Default.InsertDriveFile,
                                null,
                            )
                        },
                        trailingContent = if (!e.istOrdner) {
                            {
                                IconButton(onClick = {
                                    holeName = e.name
                                    holeBytes = e.bytes ?: 0L
                                    waehleZiel.launch(e.name)
                                }) { Icon(Icons.Default.Download, "Herunterladen") }
                            }
                        } else null,
                        // Antippen fragt, statt gleich zu speichern.
                        //
                        // Vorher fuehrte jeder Fingertipp geradewegs in den
                        // Dokumentenwaehler -- wer nur kurz in ein Foto oder
                        // ein Schreiben sehen wollte, musste es erst
                        // irgendwohin ablegen und dann selbst wiederfinden.
                        modifier = Modifier.clickable {
                            if (e.istOrdner) modell.hinein(e.name)
                            else wahlFuer = e
                        },
                    )
                    HorizontalDivider()
                }
            }
        }
    }

    z.transfer?.let { t ->
        UebertragungsDialog(t) { modell.brichAb() }
    }

    // Was soll mit der angetippten Datei geschehen?
    wahlFuer?.let { e ->
        AlertDialog(
            onDismissRequest = { wahlFuer = null },
            title = { Text(e.name) },
            text = {
                Text(
                    "Ansehen holt die Datei in den Zwischenspeicher und "
                        + "uebergibt sie einem Programm auf diesem Geraet. "
                        + "Speichern legt sie dorthin, wo du sie behalten "
                        + "willst."
                        + (e.bytes?.let { "\n\nGroesse: " + lesbar(it) } ?: ""),
                    style = MaterialTheme.typography.bodySmall,
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    modell.oeffneVorschau(e.name, e.bytes ?: 0L)
                    wahlFuer = null
                }) { Text("Ansehen") }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = { wahlFuer = null }) { Text("Abbrechen") }
                    TextButton(onClick = {
                        holeName = e.name
                        holeBytes = e.bytes ?: 0L
                        waehleZiel.launch(e.name)
                        wahlFuer = null
                    }) { Text("Speichern") }
                }
            },
        )
    }

    // Eine Vorschau liegt bereit -- anzeigen und den Wunsch zuruecksetzen.
    LaunchedEffect(z.oeffneJetzt) {
        val u = z.oeffneJetzt ?: return@LaunchedEffect
        oeffneDatei(zusammenhang, u, z.oeffneName)?.let {
            modell.melde(it, schlimm = true)
        }
        modell.oeffnenErledigt()
    }

    if (neuerOrdner) {
        var name by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { neuerOrdner = false },
            title = { Text("Neuer Ordner") },
            text = {
                OutlinedTextField(
                    value = name, onValueChange = { name = it },
                    label = { Text("Name") }, singleLine = true,
                )
            },
            confirmButton = {
                TextButton(
                    onClick = { modell.ordnerAnlegen(name.trim()); neuerOrdner = false },
                    enabled = name.isNotBlank(),
                ) { Text("Anlegen") }
            },
            dismissButton = {
                TextButton(onClick = { neuerOrdner = false }) { Text("Abbrechen") }
            },
        )
    }
}

@Composable
private fun FortschrittBalken(f: Fortschritt) {
    val (text, anteil) = when (f) {
        is Fortschritt.Warten -> "Warte auf den Agenten..." to null
        is Fortschritt.Hoch -> "Hochladen: ${f.getan} von ${f.gesamt}" to
                (f.getan.toFloat() / f.gesamt)
        is Fortschritt.Runter -> "Holen: ${lesbar(f.getan)} von ${lesbar(f.gesamt)}" to
                (if (f.gesamt > 0) f.getan.toFloat() / f.gesamt else null)
        is Fortschritt.Summe -> "Pruefsumme: ${lesbar(f.getan)} von ${lesbar(f.gesamt)}" to
                (if (f.gesamt > 0) f.getan.toFloat() / f.gesamt else null)
        is Fortschritt.Stueck -> "Stueck ${f.getan} von ${f.gesamt}" to
                (if (f.gesamt > 0) f.getan.toFloat() / f.gesamt else null)
    }
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text(text, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(4.dp))
        if (anteil != null) {
            LinearProgressIndicator(progress = { anteil }, modifier = Modifier.fillMaxWidth())
        } else {
            LinearProgressIndicator(Modifier.fillMaxWidth())
        }
    }
}


/* ------------------------------------------------- Uebertragungsdialog */

/**
 * Was waehrend einer Uebertragung auf dem Bildschirm steht.
 *
 * WARUM EIN DIALOG UND NICHT NUR EIN BALKEN
 * ------------------------------------------
 * Vorher stand unter dem Titel eine Zeile wie "Pruefsumme: 8,2 MB von
 * 8,2 MB" -- und danach passierte minutenlang sichtbar nichts. Der Grund
 * ist harmlos: Nach der Pruefsumme geht der erste Block hinaus, und ein
 * Block ist ein vollstaendiger Umlauf ueber den Vermittler. Nur sah man das
 * nicht, und was man nicht sieht, haelt man fuer haengengeblieben.
 *
 * Der Dialog sagt deshalb dreierlei gleichzeitig: WAS gerade laeuft (die
 * Phase), WIE WEIT (Balken und Prozent), und WIE LANGE NOCH. Und er hat
 * einen Abbruch -- eine Uebertragung, die man nur durch Beenden der App
 * loswird, ist keine.
 *
 * Er ist absichtlich NICHT wegtippbar (`onDismissRequest` tut nichts): Wer
 * ihn versehentlich schliesst, waehrend acht Megabyte laufen, haette keinen
 * Weg zurueck zum Abbruch.
 */
@Composable
private fun UebertragungsDialog(t: Transfer, aufAbbruch: () -> Unit) {
    // Eigene Uhr, damit die Restzeit LAEUFT.
    //
    // Der Zustand aendert sich nur, wenn ein Fortschritt hereinkommt -- und
    // zwischen zwei Bloecken vergeht bei grossen Dateien eine Minute. Ohne
    // diesen Takt stuende dieselbe Zahl die ganze Zeit da, und genau das
    // sieht wieder nach Stillstand aus.
    var nun by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            kotlinx.coroutines.delay(1000)
            nun = System.currentTimeMillis()
        }
    }
    // Wie lange schon nichts mehr hereinkam.
    //
    // Das ist KEINE Schaetzung, sondern eine Messung: `t.jetzt` ist der
    // Zeitpunkt der letzten Fortschrittsmeldung. Deshalb darf diese Zahl
    // etwas behaupten, wo die Restzeit es laengst nicht mehr darf.
    val stille = (nun - t.jetzt) / 1000
    val rest = t.restSekunden?.let { (it - stille).coerceAtLeast(0) }

    AlertDialog(
        onDismissRequest = { },
        icon = { CircularProgressIndicator(Modifier.size(28.dp)) },
        title = { Text(if (t.hinauf) "Wird hochgeladen" else "Wird geholt") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(t.name, style = MaterialTheme.typography.bodyMedium)
                Text(t.phase, style = MaterialTheme.typography.bodySmall)

                val anteil = t.anteil
                if (anteil != null) {
                    LinearProgressIndicator(
                        progress = { anteil }, modifier = Modifier.fillMaxWidth())
                } else {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                }

                Row(Modifier.fillMaxWidth()) {
                    Text(
                        if (t.gesamt > 0)
                            "${lesbar(t.getan)} von ${lesbar(t.gesamt)}"
                        else "Groesse noch unbekannt",
                        Modifier.weight(1f),
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Text(
                        when {
                            // Nach dem Druck auf Abbrechen sagt eine
                            // Restzeit nichts mehr: Sie rechnet das Ende
                            // einer Uebertragung aus, die gar nicht mehr
                            // ans Ende kommen soll.
                            t.abbruch -> ""
                            // Schweigt es zu lange, hat die Schaetzung
                            // ausgedient -- dann zaehlt, was gemessen ist.
                            // Vorher zaehlte die Restzeit stur bis Null und
                            // blieb dort stehen: "noch 0 s", waehrend sich
                            // nichts mehr ruehrte. Genau das Bild von
                            // Stillstand, gegen das dieser Dialog gebaut
                            // wurde.
                            stille >= STILL_AB -> "seit ${lesbareDauer(stille)} still"
                            rest != null && rest > 0 -> "noch ${lesbareDauer(rest)}"
                            // Die Schaetzung ist aufgebraucht, es kommt aber
                            // noch etwas an. Keine Zahl mehr behaupten.
                            rest != null -> "gleich fertig"
                            // Solange nichts Belastbares da ist, wird auch
                            // nichts behauptet. Eine Schaetzung, die von 40
                            // Minuten auf 20 Sekunden springt, ist
                            // schlechter als gar keine. Kurz gehalten: Der
                            // Byte-Stand daneben brach sonst um.
                            else -> "Restzeit offen"
                        },
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        },
        confirmButton = {
            // Nach dem ersten Druck ist der Wunsch gesetzt; jeder weitere
            // liefe ins Leere. Ein Knopf, der noch drueckbar aussieht, aber
            // nichts mehr bewirkt, ist genau der Knopf, den man wieder und
            // wieder drueckt -- deshalb wird er hier still.
            TextButton(onClick = aufAbbruch, enabled = !t.abbruch) {
                Text(if (t.abbruch) "Wird beendet" else "Abbrechen")
            }
        },
    )
}

/**
 * Ab wann Schweigen erwaehnenswert ist.
 *
 * Zwanzig Sekunden, nicht zehn. Waehrend des Wartens meldet der Client bei
 * jedem Abruf (hoechstens 1,5 s Abstand), und beim Holen vor jedem Stueck
 * -- Schweigen entsteht also nur, wenn ein einzelner Abruf lange braucht.
 * Ein Stueck von 48 KiB ueber eine schlechte Mobilfunkstrecke kann gut
 * dreizehn Sekunden dauern, und das ist kein Fehler, sondern langsam. Erst
 * jenseits davon ist die Stille eine Auskunft.
 */
private const val STILL_AB = 20L

/**
 * Sekunden in etwas, das man lesen kann.
 *
 * Keine Nachkommastellen und keine Stunden mit Sekunden: Bei einer
 * Schaetzung taeuscht jede zusaetzliche Stelle eine Genauigkeit vor, die
 * sie nicht hat.
 */
private fun lesbareDauer(s: Long): String = when {
    s < 60 -> "$s s"
    s < 3600 -> "${s / 60} min ${s % 60} s"
    else -> "${s / 3600} h ${(s % 3600) / 60} min"
}


/* ------------------------------------------------------ Datei oeffnen */

/**
 * Eine geholte Datei dem Geraet zum Anzeigen geben.
 *
 * WARUM KEINE EIGENE VORSCHAU
 * ----------------------------
 * Eine eingebaute Anzeige koennte Bilder. Sie koennte kein PDF, kein docx,
 * kein Video, keine Tabelle -- und genau das sind die Dateien, die man
 * unterwegs aufmachen will. Das Geraet hat fuer all das schon Programme,
 * und die kennt der Anwender.
 *
 * Der Preis ist ehrlich zu nennen: Die Datei verlaesst damit AHPT. Was das
 * fremde Programm damit tut -- in eine Wolke sichern etwa -- liegt nicht
 * mehr in unserer Hand. Deshalb passiert es nur auf ausdruecklichen Wunsch
 * und nie von selbst.
 *
 * `FLAG_GRANT_READ_URI_PERMISSION` ist noetig, weil die Adresse aus dem
 * Dokumentenwaehler kommt: Ohne die Freigabe darf das andere Programm sie
 * nicht lesen und zeigt eine leere Seite statt einer Fehlermeldung.
 */
private fun oeffneDatei(zusammenhang: Context, u: Uri, name: String): String? {
    val endung = name.substringAfterLast('.', "").lowercase()
    val typ = MimeTypeMap.getSingleton().getMimeTypeFromExtension(endung)
        ?: zusammenhang.contentResolver.getType(u)
        ?: "*/*"
    val absicht = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(u, typ)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    return try {
        zusammenhang.startActivity(absicht)
        null
    } catch (e: ActivityNotFoundException) {
        // Kein Programm dafuer. Das ist keine Panne, sondern eine Auskunft
        // -- und sie gehoert auf den Bildschirm, nicht ins Log.
        "Auf diesem Geraet ist kein Programm fuer \"$name\" ($typ) " +
            "eingerichtet. Die Datei liegt aber, wo du sie hingelegt hast."
    }
}
