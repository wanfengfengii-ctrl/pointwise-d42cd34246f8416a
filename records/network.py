from collections import deque
from dataclasses import dataclass

from records.transmissions import Transmission, require_text


def validate_stations(values: object) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)) or not values:
        raise ValueError('station network requires a nonempty station list')
    stations = tuple(require_text(value, 'station') for value in values)
    if len(set(stations)) != len(stations):
        raise ValueError('duplicate station')
    return stations


@dataclass(frozen=True)
class StationNetwork:
    stations: tuple[str, ...]
    transmissions: tuple[Transmission, ...]


def topological_order(network: StationNetwork) -> tuple[str, ...]:
    stations = validate_stations(network.stations)
    incoming = dict.fromkeys(stations, 0)
    outgoing = {station: [] for station in stations}
    for edge in network.transmissions:
        if edge.source not in incoming or edge.target not in incoming:
            raise ValueError('transmission endpoint outside network')
        outgoing[edge.source].append(edge.target)
        incoming[edge.target] += 1
    available = deque(station for station in stations if incoming[station] == 0)
    ordered = []
    while available:
        station = available.popleft()
        ordered.append(station)
        for target in outgoing[station]:
            incoming[target] -= 1
            if incoming[target] == 0:
                available.append(target)
    if len(ordered) != len(stations):
        raise ValueError('station network contains a directed cycle')
    return tuple(ordered)
