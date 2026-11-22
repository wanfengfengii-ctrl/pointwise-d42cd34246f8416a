import hashlib
import sqlite3
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FirstReceipt:
    receipt_id: str
    report_id: str
    snapshot_digest: str

    def to_document(self) -> dict:
        return asdict(self)


def initialize_receipts(conn: sqlite3.Connection) -> None:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS first_receipts (
            report_id TEXT PRIMARY KEY NOT NULL REFERENCES reports(report_id),
            receipt_id TEXT NOT NULL UNIQUE,
            snapshot_digest TEXT NOT NULL
        )
    ''')


def make_first_receipt(report_id: str, snapshot: str) -> FirstReceipt:
    digest = hashlib.sha256(snapshot.encode('utf-8')).hexdigest()
    return FirstReceipt(f'first:{report_id}', report_id, digest)


def insert_first_receipt(conn: sqlite3.Connection, receipt: FirstReceipt) -> None:
    if not conn.in_transaction:
        raise ValueError('first receipt requires an active signing transaction')
    conn.execute('INSERT INTO first_receipts VALUES (?, ?, ?)', (
        receipt.report_id, receipt.receipt_id, receipt.snapshot_digest,
    ))


def load_first_receipt(conn: sqlite3.Connection, report_id: str) -> FirstReceipt:
    row = conn.execute('''
        SELECT receipt_id, report_id, snapshot_digest FROM first_receipts WHERE report_id = ?
    ''', (report_id,)).fetchone()
    if row is None:
        raise KeyError(report_id)
    return FirstReceipt(*row)
