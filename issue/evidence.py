from dataclasses import dataclass

from issue.origins import origin_key
from records.custody import CustodyTurn
from records.surveys import FrozenSurvey
from records.transmissions import Transmission


def _put_origin_reference(record: dict, kind: str) -> dict:
    del record['origin']
    record['origin_key'] = origin_key(kind, record['id'])
    return record


@dataclass(frozen=True)
class EvidenceBody:
    stations: tuple[str, ...]
    transmissions: tuple[Transmission, ...]
    custody_turns: tuple[CustodyTurn, ...]

    def to_document(self) -> dict:
        return {
            'stations': list(self.stations),
            'transmissions': [
                _put_origin_reference(edge.to_record(), 'transmission') for edge in self.transmissions
            ],
            'custody_turns': [
                _put_origin_reference(turn.to_record(), 'custody') for turn in self.custody_turns
            ],
        }


def build_evidence(survey: FrozenSurvey) -> EvidenceBody:
    return EvidenceBody(survey.network.stations, survey.network.transmissions, survey.custody_turns)
