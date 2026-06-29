"""I-1.7: Watch-Event-Handler (Trigger-Logik, ohne realen Observer).

Der Handler bildet fs-Events auf rel_path ab; der reale inotify-/Polling-Observer
ist Glue (WSL2-FS-abhaengig) und nicht Teil der schnellen det-Suite.
"""
from __future__ import annotations

from watchdog.events import DirModifiedEvent, FileCreatedEvent, FileModifiedEvent

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
    IngestEventHandler(tmp_path, calls.append).on_modified(DirModifiedEvent(str(tmp_path)))
    assert calls == []


def test_custom_suffix(tmp_path):
    f = tmp_path / "a.js"
    f.write_text("x")
    calls: list[str] = []
    IngestEventHandler(tmp_path, calls.append, suffixes=(".js",)).on_modified(
        FileModifiedEvent(str(f))
    )
    assert calls == ["a.js"]
