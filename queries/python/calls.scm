; call_graph fuer Python - Capture-Konvention (I-1.85, approximativ).
; @reference.call = die Aufrufstelle (gibt Span). @callee = der aufgerufene
; Ausdruck (Text = callee_raw). caller bestimmt der Kern via Span-Containment
; gegen das symbol_index; die heuristische Aufloesung (callee_ref) und die
; Kanten-confidence ebenfalls (self ueber die Profil-Achse self_keyword).
(call
  function: (_) @callee) @reference.call
