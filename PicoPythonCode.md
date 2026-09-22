# PicoEnviro+ - Modulare Wetterstation

Pimoroni Pico Enviro+ Pack (BME688, LTR-559 Lichtsensor, MEMS-Mikrofon,
240x240 LCD, RGB-LED) auf einem Pico W. MicroPython mit PicoGraphics/
`pimoroni`-Bibliotheken aus dem generischen Pimoroni-Firmware-Build.

## Dateien -> Pico

Alle neun `.py`-Dateien direkt ins Wurzelverzeichnis des Pico kopieren
(z.B. per Thonny), keine Unterordner:

    secrets.py
    config.py
    sensors.py
    system.py
    wifi.py
    history.py
    web.py
    display.py
    main.py

## Voraussetzung: Firmware

Der generische "batteries included" MicroPython-Build von
https://github.com/pimoroni/pimoroni-pico/releases (Board-Variante
`enviro.uf2`) muss geflasht sein. Der bringt `picographics`, `pimoroni`,
`pimoroni_i2c`, `breakout_bme68x` und `breakout_ltr559` schon mit - diese
Bibliotheken sind NICHT Teil dieses Pakets.

**Wichtig, falls die Firmware aktualisiert wurde:** Neuere Firmware-Builds
(getestet: `picow v1.29.0-2`, 2026-08-31) haben die Vektorschrift `"sans"`
entfernt - `PicoGraphics.set_font()` kennt dort nur noch `bitmap6`,
`bitmap8` und `bitmap14_outline`. Dieses Projekt läuft bereits auf
`bitmap8` (siehe unten) und braucht daher **keine** Vektorschrift - falls
deine Firmware `"sans"` noch anbietet, funktioniert das Paket trotzdem,
falls nicht, auch.

## Vor dem ersten Start

1. `secrets.py` öffnen und WLAN_SSID / WIFI_PASSWORD eintragen.
2. `config.py` gegen dein Referenzgerät kalibrieren (Beispielwerte aus
   Vergleichsmessungen an einem konkreten Gerät - für dein eigenes Exemplar
   neu ermitteln, nicht ungeprüft übernehmen):
   - `TEMP_OFFSET_ON` / `TEMP_OFFSET_OFF` - **zwei** Temperatur-Offsets, weil
     das Backlight spürbar zur Eigenerwärmung beiträgt. Wenn das Display bei
     dir meist ausgeschaltet bleibt (z.B. weil du übers Web-Dashboard
     abliest), ist `_OFF` der praxisrelevante Wert, nicht `_ON`.
   - `PRESSURE_OFFSET_HPA`, `HUMIDITY_TRIM` - Feinjustage nach der
     physikalischen Korrektur (Meereshöhen-Umrechnung bzw. Magnus-Formel).
   - `BME_HEATER_TEMP_C` / `_DURATION_MS` - bewusst auf 320°C/150ms gesetzt
     (nicht der Bibliotheks-Default 300°C/100ms), um mit dem parallel
     laufenden BME690-Projekt vergleichbare Gaswerte zu bekommen.
3. `LED_B`, `MIC_ADC_PIN`: beide inzwischen per REPL-Test bestätigt (GP10
   bzw. GP26) - der Schaltplan-PDF-Text hatte GP8 für die LED fälschlich
   ausgewiesen. Nur relevant, falls du ein abweichendes Board-Layout hast.

## Reihenfolge beim ersten Testlauf

`main.py` importiert die anderen sieben Module; ein fehlender Import fällt
sofort beim Boot auf (REPL-Fehlermeldung in Thonny). Nach dem Kopieren
einmal per Ctrl+D (Soft-Reset) oder Power-Cycle neu starten.

**Watchdog (`WDT_TIMEOUT_MS`):** Während der Entwicklung mit Thonny auf `0`
(deaktiviert) lassen - einmal aktiviert, lässt sich der WDT nicht mehr
abschalten, und "Stop" in Thonny füttert ihn nicht mehr, wodurch die
Verbindung nach Ablauf der Zeit abreißt. Erst scharf schalten (z.B. `8000`,
Maximum auf dem RP2040 ist 8388 ms), wenn das Gerät eigenständig läuft.

## Nach dem Start

Taste A schaltet das Display an/aus, Taste B WLAN/Webserver, X/Y blättern
zwischen den Seiten. Erst nach erfolgreicher WLAN-Verbindung (IP vergeben)
startet der Webserver automatisch - im Browser die IP von der WLAN-Seite
aufrufen. Das Dashboard aktualisiert Messwerte alle paar Sekunden, Diagramme
jede Minute (`WEB_REFRESH_S`/`WEB_CHART_REFRESH_S`).

Nach `AUTO_OFF_IDLE_MS` (Standard: 2 Minuten) ohne Tastendruck schaltet sich
das Display automatisch ab - siehe "Bildschirmschoner" unten.

## Funktionsumfang

### Anzeige: bitmap8/6/14_outline statt Vektorschrift
Als Reaktion auf den Firmware-bedingten Wegfall von `"sans"` (siehe oben)
läuft die Anzeige jetzt komplett auf Bitmap-Schriften. Wichtige, per REPL
bestätigte Eigenheiten dieser Schriftfamilie:
- Skaliert nur in **ganzen** Schritten (`scale=1.5` sieht identisch zu
  `scale=1` aus) - feste Zwei-Stufen-Hierarchie: `scale=2` für
  Werte/Titel, `scale=1` für Labels/Beschreibungen/Fußzeile.
- Zeichnet oben-links, ohne Grundlinien-Überstand wie die frühere
  Vektorschrift - deshalb reichen kleine y-Werte, keine Mindest-Abstands-
  Regel mehr nötig.
- `bitmap6` kennt nur Großbuchstaben; `bitmap14_outline` ist eine
  Siebensegment-/LCD-Ziffern-Optik (kein echter Kontur-Font) und ca. 1,8x
  breiter als `bitmap8` pro Zeichen.
- Die große Temperaturzahl auf der Startseite nutzt `bitmap14_outline`
  (`scale=2`), das Min/Max-Feld daneben `bitmap6` (`scale=2`) - beide
  bewusst so gewählt, dass sie zur restlichen `bitmap8`-Anzeige passen,
  nicht weil sie technisch nötig wären.

### Selbsttest-Näherung
Boschs eigener Selbsttest prüft den internen Heizstrom-Regelwert (`idac`) -
über diese Bibliothek nicht zugänglich (`bme.read()` liefert 7 Werte, keiner
davon `idac`). `SelfTest` in `sensors.py` prüft stattdessen über ein
gleitendes 5-Zyklen-Fenster: Heizer stabil, Gaswert vom Sensor als gültig
markiert, und der kOhm-Wert in einer plausiblen Spanne (0,5-5000 kOhm) -
fängt einen offenen/kurzgeschlossenen Heizwiderstand ab, auch ohne Zugriff
auf `idac`.

### Robustere Trendberechnung
`history.Trend.delta()` gibt erst einen Wert zurück, wenn das Zeitfenster
tatsächlich (zu min. 90%) gefüllt ist - vorher reichten schon zwei Punkte
kurz nacheinander, was direkt nach jedem Boot zu stark verzerrten
"+6 C / 10 min"-artigen Anzeigen führte (der Wert war real, bezog sich aber
nur auf ein paar Sekunden/Minuten Spanne, nicht auf die behauptete
Fensterlänge).

### Bildschirmschoner & LED
Nach `AUTO_OFF_IDLE_MS` ohne Tastendruck ruft die Hauptschleife dieselbe
`toggle_backlight()`-Methode auf, die Taste A auch manuell nutzt - kein
Sonderfall zum Aufwachen nötig, Taste A tut ja ohnehin nur das eine.
Andere Tasten (B/X/Y) lösen den Timer-Reset ebenfalls aus, ohne selbst
etwas Sichtbares zu bewirken, solange das Display aus ist.

Die RGB-LED (unabhängig vom Backlight ansteuerbar) geht dabei NICHT
komplett dunkel, sondern zeigt ein sanftes rosa Pulsieren
(`SLEEP_LED_COLOR`, `SLEEP_LED_PEAK`, `SLEEP_LED_PERIOD_MS`) als
"lebt noch"-Signal - bewusst keine der vier IAQ-Farben, um Verwechslung mit
"kalibriert gerade" zu vermeiden. Ist es hell genug (`LED_NIGHT_LUX_THRESHOLD`,
Standard 50 Lux, dieselbe Grenze wie `describe_light()`s "dunkel"-Kategorie),
geht die LED stattdessen ganz aus - kein Pulsieren, wo es ohnehin kaum
auffiele. Das ist ein reiner Helligkeits-, kein Uhrzeit-Vergleich; der
Sensor kennt keine Tageszeit.

### Web-Dashboard: Speicher-Fix für den Verlauf
Der `/history`-Endpunkt (180 Punkte x 4 Messreihen) verschwand nach vielen
Stunden Laufzeit gelegentlich dauerhaft (nur Geräte-Neustart half) - Verdacht:
Speicherfragmentierung durch wiederholtes Erzeugen kompletter Python-Listen
bei jeder Anfrage. `History.series_json()` baut das JSON jetzt direkt aus
dem Ringpuffer, ohne Zwischenliste; `_history_payload()` ruft zusätzlich
`gc.collect()` vor dem Aufbau. **Nicht abschließend bestätigt**, da echtes
Nachstellen des Fehlers Tage an Laufzeit braucht - bislang kein Wiederauftreten.

Zusätzlich hatte die Hauptschleife ursprünglich **kein** `time.sleep()` und
baute pro Durchlauf das komplette Status-Dict neu auf - potenziell erhebliche
Allokationslast über viele Stunden. `LOOP_SLEEP_MS` (10 ms, wie im
BME690-Projekt) bremst das jetzt.

## Bekannte Grenzen
- Kalibrierwerte (Offsets, IAQ-Schwellen) sind an einem konkreten Gerät
  gegen eine externe Referenz (SwitchBot-Sensor, DWD-Luftdruckdaten)
  ermittelt - für ein anderes Exemplar als Ausgangspunkt brauchbar, aber
  nicht blind übernehmen.
- Der Speicher-Fix für `/history` ist nach aktuellem Stand plausibel
  begründet, aber nicht durch tagelanges kontrolliertes Nachstellen bewiesen.
- MQTT/Home-Assistant-Anbindung ist bewusst noch nicht Teil dieses Pakets -
  kann bei Bedarf ergänzt werden.

## Verifiziert vor der Auslieferung
- Alle Dateien einzeln mit `py_compile` auf Syntaxfehler geprüft.
- Trend- und Speicher-Fixes mit synthetischen Testfällen gegengerechnet,
  nicht nur auf dem Papier hergeleitet.

**Was nicht vorab geprüft werden konnte:** Echtes Verhalten auf der Hardware
(Timing, I2C, Speicherverbrauch, tatsächliches Schriftbild). `web.py` lief
zu keinem Zeitpunkt in dieser Entwicklungsumgebung selbst - jede
Layout-/Zeitverhalten-Aussage stammt aus Foto-/Screenshot-Rückmeldungen nach
echten Testläufen, nicht aus eigener Beobachtung.

Disclaimer: Diese Datei ist mit Unterstützung eines KI-Assistenten (Claude,
Anthropic) entstanden und wurde iterativ gegen echtes Hardware-Feedback
abgeglichen.
