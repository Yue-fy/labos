"""Owned transaction boundaries must release SQLite descriptors without GC."""
import gc
import sqlite3

import pytest

from labos.cooperation_worker import Worker
from labos.pilot_worker import PilotWorker


@pytest.mark.parametrize("factory", [Worker.db, PilotWorker.physical_db])
@pytest.mark.parametrize("fail", [False, True])
def test_owned_worker_connections_commit_or_rollback_then_close(tmp_path, factory, fail):
    class Owner:
        database = tmp_path / "state.sqlite"
        execution_database = database
    with sqlite3.connect(Owner.database) as setup:
        setup.execute("CREATE TABLE facts(value TEXT)")
    setup.close()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        def transaction():
            with factory(Owner()) as db:
                held.append(db)
                db.execute("INSERT INTO facts VALUES('durable')")
                if fail:
                    raise RuntimeError("rollback")
                return db.execute("SELECT value FROM facts").fetchone()[0]
        held = []
        if fail:
            with pytest.raises(RuntimeError, match="rollback"):
                transaction()
        else:
            assert transaction() == "durable"
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            held[0].execute("SELECT 1")
        with sqlite3.connect(Owner.database) as read:
            assert read.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == (0 if fail else 1)
        read.close()
    finally:
        if was_enabled:
            gc.enable()


def test_worker_transactions_do_not_accumulate_descriptors_without_gc(tmp_path):
    from pathlib import Path
    if not Path("/proc/self/fd").exists():
        pytest.skip("Linux descriptor accounting")
    owner = type("Owner", (), {"database": tmp_path / "state.sqlite"})()
    before = len(list(Path("/proc/self/fd").iterdir()))
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(200):
            with Worker.db(owner) as db:
                db.execute("CREATE TABLE IF NOT EXISTS facts(value TEXT)")
                db.execute("INSERT INTO facts VALUES('committed')")
        assert len(list(Path("/proc/self/fd").iterdir())) <= before
    finally:
        if was_enabled:
            gc.enable()


def test_program_contexts_close_after_intent_completion_and_cached_return(tmp_path, central_config, monkeypatch):
    from test_program_connector import connector, program_task
    import httpx
    real_connect = sqlite3.connect
    held = []
    def tracked(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        held.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, "connect", tracked)
    worker = connector(tmp_path, central_config, transport=httpx.MockTransport(lambda _: pytest.fail("network")))
    message = {"id": "once", "body": program_task()}
    # Exercise a deterministic built-in, without a subprocess or instrument.
    first = worker.responder.respond(message, "")
    assert first["answer"]["status"] == "completed"
    assert worker.responder.respond(message, "") == first
    worker.client.close()
    assert len(held) == 5  # report init, program init, intent, result, cached lookup
    for connection in held:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    with real_connect(worker.execution_database) as read:
        assert read.execute("SELECT state FROM executions").fetchone()[0] == "finished"
    read.close()


@pytest.mark.parametrize("table", [False, True])
def test_pilot_constructor_marker_check_closes_on_rejection(tmp_path, monkeypatch, table):
    from test_pilot_worker import configuration
    config = configuration(tmp_path)
    config.state_dir.mkdir()
    with sqlite3.connect(config.state_dir / "correspondence.sqlite") as setup:
        if table:
            setup.execute("CREATE TABLE state(key TEXT PRIMARY KEY, value TEXT)")
            setup.execute("INSERT INTO state VALUES('worker_kind','report')")
    setup.close()
    real_connect, held = sqlite3.connect, []
    def tracked(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        held.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, "connect", tracked)
    with pytest.raises(ValueError, match="separate state directory"):
        PilotWorker(config)
    assert len(held) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        held[0].execute("SELECT 1")


def test_report_constructor_identity_rejection_closes_connection(tmp_path, central_config, monkeypatch):
    import httpx
    import json
    from test_cooperation_worker import connection, Reports
    config = connection(tmp_path, central_config, "pc")
    transport = httpx.MockTransport(lambda _: pytest.fail("network"))
    worker = Worker(config, transport, Reports())
    worker.client.close()
    values = json.loads(config.connection_config.read_text())
    values["server_url"] = "https://different.example.org"
    config.connection_config.write_text(json.dumps(values))
    real_connect, held = sqlite3.connect, []
    def tracked(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        held.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, "connect", tracked)
    with pytest.raises(ValueError, match="state identity differs"):
        Worker(config, transport, Reports())
    assert len(held) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        held[0].execute("SELECT 1")
