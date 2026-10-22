import sqlite3

import pytest

from labos.journal import Journal


def test_journal_closes_connection_on_success_and_failure(tmp_path):
    journal = Journal(tmp_path)
    with journal.connect() as db:
        assert db.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        db.execute("SELECT 1")
    with pytest.raises(RuntimeError, match="interrupted"):
        with journal.connect() as interrupted:
            interrupted.execute("INSERT INTO devices(id,run_id) VALUES('test','run')")
            raise RuntimeError("interrupted")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        interrupted.execute("SELECT 1")
    with journal.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM devices WHERE id='test'").fetchone()[0] == 0
