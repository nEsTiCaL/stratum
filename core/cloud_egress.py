"""Cloud-Egress-Vorbereitung (I-3.6): Bundle bauen + Redaction-Gate.

Verdrahtet I-3.2 (bundling) und I-3.3/3.4 (redaction_gate) fuer den Cloud-Pfad
des Workers. Position fix: Bundling -> Gate -> Adapter. IO-frei bis auf den
injizierten source_provider (Hotspot-Snippets); die Trace-Zeile schreibt der
Aufrufer (Worker), nicht diese Funktion -- Vertrag wie select_hotspots/gate.

Rueckgabe je Entscheidung:
  PASS   -> cache_prefix = Core Bundle (stabil, cache-faehig), tail = Task+Hotspots.
            Zusammen byte-gleich mit dem gescannten Bundle -> Redaction bleibt gueltig.
  REDACT -> cache_prefix None (Secret evtl. im Core -> kein Cache), tail = ganzes
            redigiertes Bundle.
  BLOCK  -> cache_prefix/tail None; kein Egress, Knoten bleibt unresolved.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.bundling import (
    Bundle,
    TaskContext,
    build_core_bundle,
    select_hotspots,
    serialize_core_bundle,
    serialize_hotspots,
    serialize_task_context,
)
from core.redaction_gate import Decision, RedactionReport, gate
from core.repository import Repository
from core.secret_scan import EgressPolicy, Sensitivity


@dataclass(frozen=True)
class CloudEgress:
    """Ergebnis der Egress-Vorbereitung fuer den Worker."""

    decision: Decision
    cache_prefix: str | None
    tail: str | None
    report: RedactionReport


def prepare_cloud_egress(
    repo: Repository,
    scope: str,
    *,
    question: str,
    sensitivity: Sensitivity,
    policy: EgressPolicy,
    source_provider: Callable[[str], str],
    prior_result: dict[str, Any] | None = None,
) -> CloudEgress:
    """Baut das Bundle fuer scope (Core + Task-Kontext + Hotspots) und laesst es
    durchs Redaction-Gate. Liefert die fertig zerlegten Strings fuer den
    CloudAdapter (cache_prefix/tail) oder BLOCK ohne Nutzlast."""
    scopes = [scope]
    core = build_core_bundle(repo, scopes)
    ctx = TaskContext(question=question, prior_result=prior_result)
    hotspots = select_hotspots(repo, scopes, source_provider)
    bundle = Bundle(core=core, task_context=ctx, hotspots=hotspots)

    decision, _gated, report = gate(bundle, sensitivity, policy)

    if decision == Decision.BLOCK:
        return CloudEgress(decision, None, None, report)

    if decision == Decision.REDACT:
        redacted = report.redacted_content or b""
        return CloudEgress(decision, None, redacted.decode("utf-8", "replace"), report)

    # PASS: Core als stabilen Cache-Prefix, Task+Hotspots als variablen Tail.
    # cache_prefix + tail == serialize_bundle(bundle) (modulo Trenner) -> das
    # Gesendete entspricht dem Gescannten.
    cache_prefix = serialize_core_bundle(core).decode("utf-8")
    tail_bytes = serialize_task_context(ctx) + b"\n" + serialize_hotspots(hotspots)
    return CloudEgress(decision, cache_prefix, tail_bytes.decode("utf-8"), report)
