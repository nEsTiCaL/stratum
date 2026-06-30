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
                             priority, depends_on, flags)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                                    ARRAY(SELECT jsonb_array_elements_text(q.depends_on))
                                )
                                AND dep.status != 'done'
                          )
                        ORDER BY q.priority DESC, q.created_at
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING id, dag_id, node_id, task_type, scope, model,
                              depends_on, flags, payload, attempts, status
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
        """Markiert einen Knoten als fehlgeschlagen; attempts wird erhoeht.

        Der Knoten kehrt zu 'pending' zurueck. Validator/Eskalation
        entscheiden, ob und mit welchem Modell ein erneuter Claim erfolgt.
        """
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE queue SET status = 'pending', attempts = attempts + 1 "
                    "WHERE id = %s",
                    (item_id,),
                )


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
    )
