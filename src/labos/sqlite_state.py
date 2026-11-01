"""Transactions for connections owned by a worker, with deterministic release."""
from contextlib import contextmanager
import sqlite3


@contextmanager
def owned_connection(database, *, timeout=5, rows=False):
    connection = sqlite3.connect(database, timeout=timeout)
    try:
        if rows:
            connection.row_factory = sqlite3.Row
        with connection:
            yield connection
    finally:
        connection.close()
