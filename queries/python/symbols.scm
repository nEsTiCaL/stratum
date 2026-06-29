; symbol_index fuer Python - Capture-Konvention (I-1.85, tags.scm-Stil).
; Der Extraktor-Kern liest NUR die Capture-Namen, keine Knotentypen:
;   @name              Bezeichner der Definition
;   @definition.<kind> Definitionsknoten; <kind> (class|function|method|var) ist
;                      der Suffix, den der Kern als String uebernimmt
;   @parent            Name des umschliessenden Scopes (nur wo zutreffend)
;   @signature         Signaturknoten (Parameter bzw. Basisklassen), Text verbatim
;   @doc               Doc-Knoten; der Kern entfernt Delimiter generisch
; Definitions-Pattern sind allgemein -> spezifisch geordnet: ein spaeteres
; Pattern verfeinert einen frueheren Treffer desselben Knotens (Kern-Dedup nach
; Knoten, hoeherer Pattern-Index gewinnt). Methode verfeinert so Funktion.

; Klassen (Basisklassen als @signature, Docstring als @doc)
(class_definition
  name: (identifier) @name
  superclasses: (argument_list)? @signature
  body: (block . (string)? @doc)) @definition.class

; Funktionen - Catch-all fuer jede function_definition (auch Methoden)
(function_definition
  name: (identifier) @name
  parameters: (parameters) @signature
  body: (block . (string)? @doc)) @definition.function

; Methoden - function_definition im Klassenrumpf (direkt oder dekoriert);
; traegt @parent = Klassenname und verfeinert die Catch-all-Funktion.
(class_definition
  name: (identifier) @parent
  body: (block
    [(function_definition
       name: (identifier) @name
       parameters: (parameters) @signature
       body: (block . (string)? @doc)) @definition.method
     (decorated_definition
       (function_definition
         name: (identifier) @name
         parameters: (parameters) @signature
         body: (block . (string)? @doc)) @definition.method)]))

; Modulebene: Zuweisung an einen einfachen Namen (var; ALL_CAPS -> const im Kern)
(module
  (assignment
    left: (identifier) @name) @definition.var)

; Klassenebene: Attribut-Zuweisung an einen einfachen Namen, traegt @parent
(class_definition
  name: (identifier) @parent
  body: (block
    (assignment
      left: (identifier) @name) @definition.var))
