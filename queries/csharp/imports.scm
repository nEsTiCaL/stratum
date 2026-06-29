; dependency_graph fuer C# - Capture-Konvention (I-1.10).
; using <Namespace>; -> @name = Namespace-Referenz (identifier oder qualified_name),
; @import.module = das using_directive (Span). kind "module". Profil
; import_resolution=namespace_passthrough: target = rohe Namespace-Id, KEINE
; FS-Aufloesung in S1 (echte Aufloesung ueber Repo-Layout erst S4).
; using static / using Alias = ... sind in S1 nicht gesondert behandelt.

(using_directive
  (identifier) @name) @import.module

(using_directive
  (qualified_name) @name) @import.module
