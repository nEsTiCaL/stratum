; dependency_graph fuer TypeScript - Capture-Konvention (I-1.9).
; @name = der Modul-Specifier (string_fragment, ohne Quotes) = raw. @import.module
; = das umschliessende Statement (Span). kind einheitlich "module"; die Relativitaet
; steckt im target (Profil import_resolution=relative_path_ext: ./x bzw. ../x werden
; gegen den Dateipfad aufgeloest, bare Specifier wie 'react' -> extern, target None).
; Erfasst ESM-Importe (default/named/namespace/side-effect) und Re-Exporte
; (export ... from). require()/dynamic import() sind in S1 NICHT erfasst (braeuchten
; callee-Name-Praedikate; dokumentierte Luecke, siehe js-ts-umsetzung.md).

(import_statement
  source: (string (string_fragment) @name)) @import.module

(export_statement
  source: (string (string_fragment) @name)) @import.module
