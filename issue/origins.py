from dataclasses import asdict, dataclass

from records.surveys import FrozenSurvey
from records.transmissions import require_fields, require_text


def origin_key(kind: str, record_id: str) -> str:
    return f'{kind}:{record_id}'


@dataclass(frozen=True)
class OriginEntry:
    kind: str
    record_id: str
    block_id: str
    revision_id: str
    location: str

    @property
    def key(self) -> str:
        return origin_key(self.kind, self.record_id)

    def to_document(self) -> dict:
        return asdict(self)

    @classmethod
    def from_document(cls, value: object) -> 'OriginEntry':
        fields = ('kind', 'record_id', 'block_id', 'revision_id', 'location')
        row = require_fields(value, fields, 'origin entry')
        entry = cls(*(require_text(row[field], field) for field in fields))
        if entry.kind not in ('transmission', 'custody'):
            raise ValueError('unknown origin kind')
        return entry


def build_origin_catalog(survey: FrozenSurvey) -> dict[str, OriginEntry]:
    entries = {}
    for kind, records in (
        ('transmission', survey.network.transmissions), ('custody', survey.custody_turns)
    ):
        for record in records:
            entry = OriginEntry(kind, record.id, survey.block_id, survey.revision_id, record.origin)
            entries[entry.key] = entry
    return entries
