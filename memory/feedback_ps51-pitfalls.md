---
name: feedback_ps51-pitfalls
description: PowerShell 5.1 Fallstricke: UTF-8-Encoding ohne BOM und @{u}-Hashtable-Parsing
metadata:
  type: feedback
---

## Regel 1: Keine Non-ASCII-Zeichen in .ps1-Dateien

Keine Sonderzeichen (Em-Dash `--`, typografische Anfuehrungszeichen etc.) in
PowerShell-Skript-Dateien verwenden.

**Why:** PS5.1 liest `.ps1`-Dateien ohne BOM als Windows-1252. UTF-8-kodiertes
Em-Dash `--` (U+2014, Bytes `E2 80 94`) wird als drei Windows-1252-Zeichen
interpretiert; `0x94` ist das rechte typografische Anfuehrungszeichen `"` --
das schliesst den laufenden String-Literal vorzeitig. Alle nachfolgenden
Parse-Fehler kaskadieren aus diesem ersten Bruch.

**How to apply:** Ersetze alle non-ASCII-Zeichen durch ASCII-Alternativen:
`--` statt `--`, gerade Anfuehrungszeichen statt typografische. Oder Datei mit
UTF-8-BOM speichern (`Out-File -Encoding utf8` in PS7, oder Write-Tool + UTF-8).

## Regel 2: `@{u}` nicht in Double-Quoted-Strings

Git-Refs wie `@{u}` (upstream) niemals direkt in doppelt gequoteten PS-Strings
einbetten.

**Why:** PS5.1 interpretiert `@{...}` als Hashtable-Literal auch innerhalb von
Double-Quoted-Strings. Ergibt Parse-Fehler "Operator = fehlt nach Schluessel im
Hashliteral".

**How to apply:** Bash-Kommandos mit `@{u}` als Variable via Konkatenation aufbauen:
```powershell
$bashSync = 'cd ' + $WslRepo + ' && git fetch origin && git reset --hard @{u}'
wsl -d Debian -- bash -c $bashSync
```
Single-Quoted-String `'...'` wird nicht interpoliert (kein `$WslRepo`),
daher Konkatenation mit dem Variablenwert.
