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

from core.ingest import ingest_file
from core.repository import Repository
from core.secret_scan import SecretScan


class IngestEventHandler(FileSystemEventHandler):
    """Ruft on_file(rel_path) fuer geaenderte/neue Dateien passender Endung."""

    def __init__(
        self,
        repo_root: str | Path,
        on_file: Callable[[str], object],
        suffixes: tuple[str, ...] = (".py",),
    ) -> None:
        self._root = Path(repo_root).resolve()
        self._on_file = on_file
        self._suffixes = suffixes

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        raw = event.src_path
        path = Path(raw.decode() if isinstance(raw, bytes) else raw)
        if path.suffix not in self._suffixes:
            return
        try:
            rel = path.resolve().relative_to(self._root).as_posix()
        except ValueError:
            return  # ausserhalb der Repo-Wurzel
        self._on_file(rel)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)


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
            repo, repo_root, rel, source_hash=source_hash, scan=scan
        ),
        suffixes=suffixes,
    )
    observer.schedule(handler, str(repo_root), recursive=True)
    observer.start()
    return observer
