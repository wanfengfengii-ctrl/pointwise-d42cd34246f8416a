import sqlite3

from adjudicate.attachment import attachment_digest
from records.transmissions import require_text
from reports.export import ReportView, decode_report_snapshot
from reports.receipts import load_first_receipt


def read_report(conn: sqlite3.Connection, report_id: str) -> ReportView:
    report_id = require_text(report_id, 'report id')
    row = conn.execute('SELECT snapshot FROM reports WHERE report_id = ?', (report_id,)).fetchone()
    if row is None:
        raise KeyError(report_id)
    receipt = load_first_receipt(conn, report_id)
    return decode_report_snapshot(row[0], receipt)


def read_rejection(conn: sqlite3.Connection, report_id: str) -> bytes | None:
    """Return the original signed rejection attachment bytes.

    Old reports and reachable reports have no attachment and return ``None``.
    Unknown report ids raise :class:`KeyError`.  A report whose snapshot
    declares an attachment while the stored row is missing or no longer bound
    to those exact bytes raises :class:`ValueError`.
    """
    report = read_report(conn, report_id)
    row = conn.execute(
        'SELECT attachment, attachment_digest FROM rejections WHERE report_id = ?', (report_id,)
    ).fetchone()
    if report.attachment_digest is None:
        if row is not None:
            raise ValueError('stored rejection attachment is not bound by its report snapshot')
        return None
    if row is None:
        raise ValueError('report declares a rejection attachment but none is stored')
    attachment, stored_digest = row
    if not isinstance(attachment, bytes) or not attachment:
        raise ValueError('stored rejection attachment is empty or invalid')
    actual_digest = attachment_digest(attachment)
    if stored_digest != actual_digest or report.attachment_digest != actual_digest:
        raise ValueError('stored rejection attachment does not match the signed binding')
    return attachment
