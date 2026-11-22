import sqlite3
from dataclasses import dataclass

from receive.envelope import decode_envelope
from receive.integrity import VerifiedPackage, verify_integrity
from receive.survey_check import SurveyRef, require_survey_match
from records.transmissions import require_text


@dataclass(frozen=True)
class ReceivedPackage:
    receipt_id: str
    survey: SurveyRef
    payload: bytes
    package: VerifiedPackage


def _validated_receipt(receipt_id: str, payload: bytes, expected: SurveyRef) -> ReceivedPackage:
    package = verify_integrity(decode_envelope(payload))
    require_survey_match(package, expected)
    return ReceivedPackage(receipt_id, expected, payload, package)


def accept(conn: sqlite3.Connection, receipt_id: str, payload: bytes, expected: SurveyRef) -> ReceivedPackage:
    receipt_id = require_text(receipt_id, 'receipt id')
    received = _validated_receipt(receipt_id, payload, expected)
    values = expected.survey_id, expected.block_id, expected.revision_id, payload
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        existing = conn.execute('''
            SELECT survey_id, block_id, revision_id, payload FROM holdings WHERE receipt_id = ?
        ''', (receipt_id,)).fetchone()
        if existing is None:
            conn.execute('INSERT INTO holdings VALUES (?, ?, ?, ?, ?)', (receipt_id, *values))
        elif tuple(existing) != values:
            raise ValueError('receipt id already binds a different received package')
    return received


def load_received(conn: sqlite3.Connection, receipt_id: str) -> ReceivedPackage:
    receipt_id = require_text(receipt_id, 'receipt id')
    row = conn.execute('''
        SELECT survey_id, block_id, revision_id, payload FROM holdings WHERE receipt_id = ?
    ''', (receipt_id,)).fetchone()
    if row is None:
        raise KeyError(receipt_id)
    return _validated_receipt(receipt_id, row[3], SurveyRef(*row[:3]))
