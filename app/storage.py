import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    """Short-lived SQLite transactions; business services own document semantics."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "records.sqlite3"
        with self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS documents "
                "(kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind, id))"
            )

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def put(self, kind, identifier, value, connection=None):
        if connection is None:
            with self.transaction() as transaction:
                self.put(kind, identifier, value, transaction)
            return
        connection.execute(
            "INSERT INTO documents(kind,id,body) VALUES(?,?,?) "
            "ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
            (kind, identifier, json.dumps(value, ensure_ascii=False)),
        )

    def get(self, kind, identifier, connection=None):
        if connection is None:
            with self.transaction() as transaction:
                return self.get(kind, identifier, transaction)
        row = connection.execute(
            "SELECT body FROM documents WHERE kind=? AND id=?", (kind, identifier)
        ).fetchone()
        if row is None:
            raise KeyError(identifier)
        return json.loads(row[0])

    def list(self, kind, connection=None):
        if connection is None:
            with self.transaction() as transaction:
                return self.list(kind, transaction)
        return [
            json.loads(row[0])
            for row in connection.execute("SELECT body FROM documents WHERE kind=? ORDER BY rowid", (kind,))
        ]
