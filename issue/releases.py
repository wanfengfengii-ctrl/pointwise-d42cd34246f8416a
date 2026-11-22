import sqlite3
from dataclasses import dataclass

from issue.evidence import build_evidence
from issue.manifest import PackageManifest, encode_package
from issue.origins import build_origin_catalog
from records.surveys import read_frozen_survey
from records.transmissions import require_text


@dataclass(frozen=True)
class IssuedPackage:
    manifest: PackageManifest
    payload: bytes
    issue_receipt_id: str


def initialize_releases(conn: sqlite3.Connection) -> None:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS releases (
            release_id TEXT PRIMARY KEY NOT NULL,
            survey_id TEXT NOT NULL REFERENCES surveys(survey_id),
            block_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            payload BLOB NOT NULL,
            issue_receipt_id TEXT NOT NULL UNIQUE
        )
    ''')


def issue_package(conn: sqlite3.Connection, survey_id: str, release_id: str) -> IssuedPackage:
    survey_id = require_text(survey_id, 'survey id')
    release_id = require_text(release_id, 'release id')
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        survey = read_frozen_survey(conn, survey_id)
        manifest = PackageManifest(release_id, survey_id, survey.block_id, survey.revision_id)
        row = conn.execute('''
            SELECT survey_id, block_id, revision_id, payload, issue_receipt_id
            FROM releases WHERE release_id = ?
        ''', (release_id,)).fetchone()
        if row is not None:
            if tuple(row[:3]) != (survey_id, survey.block_id, survey.revision_id):
                raise ValueError('release id already binds a different frozen survey')
            return IssuedPackage(manifest, row[3], row[4])

        payload = encode_package(manifest, build_evidence(survey), build_origin_catalog(survey))
        receipt_id = f'issue:{release_id}'
        conn.execute('INSERT INTO releases VALUES (?, ?, ?, ?, ?, ?)', (
            release_id, survey_id, survey.block_id, survey.revision_id, payload, receipt_id,
        ))
        return IssuedPackage(manifest, payload, receipt_id)
