import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from issue.evidence import EvidenceBody
from issue.origins import OriginEntry
from records.transmissions import require_fields, require_text


PACKAGE_VERSION = 1


@dataclass(frozen=True)
class PackageManifest:
    release_id: str
    survey_id: str
    block_id: str
    revision_id: str

    def to_document(self) -> dict:
        return asdict(self)

    @classmethod
    def from_document(cls, value: object) -> 'PackageManifest':
        fields = ('release_id', 'survey_id', 'block_id', 'revision_id')
        row = require_fields(value, fields, 'package manifest')
        return cls(*(require_text(row[field], field) for field in fields))


def _canonical_bytes(document: dict) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def compute_package_digest(unsigned: dict) -> str:
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def encode_package(manifest: PackageManifest, evidence: EvidenceBody,
                   origins: Mapping[str, OriginEntry]) -> bytes:
    unsigned = {
        'version': PACKAGE_VERSION,
        'manifest': manifest.to_document(),
        'evidence': evidence.to_document(),
        'origins': {key: entry.to_document() for key, entry in origins.items()},
    }
    return _canonical_bytes({**unsigned, 'digest': compute_package_digest(unsigned)})
