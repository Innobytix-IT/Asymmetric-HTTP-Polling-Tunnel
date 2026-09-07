/*
 * Gestaltung.kt -- dieselbe Erscheinung wie das Portal
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * WOZU
 * ----
 * Portal und App sind zwei Wege zu derselben Sache. Sie sollen auch so
 * aussehen. Die Werte hier sind KEINE Nachempfindung, sondern die
 * Farbvariablen aus portal/index.html, Zeile fuer Zeile uebernommen -- wer
 * dort etwas aendert, findet es hier unter demselben Namen wieder.
 *
 * WARUM NUR EINE ERSCHEINUNG, OHNE HELL-DUNKEL-UMSCHALTUNG
 * --------------------------------------------------------
 * Weil das Portal es so haelt, und aus demselben Grund: Ein Terminal in
 * Schwarz auf Weiss waere keines mehr. Das ist eine Entscheidung vom
 * 03.09.2026, keine vergessene Fallunterscheidung. Android faerbt Material
 * sonst gern nach dem Hintergrundbild des Nutzers ein (Dynamic Color); das
 * ist hier ausdruecklich NICHT gewollt, deshalb ein festes Farbschema.
 */
package de.innobytix.ahpt

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/* Die Palette aus portal/index.html, gleiche Namen. */
private val Grund = Color(0xFF070B08)
private val Flaeche = Color(0xFF0C130D)
private val FlaecheHoch = Color(0xFF10190F)
private val Rand = Color(0xFF1D3A24)
private val RandHell = Color(0xFF2F6A3C)
private val Text = Color(0xFFC9F7D6)
private val Leise = Color(0xFF5FA876)
private val Akzent = Color(0xFF3CFF77)
private val AkzentGlut = Color(0xFF8DFFB0)
private val AkzentHell = Color(0xFF0F2717)
private val Warn = Color(0xFFFFB84D)
private val WarnHell = Color(0xFF2B2109)
private val Fehler = Color(0xFFFF4D6A)
private val FehlerHell = Color(0xFF2B0C14)

/** Auf dem Akzent steht dunkler Text, nicht heller -- wie `button.haupt`. */
private val AufAkzent = Color(0xFF04140A)

private val Farben = darkColorScheme(
    primary = Akzent,
    onPrimary = AufAkzent,
    primaryContainer = AkzentHell,
    onPrimaryContainer = AkzentGlut,
    secondary = Akzent,
    onSecondary = AufAkzent,
    secondaryContainer = AkzentHell,
    onSecondaryContainer = AkzentGlut,
    tertiary = Warn,
    onTertiary = WarnHell,
    background = Grund,
    onBackground = Text,
    surface = Flaeche,
    onSurface = Text,
    surfaceVariant = FlaecheHoch,
    onSurfaceVariant = Leise,
    surfaceContainer = Flaeche,
    surfaceContainerHigh = FlaecheHoch,
    surfaceContainerHighest = FlaecheHoch,
    outline = RandHell,
    outlineVariant = Rand,
    error = Fehler,
    onError = FehlerHell,
    errorContainer = FehlerHell,
    onErrorContainer = Fehler,
)

/**
 * Monospace ueberall.
 *
 * Das Portal laedt bewusst KEINEN Webfont -- kein Fremdinhalt vom
 * Vermittler. Hier gaebe es die Wahl, aber die Systemschrift traegt den
 * Terminal-Look genauso, und eine mitgelieferte Schriftdatei waere ein
 * Megabyte fuer nichts.
 */
private val Schrift = Typography().let { v ->
    fun androidx.compose.ui.text.TextStyle.mono() = copy(fontFamily = FontFamily.Monospace)
    Typography(
        displayLarge = v.displayLarge.mono(), displayMedium = v.displayMedium.mono(),
        displaySmall = v.displaySmall.mono(),
        headlineLarge = v.headlineLarge.mono(), headlineMedium = v.headlineMedium.mono(),
        headlineSmall = v.headlineSmall.mono(),
        titleLarge = v.titleLarge.mono().copy(fontSize = 19.sp),
        titleMedium = v.titleMedium.mono(), titleSmall = v.titleSmall.mono(),
        bodyLarge = v.bodyLarge.mono().copy(fontSize = 15.sp),
        bodyMedium = v.bodyMedium.mono(), bodySmall = v.bodySmall.mono(),
        labelLarge = v.labelLarge.mono(), labelMedium = v.labelMedium.mono(),
        labelSmall = v.labelSmall.mono(),
    )
}

/** `--radius: 3px`. Material rundet sonst grosszuegig ab; ein Terminal nicht. */
private val Kanten = Shapes(
    extraSmall = androidx.compose.foundation.shape.RoundedCornerShape(3.dp),
    small = androidx.compose.foundation.shape.RoundedCornerShape(3.dp),
    medium = androidx.compose.foundation.shape.RoundedCornerShape(3.dp),
    large = androidx.compose.foundation.shape.RoundedCornerShape(3.dp),
    extraLarge = androidx.compose.foundation.shape.RoundedCornerShape(3.dp),
)

/**
 * Das Zeilenraster ueber allem -- `body::before` im Portal.
 *
 * Eine waagerechte Linie je drei Bildpunkte, sehr schwach. Auf einem
 * Telefon mit hoher Punktdichte waeren drei GERAETEpunkte unsichtbar fein,
 * deshalb wird in dp gerechnet und nicht in Pixeln.
 */
private fun Modifier.zeilenraster() = drawWithContent {
    drawContent()
    val abstand = 3.dp.toPx()
    val farbe = Akzent.copy(alpha = 0.05f)
    var y = 0f
    while (y < size.height) {
        drawRect(color = farbe, topLeft = androidx.compose.ui.geometry.Offset(0f, y),
                 size = androidx.compose.ui.geometry.Size(size.width, 1.dp.toPx()))
        y += abstand
    }
}

@Composable
fun AhptGestaltung(inhalt: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Farben, typography = Schrift, shapes = Kanten) {
        Box(Modifier.fillMaxSize().background(Grund).zeilenraster()) { inhalt() }
    }
}
