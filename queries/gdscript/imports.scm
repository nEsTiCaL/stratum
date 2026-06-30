; dependency_graph fuer GDScript (I-1.11b). Datei-Abhaengigkeiten ueber res://-Pfade:
; extends "res://..", preload("res://.."), load("res://..").
; @name = der Pfad-String (mit Quotes; der Kern strippt sie wertbasiert), @import.module
; = das umschliessende Statement/der Call (Span). kind einheitlich "module"; die
; Aufloesung steckt im target (Profil import_resolution=res_path: res:// = Repo-Wurzel,
; anderes wie user:// -> target None). preload/load sind KEINE Keywords, sondern
; gewoehnliche Calls -> #eq?-Praedikat auf den Callee-Namen (wie JS require()).
; Bare `extends ClassName` (ohne Pfad) ist KEINE Datei-Abhaengigkeit: braucht die
; projektweite class_name-Tabelle -> erst S4, hier bewusst nicht erfasst.

; extends "res://.." -> Datei-Basisklasse als Abhaengigkeit
(extends_statement
  (string) @name) @import.module

; preload("res://..")
((call
  (identifier) @_fn
  (arguments (string) @name)) @import.module
 (#eq? @_fn "preload"))

; load("res://..") - nur Literal-Pfade; dynamisches load(var) matcht nicht
((call
  (identifier) @_fn
  (arguments (string) @name)) @import.module
 (#eq? @_fn "load"))
