from dataclasses import dataclass

from records.custody import CustodyTurn
from records.times import ClosedWindow
from records.transmissions import Transmission


@dataclass(frozen=True)
class TransferWindow:
    departures: ClosedWindow
    arrivals: ClosedWindow
    previous_arrivals: ClosedWindow | None


def propagate_window(transmission: Transmission, previous: ClosedWindow | None = None,
                     turn: CustodyTurn | None = None) -> TransferWindow | None:
    if previous is None and turn is None:
        return TransferWindow(transmission.departure,
                              transmission.departure.shift(transmission.duration), None)
    if previous is None or turn is None or turn.station != transmission.source:
        raise ValueError('relay propagation requires its incoming window and a local custody turn')
    eligible = previous.intersection(turn.window)
    if eligible is None:
        return None
    # For each departure in this range, at least the first eligible arrival can wait for it.
    departures = transmission.departure.intersection(ClosedWindow(eligible.start, turn.window.end))
    if departures is None:
        return None
    return TransferWindow(departures, departures.shift(transmission.duration), eligible)
