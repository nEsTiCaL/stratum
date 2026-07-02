"""Repository-Interface: das einzige Modul mit SQL (I-1.2).

Kapselt den Artifact-Store hinter put/get/staleness. Liefert und nimmt das
einheitliche Result-Objekt (ResultDet | ResultProb). Versionierung statt
Loeschen: ein neues Artefakt verdraengt das bisherige aktuelle desselben
(scope, artifact_type) per superseded-Flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from core.models.provenance_schema import ProducerClass, Provenance
from core.models.result_det_schema import ResultDet
from core.models.result_prob_schema import ResultProb

Result = ResultDet | ResultProb


@dataclass(frozen=True)
class TraceEntry:
    """Eine Trace-Zeile. Kein Artefakt, kein Result-Schema (reine Chronik)."""

    id: int
    session_id: str
    stage: str
    artifact_id: int | None
    detail: dict[str, Any] | None
    timestamp: datetime


@dataclass(frozen=True)
class SymbolHit:
    """Ein Treffer der repo-weiten Symbol-Suche: Fundort (scope) plus die
    symbol_index-Felder eines Symbols (I-1.4). Geliefert von find_symbol."""

    scope: str
    name: str
    kind: str
    span: list[int] | None
    parent: str | None
    visibility: str | None
    signature: str | None
    docstring: str | None


# Spaltenreihenfolge fuer das Auslesen, einmal definiert.
_SELECT_COLUMNS = (
    "schema_version, artifact_type, scope, producer_class, source_hash, "
    "input_hash, producer, producer_version, confidence, timestamp, "
    "content, findings, risks, recommendations"
)


def _jsonb(value: object | None) -> Jsonb | None:
    """None -> SQL NULL (nicht JSON null); sonst als jsonb adaptieren."""
    return Jsonb(value) if value is not None else None


class Repository:
    """Zugriff auf den Artifact-Store. Eine Instanz haelt eine Verbindung."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def put_artifact(self, result: Result) -> int:
        """Schreibt ein Artefakt, verdraengt das bisherige aktuelle atomar.

        Liefert die id der neuen Zeile.
        """
        p = result.provenance
        dump = result.model_dump(mode="json")
        artifact_type = result.artifact_type.value
        confidence = dump.get("confidence")

        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE artifacts SET superseded = true "
                    "WHERE scope = %s AND artifact_type = %s AND superseded = false",
                    (result.scope, artifact_type),
                )
                cur.execute(
                    """
                    INSERT INTO artifacts (
                        schema_version, artifact_type, scope, producer_class,
                        source_hash, input_hash, producer, producer_version,
                        confidence, timestamp, content, findings, risks,
                        recommendations, superseded
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false
                    )
                    RETURNING id
                    """,
                    (
                        p.schema_version,
                        artifact_type,
                        result.scope,
                        p.producer_class.value,
                        p.source_hash,
                        p.input_hash,
                        p.producer,
                        p.producer_version,
                        confidence,
                        p.timestamp,
                        _jsonb(dump["content"]),
                        _jsonb(dump.get("findings")),
                        _jsonb(dump.get("risks")),
                        _jsonb(dump.get("recommendations")),
                    ),
                )
                row = cur.fetchone()
                assert row is not None  # RETURNING liefert immer eine Zeile
                return row[0]

    def get_current(self, scope: str, artifact_type: str) -> Result | None:
        """Aktuelles (nicht superseded) Artefakt fuer (scope, artifact_type)."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {_SELECT_COLUMNS} FROM artifacts "
                "WHERE scope = %s AND artifact_type = %s AND superseded = false",
                (scope, str(artifact_type)),
            )
            row = cur.fetchone()
        return _row_to_result(row) if row is not None else None

    def write_trace(
        self,
        session_id: str,
        stage: str,
        *,
        artifact_id: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> int:
        """Haengt eine Trace-Zeile an (write-time-Zeitstempel). Liefert die id.

        Laeuft ab S1 bei jeder Stufe mit; speist spaeter Kalibrierung (S5) und
        das Live-Dashboard.
        """
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO trace "
                    "(session_id, stage, artifact_id, detail, timestamp) "
                    "VALUES (%s, %s, %s, %s, now()) RETURNING id",
                    (session_id, stage, artifact_id, _jsonb(detail)),
                )
                row = cur.fetchone()
                assert row is not None
                return row[0]

    def get_trace(self, session_id: str) -> list[TraceEntry]:
        """Alle Trace-Zeilen einer Session, chronologisch."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT id, session_id, stage, artifact_id, detail, timestamp "
                "FROM trace WHERE session_id = %s ORDER BY timestamp, id",
                (session_id,),
            )
            return [TraceEntry(*row) for row in cur.fetchall()]

    def find_symbol(self, name: str, *, kind: str | None = None) -> list[SymbolHit]:
        """Sucht ein Symbol ueber ALLE aktuellen symbol_index-Artefakte (I-D.0).

        Quer-Suche statt Punkt-Lookup: serverseitiger jsonb-Lateral-Join ueber
        den symbols-Array, exakter Namensvergleich, optionaler kind-Filter.
        Deterministisch geordnet (scope, Span-Start). Nur symbol_index, nur
        nicht-superseded.
        """
        sql = (
            "SELECT a.scope, sym "
            "FROM artifacts a, jsonb_array_elements(a.content->'symbols') sym "
            "WHERE a.artifact_type = 'symbol_index' AND a.superseded = false "
            "AND sym->>'name' = %s"
        )
        params: list[object] = [name]
        if kind is not None:
            sql += " AND sym->>'kind' = %s"
            params.append(kind)
        sql += " ORDER BY a.scope, (sym->'span'->>0)::int, (sym->'span'->>1)::int"

        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return [_row_to_symbol_hit(scope, sym) for scope, sym in cur.fetchall()]

    def verify_api_key(self, key: str) -> str | None:
        """Gibt den Owner-Namen zurueck wenn der Key gueltig ist, sonst None."""
        from core.auth import hash_key

        key_hash = hash_key(key)
        row = self._conn.execute(
            "SELECT owner FROM capabilities "
            "WHERE key_hash = %s AND revoked = false "
            "AND (expires_at IS NULL OR expires_at > now())",
            (key_hash,),
        ).fetchone()
        return row[0] if row else None

    def register_capability(self, owner: str, key_hash: str, key_prefix: str) -> int:
        """Legt einen neuen API-Key an. Gibt die capability-id zurueck."""
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO capabilities (owner, key_hash, key_prefix) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (owner, key_hash, key_prefix),
                )
                row = cur.fetchone()
                assert row is not None
                return row[0]

    def staleness_lookup(self, scope: str, artifact_type: str, input_hash: str) -> bool:
        """True, wenn ein aktuelles Artefakt genau diesen input_hash hat.

        Treffer = die Eingabe ist unveraendert, das Artefakt aktuell (kein Re-Index).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM artifacts "
                "WHERE scope = %s AND artifact_type = %s AND input_hash = %s "
                "AND superseded = false)",
                (scope, str(artifact_type), input_hash),
            )
            row = cur.fetchone()
            assert row is not None
            return bool(row[0])


def _row_to_symbol_hit(scope: str, sym: dict[str, Any]) -> SymbolHit:
    return SymbolHit(
        scope=scope,
        name=sym["name"],
        kind=sym["kind"],
        span=sym.get("span"),
        parent=sym.get("parent"),
        visibility=sym.get("visibility"),
        signature=sym.get("signature"),
        docstring=sym.get("docstring"),
    )


def _row_to_result(row: tuple) -> Result:
    (
        schema_version,
        artifact_type,
        scope,
        producer_class,
        source_hash,
        input_hash,
        producer,
        producer_version,
        confidence,
        timestamp,
        content,
        findings,
        risks,
        recommendations,
    ) = row

    provenance = Provenance(
        schema_version=schema_version,
        source_hash=source_hash,
        input_hash=input_hash,
        producer=producer,
        producer_version=producer_version,
        producer_class=producer_class,
        timestamp=timestamp,
        artifact_type=artifact_type,
        scope=scope,
    )

    if producer_class == ProducerClass.prob.value:
        return ResultProb(
            artifact_type=artifact_type,
            scope=scope,
            content=content,
            confidence=confidence,
            findings=findings,
            risks=risks,
            recommendations=recommendations,
            provenance=provenance,
        )
    return ResultDet(
        artifact_type=artifact_type,
        scope=scope,
        content=content,
        provenance=provenance,
    )
