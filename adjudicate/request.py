from dataclasses import dataclass

from receive.holdings import ReceivedPackage
from receive.survey_check import SurveyRef, require_survey_match
from records.times import ClosedWindow
from records.transmissions import require_fields, require_text


@dataclass(frozen=True)
class DeliveryRequest:
    receipt_id: str
    survey: SurveyRef
    source: str
    destination: str
    receipt_window: ClosedWindow

    def to_document(self) -> dict:
        return {
            'receipt_id': self.receipt_id,
            'survey': self.survey.to_document(),
            'source': self.source,
            'destination': self.destination,
            'receipt_window': self.receipt_window.to_document(),
        }

    @classmethod
    def from_document(cls, value: object) -> 'DeliveryRequest':
        fields = ('receipt_id', 'survey', 'source', 'destination', 'receipt_window')
        row = require_fields(value, fields, 'delivery request')
        return cls(row['receipt_id'], SurveyRef.from_document(row['survey']),
                   row['source'], row['destination'], ClosedWindow.from_document(row['receipt_window']))


def validate_request(request: DeliveryRequest, received: ReceivedPackage) -> None:
    if request.receipt_id != received.receipt_id:
        raise ValueError('request does not specify the loaded receipt')
    require_survey_match(received.package, request.survey)
    stations = received.package.evidence.stations
    source = require_text(request.source, 'source station')
    destination = require_text(request.destination, 'destination station')
    if source not in stations or destination not in stations:
        raise ValueError('request station is outside the frozen survey')
    if not isinstance(request.receipt_window, ClosedWindow):
        raise ValueError('request requires a closed receipt window')
