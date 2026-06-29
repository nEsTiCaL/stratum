; symbol_index fuer JavaScript - Mini-Umfang (I-1.85 Agnostik-Beleg).
; Belegt, dass der Extraktor-Kern grammar-agnostisch ist: eine zweite Grammar
; ohne jede Kern-Aenderung. Voller JS/TS-Umfang (Funktionsformen, Imports,
; Sichtbarkeit via export, calls) folgt in I-1.9; hier nur die Grundformen.
; Capture-Konvention wie bei Python (@name, @definition.<kind>, @parent, @signature).

(class_declaration
  name: (identifier) @name) @definition.class

(function_declaration
  name: (identifier) @name
  parameters: (formal_parameters) @signature) @definition.function

(class_declaration
  name: (identifier) @parent
  body: (class_body
    (method_definition
      name: (property_identifier) @name
      parameters: (formal_parameters) @signature) @definition.method))

; const/let/var strukturell unterschieden (JS hat ein const-Keyword) - der Kern
; braucht hier KEINE Namensheuristik (profile const_strategy=none).
(lexical_declaration
  "const"
  (variable_declarator
    name: (identifier) @name)) @definition.const

(lexical_declaration
  "let"
  (variable_declarator
    name: (identifier) @name)) @definition.var

(variable_declaration
  (variable_declarator
    name: (identifier) @name)) @definition.var
