import json
from dataclasses import dataclass
from fractions import Fraction

from adjudicate.request import DeliveryRequest
from adjudicate.witness import DeliveryWitness
from records.times import encode_shift_second, parse_shift_second
from reports.receipts import FirstReceipt, make_first_receipt


def _snapshot_document(report_id: str, request: DeliveryRequest, release_id: str, package_digest: str,
                       arrival: Fraction | None, witness: DeliveryWitness | None) -> dict:
    if (arrival is None) != (witness is None):
        raise ValueError('a delivery time requires its matching witness')
    if witness is not None and (not witness.legs or witness.legs[-1].arrival != arrival):
        raise ValueError('witness does not end at the signed delivery time')
    return {
        'report_id': report_id,
        'request': request.to_document(),
        'release_id': release_id,
        'package_digest': package_digest,
        'status': 'reachable' if arrival is not None else 'unreachable',
        'arrival': encode_shift_second(arrival) if arrival is not None else None,
        'witness': witness.to_document() if witness is not None else None,
    }


@dataclass(frozen=True)
class ReportView:
    report_id: str
    request: DeliveryRequest
    release_id: str
    package_digest: str
    arrival: Fraction | None
    witness: DeliveryWitness | None
    first_receipt: FirstReceipt

    @property
    def reachable(self) -> bool:
        return self.arrival is not None

    def to_document(self) -> dict:
        snapshot = _snapshot_document(self.report_id, self.request, self.release_id,
                                      self.package_digest, self.arrival, self.witness)
        return {**snapshot, 'first_receipt': self.first_receipt.to_document()}


def encode_report_snapshot(report_id: str, request: DeliveryRequest, release_id: str, package_digest: str,
                           arrival: Fraction | None, witness: DeliveryWitness | None) -> str:
    document = _snapshot_document(report_id, request, release_id, package_digest, arrival, witness)
    return json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def decode_report_snapshot(snapshot: str, receipt: FirstReceipt) -> ReportView:
    document = json.loads(snapshot)
    report_id = document['report_id']
    if make_first_receipt(report_id, snapshot) != receipt:
        raise ValueError('stored first receipt does not match its report snapshot')
    arrival = document['arrival']
    witness = document['witness']
    return ReportView(report_id, DeliveryRequest.from_document(document['request']),
                      document['release_id'], document['package_digest'],
                      parse_shift_second(arrival) if arrival is not None else None,
                      DeliveryWitness.from_document(witness) if witness is not None else None,
                      receipt)
