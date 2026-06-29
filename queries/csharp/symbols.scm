; symbol_index fuer C# - Capture-Konvention (I-1.10). Kern unveraendert.
; Sichtbarkeit ueber (modifier)* @visibility (mehrere Modifier moeglich, der Kern
; scannt sie auf Access-Keywords); fehlt ein Access-Modifier -> Profil-Default
; (default_private: Member privat, Top-Level-Typ internal). Member-@parent ueber
; einen Wildcard-Typknoten (_ name: ... body: (declaration_list ...)).
; Bekannte S1-Naeherungen: Interface-Member tragen keinen Modifier -> private
; (statt implizit public); const-Felder -> var (const ist nur ein Modifier,
; strukturell nicht von var trennbar).

; ---- Typdeklarationen (Top-Level oder im namespace; kind explizit) ----
(namespace_declaration
  name: [(qualified_name) (identifier)] @name) @definition.namespace

(class_declaration
  (modifier)* @visibility
  name: (identifier) @name) @definition.class

(interface_declaration
  (modifier)* @visibility
  name: (identifier) @name) @definition.interface

(struct_declaration
  (modifier)* @visibility
  name: (identifier) @name) @definition.struct

(enum_declaration
  (modifier)* @visibility
  name: (identifier) @name) @definition.enum

(record_declaration
  (modifier)* @visibility
  name: (identifier) @name) @definition.record

; ---- Member (parent = umschliessender Typname via Wildcard-Knoten) ----
(_
  name: (identifier) @parent
  body: (declaration_list
    (method_declaration
      (modifier)* @visibility
      name: (identifier) @name
      parameters: (parameter_list) @signature) @definition.method))

(_
  name: (identifier) @parent
  body: (declaration_list
    (constructor_declaration
      (modifier)* @visibility
      name: (identifier) @name
      parameters: (parameter_list) @signature) @definition.constructor))

(_
  name: (identifier) @parent
  body: (declaration_list
    (property_declaration
      (modifier)* @visibility
      name: (identifier) @name) @definition.property))

(_
  name: (identifier) @parent
  body: (declaration_list
    (field_declaration
      (modifier)* @visibility
      (variable_declaration
        (variable_declarator name: (identifier) @name))) @definition.var))
