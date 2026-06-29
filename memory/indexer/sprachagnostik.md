---
id: sprachagnostik
title: Sprachagnostik des Extraktor-Kerns - Befund und Grenzziehung
type: decision
status: active
created: 2026-06-29
updated: 2026-06-29
status: active
tags: [indexer, tree-sitter, multilang]
related: ["[[_core]]", "[[inkremente-schritt-1]]"]
---

# Sprachagnostik des Extraktor-Kerns

Befund + Grenzziehung vor der ersten Fremdsprache. Umgesetzt von
[[inkremente-schritt-1]] I-1.85.

## Befund (Ausgangslage)

Das Versprechen "sprachunabhaengiger Kern, Sprachspezifisches nur in .scm" gilt
aktuell nur fuer die halbe Pipeline. Die .scm finden die Knoten, aber die
Nachverarbeitung in core/indexer/{symbols,imports,calls}.py liest hart
Python-AST-Knotentypen und -Konventionen (class_definition/function_definition,
string/string_content, Felder parameters/superclasses, "self", fuehrender
Unterstrich, relative_import). Bei der ersten Fremdsprache bricht das.

Schon agnostisch (traegt unveraendert): die Wirbelsaeule sieht nur scope +
content-jsonb -> Store, Migration, Provenance, Trace, Ingestion, scope,
Supersede/Staleness, Secret-Scan, Registry, Query-Schleife.

## Sprachlandschaft (Recherche, 2026)

Drei Methodiken, drei Linsen, konsistentes Bild:
- TIOBE Jun 2026 (Suchmaschinen-Mentions): Python, C, C++, Java, C#, JavaScript,
  SQL, ..., Go, ..., Rust (#12).
- Stack Overflow 2025 (Nutzung): JavaScript, HTML/CSS, SQL, Python, TypeScript,
  Java, Bash, C#, C++, C, PHP, Go, Rust.
- GitHub Octoverse 2025 (Contributors): TypeScript #1, Python #2, JavaScript #3,
  Java, C#, ...

Konsens-Set strukturierter general-purpose-Sprachen (gegen das die Konvention
validiert wird): Python, JavaScript, TypeScript, Java, C#, C, C++, Go, Rust,
PHP, Ruby, Kotlin, Swift, Dart, Scala (+ GDScript projektintern). Nicht-Code-
Struktur-Faelle (SQL, HTML/CSS, Shell) passen nicht ins Funktion/Klasse/Import-
Modell -> out of scope (spaeter ggf. reduziert).

Konkret implementiert: Python (Referenz), JS/TS (I-1.9), C#/GDScript (geplant).
Die Analyse deckt aber das ganze Konsens-Set ab, damit C#/Go/Rust spaeter
nichts brechen.

## Grenzziehung (die Entscheidung)

Leitsatz: So viel wie moeglich agnostisch ueber die Capture-Konvention; das
Profil ist die begruendete Ausnahme; semantisch Hartes ist out of scope (S1).

### AGNOSTISCH (Kern + Capture-Konvention, KEIN Profil)

Capture-Vokabular je queries/<lang>/*.scm (tags.scm-Stil):

```
@name               Bezeichner der Definition (Pflicht)
@definition.<kind>  Definitionsknoten; <kind> aus kontrolliertem, offenem
                    Vokabular: function method class struct interface enum
                    trait record namespace type constant field property
                    constructor macro  (Kern liest nur den Suffix als String)
@parent             Name des umschliessenden Scopes (optional)
@signature          Parameter-/Signaturknoten (Text verbatim)
@param              je deklarierter Parameter (Kern zaehlt -> arity)
@doc                Doc-Knoten (String ODER Kommentar)
@visibility         Modifier-Knoten, wo syntaktisch vorhanden
@reference.call     Aufrufknoten;  @callee = Callee-Ausdruck
@import.module|symbol|relative   Import-Referenz (kind aus Capture-Suffix)
```

Ableitung im Kern (rein generisch):

```
Feld          | Quelle
--------------+--------------------------------------------------------
name          | @name
kind          | Suffix von @definition.*  (String, Kern validiert NICHT)
span          | Knoten start/end
parent        | @parent ODER Span-Containment gegen symbol_index
signature     | @signature Text
arity         | count(@param)
visibility    | @visibility normalisiert; sonst Profil-Strategie
docstring     | @doc Text via generischem Delimiter-Stripper
caller (call) | Span-Containment gegen symbol_index  (KEIN Vorfahren-Walk)
callee_raw    | @callee Text
callee_ref    | Name-Match gegen symbol_index (+ self via Profil)
import raw    | @import.* Text
import kind   | Suffix von @import.*
import target | Profil-Strategie
```

Schluessel-Einsicht: caller (call_graph) und parent loesen sich ueber
SPAN-CONTAINMENT gegen das symbol_index auf - das innerste Symbol, dessen Span
die Zeile enthaelt. Voellig sprachagnostisch, kein Vorfahren-Walk per
Knotentyp, kein Profil. (Loest den groessten bisherigen Python-Klotz auf.)

method-vs-function, Sichtbarkeits-Modifier, Doc-Knoten: kommen aus der .scm
(Pattern unterscheidet Methode strukturell, Modifier wird gecaptured), nicht
aus Kern-Logik.

### PROFIL (schmal, je Eintrag mit Begruendung "warum nicht .scm")

```
visibility_strategy | none | underscore_prefix | uppercase_export
   warum: nur wo KEIN @visibility-Modifier existiert. Python/GDScript ->
   underscore_prefix; Go -> uppercase_export; Modifier-Sprachen (Java/C#/
   Kotlin/Swift/Scala/PHP/C++/Rust/TS) -> none (Capture reicht).
self_keyword        | "self" | "this" | "$this" | None
   warum: Selbst-Methoden-Aufloesung. Go: None (Receiver-Name beliebig,
   nicht aufloesbar). Nicht syntaktisch generisch fassbar.
import_resolution   | namespace_passthrough (default) | relative_path | relative_path_ext
   warum: Aufloesung des target unterscheidet sich fundamental. Default
   namespace_passthrough (target = rohe Modul-/Namespace-Id, KEINE
   FS-Aufloesung) deckt Java/C#/C++/Go/Rust/PHP. relative_path = Python.
   relative_path_ext = JS/TS (./x -> x.js | x/index.js).
const_strategy      | none (default) | uppercase_name
   warum: const-Erkennung ist NICHT universell. Sprachen MIT const-Keyword
   (Go, JS/TS, C#, Rust) druecken const strukturell in der .scm aus
   (@definition.const) -> none. Nur Sprachen OHNE Keyword, die die
   SCREAMING_SNAKE_CASE-Konvention nutzen (Python), brauchen uppercase_name
   (kind var + name.isupper() -> const). name-basiert -> nicht .scm-faehig.
   WICHTIG Go: dort heisst ALL_CAPS/Grossbuchstabe Export, NICHT const -> none.
```

Regel: jeder neue Profil-Eintrag braucht eine dokumentierte Begruendung, warum
er nicht per Capture-Konvention ausdrueckbar ist. Ziel ist ein moeglichst
leeres Profil; Modifier-Sprachen sollen ganz ohne Eintrag auskommen.

### OUT OF SCOPE (S1; bewusst nicht im Kern)

- echte target-Aufloesung namespace-basierter Sprachen -> S4 (Graph kennt
  Repo-Layout). In S1 bleibt target = Modul-/Namespace-Id.
- Typaufloesung, Dispatch, Generics-Semantik -> LSP-Upgrade nach S3.
- anonyme Funktionen/Lambdas als Symbole -> nur benannte Definitionen.
- Makro-/Praeprozessor-Expansion (C/C++ #define, Rust macro!) -> als Symbol
  erfasst, nicht expandiert.
- nicht-strukturelle Sprachen (SQL, HTML/CSS, Shell) -> passen nicht ins
  Modell, kein Kernziel.

## Ist-Zustand und Python-Rework (I-1.85 fasst Bestehendes an)

I-1.85 ist KEIN Greenfield: der bereits implementierte Python-Pfad wird
mit-ueberarbeitet, nicht nur ergaenzt. Betroffen (Stand nach Schritt 1):

```
queries/python/{symbols,imports,calls}.scm   -> auf Capture-Konvention umstellen
core/indexer/registry.py                      -> Profil-Lookup ergaenzen
core/indexer/symbols.py                        -> Kern: Captures statt Knotentypen
core/indexer/imports.py                        -> Kern + import_resolution-Profil
core/indexer/calls.py                          -> Span-Containment + self_keyword
core/indexer/__init__.py                       -> ggf. Exporte
core/ingest.py (_BUILDERS)                     -> sprach-dispatched (Builder-Set
                                                  je Sprache: Py/JS/TS/C# = 3,
                                                  GDScript = 2 ohne dependency_graph)
core/indexer/profiles.py                       -> NEU, Python-Eintrag
tests/test_indexer_{symbols,imports,calls}.py  -> bleiben das Regressionsnetz,
tests/fixtures/python/*                            Erwartungen UNVERAENDERT
```

Die vorhandenen Golden-Erwartungen (symbols/imports/calls) sind der Vertrag: das
Verhalten fuer Python muss byte-identisch bleiben. Aendert sich ein erwarteter
Wert, ist das ein Bug im Refactor, kein erlaubter Output-Wechsel.

## Umsetzung (I-1.85, erledigt 2026-06-29)

Konkrete Entscheidungen beim Bau (alle Python-Golden byte-identisch, Kern
grep-frei von Python-Knotentypen):

- parent (symbols): von den zwei Optionen "@parent ODER Span-Containment" wurde
  @parent gewaehlt. Die .scm setzt @parent in den Methoden-/Klassenattribut-
  Pattern (Klassenname). Span-Containment bleibt fuer caller (call_graph)
  reserviert - dort gibt es kein sauberes @parent. So exakte Python-Paritaet.
- method-vs-function: ueber die .scm wie geplant. Catch-all `@definition.function`
  fuer jede function_definition PLUS verfeinerndes `@definition.method`-Pattern
  (Funktion im Klassenrumpf, direkt ODER dekoriert via Alternation). Der Kern
  dedupt nach Definitionsknoten; hoeherer Pattern-Index gewinnt -> Methode
  schlaegt Funktion. Dekorierte/async Methoden landen so korrekt als method.
- const-vs-var: 4. Profil-Achse const_strategy (none | uppercase_name), NICHT
  generisch im Kern. Korrigiert die fruehere Planungsannahme "genau 3 Achsen":
  Go zwingt dazu. Go hat ein const-Keyword (echte const aus der .scm) UND
  Grossbuchstabe = Export -> eine universelle ALL_CAPS->const-Regel wuerde
  exportierte Go-Vars (z.B. `var X`) falsch zu const machen. Daher: Keyword-
  Sprachen const_strategy=none (const strukturell in .scm), Python=uppercase_name
  (name.isupper(), weil kein Keyword). Belegt im JS-Mini-Smoke: JS unterscheidet
  const/let/var strukturell (kind-Feld), const_strategy bleibt none.
- docstring: generischer Delimiter-Stripper auf dem @doc-Text (String-Praefix
  r/b/f/u, Quote-Paare """/'''/"/' , Kommentar-Delimiter /* */ // /// #).
- visibility: @visibility-Capture hat Vorrang (Modifier-Sprachen), sonst
  Profil-Strategie. Python nutzt underscore_prefix.

## Reihenfolge-Abhaengigkeit (wichtig fuer den Bau)

caller/parent via Span-Containment heisst: symbol_index muss VOR calls/imports
vorliegen. Der Extraktor baut erst die Symboltabelle (name, span, kind, parent),
dann konsumieren calls/imports sie (calls.py tut das heute schon via
extract_symbols; kuenftig liefert die Tabelle auch die Spans fuer Containment).

## Checkliste: Sprache hinzufuegen (Ergebnis von I-1.85)

```
1. PROBE FIRST (Pflicht, nicht optional): Grammar-Name im language-pack pruefen
   (z.B. c_sharp mit Unterstrich) + Knotentypen/Felder/Quantoren sondieren gegen
   die ECHTE Grammar (Probe-Skript, siehe [[_core]]). Hauptaufwand liegt hier.
   Dabei zwei Dinge VORAB klaeren:
   a) Sichtbarkeits-DEFAULT der Sprache (kein-Modifier -> was?). "none" (=public)
      stimmt selten ungeprueft: C#-Member default private, Top-Level internal;
      JS nicht-exportiert = modul-privat. Default bestimmt die visibility_strategy.
   b) Konstrukte, die NICHT sauber capture-bar sind (brauchen Praedikat/Kernlogik)
      -> bewusst als dokumentierte Luecke verschieben (wie JS require()/import()),
      NICHT den Kern aufweichen.
2. queries/<lang>/{symbols,imports,calls}.scm nach Capture-Konvention schreiben
   (@name, @definition.<kind>, @parent, @signature, @param, @doc, @visibility,
   @reference.call + @callee, @import.*). Mechanismen wiederverwenden: Dedup nach
   Knoten + Pattern-Reihenfolge (allgemein -> spezifisch; spaeteres Pattern
   gewinnt) fuer Verfeinerungen.
3. Profil-Eintrag in profiles.py NUR fuer das, was die .scm nicht ausdrueckt
   (visibility_strategy, self_keyword, import_resolution, const_strategy) - mit
   Begruendung "warum nicht .scm".
4. Sprache in Registry registrieren + Builder-Set in der ingest-Dispatch
   eintragen (welche Artefakte die Sprache erzeugt).
5. Tests zweigleisig (siehe Teststrategie): Golden-Fixtures (byte-exakt) UND
   Real-Code-Smoke (kleines echtes Beispiel, Invarianten via tests/_invariants.py)
   unter tests/fixtures/<lang>/, test_*_<lang>.
6. KERN-DIFF: calls.py bleibt strikt git-diff leer (der harte Agnostik-Beleg).
   symbols.py/imports.py duerfen NUR generische, profilgesteuerte Erweiterungen
   bekommen (neue visibility_strategy/import_resolution-Werte, parent-bewusste
   Logik) - NIE sprachspezifisches Inlinen. Jede solche Erweiterung hier
   dokumentieren.
```

## Teststrategie je Artefakt/Sprache (zweigleisig)

Synthetische Golden-Fixtures allein decken nur die Faelle ab, die man sich
ausdenkt. Reale Idiome (vielgestaltige JS-Funktionen, C#-Properties, GDScript-
Annotationen) fallen durch. Daher je Sprache ZWEI Ebenen:

```
1. Golden (synthetisch, byte-exakt): der Vertrag. Kleine, gezielte Fixture ->
   erwartetes JSON exakt. Bestehend fuer Python.
2. Real-Code-Smoke (kleines ECHTES Beispiel): Invarianten/Properties statt
   byte-exakt (robust gegen Code-Aenderungen):
     - kein Crash; partial=False bei gueltigem Code; Determinismus (2x gleich)
     - jedes Symbol: nicht-leerer name, span[0]<=span[1], span in Dateigrenzen
     - method hat parent; arity == count(params); callee_ref in Symbolnamen | None
     - ein paar bekannte Schluessel-Symbole sind vorhanden (nicht erschoepfend)
     - Durchstich durch den Store (put -> get_current)
   Ein wiederverwendbarer Invarianten-Checker deckt alle Sprachen ab.
```

Python dogfooded den eigenen core/ (z.B. core/scope.py, core/secret_scan.py) als
Real-Code-Korpus - deckt sich mit Nutzstufe N1 (Navigation am eigenen Code).
Fuer JS/TS/C#/GDScript je 1-2 kleine idiomatische Beispieldateien. Beispiele
klein halten: die det-Suite muss in Sekunden gruen bleiben.

## Standing-Invariante fuer I-1.9 bis I-1.11 (bindend)

Eine neue Sprache aendert NUR .scm + einen profiles.py-Eintrag + Registrierung +
Fixtures/Tests. Der Kern (symbols/imports/calls.py) bleibt unveraendert. Erzwingt
eine Sprache eine Kern-Aenderung, ist das das Signal eines undichten Abstrakts:
dann das Capture-Vokabular erweitern (bevorzugt) ODER eine begruendete
Profil-Achse ergaenzen (in dieser Notiz dokumentieren) - NIE Sprachspezifisches
in den Kern inlinen. Genau dieser Test (Kern unberuehrt) ist die Abnahme von
I-1.9. Sprach-Besonderheiten je Increment stehen in [[inkremente-schritt-1]]
(I-1.9/1.10/1.11).

Verfeinerung (I-1.9, mit Nutzer): "Kern git-diff leer" gilt strikt fuer calls.py.
symbols.py/imports.py duerfen GENERISCHE, profilgesteuerte Erweiterungen bekommen
(der hier genannte Ausweg), kein language-inlining. Konkret bei I-1.9:
_visibility parent-bewusst + export-Strategie (korrekte JS-Sichtbarkeit war
Vorgabe), relative_path_ext. Details: [[js-ts-umsetzung]].

## Quellen

- TIOBE Index: https://www.tiobe.com/tiobe-index/ (Jun 2026 via
  https://www.techrepublic.com/article/news-tiobe-index-language-rankings/)
- Stack Overflow Developer Survey 2025: https://survey.stackoverflow.co/2025/technology/
- GitHub Octoverse 2025: https://github.blog/news-insights/octoverse/octoverse-a-new-developer-joins-github-every-second-as-ai-leads-typescript-to-1/
