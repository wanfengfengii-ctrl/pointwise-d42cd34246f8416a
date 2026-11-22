import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from adjudicate.attachment import encode_rejection_attachment
from adjudicate.coverage import enumerate_station_sets
from adjudicate.reachability import feasible_arrivals
from adjudicate.rejection_review import verify_rejection as verify_rejection
from adjudicate.request import DeliveryRequest, validate_request
from adjudicate.witness import DeliveryWitness, build_witness
from receive.holdings import load_received
from receive.integrity import VerifiedPackage
from reports.export import ReportView
from reports.signing import ReportDraft, sign_report
from records.transmissions import require_text

__all__ = ('DeliveryVerdict', 'check', 'check_with_rejection', 'verify_rejection')


@dataclass(frozen=True)
class DeliveryVerdict:
    arrival: Fraction | None
    witness: DeliveryWitness | None


def _adjudicate(package: VerifiedPackage, request: DeliveryRequest) -> DeliveryVerdict:
    best_time = None
    best_candidate = None
    for candidate in feasible_arrivals(package, request):
        feasible = candidate.transfer.arrivals.intersection(request.receipt_window)
        if feasible is not None and (best_time is None or feasible.start < best_time):
            best_time = feasible.start
            best_candidate = candidate
    if best_candidate is None:
        return DeliveryVerdict(None, None)
    return DeliveryVerdict(best_time, build_witness(best_candidate, best_time, package.origins))


def check(conn: sqlite3.Connection, report_id: str, request: DeliveryRequest,
          *, before_commit: Callable[[], None] | None = None) -> ReportView:
    report_id = require_text(report_id, 'report id')
    if not isinstance(request, DeliveryRequest):
        raise ValueError('a delivery request is required')
    received = load_received(conn, request.receipt_id)
    validate_request(request, received)
    package = received.package
    verdict = _adjudicate(package, request)
    draft = ReportDraft(request, package.manifest.release_id, package.digest, verdict.arrival, verdict.witness)
    return sign_report(conn, report_id, draft, before_commit=before_commit)


def check_with_rejection(conn: sqlite3.Connection, report_id: str, request: DeliveryRequest,
                         *, before_commit: Callable[[], None] | None = None) -> ReportView:
    """Sign a verdict, attaching closed time-set evidence when unreachable.

    Reachable cases reuse the original verdict and carry no attachment.  When
    delivery is impossible, the per-station closed time sets are derived from
    the verified fixed item and signed together with the report and first
    receipt in one transaction; a callback failure rolls all three back.
    """
    report_id = require_text(report_id, 'report id')
    if not isinstance(request, DeliveryRequest):
        raise ValueError('a delivery request is required')
    received = load_received(conn, request.receipt_id)
    validate_request(request, received)
    package = received.package
    verdict = _adjudicate(package, request)
    attachment = None
    if verdict.arrival is None:
        station_sets = enumerate_station_sets(package, request)
        attachment = encode_rejection_attachment(
            report_id, request, package.manifest.release_id, package.digest, station_sets
        )
    draft = ReportDraft(request, package.manifest.release_id, package.digest, verdict.arrival,
                        verdict.witness, attachment)
    return sign_report(conn, report_id, draft, before_commit=before_commit)
