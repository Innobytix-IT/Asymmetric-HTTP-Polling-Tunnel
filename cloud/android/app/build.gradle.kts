/*
 * app -- die Oberflaeche und alles, was es nur unter Android gibt.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 Manuel Person, InnoBytix-IT
 */
plugins {
    id("com.android.application")
    kotlin("android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "de.innobytix.ahpt"
    compileSdk = 35

    defaultConfig {
        applicationId = "de.innobytix.ahpt"
        // 26 (Android 8) wegen java.util.Base64 und weil der Schluesselspeicher
        // erst ab da zuverlaessig hardwaregestuetzt ist. Aeltere Geraete
        // bekommen weiterhin das Portal -- dafuer gibt es beides.
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        // Fuer Pruefungen, die AUF dem Geraet laufen muessen. Der Kern
        // laesst sich auf der JVM pruefen, Androids Netzschicht nicht: Dort
        // liegt unter HttpURLConnection OkHttp, auf der JVM nicht. Ein
        // Unterschied zwischen beiden faellt nur hier auf.
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    sourceSets["main"].kotlin.srcDir("src/main/kotlin")
    sourceSets["androidTest"].kotlin.srcDir("src/androidTest/kotlin")
}

dependencies {
    implementation(project(":kern"))

    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")

    // QR-Codes lesen, fuer die Kopplung mit dem Einrichtungs-Assistenten.
    //
    // ZXing und NICHT Googles ML Kit: Letzteres ist unfrei und zieht die
    // Play-Dienste nach. Diese App steht unter der AGPL und soll ohne
    // Google-Dienste laufen koennen -- sonst faellt der Weg ueber F-Droid
    // aus, und der ist gerade fuer dieses Projekt der passende: Dort wird
    // aus dem Quelltext gebaut, was belegt, dass die App wirklich dem
    // Repository entspricht.
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")

    // Hochladen laeuft weiter, wenn die App in den Hintergrund geht. Genau
    // dafuer lohnt sich eine App gegenueber dem Portal: 4 MiB brauchen ueber
    // bplaced rund dreieinhalb Minuten, und so lange muss niemand das Telefon
    // wachhalten.
    implementation("androidx.work:work-runtime-ktx:2.10.0")

    // Nur fuer die Geraetepruefungen (src/androidTest). Sie wandern nicht
    // ins ausgelieferte APK.
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
