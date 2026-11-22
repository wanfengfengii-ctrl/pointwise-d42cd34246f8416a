"""Exact closed time sets used as rejection evidence.

A station's time set is the finite union of closed windows during which the
fixed payload can actually be present at that station under the frozen survey
rules.  All arithmetic stays on :class:`fractions.Fraction` values so closed
endpoints are counted exactly, including rational seconds such as ``1/3``.

The sets are derived only from transmission departure windows, their fixed
positive durations and the named custody turns (an actual arrival and the next
departure must share one named turn, and the arrival must not be later than
that departure).  This module never reruns the signed adjudication; it only
reuses the same closed-window time operations.
"""
from collections import defaultdict

from adjudicate.arrival_windows import propagate_window
from adjudicate.request import DeliveryRequest
from receive.integrity import VerifiedPackage
from records.times import ClosedWindow


def merge_intervals(windows: object) -> tuple[ClosedWindow, ...]:
    """Merge touching or overlapping closed windows into a sorted disjoint union."""
    if not isinstance(windows, (tuple, list)):
        raise ValueError('a time set must be a list of closed windows')
    ordered = sorted((ClosedWindow(window.start, window.end) for window in windows),
                     key=lambda window: (window.start, window.end))
    merged: list[ClosedWindow] = []
    for window in ordered:
        if not merged or window.start > merged[-1].end:
            merged.append(window)
        elif window.end > merged[-1].end:
            merged[-1] = ClosedWindow(merged[-1].start, window.end)
    return tuple(merged)


def enumerate_station_sets(package: VerifiedPackage,
                           request: DeliveryRequest) -> dict[str, tuple[ClosedWindow, ...]]:
    """Compute the exact set of possible presence times for every network station.

    The source station holds the union of its first-hop departure windows.
    Every other station receives the arrival windows produced hop by hop:
    each propagated arrival and the next departure must fit one named custody
    turn, with the arrival no later than the departure.  Stations without any
    feasible moment are reported with an empty union, including the
    destination when delivery is impossible.
    """
    outgoing: dict[str, list] = defaultdict(list)
    for edge in package.evidence.transmissions:
        outgoing[edge.source].append(edge)
    local_turns: dict[str, list] = defaultdict(list)
    for turn in package.evidence.custody_turns:
        local_turns[turn.station].append(turn)

    raw_arrivals: dict[str, list[ClosedWindow]] = defaultdict(list)
    for edge in outgoing[request.source]:
        raw_arrivals[request.source].append(edge.departure)

    sets: dict[str, tuple[ClosedWindow, ...]] = {}
    for station in package.station_order:
        if station == request.destination:
            sets[station] = merge_intervals(raw_arrivals[station])
            continue
        if station == request.source:
            source_windows = raw_arrivals[station]
            sets[station] = merge_intervals(source_windows)
            for edge in outgoing[station]:
                transfer = propagate_window(edge)
                if transfer is not None:
                    raw_arrivals[edge.target].append(transfer.arrivals)
            continue

        incoming_windows = tuple(raw_arrivals[station])
        sets[station] = merge_intervals(incoming_windows)
        # Keep each individual window when propagating, mirroring the closed
        # custody intersection used for a single witnessed transfer.
        for previous in incoming_windows:
            for turn in local_turns[station]:
                for edge in outgoing[station]:
                    transfer = propagate_window(edge, previous, turn)
                    if transfer is not None:
                        raw_arrivals[edge.target].append(transfer.arrivals)

    for station in package.evidence.stations:
        sets.setdefault(station, ())
    return sets


def union_covers(outer_windows: object, window: ClosedWindow) -> bool:
    """Return whether a closed ``window`` lies inside the merged outer union."""
    outer = merge_intervals(outer_windows)
    cursor = window.start
    for interval in outer:
        if interval.end < cursor:
            continue
        if interval.start > cursor:
            return False
        if interval.end >= window.end:
            return True
        cursor = interval.end
    return False


def unions_intersect(left_windows: object, right_windows: object) -> bool:
    """Return whether two finite unions of closed windows share any point."""
    left = merge_intervals(left_windows)
    right = merge_intervals(right_windows)
    for left_window in left:
        for right_window in right:
            if max(left_window.start, right_window.start) <= min(left_window.end, right_window.end):
                return True
    return False
