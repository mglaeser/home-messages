# Home Messages

Home Assistant sendet Nachrichten an einzelne iMessage-Empfänger oder vorhandene
iMessage-Gruppen. Für einzelne Empfänger kann Sipgate-SMS als Ersatz aktiviert
werden. Empfängerkürzel und Zugangsdaten werden in der Integration verwaltet.

[English and full API reference](README.md) · [Änderungen](CHANGELOG.md) ·
[Hilfe](SUPPORT.md)

**Voraussetzung ist der separat installierte
[iMessage Proxy](https://github.com/mglaeser/imessage-proxy) auf einem Mac, der
bei Nachrichten angemeldet ist.** Home Messages läuft in Home Assistant und
installiert oder verwaltet diesen Mac-Dienst nicht. HA kann auf einem anderen
Gerät laufen. Sipgate ist optional und standardmäßig deaktiviert.

## Installation

Benötigt werden Home Assistant **2026.9.1 oder neuer**, ein erreichbarer Proxy
mit kompatibler 1.0-API und ein API-Schlüssel mit `messages:send`. Für den Versand
an konfigurierte Gruppen werden zusätzlich `messages:read`, aktivierte
Nachrichten-Lesezugriffe und die
entsprechenden macOS-Berechtigungen benötigt. Ziele müssen im Proxy
freigegeben sein. Nutze ein vertrauenswürdiges Netz oder einen passend
eingerichteten HTTPS-Endpunkt.

Die Integration ist als **benutzerdefiniertes HACS-Repository** installierbar.
Eine Aufnahme in den HACS-Standardkatalog ist noch nicht bestätigt.

1. In HACS das Menü → **Benutzerdefinierte Repositories** öffnen.
2. `https://github.com/mglaeser/home-messages` als **Integration** hinzufügen.
3. Home Messages herunterladen und Home Assistant neu starten.
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Home Messages**
   öffnen.

Alternativ `custom_components/home_messages` aus einem
[Release](https://github.com/mglaeser/home-messages/releases) in denselben Pfad
im HA-Konfigurationsverzeichnis kopieren und HA neu starten. Für dieses
Verzeichnis eine einheitliche Installations- und Aktualisierungsmethode nutzen.

## Konfiguration

Es wird ein Integrationseintrag unterstützt. Über **Konfigurieren** lassen sich
Proxy-Adresse, API-Schlüssel, Empfänger, Gruppen und optionale Sipgate-Daten
bearbeiten. Leere Passwortfelder behalten gespeicherte Werte bei. Speichern
prüft lokale Angaben; dabei werden keine Verbindung getestet und keine
Nachrichten gesendet.

Pro Empfänger eine Zeile `KÜRZEL=+internationaleTelefonnummer` anlegen.
Die folgenden Nummern sind reservierte fiktive Beispiele und müssen ersetzt
werden:

```text
AA=+12025550101
BB=+12025550102
CC=+12025550103
```

Kürzel beginnen mit einem Buchstaben und erlauben Buchstaben, Ziffern und
Unterstriche, maximal 16 Zeichen. Groß-/Kleinschreibung ist egal; Bindestriche
sind für Gruppen reserviert.

Ab **1.2.0** verwendet eine Auswahl mit Bindestrich die hinterlegte Chat-ID für
genau diese Kürzelkombination. Fehlt die Zuordnung, werden die Empfänger genauso
einzeln angeschrieben wie bei einer kommagetrennten Auswahl. Diese Entscheidung
fällt vor dem Versand; sie ist kein Ersatzversand nach einem Gruppenfehler.

| `initials` | Mit passender Gruppenzuordnung | Ohne diese Zuordnung |
| --- | --- | --- |
| `AA,BB` | Zwei einzelne Nachrichten | Zwei einzelne Nachrichten |
| `AA-BB` | Eine Nachricht an die AA/BB-Gruppe | Zwei einzelne Nachrichten wie bei `AA,BB` |
| `AA-BB,CC` | Eine Gruppennachricht und eine einzelne Nachricht an CC | Drei einzelne Nachrichten |
| `AA-BB-CC` | Eine Nachricht an die Dreiergruppe | Drei einzelne Nachrichten |

`BB-AA` und `AA-BB` wählen dieselbe Kürzelkombination. Eine Zuordnung für nur
einen Teil der Auswahl wird nicht verwendet. Ungültige Kürzel und fehlerhafte
vorhandene Gruppenzuordnungen bleiben Fehler; sie lösen keinen Einzelversand aus.

Identische tatsächlich verwendete Ziele werden zusammengefasst. Ohne eine
AA/BB-Gruppenzuordnung sendet `AA-BB,BB` einmal an AA und einmal an BB. Mit dieser
Zuordnung werden die Gruppe und BB einzeln angeschrieben. Die Schreibreihenfolge
legt keine Versandreihenfolge fest.

Für den Versand in einen gemeinsamen Chat muss die Gruppe bereits in
Nachrichten bestehen. Ihre numerische Chat-ID und
Teilnehmer über die Metadaten-API des Proxys prüfen. Anschließend genau
`chat_id:ID` im Proxy freigeben und die Zuordnung in HA eintragen:

```text
AA-BB=chat_id:42
AA-BB-CC=chat_id:43
```

IDs sind Beispiele und gelten nur für die jeweilige Nachrichten-Datenbank.
`AA-BB=42` ist ebenfalls gültig. Freigegebene Telefonnummern erlauben nicht
automatisch den Gruppenversand.

Vor dem Versand einer neuen Anfrage mit konfigurierten Gruppenzielen werden
deren Metadaten geprüft: Chat-ID, iMessage, Gruppenstatus und exakt die
konfigurierten Telefonnummern. Zusätzliche oder fehlende Mitglieder,
E-Mail-Identitäten und nicht lesbare Metadaten verhindern den gesamten Auftrag
vor dem Versand. Diese Prüfung sperrt spätere Mitgliedschaftsänderungen in
Nachrichten nicht. Konfigurierte Gruppenziele werden bei Metadaten-, Proxy-
oder Versandfehlern sowie unklarem Versandstatus niemals in Einzelnachrichten
oder SMS aufgeteilt. Ohne Gruppenzuordnung ist keine Chat-Metadatenabfrage nötig;
es gelten der normale Einzelversand und dessen Freigaben.

## Aktionen und REST

In **Entwicklerwerkzeuge → Aktionen** kann eine lokale Vorschau ausgeführt werden:

```yaml
action: home_messages.send
data:
  text: "Die Waschmaschine ist fertig."
  initials: "AA-BB"
  request_id: "waschgang-20261012-01"
  dry_run: true
response_variable: delivery
```

`dry_run: true` prüft Text und gespeicherte Zielzuordnungen und zeigt die
tatsächlich verwendeten Ziele. Ohne AA/BB-Gruppenzuordnung liefert das Beispiel
`AA-BB` zwei Ergebnisse mit `target_type: single`, für `AA` und `BB`. Die Vorschau
prüft keine Verbindung, aktuellen Gruppenmitglieder oder Proxy-Freigaben. Für
einen echten Versand `dry_run` weglassen oder auf `false` setzen.

`text` erlaubt 1–4.000 Zeichen, keinen führenden Bindestrich und keine
unzulässigen Steuerzeichen. `initials` erlaubt maximal 256 Zeichen.
Die optionale `request_id` erlaubt 8–80 Buchstaben, Ziffern sowie `.`, `_`, `~`
und `-`. Jeder neue logische Versand benötigt eine neue ID.

`home_messages.test_connection` ruft den Proxy-Status ab, ohne etwas zu senden.
Die Sipgate-Prüfung kontrolliert nur das Vorhandensein der Konfigurationsfelder.

Die normale HA-REST-API verwendet einen HA-Token und
`POST /api/services/home_messages/send?return_response`. Zusätzlich zeigt
**Konfigurieren** eine private, nur lokal erreichbare Webhook-URL. In Apple Home
bei **Inhalte von URL abrufen**: POST mit Formular- oder JSON-Feldern `text` und
`initials`; optional `request_id` und `dry_run`. Die Webhook-URL selbst ist das
Geheimnis, dort wird kein Proxy-Schlüssel benötigt.
Vollständige [REST-Beispiele](README.md#rest-api-and-apple-home-shortcuts).

## Status, Ersatzversand und Datenschutz

HTTP 202 am Webhook bedeutet angenommen und eingereiht, nicht zugestellt.
Auch `state: accepted` bestätigt nur die Annahme durch den Transport.
`complete: true` bedeutet, dass die Verarbeitung beendet ist; jedes einzelne
Ergebnis muss geprüft werden. Der Sensor **Letzter Versand** zeigt den jüngsten
Auftrag, und Fehler erzeugen eine HA-Benachrichtigung.

Ab 1.1.2 werden auch vor dem Versand abgewiesene echte Anfragen im Sensor als
`failed` und als persistente HA-Benachrichtigung sichtbar. Die Attribute enthalten
`phase: preflight`, einen sicheren Fehlercode/-text und ein ausdrücklich
abgewiesenes Ergebnis. Ab 1.2.0 ist eine fehlende Gruppenzuordnung kein Fehler;
sie führt zu Einzelzielen. Fehlerhafte vorhandene Zuordnungen und ungültige
Kürzel werden weiterhin abgewiesen. Bei Validierungsfehlern meldet die Aktion
einen Fehler; der Webhook antwortet mit HTTP 400 bzw. 409.
Solche Ablehnungen reservieren keine Anfrage-ID und ändern das Journal nicht;
sie werden nach einem Neustart nicht daraus wiederhergestellt. Fehlgeschlagene
Vorschauen verändern weder Status noch Benachrichtigungen.

Nur bei Einzelzielen kann ein eindeutiger Fehler vor der iMessage-Übergabe einen
Sipgate-Versuch auslösen, sofern aktiviert. Berechtigungsfehler und unklare
Ergebnisse führen nicht automatisch zu SMS. Diese Regeln gelten ebenso für
Einzelziele aus einer Auswahl ohne Gruppenzuordnung. Konfigurierte Gruppen
verwenden ausschließlich iMessage und wechseln bei Fehlern nicht zum
Einzelversand. Ein Fehler bei einem späteren Ziel macht einen vorherigen
Versand nicht rückgängig.

Ein dauerhaft gespeichertes Journal verhindert erneuten Versand derselben
gespeicherten ID mit identischem Inhalt. Es umfasst höchstens 1.000 Aufträge;
alte abgeschlossene Einträge werden verdrängt. Unterbrochene Aufträge werden
nach einem Neustart als unklar behandelt und nicht fortgesetzt. Nach Verlust
oder Verdrängung des Eintrags greift die Wiederholungssperre nicht mehr. Bei
unklarem Ergebnis zunächst prüfen und nicht einfach eine neue ID erzeugen.

Das Journal enthält keine Texte, Telefonnummern oder Chat-IDs, aber Kürzel,
Anfrage-IDs, Ergebnisse und einen Fingerabdruck. Ergebnisse stehen auch im
Sensor. HA-Verlauf, Automations-Traces, API-Clients und Proxy können eigene
Daten aufbewahren. Keine sensiblen Inhalte in Anfrage-IDs verwenden und Traces
vor dem Teilen bereinigen. Integrationsdiagnosen schwärzen Zugangsdaten,
Zielzuordnungen, Proxy-Adresse und Webhook-ID.

## Aktualisierung und Entfernung

Vor Updates HA sichern, Release-Hinweise lesen und aktive Sendungen beenden
lassen. Die Domain `home_messages` bleibt unverändert. Alte Einzelkürzel mit
Bindestrich müssen ausdrücklich umbenannt und ihre Aufrufer angepasst werden.

Ein Entlade- oder Neuladeversuch während einer aktiven Anfrage wird abgelehnt;
HA setzt den Eintrag dann auf `failed_unload`. Die Anfrage zuerst beenden lassen
und danach HA neu starten; erneutes Entladen oder Neuladen behebt diesen Zustand nicht.

Zum Entfernen zuerst Aufrufer deaktivieren, aktive Sendungen abwarten, den
Integrationseintrag löschen, Dateien über HACS oder manuell entfernen und HA
neu starten. Den dedizierten Proxy-Schlüssel bei Nichtgebrauch widerrufen.
Mac-Proxy und Nachrichten-Chats bleiben bestehen; Sicherungen und Traces
können weiterhin ältere Daten enthalten.

[Mitwirken](CONTRIBUTING.md) · [Verhaltensregeln](CODE_OF_CONDUCT.md) ·
[Sicherheit](SECURITY.md) · [Apache-2.0-Lizenz](LICENSE)

Copyright 2026 Marian Klee. Unabhängige Community-Software ohne behauptete
Unterstützung durch Home Assistant, Apple oder Sipgate.
