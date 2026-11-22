import json
import re
from dataclasses import dataclass

from issue.manifest import PACKAGE_VERSION
from records.transmissions import require_fields


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON property {key!r}')
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f'invalid JSON constant {value}')


@dataclass(frozen=True)
class DecodedEnvelope:
    version: int
    manifest: dict
    evidence: dict
    origins: dict
    digest: str

    def unsigned_document(self) -> dict:
        return {
            'version': self.version,
            'manifest': self.manifest,
            'evidence': self.evidence,
            'origins': self.origins,
        }


def decode_envelope(payload: bytes) -> DecodedEnvelope:
    if not isinstance(payload, bytes):
        raise ValueError('handoff package must be bytes')
    try:
        document = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object,
                              parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError('invalid handoff package JSON') from exc
    fields = ('version', 'manifest', 'evidence', 'origins', 'digest')
    row = require_fields(document, fields, 'handoff envelope')
    if type(row['version']) is not int or row['version'] != PACKAGE_VERSION:
        raise ValueError('unsupported handoff package version')
    for field in ('manifest', 'evidence', 'origins'):
        if not isinstance(row[field], dict):
            raise ValueError(f'package {field} must be an object')
    digest = row['digest']
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('invalid handoff package digest')
    return DecodedEnvelope(row['version'], row['manifest'], row['evidence'], row['origins'], digest)
