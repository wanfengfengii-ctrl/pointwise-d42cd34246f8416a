import json
import sqlite3
from dataclasses import dataclass

from records.custody import CustodyTurn, validate_custody_turns
from records.network import StationNetwork, topological_order, validate_stations
from records.revisions import BlockRevision, load_revision
from records.transmissions import require_text, validate_transmissions


@dataclass(frozen=True)
class FrozenSurvey:
    survey_id: str
    block_id: str
    revision_id: str
    network: StationNetwork
    custody_turns: tuple[CustodyTurn, ...]

    def snapshot(self) -> dict:
        return {
            'block_id': self.block_id,
            'revision_id': self.revision_id,
            'stations': list(self.network.stations),
            'transmissions': [edge.to_record() for edge in self.network.transmissions],
            'custody_turns': [turn.to_record() for turn in self.custody_turns],
        }


def _validated_survey(survey_id: str, revision: BlockRevision) -> FrozenSurvey:
    stations = validate_stations(revision.stations)
    station_set = set(stations)
    network = StationNetwork(stations, validate_transmissions(revision.transmissions, station_set))
    topological_order(network)
    turns = validate_custody_turns(revision.custody_turns, station_set)
    return FrozenSurvey(survey_id, revision.block_id, revision.revision_id, network, turns)


def initialize_surveys(conn: sqlite3.Connection) -> None:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS surveys (
            survey_id TEXT PRIMARY KEY NOT NULL,
            block_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            snapshot TEXT NOT NULL,
            FOREIGN KEY (block_id, revision_id) REFERENCES revisions (block_id, revision_id)
        )
    ''')


def freeze(conn: sqlite3.Connection, survey_id: str, block_id: str, revision_id: str) -> FrozenSurvey:
    survey_id = require_text(survey_id, 'survey id')
    identity = require_text(block_id, 'block id'), require_text(revision_id, 'revision id')
    conn.execute('BEGIN IMMEDIATE')
    with conn:
        try:
            existing = read_frozen_survey(conn, survey_id)
        except KeyError:
            revision = load_revision(conn, *identity)
            survey = _validated_survey(survey_id, revision)
            snapshot = json.dumps(survey.snapshot(), sort_keys=True, allow_nan=False)
            conn.execute('INSERT INTO surveys VALUES (?, ?, ?, ?)', (survey_id, *identity, snapshot))
            return survey
        if (existing.block_id, existing.revision_id) != identity:
            raise ValueError('survey id already binds a different revision')
        return existing


def read_frozen_survey(conn: sqlite3.Connection, survey_id: str) -> FrozenSurvey:
    survey_id = require_text(survey_id, 'survey id')
    row = conn.execute('SELECT snapshot FROM surveys WHERE survey_id = ?', (survey_id,)).fetchone()
    if row is None:
        raise KeyError(survey_id)
    revision = BlockRevision.from_document(json.loads(row[0]))
    return _validated_survey(survey_id, revision)
