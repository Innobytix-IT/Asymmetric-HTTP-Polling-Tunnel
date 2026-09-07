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

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.net.Uri
import android.os.Bundle
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

            z.meldung?.let { Text(it.text, style = MaterialTheme.typography.bodySmall) }

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

    val waehleQuelle = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri: Uri? -> uri?.let { modell.legeAb(it) } }

    val waehleZiel = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/octet-stream"),
    ) { uri: Uri? ->
        val n = holeName
        if (uri != null && n != null) modell.holeNach(n, uri)
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
            z.fortschritt?.let { FortschrittBalken(it) }
            if (z.laedt && z.fortschritt == null) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
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
                                    waehleZiel.launch(e.name)
                                }) { Icon(Icons.Default.Download, "Herunterladen") }
                            }
                        } else null,
                        modifier = Modifier.clickable {
                            if (e.istOrdner) modell.hinein(e.name)
                            else { holeName = e.name; waehleZiel.launch(e.name) }
                        },
                    )
                    HorizontalDivider()
                }
            }
        }
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
