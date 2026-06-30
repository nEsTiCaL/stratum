---
id: lint-format-gate
title: Lint-/Format-Gate (I-1.12)
type: decision
status: active
created: 2026-06-30
updated: 2026-06-30
tags: [dev-infra, lint, ci, ruff]
related: ["[[arbeitsplan]]", "[[det-linter-review]]", "[[constraints]]"]
---

# Lint-/Format-Gate (I-1.12)

Dev-/CI-Gate fuer Stratums EIGENEN Code, Abschluss von Schritt 1. KEIN
Produktfeature: der Linter als Analyse-Producer ueber FREMDEN Code ist eine
getrennte Idee fuer S2 ([[det-linter-review]], "2 Achsen"-Abgrenzung).

## Werkzeug und Regelset

- ruff (in dev-deps gepinnt, `ruff>=0.15`; gebaut mit 0.15.20). Ersetzt
  Linter + Formatter in einem, black-kompatibel.
- `select = ["F", "E", "I", "UP", "B"]` (pyflakes, pycodestyle-Errors, isort,
  pyupgrade, bugbear). `line-length = 88`, `target-version = "py312"`.
- isort: `known-first-party = ["core"]` (sonst gruppiert ruff core-Imports als
  third-party, weil das Paket nicht installiert ist, package=false).
- `[tool.ruff.format] line-ending = "lf"` deckt sich mit .editorconfig/
  .gitattributes.

## Geltungsbereich: ganzer Baum mit Ausschluessen (nicht core/+tests/ explizit)

`make lint` laeuft `ruff check .` ueber den ganzen Baum, NICHT auf fest
genannten Pfaden. Begruendung: kuenftiger Python-Code (interfaces/web ab I-D.2)
wird automatisch erfasst, ohne das Gate anzufassen. Heute existiert ausserhalb
core/+tests/ ohnehin kein .py.

Ausschluesse (`extend-exclude`, behaelt ruff-Defaults wie .venv):

- `core/models/*`: generiert (datamodel-codegen), haengt am Drift-Gate
  (make check-drift). Konkret: der Codegen schreibt SINGLE-Quotes (`det = 'det'`);
  `ruff format` wuerde auf Double-Quotes normalisieren -> git-diff -> Drift-Bruch.
  Daher aus check UND format raus.
- `tests/fixtures/*`: absichtlich pathologische TESTDATEN, kein Projektcode.
  `symbols_with_error.py` ist bewusst syntaktisch kaputt (`def broken(:`) ->
  ruff kann die Datei nicht parsen (bricht sonst ab); `imports_basic.py` hat
  `import *` (F403) + ungenutzte Imports (F401); `calls_basic.py` `other.thing()`
  (F821). Genau die Idiome, die die Extraktoren verarbeiten sollen.

## Format wird erzwungen (nicht nur Lint)

Bewusst gegen die fruehere Churn-arme Variante entschieden: das Gate sichert in
diesem Haeppchen die Codequalitaet voll ab.

- `make lint` = `ruff check .` + `ruff format --check .` (Gate, formatiert nicht).
- `make fmt`  = `ruff format .` + `ruff check --fix .` (lokaler Komfort).
- `make check` = `lint` dann `test` (CI-Reihenfolge).
- Einmalige Erstformatierung: 29 Dateien reformatiert (grosser, rein
  mechanischer Diff). 160 Tests danach gruen (Golden-Extraktor-Output
  unveraendert; nur Layout der Quell-/Testdateien).

## Zeilenlaenge 88: bewusst trotz Churn

88 = black/ruff-Default (PEP8-strict waere 79; verbreitet 79/88/100/120). Die
"black-Kompatibilitaet" aus der Spec ist hier NICHT bindend, weil die einzigen
black-formatierten Dateien (core/models) ausgeschlossen sind -> Laenge war freie
Wahl. Gemessen: bei 88 36 E501 im Hand-Code, bei 100 nur 1, bei 120 null.
Nutzer waehlte 88 (Konvention/Qualitaet). Nach `ruff format` blieben nur 3 harte
E501 (lange String-Literale, die kein Formatter umbricht) -> per Implicit-
String-Concatenation gesplittet (repository.py SQL, scope.py f-String,
test_indexer_calls.py Test-Quelltext). Keine harten Probleme.

## Echte Code-Fixes (kein reines Config)

- 18 Findings autofixbar (I001, UP017/UP033/UP037, E401, F401-Reste).
- core/scope.py: B904 -> `raise ValueError(...) from None` (Enum-Lookup-Fehler
  bewusst durch klarere Meldung ersetzt, Kette unterdrueckt).
- 3 E501-String-Splits (siehe oben).

## CI: vorerst make-only

GitHub-Actions bewusst aufgeschoben (kein .github/ im Repo). Konsistent damit,
dass auch das Drift-Gate (I-1.0) heute nur ein make-Target ist, kein Runner.
GHA-Workflow (lint+drift+test) folgt spaeter, fruehestens Phase 2.

## Abgegrenzt / spaeter

- mypy (Typcheck): eigener spaeterer Schritt.
- Go-Lint (gofmt/go vet): erst Phase 2 mit dem Go-CLI.
- Linter-als-Producer ueber Fremdcode: [[det-linter-review]] (S2).
