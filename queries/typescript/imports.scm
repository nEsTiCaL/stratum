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

; CommonJS require("x") - via #eq?-Praedikat auf den Callee-Namen
(call_expression
  function: (identifier) @_req
  arguments: (arguments (string (string_fragment) @name))
  (#eq? @_req "require")) @import.module

; dynamischer Import import("x") - strukturell (import-Keyword als Callee)
(call_expression
  function: (import)
  arguments: (arguments (string (string_fragment) @name))) @import.module
