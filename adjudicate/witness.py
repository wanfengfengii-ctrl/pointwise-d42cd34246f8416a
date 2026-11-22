from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from adjudicate.reachability import ArrivalCandidate
from issue.origins import OriginEntry, origin_key
from records.times import ClosedWindow, encode_shift_second, parse_shift_second


@dataclass(frozen=True)
class CustodyUse:
    turn_id: str
    station: str
    window: ClosedWindow
    origin: OriginEntry

    def to_document(self) -> dict:
        return {
            'turn_id': self.turn_id,
            'station': self.station,
            'window': self.window.to_document(),
            'origin': self.origin.to_document(),
        }

    @classmethod
    def from_document(cls, document: dict) -> 'CustodyUse':
        return cls(document['turn_id'], document['station'], ClosedWindow.from_document(document['window']),
                   OriginEntry.from_document(document['origin']))


@dataclass(frozen=True)
class WitnessLeg:
    transmission_id: str
    source: str
    target: str
    departure: Fraction
    arrival: Fraction
    departure_window: ClosedWindow
    duration: Fraction
    origin: OriginEntry
    custody: CustodyUse | None

    def to_document(self) -> dict:
        return {
            'transmission_id': self.transmission_id,
            'source': self.source,
            'target': self.target,
            'departure': encode_shift_second(self.departure),
            'arrival': encode_shift_second(self.arrival),
            'departure_window': self.departure_window.to_document(),
            'duration': encode_shift_second(self.duration),
            'origin': self.origin.to_document(),
            'custody': self.custody.to_document() if self.custody is not None else None,
        }

    @classmethod
    def from_document(cls, document: dict) -> 'WitnessLeg':
        custody = document['custody']
        return cls(
            document['transmission_id'], document['source'], document['target'],
            parse_shift_second(document['departure']), parse_shift_second(document['arrival']),
            ClosedWindow.from_document(document['departure_window']),
            parse_shift_second(document['duration']), OriginEntry.from_document(document['origin']),
            CustodyUse.from_document(custody) if custody is not None else None,
        )


@dataclass(frozen=True)
class DeliveryWitness:
    legs: tuple[WitnessLeg, ...]

    def to_document(self) -> list[dict]:
        return [leg.to_document() for leg in self.legs]

    @classmethod
    def from_document(cls, document: list[dict]) -> 'DeliveryWitness':
        return cls(tuple(WitnessLeg.from_document(row) for row in document))


def build_witness(candidate: ArrivalCandidate, arrival: Fraction,
                  origins: Mapping[str, OriginEntry]) -> DeliveryWitness:
    reverse_legs = []
    current = candidate
    time = parse_shift_second(arrival)
    while current is not None:
        edge = current.transmission
        if not current.transfer.arrivals.contains(time):
            raise ValueError('selected arrival is outside its propagated window')
        departure = time - edge.duration
        custody = None
        if current.custody is not None:
            turn = current.custody
            custody = CustodyUse(turn.id, turn.station, turn.window, origins[origin_key('custody', turn.id)])
        reverse_legs.append(WitnessLeg(
            edge.id, edge.source, edge.target, departure, time, edge.departure, edge.duration,
            origins[origin_key('transmission', edge.id)], custody,
        ))
        if current.previous is not None:
            eligible = current.transfer.previous_arrivals
            if eligible is None or departure < eligible.start:
                raise ValueError('selected departure has no compatible relay arrival')
            # The chosen arrival is used unchanged when reconstructing the previous leg.
            time = min(eligible.end, departure)
        current = current.previous
    return DeliveryWitness(tuple(reversed(reverse_legs)))
