# Indexer: Kern

Deterministische Struktur-Extraktion via tree-sitter ueber .scm-Queries.
Sprachunabhaengiger Kern (core/indexer/), Sprachspezifisches nur in
queries/<sprache>/. Grundlage: [[architecture]] TG(4), [[inkremente-schritt-1]].

## Architektur

- `core/indexer/registry.py`: Grammar-Registry, Sprache -> {Parser, Query},
  lru-gecacht. Laedt .scm aus queries/<sprache>/<name>.scm.
- `core/indexer/symbols.py`: Extraktor-Kern. extract_symbols (rein syntaktisch,
  Golden-testbar) + symbol_index_result (haengt Provenance an -> ResultDet).
- Capture-Konvention in .scm: @name = Bezeichner, @<kind> = Definitionsknoten
  (Span + Grund-Art). Methode-vs-Funktion und parent leitet der Kern aus den
  Vorfahren ab (eine Mapping-Logik fuer alle Sprachen), NICHT die Query.

## tree-sitter-API (Stand 0.25.2, language-pack 1.11) - bindend

Diese Form hat mehrere Anlaeufe gekostet; fuer I-1.5/1.6/1.9 direkt nutzen:

- Parser bauen: `Parser(get_language(lang))`. Das `get_parser` des
  language-pack verhaelt sich in dieser Version unzuverlaessig (parse akzeptiert
  weder str noch bytes sauber) - NICHT verwenden.
- Parsen: `parser.parse(quelltext_bytes)` (bytes, nicht str).
- `node.text` ist bytes -> `.decode()`.
- Query: `Query(get_language(lang), scm_text)`. `lang.query(...)` ist deprecated.
- Matching: matches/captures sind von Query auf `QueryCursor` gewandert:
  `QueryCursor(query).matches(root)` -> `[(pattern_index, {capture: [Node]})]`.
- Fehlertoleranz: `root.has_error` -> partial-Flag. ERROR-Knoten matchen die
  Pattern nicht und fallen so von selbst raus; gueltige Symbole bleiben.

## Python-Grammar-Eigenheit (wichtig)

Zuweisungen und Docstrings sind in dieser Grammar-Version KEINE
`expression_statement`-Kinder, sondern direkt:
- `module -> assignment` (nicht `module -> expression_statement -> assignment`)
- `block -> assignment` (Klassen-/Funktionsrumpf)
- Docstring: erstes named child des body ist direkt ein `string`-Knoten;
  Inhalt aus dem `string_content`-Kind. (_docstring entpackt zur Sicherheit
  auch einen expression_statement-Wrapper, falls eine Grammar ihn doch setzt.)

## Symbol-Konventionen (Python, I-1.4)

- kind: function | method | class | var | const. method = function_definition
  mit umschliessender Klasse. const = ALL_CAPS-Name (name.isupper()), sonst var.
- nur Modul- und Klassen-Ebene fuer var/const; lokale Variablen in Funktionen
  werden bewusst NICHT erfasst (Pattern verlangt module/block als Elter).
- signature: parameters (func/method) bzw. superclasses (class), syntaktisch,
  inkl. Klammern; None wenn nicht vorhanden. var/const: None.
- parent: naechste umschliessende Klasse, sonst None (nicht die Funktion).
- visibility: fuehrender Unterstrich -> private, sonst public.
- span: [start_zeile, end_zeile], 1-basiert inklusive.
- Symbole deterministisch sortiert nach (span, kind, name) fuer Byte-Stabilitaet.
- input_hash = SHA-256 des Quelltexts; source_hash kommt vom Aufrufer (Ingestion).

## dependency_graph (Python, I-1.5)

- queries/python/imports.scm + core/indexer/imports.py. Felder je Import:
  raw/target/kind/span. import-level (Modul-Abhaengigkeit), Symbolnamen nicht.
- kind: module (`import a`) | symbol (`from x import ...`) | relative
  (`from . / .mod / ..pkg`). "external" wird in S1 nicht erzeugt (braucht
  Repo-Layout -> S4).
- raw = Modul-Referenz wie geschrieben (analog callee_raw), NICHT die ganze
  Zeile. Mehrfach-Import `import a, b` -> zwei Zeilen. Alias ignoriert.
- target: nur relative Imports werden gegen den Pfad der importierenden Datei
  aufgeloest (dots=1 = aktuelles Paket = Verzeichnis der Datei). Absolute ->
  NULL (ohne sys.path nicht aufloesbar). Ueber Repo-Wurzel hinaus -> NULL.
- Grammar: assignment-Eigenheit gilt analog; module_name-Feld ist dotted_name
  (absolut) oder relative_import (import_prefix=Punkte + optional dotted_name).

## Offen / folgt

- I-1.6 calls.scm (call_graph approx., einziges det-Artefakt mit Kanten-confidence).
- I-1.9 JavaScript/TS belegt die Sprachunabhaengigkeit (nur neue .scm, Kern
  unveraendert). I-1.10 C#, I-1.11 GDScript.
