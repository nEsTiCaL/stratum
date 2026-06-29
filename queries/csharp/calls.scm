; call_graph fuer C# - Capture-Konvention (I-1.10, approximativ).
; @reference.call = Aufrufstelle (Span), @callee = aufgerufener Ausdruck
; (Text = callee_raw). caller via Span-Containment, Aufloesung und Kanten-confidence
; im Kern; self ueber profile self_keyword (this). -> calls.py bleibt unveraendert.
(invocation_expression
  function: (_) @callee) @reference.call
