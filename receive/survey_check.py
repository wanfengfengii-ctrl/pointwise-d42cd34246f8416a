from dataclasses import asdict, dataclass

from receive.integrity import VerifiedPackage
from records.transmissions import require_fields, require_text


@dataclass(frozen=True)
class SurveyRef:
    survey_id: str
    block_id: str
    revision_id: str

    def __post_init__(self) -> None:
        require_text(self.survey_id, 'survey id')
        require_text(self.block_id, 'block id')
        require_text(self.revision_id, 'revision id')

    def to_document(self) -> dict:
        return asdict(self)

    @classmethod
    def from_document(cls, value: object) -> 'SurveyRef':
        fields = ('survey_id', 'block_id', 'revision_id')
        return cls(**require_fields(value, fields, 'survey reference'))


def require_survey_match(package: VerifiedPackage, expected: SurveyRef) -> None:
    if not isinstance(expected, SurveyRef):
        raise ValueError('a designated survey reference is required')
    manifest = package.manifest
    actual = SurveyRef(manifest.survey_id, manifest.block_id, manifest.revision_id)
    if actual != expected:
        raise ValueError('received package does not match the designated survey and revision')
