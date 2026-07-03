# Log-Archiv Schritt 4 (Graph-Tiefe)

Rotiert aus log.md (P4, 2026-07-03). Aera 2026-07-02/03: I-4.1..4.8
(graph_edges, rekursive CTE, Symbol-Diff, differenzierte Invalidierung) +
Konsolidierung I-4.5..4.8 (Loeschung/Rename-Hygiene, Kanten-Qualitaet,
Invalidierungs-Trace, pgvector). Details je Haeppchen in spec_schritt-4.

## [2026-07-03] decision | I-4.8 fertig: Migration 0008 CREATE EXTENSION vector (S4-Voraussetzung nachgezogen, nur Extension, Embeddings-Schema erst mit RAG); test_migrations (Extension+vector-Typ); Schritt 4 inkl. Konsolidierung VOLLSTAENDIG -> spec_schritt-4
## [2026-07-03] decision | I-4.7 fertig: invalidate_after_reingest schreibt Trace stage=invalidation (kind/marked_count/scopes, session_id durchgereicht), Repository.list_stale (Queue-Bruecke, producer_class-Filter, sortiert); 18 Tests -> spec_schritt-4
## [2026-07-03] decision | I-4.6 fertig: call-dst dateilokal auf symbol:pfad::callee_ref (konsistent mit contains, impact-erreichbar), contains-dst parent-qualifiziert (A.foo/B.foo kollisionsfrei); graph._symbol_node/_qualified_name; kein Migration (Re-Ingest); 34 Tests -> spec_schritt-4
## [2026-07-03] decision | I-4.5 fertig: Repository.retract_scope (Artefakte+ausgehende Kanten superseden, eingehende bleiben) + current_file_scopes; Watch on_deleted/on_moved -> retract; ingest_repo(prune) Glob-Domaenen-Abgleich; 22 Tests -> spec_schritt-4
## [2026-07-03] decision | Funktionsreview Datengrundlage -> Konsolidierung I-4.5..4.8 angelegt (Loeschung/Rename-Hygiene, call/contains-Kanten-Qualitaet, Invalidierungs-Trace+list_stale, pgvector-Extension) -> spec_schritt-4
## [2026-07-03] decision | Schritt 4 VOLLSTAENDIG: I-4.4 fertig -- Migration 0007 stale-Flag, Repository.mark_stale/invalidate_after_reingest (API->impact-Huelle voll, Impl->nur eigene prob), get_current(trustworthy), Watch-Hook invalidate=True, lazy -> spec_schritt-4
## [2026-07-03] decision | I-4.3 fertig: core/symdiff.change_kind (API vs Impl ueber exportierte public-Oberflaeche) + Repository.symbol_change_kind (superseded vs aktuell) -> spec_schritt-4
## [2026-07-03] decision | I-4.2 fertig: Repository.dependencies (vorwaerts src->dst) + impact (rueckwaerts dst->src), rekursive CTE mit nativer CYCLE-Klausel -> spec_schritt-4
## [2026-07-02] decision | I-4.1 fertig: graph_edges (Migration 0006) + Befuellung aus Artefakten; Kanten-Scope-Konvention -> spec_schritt-4
