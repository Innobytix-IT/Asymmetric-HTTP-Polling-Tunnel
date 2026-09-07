/*
 * kern -- Noise IK und das AHPT-Protokoll, ohne Android.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 */
plugins {
    kotlin("jvm")
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    // Die Krypto-Grundrechenarten. NICHT der JCE-Provider von BouncyCastle,
    // sondern seine untere Schicht (org.bouncycastle.crypto.*, .math.ec.*):
    // Android bringt selbst eine alte, beschnittene BouncyCastle-Fassung mit,
    // und ein zweiter registrierter Provider fuehrt dort zu Ueberraschungen,
    // die vom Geraet abhaengen. Die untere Schicht ist davon nicht betroffen
    // -- sie rechnet, ohne sich irgendwo anzumelden.
    implementation("org.bouncycastle:bcprov-jdk18on:1.79")

    // JSON. Android bringt org.json eingebaut mit, deshalb `compileOnly`:
    // Der Kern darf die Schnittstelle benutzen, die Bibliothek aber nicht ins
    // APK wandern -- zwei Fassungen derselben Klassen im selben Programm sind
    // eine Fehlerquelle, die vom Geraet abhaengt. Auf der JVM, wo es kein
    // eingebautes org.json gibt, kommt sie fuer die Pruefungen dazu.
    compileOnly("org.json:json:20240303")

    testImplementation(kotlin("test"))
    testImplementation("org.json:json:20240303")
}

tasks.test {
    useJUnitPlatform()
    // Die offiziellen Noise-Testvektoren liegen beim uebrigen Projekt, nicht
    // im Android-Zweig. Ein zweites Exemplar hier waere eine Kopie, die
    // veralten kann -- und dann prueft der Test etwas anderes als der Rest.
    systemProperty("ahpt.vektoren",
        rootProject.projectDir.resolve("../tests/ik_vektoren.json").canonicalPath)
    testLogging {
        events("passed", "failed", "skipped")
        showStandardStreams = true
    }
}
