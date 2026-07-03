"""I-1.7: Watch-Event-Handler (Trigger-Logik, ohne realen Observer).

Der Handler bildet fs-Events auf rel_path ab; der reale inotify-/Polling-Observer
ist Glue (WSL2-FS-abhaengig) und nicht Teil der schnellen det-Suite.
"""

from __future__ import annotations

from watchdog.events import (
    DirDeletedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)

from core.watch import IngestEventHandler


def test_modified_py_triggers_callback(tmp_path):
    (tmp_path / "pkg").mkdir()
    f = tmp_path / "pkg" / "a.py"
    f.write_text("x = 1")
    calls: list[str] = []
    handler = IngestEventHandler(tmp_path, calls.append)

    handler.on_modified(FileModifiedEvent(str(f)))
    assert calls == ["pkg/a.py"]


def test_created_py_triggers_callback(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1")
    calls: list[str] = []
    IngestEventHandler(tmp_path, calls.append).on_created(FileCreatedEvent(str(f)))
    assert calls == ["a.py"]


def test_non_python_ignored(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hi")
    calls: list[str] = []
    IngestEventHandler(tmp_path, calls.append).on_modified(FileModifiedEvent(str(f)))
    assert calls == []


def test_directory_event_ignored(tmp_path):
    calls: list[str] = []
    IngestEventHandler(tmp_path, calls.append).on_modified(
        DirModifiedEvent(str(tmp_path))
    )
    assert calls == []


def test_custom_suffix(tmp_path):
    f = tmp_path / "a.js"
    f.write_text("x")
    calls: list[str] = []
    IngestEventHandler(tmp_path, calls.append, suffixes=(".js",)).on_modified(
        FileModifiedEvent(str(f))
    )
    assert calls == ["a.js"]


# I-4.5: Loeschung/Rename-Events -> on_delete (retract)


def test_deleted_py_triggers_on_delete(tmp_path):
    f = tmp_path / "a.py"
    deletes: list[str] = []
    handler = IngestEventHandler(tmp_path, lambda _r: None, on_delete=deletes.append)
    handler.on_deleted(FileDeletedEvent(str(f)))
    assert deletes == ["a.py"]


def test_deleted_without_on_delete_is_noop(tmp_path):
    f = tmp_path / "a.py"
    # kein on_delete gesetzt -> kein Fehler, kein Effekt.
    IngestEventHandler(tmp_path, lambda _r: None).on_deleted(FileDeletedEvent(str(f)))


def test_deleted_non_python_ignored(tmp_path):
    f = tmp_path / "notes.txt"
    deletes: list[str] = []
    handler = IngestEventHandler(tmp_path, lambda _r: None, on_delete=deletes.append)
    handler.on_deleted(FileDeletedEvent(str(f)))
    assert deletes == []


def test_deleted_directory_ignored(tmp_path):
    deletes: list[str] = []
    handler = IngestEventHandler(tmp_path, lambda _r: None, on_delete=deletes.append)
    handler.on_deleted(DirDeletedEvent(str(tmp_path)))
    assert deletes == []


def test_moved_retracts_old_and_ingests_new(tmp_path):
    old = tmp_path / "old.py"
    new = tmp_path / "new.py"
    ingests: list[str] = []
    deletes: list[str] = []
    handler = IngestEventHandler(tmp_path, ingests.append, on_delete=deletes.append)
    handler.on_moved(FileMovedEvent(str(old), str(new)))
    assert deletes == ["old.py"]
    assert ingests == ["new.py"]


def test_moved_to_non_python_only_retracts(tmp_path):
    # a.py -> a.txt: alter scope retracted, kein Ingest eines Nicht-.py-Ziels.
    old = tmp_path / "a.py"
    new = tmp_path / "a.txt"
    ingests: list[str] = []
    deletes: list[str] = []
    handler = IngestEventHandler(tmp_path, ingests.append, on_delete=deletes.append)
    handler.on_moved(FileMovedEvent(str(old), str(new)))
    assert deletes == ["a.py"]
    assert ingests == []
