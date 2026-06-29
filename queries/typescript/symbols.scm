; symbol_index fuer TypeScript - Capture-Konvention (I-1.9).
; Superset von JavaScript: dieselben Funktions-/Klassen-/Bindungs-Pattern plus
; TS-Konstrukte (interface/type/enum/namespace, abstract class) und
; Member-Sichtbarkeit ueber accessibility_modifier. Kern unveraendert.
; Reihenfolge allgemein -> spezifisch (Dedup, hoechster Pattern-Index gewinnt);
; export-umhuellte Varianten zuletzt (tragen @visibility=export -> oeffentlich).

; ---- Klassen / Funktionen (bare) ----
(class_declaration
  name: (type_identifier) @name) @definition.class

(abstract_class_declaration
  name: (type_identifier) @name) @definition.class

(function_declaration
  name: (identifier) @name
  parameters: (formal_parameters) @signature) @definition.function

(generator_function_declaration
  name: (identifier) @name
  parameters: (formal_parameters) @signature) @definition.function

; ---- TS-Typdeklarationen ----
(interface_declaration
  name: (type_identifier) @name) @definition.interface

(type_alias_declaration
  name: (type_identifier) @name) @definition.type

(enum_declaration
  name: (identifier) @name) @definition.enum

(internal_module
  name: (identifier) @name) @definition.namespace

; ---- Variablen-Bindungen (bare, NUR Top-Level) ----
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

; ---- Funktion an eine Bindung (verfeinert const/let/var) ----
(variable_declarator
  name: (identifier) @name
  value: [(arrow_function parameters: (formal_parameters) @signature)
          (function_expression parameters: (formal_parameters) @signature)
          (generator_function parameters: (formal_parameters) @signature)]) @definition.function

; ---- Klassen-Member (mit @parent); accessibility_modifier optional als @visibility ----
(class_declaration
  name: (type_identifier) @parent
  body: (class_body
    (method_definition
      (accessibility_modifier)? @visibility
      name: (property_identifier) @name
      parameters: (formal_parameters) @signature) @definition.method))

(class_declaration
  name: (type_identifier) @parent
  body: (class_body
    (method_definition
      name: (private_property_identifier) @name @visibility
      parameters: (formal_parameters) @signature) @definition.method))

(class_declaration
  name: (type_identifier) @parent
  body: (class_body
    (public_field_definition
      (accessibility_modifier)? @visibility
      name: (property_identifier) @name) @definition.var))

(class_declaration
  name: (type_identifier) @parent
  body: (class_body
    (public_field_definition
      name: (private_property_identifier) @name @visibility) @definition.var))

; ---- Interface-Member (mit @parent) ----
(interface_declaration
  name: (type_identifier) @parent
  body: (interface_body
    (method_signature
      name: (property_identifier) @name
      parameters: (formal_parameters) @signature) @definition.method))

(interface_declaration
  name: (type_identifier) @parent
  body: (interface_body
    (property_signature
      name: (property_identifier) @name) @definition.property))

; ---- export-umhuellte Varianten (ZULETZT, tragen @visibility) ----
(export_statement
  "export" @visibility
  declaration: (class_declaration name: (type_identifier) @name) @definition.class)

(export_statement
  "export" @visibility
  declaration: (abstract_class_declaration name: (type_identifier) @name) @definition.class)

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
  declaration: (interface_declaration name: (type_identifier) @name) @definition.interface)

(export_statement
  "export" @visibility
  declaration: (type_alias_declaration name: (type_identifier) @name) @definition.type)

(export_statement
  "export" @visibility
  declaration: (enum_declaration name: (identifier) @name) @definition.enum)

(export_statement
  "export" @visibility
  declaration: (internal_module name: (identifier) @name) @definition.namespace)

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
