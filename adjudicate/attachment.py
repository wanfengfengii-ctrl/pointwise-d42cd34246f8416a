"""Rejection attachment encoding and its bindings.

The attachment is canonical JSON (sorted keys, compact separators, ASCII).  It
declares, for every station of the frozen network, the finite union of closed
intervals during which the payload can actually be present there.  The same
bytes are stored beside the report and returned unchanged on later shifts, so
a reviewer always checks the attachment that was actually signed rather than a
freshly regenerated one.

Binding chain handled by :mod:`reports.signing`:

* ``report_id`` / ``receipt_id`` / frozen survey identity / release id /
  package digest pin the attachment to the signed request and fixed item;
* ``attachment_digest`` inside the report snapshot is the SHA-256 digest of
  these exact canonical bytes, so the first receipt (which binds the report
  snapshot) transitively binds the attachment.
"""
import hashlib
import json

from adjudicate.coverage import merge_intervals
from adjudicate.request import DeliveryRequest
from records.times import ClosedWindow
from records.transmissions import require_fields, require_text

ATTACHMENT_VERSION = 1
_ATTACHMENT_FIELDS = ('version', 'report_id', 'receipt_id', 'survey_id', 'block_id',
                      'revision_id', 'release_id', 'package_digest', 'station_sets')


def attachment_digest(payload: bytes) -> str:
    if not isinstance(payload, bytes):
        raise ValueError('a rejection attachment must be bytes')
    return hashlib.sha256(payload).hexdigest()


def encode_rejection_attachment(report_id: str, request: DeliveryRequest, release_id: str,
                                package_digest: str,
                                station_sets: dict[str, tuple[ClosedWindow, ...]]) -> bytes:
    survey = request.survey
    document = {
        'version': ATTACHMENT_VERSION,
        'report_id': require_text(report_id, 'report id'),
        'receipt_id': request.receipt_id,
        'survey_id': survey.survey_id,
        'block_id': survey.block_id,
        'revision_id': survey.revision_id,
        'release_id': require_text(release_id, 'release id'),
        'package_digest': require_text(package_digest, 'package digest'),
        'station_sets': {
            require_text(station, 'station'): [window.to_document() for window in merge_intervals(windows)]
            for station, windows in station_sets.items()
        },
    }
    return json.dumps(document, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def _reject_constant(value: str) -> None:
    raise ValueError(f'invalid JSON constant {value!r}')


def decode_rejection_attachment(payload: object) -> dict:
    """Parse an attachment and validate every declared field and interval."""
    if not isinstance(payload, bytes) or not payload:
        raise ValueError('a rejection attachment must be nonempty bytes')
    try:
        document = json.loads(payload.decode('utf-8'), parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError('invalid rejection attachment JSON') from exc
    row = require_fields(document, _ATTACHMENT_FIELDS, 'rejection attachment')
    if type(row['version']) is not int or row['version'] != ATTACHMENT_VERSION:
        raise ValueError('unsupported rejection attachment version')
    for field in ('report_id', 'receipt_id', 'survey_id', 'block_id', 'revision_id',
                  'release_id', 'package_digest'):
        require_text(row[field], field)
    if not isinstance(row['package_digest'], str) or not _is_sha256(row['package_digest']):
        raise ValueError('attachment binds an invalid package digest')
    station_sets = row['station_sets']
    if not isinstance(station_sets, dict) or not station_sets:
        raise ValueError('attachment must declare at least one station time set')
    decoded_sets: dict[str, tuple[ClosedWindow, ...]] = {}
    for station, intervals in station_sets.items():
        require_text(station, 'station')
        if not isinstance(intervals, list):
            raise ValueError(f'time set for station {station!r} must be an array')
        windows = tuple(ClosedWindow.from_document(interval) for interval in intervals)
        decoded_sets[station] = windows
    row['station_sets'] = decoded_sets
    return row


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in '0123456789abcdef' for char in value)
