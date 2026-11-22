import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from adjudicate.attachment import attachment_digest
from adjudicate.request import DeliveryRequest
from adjudicate.witness import DeliveryWitness
from records.transmissions import require_text
from reports.export import ReportView, decode_report_snapshot, encode_report_snapshot
from reports.receipts import initialize_receipts, insert_first_receipt, make_first_receipt


@dataclass(frozen=True)
class ReportDraft:
    request: DeliveryRequest
    release_id: str
    package_digest: str
    arrival: Fraction | None
    witness: DeliveryWitness | None
    rejection_attachment: bytes | None = None


def initialize_reports(conn: sqlite3.Connection) -> None:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY NOT NULL,
            received_id TEXT NOT NULL REFERENCES holdings(receipt_id),
            snapshot TEXT NOT NULL
        )
    ''')
    # Rejection attachments are signed together with their report and first
    # receipt; the row exists only for reports that actually carry one.
    conn.execute('''
        CREATE TABLE IF NOT EXISTS rejections (
            report_id TEXT PRIMARY KEY NOT NULL REFERENCES reports(report_id),
            attachment BLOB NOT NULL,
            attachment_digest TEXT NOT NULL
        )
    ''')
    initialize_receipts(conn)


def sign_report(conn: sqlite3.Connection, report_id: str, draft: ReportDraft,
                *, before_commit: Callable[[], None] | None = None) -> ReportView:
    report_id = require_text(report_id, 'report id')
    attachment = draft.rejection_attachment
    digest = attachment_digest(attachment) if attachment is not None else None
    snapshot = encode_report_snapshot(report_id, draft.request, draft.release_id,
                                      draft.package_digest, draft.arrival, draft.witness, digest)
    receipt = make_first_receipt(report_id, snapshot)
    view = decode_report_snapshot(snapshot, receipt)
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        existing = conn.execute('SELECT 1 FROM reports WHERE report_id = ?', (report_id,)).fetchone()
        if existing is not None:
            raise ValueError('report id already issued')
        conn.execute('INSERT INTO reports VALUES (?, ?, ?)', (report_id, draft.request.receipt_id, snapshot))
        insert_first_receipt(conn, receipt)
        if attachment is not None:
            conn.execute('INSERT INTO rejections VALUES (?, ?, ?)', (report_id, attachment, digest))
        if before_commit is not None:
            before_commit()
    return view
