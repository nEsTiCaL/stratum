"""SQL-Queue fuer den Orchestrator-Kern (I-2.3).

Atomares Claimen via FOR UPDATE SKIP LOCKED gegen dieselbe Postgres-Instanz
wie der Artifact-Store. Kein separater Broker-Prozess.

Interface: Queue(conn) mit enqueue / claim / complete / fail.
Hinter diesem Interface kann spaeter ein NATS-Adapter folgen (R2).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from core.template_registry import DagNode, TaskDag


@dataclass(frozen=True)
class QueueItem:
    """Ein aus der Queue geclaimter Knoten (status='running')."""

    id: int
    dag_id: str
    node_id: str
    task_type: str
    scope: str
    model: str
    depends_on: tuple[str, ...]
    flags: frozenset[str]
    payload: dict[str, Any]
    attempts: int
    status: str
    owner: str = ""
    capability_id: int | None = None  # Schritt 7: -> Workspace-root pro Key


class Queue:
    """SQL-Queue: enqueue / claim / complete / fail.

    Eine Instanz haelt eine Verbindung. Alle Schreiboperationen laufen
    in expliziten Transaktionen (self._conn.transaction()), kompatibel
    mit autocommit=True und autocommit=False.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def enqueue(
        self,
        dag: TaskDag,
        model: str,
        *,
        owner: str = "",
        capability_id: int | None = None,
        priority: int = 0,
    ) -> list[int]:
        """Schreibt alle pending-Knoten des DAG in die Queue.

        Knoten mit status='done' (Store-Treffer in decompose) werden
        uebersprungen. Gibt die ids der eingefuegten Zeilen zurueck.
        """
        ids: list[int] = []
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                for node in dag.nodes:
                    if node.status == "done":
                        continue
                    cur.execute(
                        """
                        INSERT INTO queue
                            (dag_id, node_id, task_type, scope, model,
                             priority, depends_on, flags, owner, capability_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            dag.dag_id,
                            node.id,
                            node.task_type,
                            node.scope,
                            model,
                            priority,
                            json.dumps(list(node.depends_on)),
                            json.dumps(sorted(node.flags)),
                            owner,
                            capability_id,
                        ),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    ids.append(row[0])
        return ids

    def claim(self, model: str) -> QueueItem | None:
        """Beansprucht atomar den naechsten verfuegbaren Knoten fuer `model`.

        Ein Knoten ist verfuegbar wenn:
          - status = 'pending'
          - model stimmt ueberein
          - kein depends_on-Knoten im selben DAG ist noch nicht 'done'
            (fehlt der Knoten in der Queue = pre-erledigt = gilt als done)

        FOR UPDATE SKIP LOCKED: bei Konkurrenz gewinnt genau ein Claimer,
        alle anderen ueberspringen die gesperrte Zeile.
        """
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE queue
                    SET status = 'running', claimed_at = now()
                    WHERE id = (
                        SELECT q.id FROM queue q
                        WHERE q.model = %s
                          AND q.status = 'pending'
                          AND NOT EXISTS (
                              SELECT 1 FROM queue dep
                              WHERE dep.dag_id = q.dag_id
                                AND dep.node_id = ANY(
                                    ARRAY(
                                        SELECT jsonb_array_elements_text(q.depends_on)
                                    )
                                )
                                AND dep.status != 'done'
                          )
                        ORDER BY q.priority DESC, q.created_at
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING id, dag_id, node_id, task_type, scope, model,
                              depends_on, flags, payload, attempts, status,
                              owner, capability_id
                    """,
                    (model,),
                )
                row = cur.fetchone()
        return _row_to_item(row) if row is not None else None

    def complete(self, item_id: int) -> None:
        """Markiert einen Knoten als erfolgreich abgeschlossen (status='done')."""
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue SET status = 'done' WHERE id = %s",
                    (item_id,),
                )

    def fail(self, item_id: int, reason: str | None = None) -> None:
        """Markiert einen Knoten terminal als fehlgeschlagen (status='failed').

        Kein automatischer Retry auf Queue-Ebene — die EscalationLoop im Worker
        uebernimmt model-level Retries bereits intern. Expliziter Retry moeglich
        ueber direkte DB-Korrektur oder kuenftige retry()-Methode.

        `reason` (I-E.13, Befund E-13): der terminale Fehlgrund bzw. die
        Eskalations-Belegkette wird ATOMAR mit dem Status in payload.fail_reason
        abgelegt. Bisher ging der Grund nur an on_item_fail -> stdout/docker-logs;
        jetzt ist er via REST lesbar (list_tasks / GET /api/task/{id}), sodass der
        Anwender den Fail-Grund eines Knotens nicht mehr im Container-Log suchen
        muss (Belegkette-Sichtbarkeit). None -> Payload unberuehrt (Rueckwaerts-
        kompatibel fuer Aufrufer ohne Grund)."""
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                if reason is None:
                    cur.execute(
                        "UPDATE queue SET status = 'failed', "
                        "attempts = attempts + 1 WHERE id = %s",
                        (item_id,),
                    )
                else:
                    cur.execute(
                        "UPDATE queue SET status = 'failed', "
                        "attempts = attempts + 1, "
                        "payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb "
                        "WHERE id = %s",
                        (json.dumps({"fail_reason": reason}), item_id),
                    )

    def ids_for_dag(self, dag_id: str) -> list[int]:
        """Queue-ids eines DAG (created-Reihenfolge). Fuer die Idempotenz von
        Plan-Confirm: ein bereits bestaetigter Plan liefert seine schon
        eingereihten Task-ids zurueck, statt neu zu enqueuen."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM queue WHERE dag_id = %s ORDER BY created_at, id",
                (dag_id,),
            )
            return [row[0] for row in cur.fetchall()]

    def discard_dag(self, dag_id: str) -> int:
        """Verwirft alle Subtasks eines DAG (Plan-Discard, I-6.3-Erweiterung).

        Loescht saemtliche Queue-Zeilen des dag -- unabhaengig vom Status. Ein
        evtl. laufender Worker aktualisiert danach 0 Zeilen (harmlos); bereits
        erzeugte Artefakte bleiben im Store, die Trace-Historie ebenso. Gibt die
        Anzahl entfernter Knoten zurueck."""
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute("DELETE FROM queue WHERE dag_id = %s", (dag_id,))
                return cur.rowcount

    def reopen_after_verify(
        self, verify_item: QueueItem, *, feedback: str, max_attempts: int = 2
    ) -> bool:
        """Rueckkante implement<-Gate (I-7.4, verallgemeinert in I-REK.4).

        Bei einem roten Gate (lint_gate ODER test_gate) den erzeugenden
        implement/fix-Knoten im selben DAG neu oeffnen, sofern seine attempts noch
        unter der Kappung liegen -- GEMEINSAMES Attempt-Budget: jeder Gate-Fehler
        (statisch ODER Test) zaehlt auf denselben implement.attempts. Weil der
        Schreib-Sub-DAG eine Kette implement -> lint_gate -> test_gate ist, sitzt
        der implement-Knoten bei einem roten test_gate zwei Hops entfernt (hinter
        dem lint_gate); die frueher direkte depends_on-Suche fand ihn nicht. Daher
        laeuft die Suche jetzt ueber den DAG NACH OBEN durch die Gate-Knoten bis
        zum implement/fix:
          - implement/fix (Erzeuger): status='pending', attempts+=1,
            payload.verify_feedback = feedback (Kontext fuer den naechsten Patch);
          - ALLE Gate-Knoten zwischen Erzeuger und rotem Gate (inkl. des roten
            selbst): status='pending' -- so laeuft die ganze Gate-Kette nach dem
            neuen Patch erneut IN ORDNUNG (test_gate wartet via depends_on wieder
            auf das lint_gate, nicht auf den alten Patch).
        Gibt True zurueck, wenn der Erzeuger neu geoeffnet wurde; False bei
        Kappung / keinem implement-Erzeuger -> der Aufrufer laesst das Gate
        terminal fehlschlagen (Belegkette: Patch- + Report-Artefakte bleiben).
        """
        _GATE = {"lint_gate", "test_gate"}
        _IMPL = {"implement", "fix"}
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT id, node_id, task_type, depends_on, attempts "
                    "FROM queue WHERE dag_id = %s",
                    (verify_item.dag_id,),
                )
                qid: dict[str, int] = {}
                task_type: dict[str, str] = {}
                deps_of: dict[str, tuple[str, ...]] = {}
                attempts: dict[str, int] = {}
                for id_, node_id, tt, deps_j, att in cur.fetchall():
                    qid[node_id] = id_
                    task_type[node_id] = tt
                    deps_of[node_id] = tuple(deps_j) if deps_j else ()
                    attempts[node_id] = att

                # Nach oben durch die Gate-Kette laufen: implement/fix sammeln,
                # dazwischenliegende Gate-Knoten mitnehmen (bei implement stoppen,
                # nicht weiter zu architect/index hoch).
                impl_nodes: set[str] = set()
                gate_nodes: set[str] = {verify_item.node_id}
                seen = {verify_item.node_id}
                frontier = [verify_item.node_id]
                while frontier:
                    for dep in deps_of.get(frontier.pop(), ()):
                        tt = task_type.get(dep)
                        if tt in _IMPL:
                            impl_nodes.add(dep)
                        elif tt in _GATE and dep not in seen:
                            seen.add(dep)
                            gate_nodes.add(dep)
                            frontier.append(dep)

                reopenable = [n for n in impl_nodes if attempts[n] < max_attempts]
                if not reopenable:
                    return False

                feedback_json = json.dumps({"verify_feedback": feedback})
                cur.execute(
                    "UPDATE queue SET status = 'pending', attempts = attempts + 1, "
                    "claimed_at = NULL, "
                    "payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb "
                    "WHERE id = ANY(%s)",
                    (feedback_json, [qid[n] for n in reopenable]),
                )
                cur.execute(
                    "UPDATE queue SET status = 'pending', claimed_at = NULL "
                    "WHERE id = ANY(%s)",
                    ([qid[n] for n in gate_nodes],),
                )
        return True

    # --- I-REK.11: Eskalationsleiter Sprossen 2-3 (re-design, re-expand) ------
    #
    # Wenn die re-act-Kappung (reopen_after_verify) eines Schreib-Knotens
    # erschoepft ist, gibt der Worker NICHT sofort auf, sondern faehrt die Leiter:
    # re_design (den architect-Elternknoten mit Feedback neu oeffnen) -> re_expand
    # (den impl/Gate-Teilbaum superseden und frisch unter dem architect neu
    # aufbauen) -> unresolved. Der Stufen-Zaehler liegt im Payload des architect
    # (escalation_stage) -- er ueberlebt beide Reopen-Wege. Die Leiter greift NUR,
    # wenn der Schreib-Sub-DAG einen architect hat (ohne Design gibt es nichts neu
    # zu entwerfen); triviale Ketten ohne architect fallen terminal fehl wie bisher.

    def _write_chain(
        self, verify_item: QueueItem
    ) -> tuple[str | None, list[dict], list[dict], dict[str, dict]]:
        """Von einem roten Gate den Schreib-Sub-DAG nach oben aufloesen.

        Rueckgabe: (architect_node_id | None, impl_rows, gate_rows, rows_by_node_id).
        Laeuft (wie reopen_after_verify) durch die Gate-Kette bis implement/fix und
        von dort EINEN Hop weiter zum architect (falls vorhanden)."""
        _GATE = {"lint_gate", "test_gate"}
        _IMPL = {"implement", "fix"}
        rows: dict[str, dict] = {}
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT id, node_id, task_type, depends_on, attempts, status, "
                "COALESCE(payload, '{}'::jsonb), scope, model, owner, capability_id "
                "FROM queue WHERE dag_id = %s",
                (verify_item.dag_id,),
            )
            for r in cur.fetchall():
                rows[r[1]] = {
                    "id": r[0],
                    "node_id": r[1],
                    "task_type": r[2],
                    "depends_on": tuple(r[3]) if r[3] else (),
                    "attempts": r[4],
                    "status": r[5],
                    "payload": r[6] or {},
                    "scope": r[7],
                    "model": r[8],
                    "owner": r[9],
                    "capability_id": r[10],
                }
        # Aufwaerts vom roten Gate durch die Gate-Kette bis zum implement/fix.
        impl: set[str] = set()
        seen = {verify_item.node_id}
        frontier = [verify_item.node_id]
        while frontier:
            for dep in rows.get(frontier.pop(), {}).get("depends_on", ()):
                tt = rows.get(dep, {}).get("task_type")
                if tt in _IMPL:
                    impl.add(dep)
                elif tt in _GATE and dep not in seen:
                    seen.add(dep)
                    frontier.append(dep)
        # Abwaerts vom impl ALLE Gates der Kette einsammeln (lint UND test) --
        # das rote Gate liegt evtl. VOR einem weiteren (test_gate hinter lint_gate);
        # ein zurueckbleibendes Gate wuerde sonst auf einen superseded/neu gebauten
        # Knoten zeigen (re-expand). children[d] = Knoten mit d in depends_on.
        children: dict[str, list[str]] = {}
        for nid, r in rows.items():
            for d in r["depends_on"]:
                children.setdefault(d, []).append(nid)
        gates: set[str] = set()
        seen = set(impl)
        frontier = list(impl)
        while frontier:
            for ch in children.get(frontier.pop(), ()):
                if ch in seen:
                    continue
                seen.add(ch)
                if rows[ch]["task_type"] in _GATE:
                    gates.add(ch)
                    frontier.append(ch)
        architect: str | None = None
        for i in impl:
            for dep in rows[i]["depends_on"]:
                if rows.get(dep, {}).get("task_type") == "architect":
                    architect = dep
        impl_rows = [rows[n] for n in impl]
        gate_rows = [rows[n] for n in gates if n in rows]
        return architect, impl_rows, gate_rows, rows

    def escalation_stage(self, verify_item: QueueItem) -> int | None:
        """Aktuelle Eskalations-Stufe des Schreib-Sub-DAG, oder None wenn es keinen
        architect gibt (dann keine Leiter -> terminaler Fail wie bisher). Der
        Zaehler steht im Payload des architect (escalation_stage, Default 0).

        I-E.1: Ein architect MIT impact-Payload ist ein impact-ERZEUGER (bzw. der
        redesign-architect der Kette), kein REK.11-Leiter-architect: die impact-
        Kette hat ihr eigenes Design-Review-/Redesign-Regime (G3, make_impact_hook);
        reopen_for_redesign wuerde den Completion-Hook erneut feuern und gegen die
        enqueue_children-Idempotenz arbeiten. Kind-Gates der impact-Kette behalten
        die re_act-Rueckkante (reopen_after_verify) und fallen nach der Kappung
        terminal -- wie triviale Ketten ohne architect."""
        architect, impl, _gates, rows = self._write_chain(verify_item)
        if architect is None or not impl:
            return None
        if rows[architect]["payload"].get("impact"):
            return None
        return int(rows[architect]["payload"].get("escalation_stage", 0))

    def reopen_for_redesign(
        self, verify_item: QueueItem, *, feedback: str, new_stage: int
    ) -> bool:
        """Sprosse 2 (re-design): den architect-Elternknoten + den Schreib-Sub-DAG
        (impl/fix + Gates) neu oeffnen, Verify-/Test-Feedback in den Payload des
        architect legen (sein Prompt haengt es an -> er ueberarbeitet das Design;
        put_artifact supersedet das alte design, der Coder liest das neue) und die
        Stufe hochsetzen. attempts der neu geoeffneten Knoten -> 0 (frisches Budget
        gegen das neue Design). False, wenn kein architect existiert."""
        architect, impl, gates, rows = self._write_chain(verify_item)
        if architect is None or not impl:
            return False
        arch_payload = json.dumps(
            {"verify_feedback": feedback, "escalation_stage": new_stage}
        )
        impl_payload = json.dumps({"verify_feedback": feedback})
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue SET status = 'pending', attempts = 0, "
                    "claimed_at = NULL, "
                    "payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb "
                    "WHERE id = %s",
                    (arch_payload, rows[architect]["id"]),
                )
                cur.execute(
                    "UPDATE queue SET status = 'pending', attempts = 0, "
                    "claimed_at = NULL, "
                    "payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb "
                    "WHERE id = ANY(%s)",
                    (impl_payload, [n["id"] for n in impl]),
                )
                cur.execute(
                    "UPDATE queue SET status = 'pending', claimed_at = NULL "
                    "WHERE id = ANY(%s)",
                    ([n["id"] for n in gates],),
                )
        return True

    def reexpand_write_subdag(
        self, verify_item: QueueItem, *, feedback: str, new_stage: int
    ) -> bool:
        """Sprosse 3 (re-expand): der impl/Gate-Teilbaum wird verworfen (superseded,
        unabhaengig vom Status -> Belegkette bleibt) und FRISCH unter dem architect
        neu aufgebaut (neue node_ids); der architect wird mit Feedback + neuer Stufe
        neu geoeffnet. Anders als re-design gibt es dem Coder eine unbelastete
        Knoten-Identitaet (die alte Patch-/Gate-Historie liegt als superseded-Kette
        daneben). Gate-Form (lint_gate/test_gate) + Modelle werden aus der alten
        Kette uebernommen. False, wenn kein architect existiert."""
        architect, impl, gates, rows = self._write_chain(verify_item)
        if architect is None or not impl:
            return False
        impl_row = impl[0]
        suffix = f"~r{new_stage}"
        # Gate-Form der alten Kette bewahren (Reihenfolge lint -> test).
        old_gates = sorted(
            gates, key=lambda g: 0 if g["task_type"] == "lint_gate" else 1
        )
        old_ids = [n["id"] for n in impl] + [g["id"] for g in gates]
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue SET status = 'superseded' WHERE id = ANY(%s)",
                    (old_ids,),
                )
                # Frische Kette: impl' -> architect; jedes Gate' -> Vorgaenger.
                impl_id = f"{impl_row['node_id']}{suffix}"
                fresh_payload = {
                    "verify_feedback": feedback,
                    "instruction": impl_row["payload"].get("instruction", ""),
                }
                if impl_row["payload"].get("plan_design"):
                    fresh_payload["plan_design"] = impl_row["payload"]["plan_design"]
                self._insert_node(
                    cur,
                    dag_id=verify_item.dag_id,
                    node_id=impl_id,
                    task_type=impl_row["task_type"],
                    scope=impl_row["scope"],
                    model=impl_row["model"],
                    depends_on=[architect],
                    payload=fresh_payload,
                    owner=impl_row["owner"],
                    capability_id=impl_row["capability_id"],
                )
                prev = impl_id
                for g in old_gates:
                    gate_id = f"{g['node_id']}{suffix}"
                    self._insert_node(
                        cur,
                        dag_id=verify_item.dag_id,
                        node_id=gate_id,
                        task_type=g["task_type"],
                        scope=g["scope"],
                        model=g["model"],
                        depends_on=[prev],
                        payload=None,
                        owner=g["owner"],
                        capability_id=g["capability_id"],
                    )
                    prev = gate_id
                # architect neu oeffnen (Feedback + neue Stufe).
                cur.execute(
                    "UPDATE queue SET status = 'pending', attempts = 0, "
                    "claimed_at = NULL, "
                    "payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb "
                    "WHERE id = %s",
                    (
                        json.dumps(
                            {"verify_feedback": feedback, "escalation_stage": new_stage}
                        ),
                        rows[architect]["id"],
                    ),
                )
        return True

    @staticmethod
    def _insert_node(
        cur: Any,
        *,
        dag_id: str,
        node_id: str,
        task_type: str,
        scope: str,
        model: str,
        depends_on: list[str],
        payload: dict | None,
        owner: str,
        capability_id: int | None,
    ) -> None:
        """Eine einzelne Queue-Zeile einfuegen (fuer re-expand-Frischknoten)."""
        cur.execute(
            """
            INSERT INTO queue
                (dag_id, node_id, task_type, scope, model,
                 depends_on, flags, payload, owner, capability_id)
            VALUES (%s, %s, %s, %s, %s, %s, '[]'::jsonb,
                    COALESCE(%s::jsonb, '{}'::jsonb), %s, %s)
            """,
            (
                dag_id,
                node_id,
                task_type,
                scope,
                model,
                json.dumps(depends_on),
                json.dumps(payload) if payload else None,
                owner,
                capability_id,
            ),
        )

    def enqueue_children(
        self,
        parent: QueueItem,
        nodes: list[DagNode],
        *,
        base_payload: dict[str, Any] | None = None,
        model_for: Callable[[DagNode], str] | None = None,
        payload_for: Callable[[DagNode], dict[str, Any] | None] | None = None,
        priority: int = 0,
    ) -> list[int]:
        """Reiht die (nach ihrem Erzeuger entstandenen) Kinder eines Knotens ein
        (I-REK.7 Completion-Hook). Die Kinder liegen im SELBEN DAG wie der Erzeuger
        (damit die dumme claim()-Abhaengigkeitspruefung ueber depends_on greift)
        und erben owner + capability_id -> denselben Workspace.

        Sichtbarkeit = Sicherheit (Invariante 4): vor diesem Aufruf lag KEIN
        Kind-Knoten in der Queue, also konnte ihn kein Worker vorzeitig claimen;
        der Hook feuert erst, wenn der Erzeuger 'done' ist.

        Idempotenz: ein Knoten, dessen (dag_id, node_id) bereits als NICHT-
        superseded-Zeile existiert, wird uebersprungen -- so erzeugt ein erneut
        geoeffneter + fertig gewordener Erzeuger keine Dubletten. Nach einem
        supersede_subtree (re-expand) sind die alten Kinder 'superseded' und
        blockieren die frischen mit denselben IDs daher NICHT.

        base_payload : je Kind in payload gemergt (der Hook stempelt hier die
                       Tiefe depth+1 -- die naechste Ebene liest sie zurueck).
        model_for    : Claim-Key je Kind (Worker-Routing); None -> parent.model.
        payload_for  : optionales KOMPLETTES Payload je Kind (I-E.1: das Sammel-
                       test_gate traegt gate_scopes, die Gates brauchen keine
                       instruction); None-Rueckgabe -> base_payload wie bisher.
        done-Knoten (Cache-Treffer aus expand) werden wie in enqueue() ausgelassen.
        """
        payload_json = json.dumps(base_payload) if base_payload else None
        ids: list[int] = []
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT node_id FROM queue "
                    "WHERE dag_id = %s AND status != 'superseded'",
                    (parent.dag_id,),
                )
                existing = {row[0] for row in cur.fetchall()}
                for node in nodes:
                    if node.status == "done" or node.id in existing:
                        continue
                    model = model_for(node) if model_for is not None else parent.model
                    node_payload = (
                        payload_for(node) if payload_for is not None else None
                    )
                    node_payload_json = (
                        json.dumps(node_payload)
                        if node_payload is not None
                        else payload_json
                    )
                    cur.execute(
                        """
                        INSERT INTO queue
                            (dag_id, node_id, task_type, scope, model,
                             priority, depends_on, flags, payload,
                             owner, capability_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                                COALESCE(%s::jsonb, '{}'::jsonb), %s, %s)
                        RETURNING id
                        """,
                        (
                            parent.dag_id,
                            node.id,
                            node.task_type,
                            node.scope,
                            model,
                            priority,
                            json.dumps(list(node.depends_on)),
                            json.dumps(sorted(node.flags)),
                            node_payload_json,
                            parent.owner,
                            parent.capability_id,
                        ),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    ids.append(row[0])
                    existing.add(node.id)  # keine Dubletten innerhalb DIESES Aufrufs
        return ids

    def supersede_subtree(self, dag_id: str, root_node_id: str) -> int:
        """Storniert den OFFENEN Teilbaum unter `root_node_id` ATOMAR (I-REK.7).

        Der Teilbaum sind alle Nachkommen von root (Knoten, die ueber depends_on
        transitiv auf root zuruecklaufen); root selbst bleibt unberuehrt (bei
        re-expand, REK.11, wird der Erzeuger separat neu geoeffnet). Nur OFFENE
        Knoten (pending/running) werden auf status='superseded' gesetzt -- im Geist
        der I-6-superseded-Kette (Versionierung statt Loeschen): die Zeilen bleiben
        als Belegkette erhalten, sind aber nicht mehr claimbar. Bereits fertige/
        fehlgeschlagene Nachkommen bleiben als Historie stehen.

        Gibt die Zahl stornierter Zeilen zurueck.
        """
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT id, node_id, depends_on, status "
                    "FROM queue WHERE dag_id = %s",
                    (dag_id,),
                )
                qid: dict[str, int] = {}
                status: dict[str, str] = {}
                # child_of[X] = Knoten, die direkt von X abhaengen (umgekehrte Kante)
                child_of: dict[str, list[str]] = {}
                for id_, node_id, deps_j, st in cur.fetchall():
                    qid[node_id] = id_
                    status[node_id] = st
                    for dep in tuple(deps_j) if deps_j else ():
                        child_of.setdefault(dep, []).append(node_id)

                # Reverse-BFS ab root: alle Nachkommen einsammeln (root selbst NICHT)
                descendants: set[str] = set()
                frontier = list(child_of.get(root_node_id, ()))
                while frontier:
                    node_id = frontier.pop()
                    if node_id in descendants:
                        continue
                    descendants.add(node_id)
                    frontier.extend(child_of.get(node_id, ()))

                open_ids = [
                    qid[n]
                    for n in descendants
                    if status.get(n) in ("pending", "running")
                ]
                if not open_ids:
                    return 0
                cur.execute(
                    "UPDATE queue SET status = 'superseded', claimed_at = NULL "
                    "WHERE id = ANY(%s)",
                    (open_ids,),
                )
                return cur.rowcount

    def cancel_dag(self, dag_id: str) -> int:
        """Bricht einen ganzen DAG ab (I-E.7, Befund E-7): alle OFFENEN Knoten
        (pending/running) des `dag_id` werden auf status='cancelled' gesetzt und
        sind nicht mehr claimbar (claim() sieht nur 'pending'). done/failed/
        superseded bleiben als Belegkette stehen -- Zustand markieren statt Zeilen
        loeschen (im Geist der I-6-Versionierung).

        Motivation: ein terminal gefailter Knoten liess seine depends_on-Nachfolger
        (Geschwister-Goals, Sammel-Gate) fuer immer 'pending' haengen -- toter
        Queue-Bestand ohne REST-Weg zum Aufraeumen (E-7). cancel_dag ist dieser Weg.

        Abgrenzung: discard_dag LOESCHT alle Zeilen (Plan-Discard, verwirft die
        Belegkette); supersede_subtree betrifft nur EINEN Teilbaum und nutzt den
        Status 'superseded' fuer System-Ersatz-Ketten (re-expand). cancel_dag ist
        DAG-weit, terminal-erhaltend und der Anwender-Abbruch.

        Ein evtl. gerade laufender Worker aktualisiert seine (jetzt 'cancelled')
        'running'-Zeile spaeter noch (harmlos: seine ebenfalls stornierten
        Nachfolger sind nicht mehr claimbar). Gibt die Zahl stornierter Zeilen
        zurueck; idempotent (ein bereits terminaler DAG -> 0).
        """
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue SET status = 'cancelled', claimed_at = NULL "
                    "WHERE dag_id = %s AND status IN ('pending', 'running')",
                    (dag_id,),
                )
                return cur.rowcount

    def is_terminal_gate(self, item: QueueItem) -> bool:
        """True, wenn KEIN weiteres Gate im selben DAG (direkt) auf `item` haengt
        (I-REK.4). Der Auto-Apply-Nachlauf darf erst nach dem LETZTEN gruenen Gate
        laufen: ein lint_gate mit nachfolgendem test_gate ist NICHT terminal
        (dann appliziert erst der test_gate-Pass); ein lint_gate ohne test_gate und
        das test_gate selbst (Blatt) sind terminal. `?` prueft, ob node_id ein
        Element des jsonb-Arrays depends_on ist."""
        row = self._conn.execute(
            "SELECT 1 FROM queue WHERE dag_id = %s "
            "AND task_type IN ('lint_gate', 'test_gate') "
            "AND depends_on ? %s LIMIT 1",
            (item.dag_id, item.node_id),
        ).fetchone()
        return row is None

    def claim_by_id(self, item_id: int, *, model: str = "human") -> QueueItem | None:
        """Beansprucht einen spezifischen pending-Knoten per ID.

        Fuer manuelles Claiming aus dem Web-Dashboard (I-D.2): der Nutzer
        waehlt sich einen Task aus, nicht der Worker. Gibt None zurueck wenn
        der Knoten nicht existiert oder nicht mehr pending ist.
        """
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE queue
                    SET status = 'running', model = %s, claimed_at = now()
                    WHERE id = %s AND status = 'pending'
                    RETURNING id, dag_id, node_id, task_type, scope, model,
                              depends_on, flags, payload, attempts, status,
                              owner, capability_id
                    """,
                    (model, item_id),
                )
                row = cur.fetchone()
        return _row_to_item(row) if row is not None else None

    def set_model(self, item_id: int, model: str) -> None:
        """Setzt den Claim-Key (model) eines pending-Eintrags nach enqueue.

        Der model-Wert entscheidet, welcher Worker-Loop einen Knoten claimt
        (claim() filtert q.model = model). Wird genutzt, um Schreib-Tasks auf
        einem Host ohne code-faehigen Kandidaten auf 'human' umzurouten (der
        LLM-Loop laesst sie dann liegen, der Dashboard-Einreichpfad greift)."""
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue SET model = %s WHERE id = %s",
                    (model, item_id),
                )

    def update_payload(self, item_id: int, payload: dict) -> None:
        """Setzt das payload-Feld eines Queue-Eintrags (nach enqueue)."""
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue SET payload = %s WHERE id = %s",
                    (json.dumps(payload), item_id),
                )

    def mark_applied(self, *, owner: str, scope: str, diff_hash: str) -> int:
        """Markiert alle done-Tasks eines (owner, scope) als angewendet:
        payload.applied=true (blendet sie via list_tasks(exclude_applied=True) aus)
        UND payload.applied_diff_hash=diff_hash. Der Hash koppelt die
        Idempotenz-Wache an den PATCH-INHALT (E-14): nur ein erneuter Apply GENAU
        dieses Diffs wird zum No-Op statt zum Kontext-Mismatch (409); ein frischer
        Diff auf demselben scope wird normal angewendet. Gibt die Zahl markierter
        Zeilen zurueck."""
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue "
                    "SET payload = COALESCE(payload, '{}'::jsonb) "
                    "|| jsonb_build_object('applied', true, "
                    "'applied_diff_hash', %s::text) "
                    "WHERE owner = %s AND scope = %s AND status = 'done'",
                    (diff_hash, owner, scope),
                )
                return cur.rowcount

    def is_applied(self, *, owner: str, scope: str, diff_hash: str) -> bool:
        """True, wenn fuer (owner, scope) bereits ein done-Task mit GENAU diesem
        applied_diff_hash vorliegt -- die patch-gekoppelte Idempotenz-Wache fuer
        /api/apply (E-14). Ein anderer (frischer) Diff auf demselben scope matcht
        NICHT und wird darum nicht faelschlich als 'bereits angewendet'
        verschluckt."""
        row = self._conn.execute(
            "SELECT 1 FROM queue "
            "WHERE owner = %s AND scope = %s AND status = 'done' "
            "AND payload->>'applied_diff_hash' = %s LIMIT 1",
            (owner, scope, diff_hash),
        ).fetchone()
        return row is not None

    def get_status(self, item_id: int) -> str | None:
        """Gibt den aktuellen Status eines Tasks zurueck (alle Statuswerte)."""
        row = self._conn.execute(
            "SELECT status FROM queue WHERE id = %s", (item_id,)
        ).fetchone()
        return row[0] if row else None

    def get_task_info(self, item_id: int) -> dict[str, Any] | None:
        """Gibt id, task_type, scope, status, owner, model, payload und
        capability_id eines beliebigen Tasks.

        Im Gegensatz zu list_tasks() auch fuer done-Tasks abfragbar. capability_id
        speist den Workspace-root, den der Human-Pfad zur Claim-Zeit fuer den
        Lazy-Prompt-Bau braucht (I-REK.1).
        """
        row = self._conn.execute(
            "SELECT id, task_type, scope, status, owner, model, payload, "
            "capability_id FROM queue WHERE id = %s",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "task_type": row[1],
            "scope": row[2],
            "status": row[3],
            "owner": row[4],
            "model": row[5],
            "payload": row[6] or {},
            "capability_id": row[7],
        }

    def get_task_detail(self, item_id: int) -> dict[str, Any] | None:
        """Volle Queue-Zeile eines Tasks fuer GET /api/task/{id} (I-E.11).

        Ergaenzt get_task_info um dag_id, node_id, depends_on, attempts und die
        Zeitstempel -- der Anwender sieht damit via REST, WO ein Knoten im DAG
        haengt (depends_on auf failed?) und ob sein Patch angewendet wurde
        (payload.applied), statt dafuer in die DB zu muessen (Befund E-11)."""
        row = self._conn.execute(
            "SELECT id, dag_id, node_id, task_type, scope, model, status, "
            "attempts, depends_on, payload, owner, capability_id, "
            "created_at, claimed_at FROM queue WHERE id = %s",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "dag_id": row[1],
            "node_id": row[2],
            "task_type": row[3],
            "scope": row[4],
            "model": row[5],
            "status": row[6],
            "attempts": row[7],
            "depends_on": list(row[8]) if row[8] else [],
            "payload": row[9] or {},
            "owner": row[10],
            "capability_id": row[11],
            "created_at": row[12],
            "claimed_at": row[13],
        }

    def missed_expansions(self, *, max_age_hours: int = 48) -> list[QueueItem]:
        """Kandidaten fuer den Expansion-Reaper (I-E.19, Befund E-19).

        Ein Completion-Hook kann still ausfallen (2x belegt: der ERSTE
        impact-Erzeuger nach Container-Start wurde done, ohne dass Kinder
        entstanden -- kein Fehler-Log, Verdacht Startup-Race im Worker-Thread).
        Kriterium fuer "Feuerung verpasst": done-Task MIT impact-Payload, unter
        dem KEIN nicht-superseded Knoten haengt (jede Hook-Wirkung -- Kinder,
        Review, Redesign -- erzeugt mindestens einen Knoten mit node_id-Praefix
        '<node_id>/'). Der Praefix-Vergleich laeuft ueber left()/length() statt
        LIKE, damit LIKE-Wildcards in node_ids (impact_0 traegt '_') nicht
        mitmustern. max_age_hours begrenzt auf frische Leichen -- Alt-Erzeuger
        aus der Zeit vor der Gate-Kette (I-E.1) sollen nicht ewig Kandidat
        bleiben. Ein legaler No-Op-Erzeuger (Symbol betrifft nichts) bleibt
        Kandidat; die Wiederhol-Kappung liegt beim Rufer (WorkerLoop)."""
        rows = self._conn.execute(
            """
            SELECT id, dag_id, node_id, task_type, scope, model,
                   depends_on, flags, payload, attempts, status,
                   owner, capability_id
            FROM queue t
            WHERE t.status = 'done'
              AND t.payload ? 'impact'
              AND t.claimed_at > now() - %s * interval '1 hour'
              AND NOT EXISTS (
                  SELECT 1 FROM queue c
                  WHERE c.dag_id = t.dag_id
                    AND c.status != 'superseded'
                    AND left(c.node_id, length(t.node_id) + 1)
                        = t.node_id || '/'
              )
            ORDER BY t.id
            """,
            (max_age_hours,),
        ).fetchall()
        return [_row_to_item(row) for row in rows]

    def list_tasks(
        self,
        *,
        statuses: tuple[str, ...] = ("pending", "running", "failed"),
        owner: str | None = None,
        dag_id: str | None = None,
        limit: int | None = None,
        newest_first: bool = False,
        exclude_applied: bool = False,
    ) -> list[dict[str, Any]]:
        """Listet Tasks fuer das Dashboard (read-only, kein Locking).

        Default: pending, running und failed (done ausgeblendet). Mit owner-Filter
        nur Tasks dieses Owners; mit dag_id-Filter nur Tasks dieses DAGs (I-E.11:
        der Anwender kann den Endzustand seines DAGs abfragen, statt ihn im
        rotierenden Uebersichts-Fenster zu verlieren). Reihenfolge created_at asc
        (newest_first=True -> desc, fuer die begrenzte done-Liste). limit begrenzt
        die Zeilenzahl -- so laesst sich eine kurze Liste zuletzt abgeschlossener
        Tasks holen, ohne die Uebersicht mit der gesamten Historie zu fluten.
        exclude_applied=True blendet Tasks aus, deren Patch schon angewendet wurde
        (payload.applied) -- die abgeschlossene, angewandte Arbeit verschwindet
        dann aus der Uebersicht. Jede Zeile traegt node_id + applied (I-E.11:
        DAG-Struktur und Apply-Stand sichtbar, statt nur in der DB).

        I-E.13 (Befund E-13, Belegkette via REST): jede Zeile traegt zusaetzlich
        die "Warum"-Felder der supersede-/Eskalations-Kette -- fail_reason (der
        terminale Fehlgrund, jetzt in der DB statt nur in docker logs),
        verify_feedback (das Gate-Feedback, das einen Reopen ausloeste),
        escalation_stage (die Leiter-Sprosse) und base_node_id (der ~r-Suffix
        entfernt -> Versionen desselben Knotens gruppierbar). Alle vier sind None/
        gleich node_id, wo nichts anliegt -- rein additiv zur I-E.11-Sicht.
        """
        placeholders = ",".join(["%s"] * len(statuses))
        params: list[Any] = list(statuses)
        owner_clause = ""
        if owner is not None:
            owner_clause = " AND owner = %s"
            params.append(owner)
        dag_clause = ""
        if dag_id is not None:
            dag_clause = " AND dag_id = %s"
            params.append(dag_id)
        applied_clause = ""
        if exclude_applied:
            applied_clause = " AND NOT COALESCE((payload->>'applied')::boolean, false)"
        order = "DESC" if newest_first else "ASC"
        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT %s"
            params.append(limit)
        rows = self._conn.execute(
            f"SELECT id, dag_id, node_id, task_type, scope, model, status, "
            f"attempts, created_at, claimed_at, "
            f"COALESCE((payload->>'applied')::boolean, false), "
            f"payload->>'fail_reason', payload->>'verify_feedback', "
            f"(payload->>'escalation_stage')::int "
            f"FROM queue WHERE status IN ({placeholders}){owner_clause}"
            f"{dag_clause}{applied_clause} "
            f"ORDER BY created_at {order}{limit_clause}",
            params,
        ).fetchall()
        keys = (
            "id",
            "dag_id",
            "node_id",
            "task_type",
            "scope",
            "model",
            "status",
            "attempts",
            "created_at",
            "claimed_at",
            "applied",
            "fail_reason",
            "verify_feedback",
            "escalation_stage",
        )
        tasks = []
        for row in rows:
            task = dict(zip(keys, row, strict=True))
            task["base_node_id"] = _base_node_id(task["node_id"])
            tasks.append(task)
        return tasks

    def live_snapshot(self) -> dict[str, Any]:
        """Polling-Snapshot des Live-Status fuers Dashboard (I-5.1, read-only).

        Ersetzt den urspruenglich als SSE geplanten /stream durch einen
        gepollten Endpoint (P1-Entscheidung: Polling statt SSE, Stream erst mit
        der Go-CLI in P2, siehe spec_rest-api). Aggregiert Queue-Zaehler je
        Status, laufende Tasks (mit verstrichener Zeit) und die groesste
        pending-Modellcharge als Batch-Vorschau. System-weit, nicht
        owner-gefiltert.
        """
        counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
        with self._conn.cursor() as cur:
            cur.execute("SELECT status, count(*) FROM queue GROUP BY status")
            for status, n in cur.fetchall():
                counts[status] = n

            cur.execute(
                "SELECT id, task_type, scope, model, "
                "EXTRACT(EPOCH FROM now() - claimed_at)::int "
                "FROM queue WHERE status = 'running' ORDER BY claimed_at, id"
            )
            running = [
                {
                    "id": r[0],
                    "task_type": r[1],
                    "scope": r[2],
                    "model": r[3],
                    "elapsed_s": r[4],
                }
                for r in cur.fetchall()
            ]

            cur.execute(
                "SELECT model, count(*) FROM queue WHERE status = 'pending' "
                "GROUP BY model ORDER BY count(*) DESC, model LIMIT 1"
            )
            row = cur.fetchone()
        next_batch = {"model": row[0], "pending": row[1]} if row is not None else None
        return {"queue": counts, "running": running, "next_batch": next_batch}


_STAGE_SUFFIX = re.compile(r"(?:~r\d+)+$")


def _base_node_id(node_id: str) -> str:
    """Basis-node_id einer supersede-Kette (I-E.13, Befund E-13). Der re-expand-
    Suffix ~r<stufe> (I-REK.11: reexpand_write_subdag haengt ihn an die frische
    Knoten-Identitaet) wird entfernt, sodass alle Versionen desselben logischen
    Knotens denselben base_node_id tragen -- z.B. n5 (superseded) und n5~r2
    (Ersatz) -> beide 'n5'. Ohne Suffix unveraendert. Der Anwender kann die
    DAG-History damit je logischem Knoten zu einer Kette gruppieren, statt den
    ~r-Suffix selbst zu parsen. Mehrfach-Suffixe (n5~r1~r2) werden ganz
    getrimmt."""
    return _STAGE_SUFFIX.sub("", node_id)


def _row_to_item(row: tuple[Any, ...]) -> QueueItem:
    (
        id_,
        dag_id,
        node_id,
        task_type,
        scope,
        model,
        depends_on_j,
        flags_j,
        payload_j,
        attempts,
        status,
        owner,
        capability_id,
    ) = row
    return QueueItem(
        id=id_,
        dag_id=dag_id,
        node_id=node_id,
        task_type=task_type,
        scope=scope,
        model=model,
        depends_on=tuple(depends_on_j) if depends_on_j else (),
        flags=frozenset(flags_j) if flags_j else frozenset(),
        payload=dict(payload_j) if payload_j else {},
        attempts=attempts,
        status=status,
        owner=owner,
        capability_id=capability_id,
    )
