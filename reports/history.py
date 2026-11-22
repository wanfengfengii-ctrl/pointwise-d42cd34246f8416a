import sqlite3

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
