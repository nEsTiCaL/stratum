"""Filesystem-Watch als Ingestion-Trigger (I-1.7).

Entkoppelt vom Indexer: der Handler bildet fs-Events auf rel_path ab und ruft
einen injizierten Callback (die Ingestion). Die Verdrahtung mit einem Observer
ist duenne Glue. Portabilitaet: inotify feuert nur im WSL2-FS zuverlaessig
(nicht unter /mnt/c|d); fuer solche Faelle Polling-Fallback (use_polling=True).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler

from core.ingest import file_scope, ingest_file
from core.repository import Repository
from core.secret_scan import SecretScan


class IngestEventHandler(FileSystemEventHandler):
    """Bildet fs-Events auf rel_path ab und ruft Callbacks passender Endung.

    on_file(rel)   fuer geaenderte/neue/verschobene-Ziel-Dateien (Re-Ingest).
    on_delete(rel) fuer geloeschte/verschobene-Quell-Dateien (Retract, I-4.5);
                   optional, ohne Callback bleibt eine Loeschung folgenlos.
    """

    def __init__(
        self,
        repo_root: str | Path,
        on_file: Callable[[str], object],
        suffixes: tuple[str, ...] = (".py",),
        *,
        on_delete: Callable[[str], object] | None = None,
    ) -> None:
        self._root = Path(repo_root).resolve()
        self._on_file = on_file
        self._on_delete = on_delete
        self._suffixes = suffixes

    def _rel(self, raw: str | bytes) -> str | None:
        """Absoluter/roher Event-Pfad -> rel_path unter der Wurzel, oder None
        (falsche Endung oder ausserhalb der Repo-Wurzel)."""
        path = Path(raw.decode() if isinstance(raw, bytes) else raw)
        if path.suffix not in self._suffixes:
            return None
        try:
            return path.resolve().relative_to(self._root).as_posix()
        except ValueError:
            return None

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        rel = self._rel(event.src_path)
        if rel is not None:
            self._on_file(rel)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._on_delete is None:
            return
        rel = self._rel(event.src_path)
        if rel is not None:
            self._on_delete(rel)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        old = self._rel(event.src_path)
        if old is not None and self._on_delete is not None:
            self._on_delete(old)
        new = self._rel(event.dest_path)
        if new is not None:
            self._on_file(new)


def watch(
    repo_root: str | Path,
    repo: Repository,
    *,
    source_hash: str | None = None,
    suffixes: tuple[str, ...] = (".py",),
    use_polling: bool = False,
    scan: SecretScan | None = None,
):
    """Startet einen (nicht blockierenden) Observer und liefert ihn zurueck;
    der Aufrufer steuert den Lebenszyklus (stop/join)."""
    from watchdog.observers import Observer
    from watchdog.observers.polling import PollingObserver

    observer = (PollingObserver if use_polling else Observer)()
    handler = IngestEventHandler(
        repo_root,
        lambda rel: ingest_file(
            repo, repo_root, rel, source_hash=source_hash, scan=scan, invalidate=True
        ),
        suffixes=suffixes,
        on_delete=lambda rel: repo.retract_scope(file_scope(rel)),
    )
    observer.schedule(handler, str(repo_root), recursive=True)
    observer.start()
    return observer
