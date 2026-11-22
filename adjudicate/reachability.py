from collections import defaultdict
from dataclasses import dataclass, field

from adjudicate.arrival_windows import TransferWindow, propagate_window
from adjudicate.request import DeliveryRequest
from receive.integrity import VerifiedPackage
from records.custody import CustodyTurn
from records.transmissions import Transmission


@dataclass(frozen=True)
class ArrivalCandidate:
    transmission: Transmission
    transfer: TransferWindow
    previous: 'ArrivalCandidate | None' = field(default=None, repr=False)
    custody: CustodyTurn | None = None


def feasible_arrivals(package: VerifiedPackage, request: DeliveryRequest) -> tuple[ArrivalCandidate, ...]:
    outgoing = defaultdict(list)
    for edge in package.evidence.transmissions:
        outgoing[edge.source].append(edge)
    local_turns = defaultdict(list)
    for turn in package.evidence.custody_turns:
        local_turns[turn.station].append(turn)

    arrivals: dict[str, list[ArrivalCandidate]] = defaultdict(list)
    for station in package.station_order:
        if station == request.destination:
            return tuple(arrivals[station])
        if station == request.source:
            for edge in outgoing[station]:
                transfer = propagate_window(edge)
                if transfer is not None:
                    arrivals[edge.target].append(ArrivalCandidate(edge, transfer))
            continue
        for incoming in arrivals[station]:
            for turn in local_turns[station]:
                for edge in outgoing[station]:
                    transfer = propagate_window(edge, incoming.transfer.arrivals, turn)
                    if transfer is not None:
                        arrivals[edge.target].append(ArrivalCandidate(edge, transfer, incoming, turn))
    return ()
