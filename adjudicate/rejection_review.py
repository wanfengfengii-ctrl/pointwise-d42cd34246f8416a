"""Independent review of a signed rejection attachment.

The reviewer works only from the three fixed artifacts handed over by the
previous shift:

* ``report`` -- the signed :class:`~reports.export.ReportView`;
* ``received`` -- the designated received package (actual held bytes);
* ``attachment`` -- the original rejection attachment bytes.

No database connection and no rerun of the adjudication are used.  The time
sets declared by the attachment are re-derived from the verified fixed item
with the same closed-window time arithmetic, and every declaration is checked
for both *coverage* (it must contain every actually possible presence moment)
and *exclusion* (its destination declaration must exclude every legal delivery
inside the receipt window).
"""
from adjudicate.attachment import (
    attachment_digest,
    decode_rejection_attachment,
)
from adjudicate.coverage import (
    enumerate_station_sets,
    union_covers,
    unions_intersect,
)
from receive.holdings import ReceivedPackage
from records.times import ClosedWindow
from reports.export import ReportView


def verify_rejection(report: ReportView, received: ReceivedPackage, attachment: bytes) -> bool:
    _require_report(report)
    package = received.package

    document = decode_rejection_attachment(attachment)
    if attachment_digest(attachment) != report.attachment_digest:
        raise ValueError('rejection attachment does not match the report snapshot binding')
    _check_attachment_binding(document, report, received)

    declared = document['station_sets']
    network_stations = set(package.evidence.stations)
    if set(declared) != network_stations:
        raise ValueError('attachment does not declare exactly the frozen network stations')
    for windows in declared.values():
        if windows and any(not isinstance(window, ClosedWindow) for window in windows):
            raise ValueError('attachment declares an invalid closed interval')

    # Re-derive the exact time sets from the fixed item itself.  This reuses
    # the closed-window time operations but never reruns the signed verdict.
    exact_sets = enumerate_station_sets(package, report.request)

    # Coverage: every moment the payload could actually be present at a
    # station must be inside that station's declared (possibly conservative)
    # closed time set.  Checked interval by interval against the declaration.
    for station, exact_windows in exact_sets.items():
        declared_windows = declared[station]
        for exact_window in exact_windows:
            if not union_covers(declared_windows, exact_window):
                raise ValueError(f'declared time set misses a possible moment at station {station!r}')

    # Exclusion: no legal delivery moment exists, i.e. the destination's
    # declared closed set and the designated receipt window are disjoint.
    destination = report.request.destination
    if unions_intersect(declared[destination], (report.request.receipt_window,)):
        raise ValueError('declared destination time set permits a delivery inside the receipt window')

    # At least one actual transmission must exist in the frozen survey; the
    # same rule governs the original reachability adjudication.
    if not package.evidence.transmissions:
        raise ValueError('rejection evidence requires at least one transmission')
    return True


def _require_report(report: ReportView) -> None:
    if not isinstance(report, ReportView):
        raise ValueError('a signed ReportView is required')
    if report.reachable or report.attachment_digest is None:
        raise ValueError('reachable reports and legacy reports without an attachment are not rejection evidence')


def _check_attachment_binding(document: dict, report: ReportView, received: ReceivedPackage) -> None:
    if not isinstance(received, ReceivedPackage):
        raise ValueError('a ReceivedPackage is required')
    request = report.request
    survey = request.survey
    expected = (
        (document['report_id'], report.report_id),
        (document['receipt_id'], request.receipt_id),
        (document['survey_id'], survey.survey_id),
        (document['block_id'], survey.block_id),
        (document['revision_id'], survey.revision_id),
        (document['release_id'], report.release_id),
        (document['package_digest'], report.package_digest),
    )
    for field, value in expected:
        if field != value:
            raise ValueError('rejection attachment binding does not match the signed report')
    # The designated actual-receipt number and the fixed item itself.
    if received.receipt_id != request.receipt_id:
        raise ValueError('review must use the receipt designated by the report')
    if received.package.digest != report.package_digest:
        raise ValueError('received fixed item digest does not match the report binding')
    if received.package.manifest.release_id != report.release_id:
        raise ValueError('received fixed item release does not match the report binding')
    actual_identity = (
        received.package.manifest.survey_id,
        received.package.manifest.block_id,
        received.package.manifest.revision_id,
    )
    if actual_identity != (survey.survey_id, survey.block_id, survey.revision_id):
        raise ValueError('received fixed item does not match the frozen survey identity')
