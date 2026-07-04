"""Repository-Interface: das einzige Modul mit SQL (I-1.2).

Kapselt den Artifact-Store hinter put/get/staleness. Liefert und nimmt das
einheitliche Result-Objekt (ResultDet | ResultProb). Versionierung statt
Loeschen: ein neues Artefakt verdraengt das bisherige aktuelle desselben
(scope, artifact_type) per superseded-Flag.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from core.graph import GraphEdge
from core.models.provenance_schema import ProducerClass, Provenance
from core.models.result_det_schema import ResultDet
from core.models.result_prob_schema import ResultProb
from core.router import MODEL_CAPABILITIES, TIER_CONFIDENCE
from core.symdiff import ChangeKind, change_kind

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

    def get_current(
        self, scope: str, artifact_type: str, *, trustworthy: bool = False
    ) -> Result | None:
        """Aktuelles (nicht superseded) Artefakt fuer (scope, artifact_type).

        trustworthy=True verlangt zusaetzlich stale=false (I-4.4): das Artefakt
        ist noch die aktuellste Version UND seine Grundlage hat sich nicht
        geaendert. Ohne das Flag wird auch ein stale-markiertes aktuelles
        Artefakt geliefert (es ist weiterhin die neueste bekannte Version).
        """
        sql = (
            f"SELECT {_SELECT_COLUMNS} FROM artifacts "
            "WHERE scope = %s AND artifact_type = %s AND superseded = false"
        )
        if trustworthy:
            sql += " AND stale = false"
        with self._conn.cursor() as cur:
            cur.execute(sql, (scope, str(artifact_type)))
            row = cur.fetchone()
        return _row_to_result(row) if row is not None else None

    def get_current_id(self, scope: str, artifact_type: str) -> int | None:
        """DB-id des aktuellen (nicht superseded) Artefakts, oder None.

        Adress-Handle fuer die Plan-Edit-Kette (I-6.3): PUT/confirm/discard
        pruefen {id} == aktuelle id (optimistische Concurrency -> 409 bei stale),
        da das Result-Modell selbst keine DB-id traegt.
        """
        row = self._conn.execute(
            "SELECT id FROM artifacts "
            "WHERE scope = %s AND artifact_type = %s AND superseded = false",
            (scope, str(artifact_type)),
        ).fetchone()
        return row[0] if row is not None else None

    def list_current_scopes(self, artifact_type: str) -> list[str]:
        """Alle scopes mit einem aktuellen (nicht superseded) Artefakt dieses
        Typs, deterministisch geordnet. Fuer das Apply-Gate (I-7.5): welche
        Patches liegen zur Bestaetigung vor."""
        rows = self._conn.execute(
            "SELECT scope FROM artifacts "
            "WHERE artifact_type = %s AND superseded = false ORDER BY scope",
            (str(artifact_type),),
        ).fetchall()
        return [r[0] for r in rows]

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

    def put_edges(self, scope: str, edges: list[GraphEdge]) -> None:
        """Superseded alte Kanten fuer diesen scope, fuegt neue ein (I-4.1).

        Atomare TX: alle alten Kanten mit src=scope werden superseded, dann
        werden die neuen eingefuegt. Leere edges-Liste = alle alten entfernen.
        """
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE graph_edges SET superseded = true "
                    "WHERE src = %s AND superseded = false",
                    (scope,),
                )
                if edges:
                    cur.executemany(
                        "INSERT INTO graph_edges "
                        "(src, dst, edge_type, confidence, source_hash) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        [
                            (e.src, e.dst, e.edge_type, e.confidence, e.source_hash)
                            for e in edges
                        ],
                    )

    def get_edges(self, scope: str) -> list[GraphEdge]:
        """Gibt alle aktuellen (nicht superseded) Kanten eines Scopes zurueck."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT src, dst, edge_type, confidence, source_hash "
                "FROM graph_edges WHERE src = %s AND superseded = false",
                (scope,),
            )
            return [
                GraphEdge(
                    src=row[0],
                    dst=row[1],
                    edge_type=row[2],
                    confidence=row[3],
                    source_hash=row[4],
                )
                for row in cur.fetchall()
            ]

    def dependencies(self, scope: str) -> list[str]:
        """Transitive Abhaengigkeitshuelle vorwaerts (src->dst): was scope nutzt.

        Rekursive CTE ueber nicht-superseded Kanten, native CYCLE-Klausel
        bricht Zyklen sauber ab (SQL-Standard, terminiert immer). Liefert die
        erreichten Ziel-scopes deterministisch sortiert. Enthaelt scope selbst
        nur, wenn ein Zyklus dorthin zurueckfuehrt.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                WITH RECURSIVE deps(src, dst) AS (
                    SELECT src, dst FROM graph_edges
                     WHERE src = %s AND superseded = false
                  UNION ALL
                    SELECT e.src, e.dst FROM graph_edges e
                      JOIN deps d ON e.src = d.dst
                     WHERE e.superseded = false
                ) CYCLE dst SET is_cycle USING path
                SELECT DISTINCT dst FROM deps ORDER BY dst
                """,
                (scope,),
            )
            return [row[0] for row in cur.fetchall()]

    def impact(self, scope: str) -> list[str]:
        """Transitive Impact-Huelle rueckwaerts (dst->src): wer scope nutzt.

        Grundlage der differenzierten Invalidierung (I-4.4): wer haengt
        transitiv von scope ab. Rekursive CTE mit CYCLE-Klausel, deterministisch
        sortiert. Enthaelt scope selbst nur bei einem Zyklus.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                WITH RECURSIVE impact(src, dst) AS (
                    SELECT src, dst FROM graph_edges
                     WHERE dst = %s AND superseded = false
                  UNION ALL
                    SELECT e.src, e.dst FROM graph_edges e
                      JOIN impact i ON e.dst = i.src
                     WHERE e.superseded = false
                ) CYCLE src SET is_cycle USING path
                SELECT DISTINCT src FROM impact ORDER BY src
                """,
                (scope,),
            )
            return [row[0] for row in cur.fetchall()]

    def retract_scope(self, scope: str) -> None:
        """Zieht einen scope aus dem aktuellen Store zurueck (I-4.5).

        Superseded alle aktuellen Artefakte UND ausgehenden Kanten (src=scope)
        atomar. Eingehende Kanten (dst=scope) bleiben: sie gehoeren anderen
        Dateien (deren src) und beschreiben deren -- nun ins Leere zeigenden --
        Bezug weiterhin korrekt. Kein DELETE: die superseded-Historie bleibt
        erhalten. Fuer geloeschte/umbenannte Dateien; danach sehen
        get_current/find_symbol/impact den scope nicht mehr.
        """
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(
                    "UPDATE artifacts SET superseded = true "
                    "WHERE scope = %s AND superseded = false",
                    (scope,),
                )
                cur.execute(
                    "UPDATE graph_edges SET superseded = true "
                    "WHERE src = %s AND superseded = false",
                    (scope,),
                )

    def current_file_scopes(self) -> list[str]:
        """Alle scopes mit mindestens einem aktuellen Artefakt, file:-Praefix.

        Basis fuer den ingest_repo-Prune (I-4.5): Abgleich Store gegen Working
        Tree. Deterministisch geordnet.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT scope FROM artifacts "
                "WHERE superseded = false AND scope LIKE 'file:%' "
                "ORDER BY scope"
            )
            return [row[0] for row in cur.fetchall()]

    def symbol_change_kind(self, scope: str) -> ChangeKind | None:
        """Aenderungsart des zuletzt re-ingesteten symbol_index dieses Scopes.

        Vergleicht den aktuellen symbol_index mit dem gerade superseded (I-4.3).
        None, wenn kein Vorgaenger existiert (Erst-Ingest -> nichts zu
        invalidieren) oder kein aktueller symbol_index vorliegt.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM artifacts "
                "WHERE scope = %s AND artifact_type = 'symbol_index' "
                "AND superseded = false",
                (scope,),
            )
            current = cur.fetchone()
            cur.execute(
                "SELECT content FROM artifacts "
                "WHERE scope = %s AND artifact_type = 'symbol_index' "
                "AND superseded = true ORDER BY id DESC LIMIT 1",
                (scope,),
            )
            previous = cur.fetchone()
        if current is None or previous is None:
            return None
        return change_kind(
            previous[0].get("symbols", []), current[0].get("symbols", [])
        )

    def mark_stale(
        self, scopes: Sequence[str], *, producer_class: ProducerClass | None = None
    ) -> int:
        """Markiert aktuelle (nicht superseded) Artefakte der scopes als stale.

        Optional auf eine producer_class beschraenkt (z.B. nur prob). Liefert
        die Anzahl frisch markierter Zeilen. Lazy (I-4.4): setzt nur das Flag,
        stoesst KEINE Neuberechnung an.
        """
        scope_list = list(scopes)
        if not scope_list:
            return 0
        sql = (
            "UPDATE artifacts SET stale = true "
            "WHERE scope = ANY(%s) AND superseded = false AND stale = false"
        )
        params: list[object] = [scope_list]
        if producer_class is not None:
            sql += " AND producer_class = %s"
            params.append(producer_class.value)
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.rowcount

    def invalidate_after_reingest(
        self, scope: str, *, session_id: str = "ingest"
    ) -> ChangeKind | None:
        """Differenzierte Invalidierung nach Re-Ingest eines file-scopes (I-4.4).

        Bestimmt die Aenderungsart (I-4.3) und markiert abhaengige Artefakte
        lazy stale:
          - eigene prob-Artefakte immer stale (Inhalt geaendert; die eigenen
            det-Artefakte sind gerade frisch re-ingestiert)
          - API-Change: transitive Rueckwaerts-Huelle (impact, I-4.2) voll stale
          - Impl-Change: nur die eigenen prob-Artefakte (det der Abhaengigen
            bleiben gueltig)
        Schreibt eine Trace-Zeile stage="invalidation" mit kind, Anzahl
        markierter Zeilen und betroffenen scopes (Erklaerbarkeit/Kalibrierung,
        I-4.7). Liefert die Aenderungsart, None beim Erst-Ingest (kein
        Vorgaenger -> nichts zu invalidieren). Neuberechnung erfolgt
        bedarfsgetrieben ueber die Queue (list_stale), nicht hier.
        """
        kind = self.symbol_change_kind(scope)
        marked_scopes: list[str] = []
        marked_count = 0
        if kind is not None:
            marked_count += self.mark_stale([scope], producer_class=ProducerClass.prob)
            marked_scopes.append(scope)
            if kind == ChangeKind.api:
                hull = self.impact(scope)
                marked_count += self.mark_stale(hull)
                marked_scopes.extend(hull)
        self.write_trace(
            session_id,
            "invalidation",
            detail={
                "kind": kind.value if kind is not None else None,
                "marked_count": marked_count,
                "scopes": marked_scopes,
            },
        )
        return kind

    def list_stale(
        self, *, producer_class: ProducerClass | None = None
    ) -> list[tuple[str, str]]:
        """Alle aktuellen (nicht superseded) stale-Artefakte als (scope,
        artifact_type), deterministisch geordnet (I-4.7).

        Betriebs-/Queue-Bruecke: was ist nicht mehr vertrauenswuerdig und damit
        Kandidat fuer bedarfsgetriebene Neuberechnung. Optional auf eine
        producer_class beschraenkt (z.B. nur prob-Reviews).
        """
        sql = (
            "SELECT scope, artifact_type FROM artifacts "
            "WHERE superseded = false AND stale = true"
        )
        params: list[object] = []
        if producer_class is not None:
            sql += " AND producer_class = %s"
            params.append(producer_class.value)
        sql += " ORDER BY scope, artifact_type"
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return [(row[0], row[1]) for row in cur.fetchall()]

    def metrics(self) -> dict[str, Any]:
        """Dashboard-Aggregate (I-5.2, read-only): Kosten heute,
        Eskalationsrate, Anzahl stale-Artefakte.

        Quellen: cloud_costs (heutiger Tag), trace (stage='task_result',
        detail.validation_result), artifacts (stale). Periodisch abfragen,
        nicht im Sekundentakt (R5). escalation_rate ist None, solange keine
        task_result-Zeilen vorliegen (der Worker schreibt sie noch nicht ->
        Folge-Haeppchen; cost_today/stale_count sind bereits live).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM cloud_costs "
                "WHERE recorded_on = CURRENT_DATE"
            )
            cost_today = float(cur.fetchone()[0])

            cur.execute(
                "SELECT count(*) FILTER "
                "(WHERE detail->>'validation_result' = 'escalated'), count(*) "
                "FROM trace WHERE stage = 'task_result'"
            )
            escalated, total = cur.fetchone()
            escalation_rate = escalated / total if total else None

            cur.execute(
                "SELECT count(*) FROM artifacts "
                "WHERE superseded = false AND stale = true"
            )
            stale_count = cur.fetchone()[0]

        return {
            "cost_today_usd": cost_today,
            "escalation_rate": escalation_rate,
            "stale_count": stale_count,
        }

    def history(self, *, days: int = 7) -> list[dict[str, Any]]:
        """Tages-Rollup Kosten + Eskalationen der letzten `days` Tage (I-5.2).

        Vereint cloud_costs (Kosten je recorded_on) und trace-task_result
        (Eskalationen/Tasks je Kalendertag) zu einem Eintrag pro Tag, aufsteigend
        sortiert. Tage ohne Daten in einer Quelle bekommen dort 0.
        """
        buckets: dict[str, dict[str, Any]] = {}

        def _bucket(day: str) -> dict[str, Any]:
            return buckets.setdefault(
                day, {"day": day, "cost_usd": 0.0, "escalations": 0, "tasks": 0}
            )

        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT recorded_on::text, SUM(cost_usd) FROM cloud_costs "
                "WHERE recorded_on > CURRENT_DATE - %s GROUP BY recorded_on",
                (days,),
            )
            for day, cost in cur.fetchall():
                _bucket(day)["cost_usd"] = float(cost)

            cur.execute(
                "SELECT (timestamp::date)::text, "
                "count(*) FILTER (WHERE detail->>'validation_result' = 'escalated'), "
                "count(*) FROM trace WHERE stage = 'task_result' "
                "AND timestamp > now() - make_interval(days => %s) "
                "GROUP BY timestamp::date",
                (days,),
            )
            for day, escalations, tasks in cur.fetchall():
                b = _bucket(day)
                b["escalations"] = escalations
                b["tasks"] = tasks

        return [buckets[day] for day in sorted(buckets)]

    def task_type_stats(self) -> list[dict[str, Any]]:
        """Kurzstatistik je task_type aus model_metrics (I-5.4-Vorlauf).

        Ø generierte Tokens, Ø Zeit (aus eval_count/tok_s abgeleitet), Ø tok/s
        und Anzahl Messungen. Nur Zeilen mit task_type und tok_per_s>0;
        deterministisch nach task_type sortiert.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT task_type, AVG(eval_count)::float, "
                "AVG(eval_count::float / tok_per_s)::float, "
                "AVG(tok_per_s)::float, COUNT(*) FROM model_metrics "
                "WHERE task_type IS NOT NULL AND tok_per_s > 0 "
                "GROUP BY task_type ORDER BY task_type"
            )
            return [
                {
                    "task_type": r[0],
                    "avg_tokens": r[1],
                    "avg_time_s": r[2],
                    "avg_tok_s": r[3],
                    "n": r[4],
                }
                for r in cur.fetchall()
            ]

    def calibration(self) -> dict[str, Any]:
        """Kalibrierungs-Auswertung aus der task_result-Trace (I-5.4, read-only).

        Zwei Sichten, beide rein aus der Trace ableitbar (kein neues Schema):

        - by_task_type: je task_type Eskalationsrate (groesster Routing-Hebel),
          fail_rate (R1-Abbruchrate), swap_rate (Anteil attempts>1) und
          avg_attempts. Grundlage fuer Start-Modell je task_type anheben/senken.
        - confidence: je final_model die behauptete confidence (Tier-Proxy wie im
          Worker, TIER_CONFIDENCE) gegen den tatsaechlichen Validierungserfolg
          (pass-Rate). overconfidence = confidence - success_rate (>0 = zu
          konfident -> Eskalations-Schwelle anheben).

        Auswertung ist deterministisch; die Schwellen-/Matrix-Anpassung wendet der
        Mensch an (nie vollautomatisch, R5). Sortierung stabil (task_type/model).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT detail->>'task_type', count(*), "
                "count(*) FILTER (WHERE detail->>'validation_result' = 'escalated'), "
                "count(*) FILTER (WHERE detail->>'validation_result' = 'fail'), "
                "count(*) FILTER (WHERE (detail->>'attempts')::int > 1), "
                "AVG((detail->>'attempts')::float) "
                "FROM trace WHERE stage = 'task_result' "
                "AND detail->>'task_type' IS NOT NULL "
                "GROUP BY detail->>'task_type' ORDER BY detail->>'task_type'"
            )
            by_task_type = [
                {
                    "task_type": tt,
                    "n": n,
                    "escalation_rate": esc / n,
                    "fail_rate": fail / n,
                    "swap_rate": swaps / n,
                    "avg_attempts": avg_attempts,
                }
                for tt, n, esc, fail, swaps, avg_attempts in cur.fetchall()
            ]

            cur.execute(
                "SELECT detail->>'final_model', count(*), "
                "count(*) FILTER (WHERE detail->>'validation_result' = 'pass') "
                "FROM trace WHERE stage = 'task_result' "
                "AND detail->>'final_model' IS NOT NULL "
                "GROUP BY detail->>'final_model' ORDER BY detail->>'final_model'"
            )
            confidence = []
            for model, n, ok in cur.fetchall():
                cap = MODEL_CAPABILITIES.get(model)
                conf = TIER_CONFIDENCE.get(cap.cost_tier, 0.70) if cap else 0.70
                success_rate = ok / n
                confidence.append(
                    {
                        "final_model": model,
                        "confidence": conf,
                        "n": n,
                        "success_rate": success_rate,
                        "overconfidence": conf - success_rate,
                    }
                )

        return {"by_task_type": by_task_type, "confidence": confidence}

    def compare_variants(self) -> dict[str, dict[str, Any] | None]:
        """A/B der task_result-Trace nach config_variant (I-5.5b, read-only).

        Reuse der vorhandenen Erfolgs-/Eskalationssignale (kein neues Mess-
        System, roadmap-schritt-5 Teil 3): je Variant Schema-Erfolgsrate
        (success_rate = pass/n), escalation_rate und fail_rate. Speist das
        Regressions-Gate (canary.regression_verdict): eine neue Config (canary)
        darf gegenueber baseline nicht schlechter abschneiden. Fehlt eine
        Variant, ist ihr Wert None.

        Kosten/Task fehlen hier bewusst -- cloud_costs traegt (noch) keine
        config_variant-Zuordnung (Luecke, s. spec_schritt-5 I-5.5).
        """
        out: dict[str, dict[str, Any] | None] = {"baseline": None, "canary": None}
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT detail->>'config_variant', count(*), "
                "count(*) FILTER (WHERE detail->>'validation_result' = 'pass'), "
                "count(*) FILTER (WHERE detail->>'validation_result' = 'escalated'), "
                "count(*) FILTER (WHERE detail->>'validation_result' = 'fail') "
                "FROM trace WHERE stage = 'task_result' "
                "AND detail->>'config_variant' IS NOT NULL "
                "GROUP BY detail->>'config_variant'"
            )
            for variant, n, ok, esc, fail in cur.fetchall():
                out[variant] = {
                    "n": n,
                    "success_rate": ok / n,
                    "escalation_rate": esc / n,
                    "fail_rate": fail / n,
                }
        return out

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
        # findings/risks/recommendations sind nicht mehr Top-Level (liegen in
        # content); die DB-Spalten bleiben aus Kompat-Gruenden, werden aber nicht
        # mehr ins Modell gereicht (ResultProb: extra='forbid').
        del findings, risks, recommendations
        return ResultProb(
            artifact_type=artifact_type,
            scope=scope,
            content=content,
            confidence=confidence,
            provenance=provenance,
        )
    return ResultDet(
        artifact_type=artifact_type,
        scope=scope,
        content=content,
        provenance=provenance,
    )
