; symbol_index fuer JavaScript - Capture-Konvention (I-1.9).
; Kern unveraendert; nur Captures + Profil. Reihenfolge allgemein -> spezifisch:
; ein spaeteres Pattern verfeinert einen frueheren Treffer DESSELBEN Knotens
; (Kern-Dedup, hoechster Pattern-Index gewinnt). Daher: Bindungen vor
; Funktions-Bindung (Funktion gewinnt), und export-umhuellte Varianten ZULETZT
; (sie tragen @visibility = export -> oeffentlich; Abwesenheit von export ist
; nicht matchbar, der modul-private Default kommt aus profile visibility_strategy).

; ---- Klassen / Funktionen (bare) ----
(class_declaration
  name: (identifier) @name) @definition.class

(function_declaration
  name: (identifier) @name
  parameters: (formal_parameters) @signature) @definition.function

(generator_function_declaration
  name: (identifier) @name
  parameters: (formal_parameters) @signature) @definition.function

; ---- Variablen-Bindungen (bare, NUR Top-Level): const/let/var strukturell ----
; Auf program-Ebene beschraenkt (wie Python module-Ebene): funktionslokale
; Variablen sind keine Symbole. Funktionen/Arrow-Bindungen bleiben ueberall
; erfasst (s.u.), analog zu Pythons Funktions-Catch-all.
(program
  (lexical_declaration
    "const"
    (variable_declarator name: (identifier) @name) @definition.const))

(program
  (lexical_declaration
    "let"
    (variable_declarator name: (identifier) @name) @definition.var))

(program
  (variable_declaration
    (variable_declarator name: (identifier) @name) @definition.var))

; ---- Funktion an eine Bindung (verfeinert const/let/var oben) ----
(variable_declarator
  name: (identifier) @name
  value: [(arrow_function parameters: (formal_parameters) @signature)
          (function_expression parameters: (formal_parameters) @signature)
          (generator_function parameters: (formal_parameters) @signature)]) @definition.function

; ---- Klassen-Member (mit @parent) ----
(class_declaration
  name: (identifier) @parent
  body: (class_body
    (method_definition
      name: (property_identifier) @name
      parameters: (formal_parameters) @signature) @definition.method))

(class_declaration
  name: (identifier) @parent
  body: (class_body
    (method_definition
      name: (private_property_identifier) @name @visibility
      parameters: (formal_parameters) @signature) @definition.method))

(class_declaration
  name: (identifier) @parent
  body: (class_body
    (field_definition
      property: (property_identifier) @name) @definition.var))

(class_declaration
  name: (identifier) @parent
  body: (class_body
    (field_definition
      property: (private_property_identifier) @name @visibility) @definition.var))

; ---- export-umhuellte Varianten (ZULETZT, tragen @visibility) ----
(export_statement
  "export" @visibility
  declaration: (class_declaration name: (identifier) @name) @definition.class)

(export_statement
  "export" @visibility
  declaration: (function_declaration
    name: (identifier) @name
    parameters: (formal_parameters) @signature) @definition.function)

(export_statement
  "export" @visibility
  declaration: (generator_function_declaration
    name: (identifier) @name
    parameters: (formal_parameters) @signature) @definition.function)

(export_statement
  "export" @visibility
  declaration: (lexical_declaration
    "const"
    (variable_declarator name: (identifier) @name) @definition.const))

(export_statement
  "export" @visibility
  declaration: (lexical_declaration
    "let"
    (variable_declarator name: (identifier) @name) @definition.var))

(export_statement
  "export" @visibility
  declaration: (lexical_declaration
    (variable_declarator
      name: (identifier) @name
      value: [(arrow_function parameters: (formal_parameters) @signature)
              (function_expression parameters: (formal_parameters) @signature)]) @definition.function))
