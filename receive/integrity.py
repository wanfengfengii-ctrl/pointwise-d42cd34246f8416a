from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from issue.evidence import EvidenceBody
from issue.manifest import PackageManifest, compute_package_digest
from issue.origins import OriginEntry, origin_key
from receive.envelope import DecodedEnvelope
from records.custody import validate_custody_turns
from records.network import StationNetwork, topological_order, validate_stations
from records.transmissions import require_fields, require_text, validate_transmissions


@dataclass(frozen=True)
class VerifiedPackage:
    manifest: PackageManifest
    evidence: EvidenceBody
    origins: Mapping[str, OriginEntry]
    station_order: tuple[str, ...]
    digest: str


def _verify_origins(document: dict, manifest: PackageManifest) -> dict[str, OriginEntry]:
    origins = {}
    for key, value in document.items():
        entry = OriginEntry.from_document(value)
        if key != entry.key:
            raise ValueError(f'origin directory key does not match record {key!r}')
        if (entry.block_id, entry.revision_id) != (manifest.block_id, manifest.revision_id):
            raise ValueError(f'origin {key!r} belongs to a different revision')
        origins[key] = entry
    return origins


def _restore_records(values: object, kind: str, origins: dict[str, OriginEntry],
                     cited: set[str]) -> list[dict]:
    if not isinstance(values, list):
        raise ValueError(f'{kind} evidence must be an array')
    restored = []
    for value in values:
        if not isinstance(value, dict) or 'origin' in value:
            raise ValueError(f'invalid {kind} evidence row')
        record = value.copy()
        key = require_text(record.pop('origin_key', None), 'origin key')
        record_id = require_text(record.get('id'), 'evidence record id')
        if key != origin_key(kind, record_id) or key not in origins:
            raise ValueError(f'missing or unrelated origin for record {record_id!r}')
        record['origin'] = origins[key].location
        cited.add(key)
        restored.append(record)
    return restored


def verify_integrity(envelope: DecodedEnvelope) -> VerifiedPackage:
    try:
        digest = compute_package_digest(envelope.unsigned_document())
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError('package cannot be canonically encoded') from exc
    if digest != envelope.digest:
        raise ValueError('handoff package digest mismatch')
    manifest = PackageManifest.from_document(envelope.manifest)
    origins = _verify_origins(envelope.origins, manifest)
    row = require_fields(envelope.evidence, ('stations', 'transmissions', 'custody_turns'), 'evidence')
    stations = validate_stations(row['stations'])
    station_set = set(stations)
    cited = set()
    transmissions = validate_transmissions(
        _restore_records(row['transmissions'], 'transmission', origins, cited), station_set
    )
    custody_turns = validate_custody_turns(
        _restore_records(row['custody_turns'], 'custody', origins, cited), station_set
    )
    if cited != set(origins):
        raise ValueError('package origin directory contains unused entries')
    order = topological_order(StationNetwork(stations, transmissions))
    evidence = EvidenceBody(stations, transmissions, custody_turns)
    return VerifiedPackage(manifest, evidence, MappingProxyType(origins), order, digest)
