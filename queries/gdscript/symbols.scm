; symbol_index fuer GDScript - Capture-Konvention (I-1.11, reduziert). Kern unveraendert.
; Eigenheit: das FILE ist die Klasse (class_name). Top-Level-Funktionen sind faktisch
; Methoden der Datei-Klasse, syntaktisch aber source-Ebene -> hier als function mit
; parent None gefuehrt (Zugehoerigkeit ist semantisch, S4). method-vs-function kommt
; aus der .scm (zwei Pattern: source-Ebene = function, class_body = method).
; const ist strukturell (const_statement) -> @definition.const. Annotationen
; (@export/@onready) liegen als Kind 'annotations' am variable_statement und werden
; NICHT als Symbol erfasst. Sichtbarkeit per Profil underscore_prefix.

; ---- Datei-Klasse (class_name X) ----
(class_name_statement
  name: (name) @name) @definition.class

; ---- Innere Klasse (optionales inline extends als signature) ----
(class_definition
  name: (name) @name
  (extends_statement (type) @signature)?) @definition.class

; ---- Top-Level-Funktionen (source-Ebene -> function, parent None) ----
(source
  (function_definition
    name: (name) @name
    parameters: (parameters) @signature) @definition.function)

; ---- Methoden (im class_body, @parent = Klassenname) ----
(class_definition
  name: (name) @parent
  body: (class_body
    (function_definition
      name: (name) @name
      parameters: (parameters) @signature) @definition.method))

; ---- Top-Level var/const ----
(source
  (variable_statement name: (name) @name) @definition.var)
(source
  (const_statement name: (name) @name) @definition.const)

; ---- Klassen-Member var/const ----
(class_definition
  name: (name) @parent
  body: (class_body
    (variable_statement name: (name) @name) @definition.var))
(class_definition
  name: (name) @parent
  body: (class_body
    (const_statement name: (name) @name) @definition.const))

; ---- Signale und Enums ----
(signal_statement
  name: (name) @name
  parameters: (parameters)? @signature) @definition.signal

(enum_definition
  name: (name) @name) @definition.enum
