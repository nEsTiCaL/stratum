; call_graph fuer GDScript - Capture-Konvention (I-1.11, grob/approximativ).
; GDScript-Calls weichen ab: bare `foo()` = (call (identifier) ...) OHNE function:-Feld;
; member `obj.method()` = (attribute (attribute_call ...)). Daher zwei Pattern.
; bare Calls loesen via Heuristik gegen lokale Defs auf; member-Calls werden erfasst,
; bleiben aber callee_ref NULL (callee_raw enthaelt den Aufruf inkl. Klammern, die
; self-Heuristik greift hier nicht - bewusst "grobe calls" laut Spec). calls.py bleibt
; unveraendert.
(call
  (identifier) @callee) @reference.call

(attribute
  (attribute_call)) @callee @reference.call
