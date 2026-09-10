# AHPT Cloud als Android-App

Dasselbe wie `../portal/`, nur als App. Das Portal bleibt unveraendert — wer
lieber die HTML-Datei auf dem Handy oeffnet, kann das weiter tun. Diese App
ist ein zweiter Weg, kein Ersatz.

## Warum ueberhaupt, wenn es das Portal schon gibt

Eine App, die nur das Portal in einen Rahmen packt (WebView), loeste zwar
das Hoster-Problem — der Code kaeme dann aus der App und nicht vom Webspace —,
aber drei Dinge kann sie nicht:

**WebCrypto kennt X25519 erst seit Chrome 133** (Anfang 2025). Die Android
System WebView wird zwar nachgezogen, aber auf Geraeten ohne Google-Dienste
oder mit eingefrorener WebView startet das Portal gar nicht, mit einer
Meldung, die niemand deuten kann.

**Der private Schluessel liegt im Portal in `localStorage`.** Das steht auch
so in `portal/index.html`: auf einem fremden Rechner bedenklich. Hier liegt
er verschluesselt, und der Schluessel des Umschlags steckt im
Android-Schluesselspeicher, wo er nicht auslesbar ist.

**Hochladen im Hintergrund.** 4 MiB brauchen ueber bplaced rund dreieinhalb
Minuten. Eine Webseite muss dafuer offen und im Vordergrund bleiben.

Zwei weitere Unterschiede sind keine Geschmacksfrage, sondern heben Grenzen
auf, an denen der Browser haengt: Pruefsumme und Herunterladen laufen hier
**streamend**. `crypto.subtle.digest` verlangt den ganzen Datenblock auf
einmal, deshalb muss `ahpt.js` jede Datei einmal vollstaendig in den Speicher
ziehen. Hier haengt die Groesse am freien Speicherplatz, nicht am
Arbeitsspeicher.

## Zwei Module, und warum

    kern/    Noise IK und das Protokoll. Reines Kotlin, OHNE Android.
    app/     Oberflaeche, Schluesselspeicher, Dateiauswahl.

Die Trennung ist keine Formsache. Nur so laufen die Pruefungen ohne Geraet
und ohne Emulator:

    ./gradlew :kern:test

Waere die Krypto im Android-Modul, braeuchte jede Pruefung einen Emulator —
und Pruefungen, die umstaendlich sind, laufen irgendwann nicht mehr.

## Was geprueft ist

    Noise IK gegen die offiziellen Vektoren     beide Suiten, Byte fuer Byte
    Protokoll gegen eine boeswillige Gegenstelle 11 Pruefungen

Die Krypto ist die **dritte** Umsetzung desselben Verfahrens nach `krypto.py`
und `portal/noise.js`, und sie rechnet gegen dieselbe Datei:
`../tests/ik_vektoren.json`. Kein zweites Exemplar, das veralten koennte.

Der Unterschied zwischen den beiden Pruefungen ist wichtig. Ein Durchstich
gegen den echten Agenten zeigt, dass beide Seiten dieselbe Sprache sprechen.
Er kann aber nicht zeigen, dass die Schranken halten — dafuer muesste der
Agent sich falsch verhalten. Deshalb steht in `ProtokollTest.kt` eine
Gegenstelle, die genau das tut, wogegen die Schranken gebaut sind: fremde
Marke im Umschlag, Rueckfall auf Klartext, Stueckdateinamen mit Pfadanteil.

Die App spricht `noise_ik` (ChaChaPoly), also dieselbe Suite wie
`ahpt_client.py` — nicht `noise_ik_aes` wie das Portal, das nur deshalb auf
AES-GCM ausweicht, weil WebCrypto kein ChaCha kennt. Der Agent nimmt beide
und antwortet in derselben.

## Bauen

Vorausgesetzt sind ein Android SDK (API 35) und ein JDK 17.

`local.properties` anlegen — die Datei ist rechnergebunden und steht
deshalb in `.gitignore`:

    sdk.dir=/pfad/zum/Android/Sdk

Unter Windows mit **Vorwaerts-Slashes** schreiben. Backslashes sind in
`.properties`-Dateien Fluchtzeichen: aus `C:\Users\...` wird still
`C:Users...`, und der Bau bricht mit einer Meldung ab, die den Pfad nicht
nennt.

    ./gradlew :kern:test           # Pruefungen, ohne Geraet
    ./gradlew :app:assembleDebug   # APK nach app/build/outputs/apk/debug/

### Eine Fassung, die man weitergeben kann

Der Debug-Bau oben ist zum Entwickeln da, nicht zum Verteilen: Er ist als
`debuggable` markiert und traegt einen Schluessel, den sich jeder Rechner
selbst erzeugt. Auf einem fremden Geraet hat er nichts verloren.

Fuer eine weitergebbare Fassung braucht es einen eigenen
Schluesselspeicher. **Den legst du an, nicht das Projekt** — er und sein
Passwort bleiben bei dir und stehen in `.gitignore`:

```bash
keytool -genkeypair -v -keystore ahpt.jks -alias ahpt -keyalg RSA -keysize 4096 -validity 10000
```

`keytool` fragt dann nach einem Passwort und ein paar Angaben zur Person.
Danach eine Datei `android/keystore.properties` anlegen:

    speicher=/pfad/zu/ahpt.jks
    speicherPasswort=<dein Passwort>
    schluessel=ahpt
    schluesselPasswort=<dein Passwort>

Und dann:

    ./gradlew :app:assembleRelease   # nach app/build/outputs/apk/release/

**Diesen Schluesselspeicher nie verlieren.** Android laesst eine
Aktualisierung nur zu, wenn sie mit demselben Schluessel signiert ist wie
die installierte Fassung. Ist er weg, koennen deine Nutzer nicht mehr
aktualisieren, sondern muessten deinstallieren und neu einrichten — mit
neuem Geraeteschluessel.

Fehlt `keystore.properties`, laeuft alles wie bisher; `assembleRelease`
liefert dann ein **unsigniertes** APK, das Android nicht installiert. Das
ist Absicht: Wer nur die Pruefungen laufen lassen will, soll sich keinen
Schluesselspeicher anlegen muessen.

## Einrichten

Beim ersten Start fragt die App nach:

1. **Adresse des Vermittlers** — das Verzeichnis, in dem `relay.php` liegt.
2. **Oeffentlicher Schluessel des Agenten** — aus dessen Startausgabe.
3. Dann **Schluessel erzeugen**. Der oeffentliche Teil gehoert in die
   `clients`-Liste des Agenten; ohne ihn dort weist er jede Frage ab.

Beides von Hand uebertragen, niemals ueber den Vermittler: Was dort liegt,
kann der Hoster austauschen, und genau das soll die Verschluesselung
verhindern.

## Die Erscheinung

Dieselbe wie im Portal — Terminal-Palette, Monospace, kantige Raender. Die
Farbwerte in `Gestaltung.kt` sind aus `portal/index.html` uebernommen, unter
denselben Namen. Dynamic Color ist ausgeschaltet: Android faerbt Material
sonst nach dem Hintergrundbild des Nutzers ein, und ein Terminal in Rosa
waere keines mehr.

## Was es nicht gibt

**Mehrere Vermittler.** Diese App gehoert zu `cloud/`, und dort gibt es
genau einen. Die Mehrwegigkeit steht in `../../cloud3000/`, und sie braucht
immer beide Seiten: Ein Client, der bei zwei Adressen fragt, bekommt trotzdem
nur an einer eine Antwort, solange der Agent nur dort ablegt.

**Kein Loeschen, kein Ueberschreiben** — wie ueberall in AHPT Cloud. Gibt es
den Namen schon, zaehlt der Agent hoch, und die App sagt es.
