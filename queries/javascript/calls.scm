; call_graph fuer JavaScript - Capture-Konvention (I-1.9, approximativ).
; Selbe Form wie Python: @reference.call = Aufrufstelle (Span), @callee =
; aufgerufener Ausdruck (Text = callee_raw). caller via Span-Containment, Aufloesung
; und Kanten-confidence im Kern; self ueber profile self_keyword (this). new_expression
; (new C()) ist bewusst kein call. -> calls.py bleibt unveraendert.
(call_expression
  function: (_) @callee) @reference.call
