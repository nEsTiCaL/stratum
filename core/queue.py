"""SQL-Queue fuer den Orchestrator-Kern (I-2.3).

Atomares Claimen via FOR UPDATE SKIP LOCKED gegen dieselbe Postgres-Instanz
wie der Artifact-Store. Kein separater Broker-Prozess.

Interface: Queue(conn) mit enqueue / claim / complete / fail.
Hinter diesem Interface kann spaeter ein NATS-Adapter folgen (R2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg

from core.template_registry import TaskDag


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

    def fail(self, item_id: int) -> None:
        """Markiert einen Knoten terminal als fehlgeschlagen (status='failed').

        Kein automatischer Retry auf Queue-Ebene — die EscalationLoop im Worker
        uebernimmt model-level Retries bereits intern. Expliziter Retry moeglich
        ueber direkte DB-Korrektur oder kuenftige retry()-Methode.
        """
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue SET status = 'failed', attempts = attempts + 1 "
                    "WHERE id = %s",
                    (item_id,),
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
        """Rueckkante implement<-verify (I-7.4).

        Bei rotem Verify die Vorgaenger-Knoten (task_type implement/fix) des
        verify-Knotens im selben DAG neu oeffnen, sofern ihre attempts noch
        unter der Kappung liegen:
          - Vorgaenger: status='pending', attempts+=1, payload.verify_feedback
            = feedback (Kontext fuer den naechsten Patch-Versuch)
          - der verify-Knoten selbst: status='pending' (laeuft nach dem neuen
            Patch erneut; wartet via depends_on auf den Vorgaenger)
        Gibt True zurueck, wenn mindestens ein Vorgaenger neu geoeffnet wurde;
        False bei Kappung (kein Vorgaenger mehr unter max_attempts) -> der
        Aufrufer laesst den verify-Knoten terminal fehlschlagen (Belegkette:
        Patch- + lint_report-Artefakt bleiben im Store).
        """
        deps = list(verify_item.depends_on)
        if not deps:
            return False
        feedback_json = json.dumps({"verify_feedback": feedback})
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM queue "
                    "WHERE dag_id = %s AND node_id = ANY(%s) "
                    "AND task_type IN ('implement', 'fix') "
                    "AND attempts < %s",
                    (verify_item.dag_id, deps, max_attempts),
                )
                reopen_ids = [r[0] for r in cur.fetchall()]
                if not reopen_ids:
                    return False
                cur.execute(
                    "UPDATE queue SET status = 'pending', attempts = attempts + 1, "
                    "claimed_at = NULL, "
                    "payload = COALESCE(payload, '{}'::jsonb) || %s::jsonb "
                    "WHERE id = ANY(%s)",
                    (feedback_json, reopen_ids),
                )
                cur.execute(
                    "UPDATE queue SET status = 'pending', claimed_at = NULL "
                    "WHERE id = %s",
                    (verify_item.id,),
                )
        return True

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

    def mark_applied(self, *, owner: str, scope: str) -> int:
        """Markiert alle done-Tasks eines (owner, scope) als angewendet
        (payload.applied=true). Nach (Auto-)Apply verschwindet die abgeschlossene,
        angewandte Arbeit aus der Uebersicht (list_tasks(exclude_applied=True)) und
        ein erneuter Apply desselben Patches wird zum No-Op statt zum
        Kontext-Mismatch (409). Gibt die Zahl markierter Zeilen zurueck."""
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue "
                    "SET payload = COALESCE(payload, '{}'::jsonb) "
                    "|| '{\"applied\": true}'::jsonb "
                    "WHERE owner = %s AND scope = %s AND status = 'done'",
                    (owner, scope),
                )
                return cur.rowcount

    def is_applied(self, *, owner: str, scope: str) -> bool:
        """True, wenn fuer (owner, scope) bereits ein angewandter done-Task
        vorliegt -- Idempotenz-Wache fuer /api/apply (Doppel-Apply -> No-Op)."""
        row = self._conn.execute(
            "SELECT 1 FROM queue "
            "WHERE owner = %s AND scope = %s AND status = 'done' "
            "AND COALESCE((payload->>'applied')::boolean, false) LIMIT 1",
            (owner, scope),
        ).fetchone()
        return row is not None

    def get_status(self, item_id: int) -> str | None:
        """Gibt den aktuellen Status eines Tasks zurueck (alle Statuswerte)."""
        row = self._conn.execute(
            "SELECT status FROM queue WHERE id = %s", (item_id,)
        ).fetchone()
        return row[0] if row else None

    def get_task_info(self, item_id: int) -> dict[str, Any] | None:
        """Gibt id, task_type, scope, status und owner eines beliebigen Tasks.

        Im Gegensatz zu list_tasks() auch fuer done-Tasks abfragbar.
        """
        row = self._conn.execute(
            "SELECT id, task_type, scope, status, owner, model, payload "
            "FROM queue WHERE id = %s",
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
        }

    def list_tasks(
        self,
        *,
        statuses: tuple[str, ...] = ("pending", "running", "failed"),
        owner: str | None = None,
        limit: int | None = None,
        newest_first: bool = False,
        exclude_applied: bool = False,
    ) -> list[dict[str, Any]]:
        """Listet Tasks fuer das Dashboard (read-only, kein Locking).

        Default: pending, running und failed (done ausgeblendet). Mit owner-Filter
        nur Tasks dieses Owners. Reihenfolge created_at asc (newest_first=True ->
        desc, fuer die begrenzte done-Liste). limit begrenzt die Zeilenzahl -- so
        laesst sich eine kurze Liste zuletzt abgeschlossener Tasks holen, ohne die
        Uebersicht mit der gesamten Historie zu fluten. exclude_applied=True
        blendet Tasks aus, deren Patch schon angewendet wurde (payload.applied) --
        die abgeschlossene, angewandte Arbeit verschwindet dann aus der Uebersicht.
        """
        placeholders = ",".join(["%s"] * len(statuses))
        params: list[Any] = list(statuses)
        owner_clause = ""
        if owner is not None:
            owner_clause = " AND owner = %s"
            params.append(owner)
        applied_clause = ""
        if exclude_applied:
            applied_clause = " AND NOT COALESCE((payload->>'applied')::boolean, false)"
        order = "DESC" if newest_first else "ASC"
        limit_clause = ""
        if limit is not None:
            limit_clause = " LIMIT %s"
            params.append(limit)
        rows = self._conn.execute(
            f"SELECT id, dag_id, task_type, scope, model, status, "
            f"attempts, created_at, claimed_at "
            f"FROM queue WHERE status IN ({placeholders}){owner_clause}"
            f"{applied_clause} "
            f"ORDER BY created_at {order}{limit_clause}",
            params,
        ).fetchall()
        keys = (
            "id",
            "dag_id",
            "task_type",
            "scope",
            "model",
            "status",
            "attempts",
            "created_at",
            "claimed_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

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
