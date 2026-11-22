import json
import sqlite3
from dataclasses import dataclass

from records.transmissions import require_fields, require_text


_REVISION_FIELDS = ('block_id', 'revision_id', 'stations', 'transmissions', 'custody_turns')


@dataclass(frozen=True)
class BlockRevision:
    block_id: str
    revision_id: str
    stations: tuple[str, ...]
    transmissions: tuple[dict, ...]
    custody_turns: tuple[dict, ...]

    @classmethod
    def from_document(cls, value: object) -> 'BlockRevision':
        row = require_fields(value, _REVISION_FIELDS, 'block revision')
        block_id = require_text(row['block_id'], 'block id')
        revision_id = require_text(row['revision_id'], 'revision id')
        for field in ('stations', 'transmissions', 'custody_turns'):
            if not isinstance(row[field], list):
                raise ValueError(f'{field} must be an array')
        return cls(block_id, revision_id, tuple(row['stations']),
                   tuple(row['transmissions']), tuple(row['custody_turns']))

    def to_document(self) -> dict:
        return {
            'block_id': self.block_id,
            'revision_id': self.revision_id,
            'stations': list(self.stations),
            'transmissions': list(self.transmissions),
            'custody_turns': list(self.custody_turns),
        }


def initialize_revisions(conn: sqlite3.Connection) -> None:
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            block_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            document TEXT NOT NULL,
            PRIMARY KEY (block_id, revision_id)
        )
    ''')


def save_revision(conn: sqlite3.Connection, revision: BlockRevision) -> None:
    document = revision.to_document()
    BlockRevision.from_document(document)
    try:
        raw = json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('registration must be finite JSON data') from exc
    identity = revision.block_id, revision.revision_id
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        existing = conn.execute(
            'SELECT document FROM revisions WHERE block_id = ? AND revision_id = ?', identity
        ).fetchone()
        if existing is None:
            conn.execute('INSERT INTO revisions VALUES (?, ?, ?)', (*identity, raw))
        elif existing[0] != raw:
            raise ValueError('revision id already binds different registration data')


def load_revision(conn: sqlite3.Connection, block_id: str, revision_id: str) -> BlockRevision:
    identity = require_text(block_id, 'block id'), require_text(revision_id, 'revision id')
    row = conn.execute(
        'SELECT document FROM revisions WHERE block_id = ? AND revision_id = ?', identity
    ).fetchone()
    if row is None:
        raise KeyError(identity)
    return BlockRevision.from_document(json.loads(row[0]))
