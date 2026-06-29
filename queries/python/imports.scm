; dependency_graph fuer Python, import-level (I-1.5).
; @module / @from_module / @relative = die Modul-Referenz wie geschrieben.
; Der Extraktor-Kern bestimmt Span (umschliessendes Statement), kind und die
; Aufloesung relativer Pfade. Importierte Symbolnamen sind import-level
; irrelevant und werden nicht erfasst.

; import a  |  import a.b
(import_statement
  name: (dotted_name) @module)

; import a as x  (Alias egal, Modul zaehlt)
(import_statement
  name: (aliased_import (dotted_name) @module))

; from x import ...  (absolut)
(import_from_statement
  module_name: (dotted_name) @from_module)

; from . / .mod / ..pkg import ...  (relativ)
(import_from_statement
  module_name: (relative_import) @relative)
