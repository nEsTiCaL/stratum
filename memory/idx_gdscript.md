# I-1.11 GDScript: Findings, Plan

## Stand: ERLEDIGT (I-1.11 fertig, 2026-06-30)

Umgesetzt wie geplant. queries/gdscript/{symbols,calls}.scm + Profil
(underscore_prefix/self/const-none); ingest .gd -> 2 Builder (symbol_index +
call_graph, KEIN dependency_graph). calls.py git-diff LEER (Agnostik ueber 5
Sprachen); kein GDScript-Knotentyp im Kern. 157 Tests gruen. Risiken aufgeloest:
member-Calls (self.x()) bewusst callee_ref NULL (grobe calls, calls.py unberuehrt),
callee_raw enthaelt den Aufruf-Text; Datei-Klasse-Quirk wie geplant (top-level-
Member parent None). Golden + Real-Code-Smoke + 2-Builder-ingest-Test.

Findings + Plan unten als Referenz.

## I-1.11b: GDScript auf Paritaet (ERLEDIGT 2026-06-30)

Folge-Inkrement, weil die Reduktion (kein dependency_graph, self-Calls unaufgeloest)
GDScripts det-Graph systematisch duenner machte als bei C#/Python -> schlechtere
Grundierung des Agenten auf GDScript-Repos. Der Reduktions-Beleg (Builder-Set-
Dispatch traegt 2 vs 3) war erbracht, also Promotion zum First-Class-Buerger. 160
Tests gruen.

### Sondierung (neue Knoten-Shapes, has_error=False)
- `extends "res://x.gd"` -> `(extends_statement (string))`; der `string`-Knoten hat
  KEIN `string_content`-Kind (anders als JS `string_fragment`), nur zwei `"`-Token
  + anonymer Inhalt -> Text inkl. Quotes, im Kern wertbasiert strippen.
- `extends BaseActor` -> `(extends_statement (type (identifier)))` (kein Pfad).
- `preload(...)`/`load(...)` -> gewoehnliche `(call (identifier) (arguments (string)))`;
  preload/load sind KEINE Keywords -> `#eq?`-Praedikat (wie JS require()).
- `class_name` und `extends` sind Geschwister auf `source`-Ebene, BEIDE Reihenfolgen
  kommen vor (extends-first ist haeufig).

### Drei Workstreams
- A self-Calls: zwei neue Profil-Achsen statt Sprachname im Kern (Agnostik gewahrt):
  `self_call_match` (strict|lenient; GDScript lenient, weil callee_raw die Klammern
  traegt -> re.match statt fullmatch) und `self_module_fallback` (bool; GDScript True:
  self.m() ohne Klassen-Scope loest gegen Top-Level-Funktionen = Datei-als-Klasse).
  Py/JS/TS/C# erben die Defaults (strict/False) -> null Regression.
- B extends-Signatur: Datei-Klasse traegt jetzt die Basisklasse. Zwei kombinierte
  source-Pattern (je Reihenfolge) + Standalone; hoeherer Pattern-Index gewinnt im
  Dedup -> Variante mit @signature verdraengt die signaturlose. Rein .scm.
- C dependency_graph: queries/gdscript/imports.scm (extends-String + preload/load
  via #eq?) + neue import_resolution-Strategie `res_path` (res:// = Repo-Wurzel,
  Praefix abschneiden; user:///dynamisch -> target None) + generisches `_unquote`
  im Kern (wertbasiert, trifft nur GDScript) + ingest .gd -> 3 Builder (_ALL_THREE).

### Bewusst NICHT gemacht: Datei-als-Klasse im Symbol-Modell (-> S4)
Die saubere Loesung (Top-Level-Funktionen als kind=method, parent=class_name) wurde
verworfen, weil sie: (1) die bare-Call-LOCAL_DEF-Aufloesung BRICHT (module_defs
filtert parent is None), (2) ohne class_name unvollstaendig ist (anonyme Datei-
Klassen), (3) eine bewusste S1-Grenze halb und ohne die projektweite class_name-
Tabelle vorzieht. Der calls.py-Fallback loest den Aufruf, ohne kind/parent
umzustellen. OFFEN fuer S4: Datei-als-Klasse ganzheitlich modellieren (mit
class_name-Tabelle, cross-file). Bis dahin: Top-Level-Member parent None,
callee_ref des self-Calls = bare Funktionsname. Artefakte sind Cache -> S4
re-indiziert, keine Migration.

### Akzeptierte S1-Grenzen (Rest)
- bare `extends ClassName` (kein Pfad) -> keine Datei-Abhaengigkeit (class_name-
  Tabelle erst S4).
- self.m() callee_ref = bare Name (nicht "Klasse.m"), weil Datei-Klasse ggf.
  namenlos; zeigt korrekt auf das Top-Level-Funktionssymbol.

### Wichtige Folge fuer die Agnostik-Erzaehlung
calls.py ist ab I-1.11b NICHT mehr git-diff-leer. Der Beleg "5 Sprachen, calls.py
nie angefasst" endet hier - durch eine GENERISCHE, profilgesteuerte Aenderung (kein
language-inlining), also Agnostik intakt. Regel angeglichen an symbols.py/imports.py
(seit I-1.9 generisch erweiterbar). Siehe `idx_sprachagnostik` (aktualisiert).

---

Vorab-Analyse + Bauplan. GDScript ist bewusst REDUZIERT: nur symbol_index +
call_graph (2 Builder, KEIN dependency_graph). Grammar 'gdscript' (on-demand,
siehe `env_core`). Reifegrad galt als gering - die Sondierung zeigt aber
eine saubere, gut benannte Grammar.

## Grammatik-Findings (sondiert, has_error=False auf repraesentativem Code)

Top-Level-Statements sind direkte Kinder von `source` (das FILE ist die Klasse):
- `class_name_statement name: (name)` - Name der Datei-Klasse (`class_name X`).
- `extends_statement (type (identifier))` - Basisklasse (`extends Node`).
- `signal_statement name: (name) parameters: (parameters)?` - Signal.
- `const_statement name: (name) value:` - Konstante (STRUKTURELL -> @definition.const).
- `variable_statement [annotations] name: (name) value:` - Variable; @export/@onready
  liegen im Kind `annotations` (KEIN eigenes Symbol).
- `enum_definition name: (name) body: (enumerator_list (enumerator left: (identifier)))`.
- `function_definition name: (name) parameters: (parameters) body:`.
- `class_definition name: (name) [extends_statement] body: (class_body ...)` - innere
  Klasse; bei `class Inner extends Base:` ist extends_statement INLINE als Kind.

Calls (fuer call_graph, MUSS noch im Bau finalisiert werden):
- bare: `(call (identifier) (arguments))` - KEIN `function:`-Feld wie Python/JS/C#!
- member: `(attribute (identifier) (attribute_call (identifier) (arguments)))` -
  `self.die()` -> attribute mit identifier "self" + attribute_call "die". Die
  callee-Form weicht ab -> calls.scm/callee-Capture sorgfaeltig bauen und gegen
  die Heuristik (self_keyword=self) pruefen. Ziel weiterhin: calls.py UNVERAENDERT
  (nur .scm); falls die abweichende callee-Struktur das verhindert, ist das ein
  Signal -> Capture-Vokabular pruefen, NICHT calls.py inlinen.

## Profil (gdscript)

```
visibility_strategy = underscore_prefix   (fuehrender _ -> private; bekannte
   Unschaerfe: _ready/_process u.a. sind Engine-Callbacks, _-praefix -> als private
   gewertet obwohl faktisch public - akzeptiert, syntaktische Approximation)
self_keyword        = self
const_strategy      = none                (const_statement strukturell -> @definition.const)
import_resolution   = (unbenutzt)          GDScript hat KEINEN dependency_graph-
   Builder; Feld ist Pflicht in LanguageProfile -> Platzhalter
   (namespace_passthrough), wird nie aufgerufen.
```

## Bauplan

1. queries/gdscript/symbols.scm (Capture-Konvention):
   - class_name_statement -> @definition.class (Datei-Klasse), @name. signature
     None (das sibling extends_statement laesst sich nicht in dieselbe Pattern
     ziehen -> Datei-Klasse ohne extends-Signature; dokumentierte Naeherung).
   - class_definition -> @definition.class; bei inline extends_statement ->
     @signature = Basis. Member im class_body via @parent = Klassenname.
   - function_definition -> @definition.function (top-level) bzw. im class_body
     mit @parent -> der Kern macht KEIN method-Downgrade; method-vs-function kommt
     wie bei Python aus der .scm: zwei Pattern (top-level function, class_body
     method). (Achtung: GDScript-Datei-Klasse: top-level-Funktionen sind faktisch
     Methoden der Datei-Klasse, syntaktisch aber source-Ebene -> als function
     parent None gefuehrt; Zugehoerigkeit ist semantisch, S4. Dokumentieren.)
   - variable_statement -> @definition.var (top-level + class_body via @parent).
   - const_statement -> @definition.const.
   - signal_statement -> @definition.signal (NEUES kind), @signature aus parameters.
   - enum_definition -> @definition.enum.
   - Annotationen NICHT als Symbol erfassen.
2. queries/gdscript/calls.scm: @reference.call + @callee fuer beide Call-Formen
   (bare call + attribute/attribute_call). Gegen Heuristik (LOCAL_DEF, self.method)
   pruefen; callee_raw-Text muss "self.die" o.ae. ergeben, damit das self_keyword
   greift.
3. profiles.py: gdscript-Eintrag (s.o.). registry _PRODUCER_SHORT: gdscript -> "gd".
4. ingest.py: ".gd" -> "gdscript"; BUILDER_SET gdscript = (symbol_index_result,
   call_graph_result) - NUR 2 Builder (macht die Sprach-Dispatch konkret).
5. Tests: Golden (symbol_index, call_graph) + Real-Code-Smoke (Invarianten-Checker;
   _KINDS enthaelt "signal" bereits). KERN-DIFF: calls.py strikt leer; symbols.py
   nur falls generisch noetig (erwartet: gar nicht).

## Offene Risiken

- Abweichende callee-Struktur (attribute_call) - vor dem Golden gegen die
  Heuristik verifizieren; ggf. Capture-Vokabular statt calls.py-Aenderung.
- Datei-Klasse vs. source-Ebene: top-level-Member parent None (Zugehoerigkeit
  zur class_name-Klasse semantisch, nicht modelliert in S1).
- ingest-Builder-Set mit 2 Eintraegen: Trace hat dann 2 index-Zeilen (Test
  anpassen, falls ein GDScript-ingest-Test hinzukommt).
