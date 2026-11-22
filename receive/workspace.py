import sqlite3
from os import PathLike


def open_workspace(path: str | PathLike[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    try:
        conn.execute('PRAGMA foreign_keys = ON')
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def initialize_holdings(conn: sqlite3.Connection) -> None:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS holdings (
            receipt_id TEXT PRIMARY KEY NOT NULL,
            survey_id TEXT NOT NULL,
            block_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            payload BLOB NOT NULL
        )
    ''')
