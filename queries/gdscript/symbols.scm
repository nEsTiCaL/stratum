; symbol_index fuer GDScript - Capture-Konvention (I-1.11, reduziert). Kern unveraendert.
; Eigenheit: das FILE ist die Klasse (class_name). Top-Level-Funktionen sind faktisch
; Methoden der Datei-Klasse, syntaktisch aber source-Ebene -> hier als function mit
; parent None gefuehrt (Zugehoerigkeit ist semantisch, S4). method-vs-function kommt
; aus der .scm (zwei Pattern: source-Ebene = function, class_body = method).
; const ist strukturell (const_statement) -> @definition.const. Annotationen
; (@export/@onready) liegen als Kind 'annotations' am variable_statement und werden
; NICHT als Symbol erfasst. Sichtbarkeit per Profil underscore_prefix.

; ---- Datei-Klasse (class_name X) ----
; Eigenstaendiges Pattern (Dateien ohne extends) ZUERST, danach die beiden
; kombinierten Pattern fuer die extends-Signatur: hoeherer Pattern-Index gewinnt
; im Dedup -> die Variante mit @signature verdraengt die signaturlose. class_name
; und extends sind Geschwister auf source-Ebene und kommen in BEIDER Reihenfolge
; vor -> je ein Pattern. extends-Ziel: (type) oder (string) ("res://.." = I-1.11b).
(class_name_statement
  name: (name) @name) @definition.class
(source
  (extends_statement [(type) (string)] @signature)
  (class_name_statement name: (name) @name) @definition.class)
(source
  (class_name_statement name: (name) @name) @definition.class
  (extends_statement [(type) (string)] @signature))

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
