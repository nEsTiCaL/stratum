; dependency_graph fuer Python - Capture-Konvention (I-1.85).
; @name = Modul-Referenz wie geschrieben (raw). @import.<kind> = das umschliessende
; Statement (gibt Span); <kind> (module|symbol|relative) ist der Suffix, den der
; Kern uebernimmt. Die Aufloesung des target macht der Kern ueber die Profil-Achse
; import_resolution (Python: relative -> Pfad, absolut -> None).

; import a  |  import a.b
(import_statement
  name: (dotted_name) @name) @import.module

; import a as x  (Alias egal, Modul zaehlt)
(import_statement
  name: (aliased_import (dotted_name) @name)) @import.module

; from x import ...  (absolut)
(import_from_statement
  module_name: (dotted_name) @name) @import.symbol

; from . / .mod / ..pkg import ...  (relativ)
(import_from_statement
  module_name: (relative_import) @name) @import.relative
