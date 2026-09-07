/*
 * Bauplan fuer die Android-Fassung des Portals.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 *
 * ZWEI MODULE, UND WARUM
 * -----------------------
 * `kern` ist reines Kotlin OHNE Android. Das ist keine Formsache: Nur so
 * lassen sich Noise IK und das Protokoll gegen die Testvektoren nachrechnen,
 * ohne dass ein Geraet oder ein Emulator laufen muss -- `gradlew :kern:test`
 * genuegt. Waere die Krypto im Android-Modul, braeuchte jede Pruefung einen
 * Emulator, und Pruefungen, die umstaendlich sind, laufen irgendwann nicht
 * mehr.
 *
 * `app` ist die Oberflaeche und alles, was es nur unter Android gibt:
 * Schluesselspeicher, Dateiauswahl, Hochladen im Hintergrund.
 */
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "ahpt-android"

include(":kern")
include(":app")
