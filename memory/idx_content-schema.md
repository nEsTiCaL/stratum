# jsonb-Content-Schema der drei det-Artefakttypen

Welche Felder stehen im `content` (jsonb) von symbol_index/dependency_graph/
call_graph? N1 (`devcli index`) zeigt nur deklarierte Symbole, NICHT die
Datenform des gespeicherten jsonb-Inhalts (Sub-Struktur, analog dem bekannten
Provenance-Sub-Modell-Fund, siehe `ops_n1-queries`). Quelle der Wahrheit:
core/indexer/{symbols,imports,calls}.py.

## symbol_index

```
content = {"symbols": [ {kind, name, span:[start,end], parent, docstring,
                          signature, visibility}, ... ]}
```

`parent` = umschliessendes Symbol (Klassenname) oder null. `span` 1-indexiert,
inklusive Endzeile.

## dependency_graph

```
content = {"imports": [ {raw, target, kind, span:[start,end]}, ... ]}
```

`kind` in {module, symbol, relative}. `target` aufgeloester Pfad/Modulname,
None wenn absolut/unaufgeloest (kein LSP, R1). `raw` = Rohtext des Import-Namens.

## call_graph

```
content = {"calls": [ {caller, callee_raw, callee_ref, span:[start,end],
                        confidence}, ... ]}
```

`caller` = qualifizierter Name (`Klasse.methode` oder Funktionsname) oder
None, `callee_ref` None wenn unaufgeloest (confidence 0.0), sonst aufgeloester
Name (Heuristik: LOCAL_DEF 0.5, SELF_METHOD 0.6). Einziges det-Artefakt mit
Kanten-confidence (I-1.6, R1).

## Wann lesen

Sobald ein Modul den `content` eines dieser Artefakttypen konsumiert (z.B.
Bundling I-3.2, Hotspot-Selektor, spaeter Graph-CTE S4) diese Felder nutzen
statt symbols.py/imports.py/calls.py erneut zu lesen.
