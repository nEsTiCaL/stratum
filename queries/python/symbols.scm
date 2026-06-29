; symbol_index fuer Python (I-1.4).
; Konvention: @name = Bezeichner, @<kind> = der Definitionsknoten (gibt Span +
; Grund-Art). Methode-vs-Funktion und parent leitet der Extraktor-Kern aus den
; Vorfahren ab (eine Mapping-Logik fuer alle Sprachen), nicht die Query.

; Klassen
(class_definition
  name: (identifier) @name) @class

; Funktionen und Methoden (jede function_definition, Verschachtelung egal)
(function_definition
  name: (identifier) @name) @function

; Modulebene: Zuweisung an einen einfachen Namen (assignment ist hier direktes
; Kind von module/block, ohne expression_statement-Wrapper).
(module
  (assignment
    left: (identifier) @name) @var)

; Klassenebene: Attribut-Zuweisung an einen einfachen Namen
(class_definition
  body: (block
    (assignment
      left: (identifier) @name) @var))
