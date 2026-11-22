from collections.abc import Collection, Sequence
from dataclasses import dataclass
from fractions import Fraction

from records.times import ClosedWindow, encode_shift_second, parse_shift_second


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be nonempty text')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{field} must be valid UTF-8 text') from exc
    return value


def require_fields(value: object, fields: Collection[str], label: str) -> dict:
    if not isinstance(value, dict) or value.keys() != set(fields):
        raise ValueError(f'invalid {label} fields')
    return value


TRANSMISSION_FIELDS = ('id', 'source', 'target', 'opens', 'closes', 'duration', 'origin')


@dataclass(frozen=True)
class Transmission:
    id: str
    source: str
    target: str
    departure: ClosedWindow
    duration: Fraction
    origin: str

    def to_record(self) -> dict:
        opens, closes = self.departure.to_document()
        return {
            'id': self.id,
            'source': self.source,
            'target': self.target,
            'opens': opens,
            'closes': closes,
            'duration': encode_shift_second(self.duration),
            'origin': self.origin,
        }


def validate_transmissions(records: Sequence[dict], stations: Collection[str]) -> tuple[Transmission, ...]:
    transmissions = []
    seen = set()
    for value in records:
        row = require_fields(value, TRANSMISSION_FIELDS, 'transmission')
        record_id = require_text(row['id'], 'transmission id')
        source = require_text(row['source'], 'departure station')
        target = require_text(row['target'], 'arrival station')
        if record_id in seen:
            raise ValueError(f'duplicate transmission {record_id!r}')
        if source not in stations or target not in stations:
            raise ValueError(f'unknown station on transmission {record_id!r}')
        departure = ClosedWindow(row['opens'], row['closes'])
        duration = parse_shift_second(row['duration'])
        if duration <= 0:
            raise ValueError(f'transmission {record_id!r} requires positive duration')
        origin = require_text(row['origin'], 'transmission origin')
        transmissions.append(Transmission(record_id, source, target, departure, duration, origin))
        seen.add(record_id)
    return tuple(transmissions)
