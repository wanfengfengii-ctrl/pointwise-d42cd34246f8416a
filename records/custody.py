from collections.abc import Collection, Sequence
from dataclasses import dataclass

from records.times import ClosedWindow
from records.transmissions import require_fields, require_text


CUSTODY_FIELDS = ('id', 'station', 'opens', 'closes', 'origin')


@dataclass(frozen=True)
class CustodyTurn:
    id: str
    station: str
    window: ClosedWindow
    origin: str

    def to_record(self) -> dict:
        opens, closes = self.window.to_document()
        return {
            'id': self.id,
            'station': self.station,
            'opens': opens,
            'closes': closes,
            'origin': self.origin,
        }


def validate_custody_turns(records: Sequence[dict], stations: Collection[str]) -> tuple[CustodyTurn, ...]:
    turns = []
    seen = set()
    for value in records:
        row = require_fields(value, CUSTODY_FIELDS, 'custody turn')
        turn_id = require_text(row['id'], 'custody turn id')
        station = require_text(row['station'], 'custody station')
        if turn_id in seen:
            raise ValueError(f'duplicate custody turn {turn_id!r}')
        if station not in stations:
            raise ValueError(f'unknown station for custody turn {turn_id!r}')
        window = ClosedWindow(row['opens'], row['closes'])
        origin = require_text(row['origin'], 'custody origin')
        turns.append(CustodyTurn(turn_id, station, window, origin))
        seen.add(turn_id)
    return tuple(turns)
