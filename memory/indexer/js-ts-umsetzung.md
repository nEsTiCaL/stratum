---
id: js-ts-umsetzung
title: I-1.9 JavaScript/TypeScript - Stand, Findings, Plan
type: decision
status: open
created: 2026-06-29
updated: 2026-06-29
tags: [indexer, tree-sitter, javascript, typescript]
related: ["[[sprachagnostik]]", "[[_core]]", "[[inkremente-schritt-1]]"]
---

# I-1.9 JavaScript/TypeScript: Stand, Findings, Plan

Arbeitsstand-Notiz fuer den Kaltstart. I-1.9 ist IN ARBEIT, pausiert NACH der
Grammatik-Sondierung und VOR der Implementierung. Hier stehen die getroffenen
Entscheidungen, die sondierten Grammatik-Strukturen (nicht neu sondieren) und der
konkrete Bauplan inkl. der genauen Kern-Edits. Grundlage: [[sprachagnostik]],
[[inkremente-schritt-1]] (I-1.9).

## Wo wir stehen

- Basis-Kontext gelesen, Preflight ok (dep I-1.85 fertig).
- Grammatik javascript/typescript durchsondiert (Ergebnisse unten).
- NOCH NICHTS implementiert/committet. Nichts am Code geaendert seit I-1.85.
- Naechster Schritt: die zwei generischen Kern-Edits (imports.py, symbols.py),
  dann Profile, dann .scm, dann Golden+Smoke.

## Entscheidungen (mit Nutzer abgestimmt)

1. Sichtbarkeit MUSS korrekt wiedergegeben werden (Nutzer-Vorgabe). Konsequenz:
   eine GENERISCHE Erweiterung von symbols.py `_visibility` ist akzeptiert -
   kein language-inlining. Damit ist die I-1.9-Akzeptanz "core git-diff LEER"
   verfeinert zu: calls.py bleibt diff-leer; symbols.py und imports.py bekommen
   NUR generische, profilgesteuerte Erweiterungen (kein JS-Spezialcode). Das
   deckt sich mit der Standing-Invariante in [[sprachagnostik]] (Ausweg:
   "Capture-Vokabular erweitern ODER begruendete Profil-Achse" - NIE inlinen).
2. Grammar-Umfang: NUR JavaScript + TypeScript. tsx verschoben (Spec-Minimum
   "2-3 Grammatiken" mit 2 erfuellt).
3. imports.py: generischer `relative_path_ext`-Zweig (war in I-1.85 als
   Profil-Wert vorgesehen, aber gestubbt). JS-Imports nutzen ihn.
4. require()/dynamic import() VERSCHOBEN: saubere Erfassung braucht
   Praedikat-/Kernlogik (callee-Name-Filter "require"/"import"), was den
   agnostischen Kern kompromittieren wuerde. I-1.9 deckt ESM-Imports + Re-Export
   (export ... from) ab. Dokumentierte S1-Luecke.

## Grammatik-Findings (sondiert, bindend)

### JavaScript Symbolformen
- `function_declaration` name:(identifier) parameters:(formal_parameters).
- `generator_function_declaration` (function*) - eigener Knotentyp.
- `async` ist ein Modifier IM function_declaration, kein eigener Typ.
- Arrow/Expression an Bindung: `(variable_declarator name:(identifier)
  value:[(arrow_function) (function_expression) (generator_function)])`.
  parameters-Feld am value (formal_parameters). Name kommt aus dem Declarator.
  Single-Param-Arrow `x => x` hat KEIN formal_parameters (nur identifier) ->
  signature dann None (akzeptiert).
- `class_declaration` name:(identifier) body:(class_body).
- Member: `method_definition` name:[(property_identifier)|(private_property_identifier)]
  parameters:(formal_parameters); `field_definition` property:(property_identifier).
- `#secret` = `private_property_identifier` (Text inkl. '#').

### export-Formen
- `(export_statement declaration: (function_declaration|class_declaration|
  lexical_declaration ...))`. `export default class W` ebenfalls ueber das
  declaration-Feld (default ist nur ein Token).
- `export { g }` hat KEIN declaration-Feld (Re-Export lokaler Namen, KEINE
  Definition -> ignorieren).
- Exportiertheit ist nur ueber das umschliessende export_statement erkennbar
  (Abwesenheit von export = modul-privat, NICHT matchbar). Loesung: bare-Pattern
  + export-wrapped-Pattern, Dedup (hoeherer Pattern-Index gewinnt), das
  export-wrapped traegt @visibility.

### TypeScript-Konstrukte (zusaetzlich)
- `interface_declaration` name:(type_identifier) -> @definition.interface.
- `type_alias_declaration` name:(type_identifier) -> @definition.type.
- `enum_declaration` name:(identifier) -> @definition.enum.
- namespace -> `internal_module` name:(identifier) -> @definition.namespace.
- `abstract_class_declaration` -> @definition.class.
- `accessibility_modifier` (public/private/protected) als Member-Kind ->
  @visibility.

### Imports
- ESM: `import_statement source:(string (string_fragment))`. string_fragment =
  Specifier OHNE Quotes (raw). Deckt default/named/namespace/side-effect (alle
  haben das source-Feld).
- Re-Export: `export_statement source:(string (string_fragment))`.
- require/dynamic: `require(...)` = call in lexical_declaration; `import(...)` =
  call_expression. -> VERSCHOBEN (s.o.).

### calls
- `call_expression function:(_) @callee` - selbe Form wie Python `call`.
  member: `function:(member_expression object:(identifier|this) property:...)`.
  `this.x()` -> object ist `this` (self_keyword=this). `new Thing()` =
  new_expression (separat, nicht erfasst). -> calls.py BLEIBT diff-leer.

## Bauplan (Reihenfolge)

### 1. Kern-Edit imports.py (generisch) - WAR ALS NAECHSTES DRAN
`_resolve_target`: vor dem kind=="relative"-Zweig einfuegen:
```
if resolution == "relative_path_ext":
    return _resolve_relative_ext(raw, file_path)
```
Neue Funktion `_resolve_relative_ext(raw, file_path)`: nur raw mit "./"/"../"
aufloesen (gegen Dateiverzeichnis, ../ steigt auf, ueber Wurzel -> None), sonst
(bare specifier) -> None. KEINE Endungs-/index-Aufloesung in S1 (das ist S4).
Python-Pfad (relative_path) bleibt unveraendert -> Golden byte-identisch.

### 2. Kern-Edit symbols.py (generisch) `_visibility`
Signatur um `parent` erweitern, Aufrufstelle in `_build` anpassen. Logik:
```
if vis_nodes:
    token = vis_nodes[0].text.decode()
    return "private" if token.startswith("#") or token in ("private","protected") else "public"
if strategy == "underscore_prefix": ...        # unveraendert (Python)
if strategy == "uppercase_export": ...          # unveraendert
if strategy == "export":
    return "public" if parent else "private"     # Top-Level braucht export-Marker
return "public"                                  # "none"
```
Python nutzt underscore_prefix, vis_nodes leer -> Golden byte-identisch.
parent unterscheidet Member (public-Default) von Top-Level (modul-privat).

### 3. profiles.py
- "javascript": visibility_strategy="export", self_keyword="this",
  import_resolution="relative_path_ext", const_strategy="none".
- "typescript": identisch (Member-Modifier via @visibility, Top-Level via export).
- (Das aktuelle provisorische "javascript"-Profil mit visibility_strategy="none"
  auf "export" umstellen.) Registry _PRODUCER_SHORT hat js/ts schon.

### 4. queries/javascript/{symbols,imports,calls}.scm
- symbols: bare-Pattern je Form + export-wrapped-Variante (Dedup, export-wrapped
  LETZTES/hoechstes Pattern -> traegt @visibility). Methoden: @parent vom
  class_declaration-name; accessibility_modifier? @visibility; #-Member -> name-
  Knoten zusaetzlich als @visibility. const/let/var strukturell (wie Mini-Smoke).
- imports: `(import_statement source:(string (string_fragment) @name)) @import.module`
  + `(export_statement source:(string (string_fragment) @name)) @import.module`.
  kind einheitlich "module"; Relativitaet steckt im target (relative_path_ext:
  ./-> Pfad, bare -> None).
- calls: `(call_expression function:(_) @callee) @reference.call`.

### 5. queries/typescript/{symbols,imports,calls}.scm
JS-Patterns + interface/type/enum/namespace + abstract_class. imports/calls ~= JS.

### 6. ingest.py
_EXTENSION_LANGUAGE += {".js":"javascript", ".ts":"typescript"}; _BUILDER_SETS
+= js/ts (je 3 Builder). (Optional, vervollstaendigt Dispatch.)

### 7. Tests (zweigleisig, [[sprachagnostik]] Teststrategie)
- Golden je Artefakt fuer JS und TS (Fixtures unter tests/fixtures/javascript|
  typescript/, Erwartung byte-exakt - Output erst per Extraktion erzeugen, von
  Hand verifizieren, dann als Golden festschreiben).
- Real-Code-Smoke via tests/_invariants.py (vorhandener Checker).
- Nachweis: calls.py git-diff LEER; symbols.py/imports.py nur die o.g.
  generischen Diffs.

## Offene Punkte / Risiken

- Double-Capture eines Knotens als @name UND @visibility (fuer #-Member) muss
  in tree-sitter verifiziert werden (`(private_property_identifier) @name @visibility`
  oder zwei Member-Pattern). Beim Bau zuerst gegen die Grammar pruefen.
- Pattern-Reihenfolge im symbols.scm ist kritisch (Dedup = hoechster
  Pattern-Index gewinnt): const/var -> Funktion-Bindung -> bare decl/class ->
  export-wrapped Varianten als LETZTE.
- TS abstract/overloads: Arity (count @param) ist NICHT im symbol_index-Schema
  (kein arity-Feld); Overload-Unterscheidung passiert ueber scope, nicht hier.

## Akzeptanz-Verfeinerung (festhalten)

I-1.9-Akzeptanz "core git-diff LEER" gilt strikt fuer calls.py. symbols.py und
imports.py duerfen GENERISCHE, profilgesteuerte Erweiterungen bekommen (hier:
_visibility parent-bewusst + Token-Klassifikation + export-Strategie;
relative_path_ext). Das ist kein Bruch der Sprachagnostik, sondern der in
[[sprachagnostik]] vorgesehene Ausweg (kein language-inlining). Begruendung:
korrekte Sichtbarkeit war Nutzer-Vorgabe und ist ohne Member-vs-Top-Level-
Kontext nicht darstellbar.
