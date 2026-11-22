import hashlib
import json
import sqlite3
import unittest
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from adjudicate.request import DeliveryRequest
from issue.releases import initialize_releases, issue_package
from receive.holdings import accept
from receive.survey_check import SurveyRef
from receive.workspace import initialize_holdings, open_workspace
from records.revisions import BlockRevision, initialize_revisions, save_revision
from records.surveys import freeze, initialize_surveys
from records.times import ClosedWindow
from reports.signing import initialize_reports


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


def read_sample(name):
    return json.loads((SAMPLES / f'{name}.json').read_text(encoding='utf-8'))


def transmission(record_id, source, target, start, end, duration):
    return {'id': record_id, 'source': source, 'target': target, 'opens': start, 'closes': end,
            'duration': duration, 'origin': f'dispatch/{record_id}'}


def custody(record_id, station, start, end):
    return {'id': record_id, 'station': station, 'opens': start, 'closes': end,
            'origin': f'relay/{record_id}'}


def revision_document(stations, edges, turns=(), *, revision_id='R1'):
    return {'block_id': 'bench-42', 'revision_id': revision_id, 'stations': list(stations),
            'transmissions': list(edges), 'custody_turns': list(turns)}


def encode_fixture_package(unsigned):
    def wire(document):
        return json.dumps(document, sort_keys=True, ensure_ascii=True,
                          separators=(',', ':')).encode('ascii')

    return wire({**unsigned, 'digest': hashlib.sha256(wire(unsigned)).hexdigest()})


def faithful_fixture_package(revision, survey, release_id):
    evidence = {'stations': revision['stations']}
    origins = {}
    for group, kind in (('transmissions', 'transmission'), ('custody_turns', 'custody')):
        evidence[group] = []
        for source in revision[group]:
            record = dict(source)
            location = record.pop('origin')
            key = f'{kind}:{record["id"]}'
            record['origin_key'] = key
            evidence[group].append(record)
            origins[key] = {'kind': kind, 'record_id': record['id'], 'block_id': survey.block_id,
                            'revision_id': survey.revision_id, 'location': location}
    manifest = {'release_id': release_id, 'survey_id': survey.survey_id,
                'block_id': survey.block_id, 'revision_id': survey.revision_id}
    return encode_fixture_package({'version': 1, 'manifest': manifest, 'evidence': evidence, 'origins': origins})


class SigningInterrupted(RuntimeError):
    pass


class WorkflowCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='handoff-tests-')
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.source_path = root / 'source.sqlite'
        self.offline_path = root / 'offline.sqlite'
        self.source = sqlite3.connect(self.source_path)
        self.addCleanup(self.close_source)
        self.offline = open_workspace(self.offline_path)
        self.addCleanup(self.close_offline)
        self.initialize_source()
        self.initialize_offline()

    def initialize_source(self):
        initialize_revisions(self.source)
        initialize_surveys(self.source)
        initialize_releases(self.source)

    def initialize_offline(self):
        initialize_holdings(self.offline)
        initialize_reports(self.offline)

    def close_source(self):
        if self.source is not None:
            self.source.close()
            self.source = None

    def disconnect_source(self):
        self.close_source()
        self.source_path.unlink()
        self.assertFalse(self.source_path.exists())

    def close_offline(self):
        if self.offline is not None:
            self.offline.close()
            self.offline = None

    def reopen_offline(self):
        self.close_offline()
        self.offline = open_workspace(self.offline_path)

    def register(self, document):
        revision = BlockRevision.from_document(document)
        save_revision(self.source, revision)
        return revision

    def frozen(self, document, survey_id):
        revision = self.register(document)
        survey = SurveyRef(survey_id, revision.block_id, revision.revision_id)
        freeze(self.source, survey.survey_id, survey.block_id, survey.revision_id)
        return survey

    def delivered_package(self, document, *, name='one', source='S', destination='T', window=(0, 20)):
        survey = self.frozen(document, f'survey-{name}')
        issued = issue_package(self.source, survey.survey_id, f'release-{name}')
        receipt_id = f'held-{name}'
        accept(self.offline, receipt_id, issued.payload, survey)
        return DeliveryRequest(receipt_id, survey, source, destination, ClosedWindow(*window))

    def sample_request(self, name, *, registration=None):
        sample = read_sample(name)
        document = registration if registration is not None else sample['revision']
        query = sample['query']
        return self.delivered_package(document, name=name, source=query['source'],
                                      destination=query['destination'], window=query['receipt_window'])

    def signed_counts(self):
        reports = self.offline.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
        receipts = self.offline.execute('SELECT COUNT(*) FROM first_receipts').fetchone()[0]
        return reports, receipts

    def assert_unreachable(self, report):
        self.assertFalse(report.reachable)
        self.assertIsNone(report.arrival)
        self.assertIsNone(report.witness)
        self.assertEqual(report.first_receipt.report_id, report.report_id)

    def assert_witness(self, report, revision, request):
        self.assertTrue(report.reachable)
        legs = report.witness.legs
        self.assertTrue(legs)
        self.assertEqual(legs[0].source, request.source)
        self.assertEqual(legs[-1].target, request.destination)
        self.assertEqual(legs[-1].arrival, report.arrival)
        self.assertLessEqual(request.receipt_window.start, report.arrival)
        self.assertLessEqual(report.arrival, request.receipt_window.end)
        transmissions = {row['id']: row for row in revision['transmissions']}
        turns = {row['id']: row for row in revision['custody_turns']}
        self.assertEqual(len({leg.transmission_id for leg in legs}), len(legs))
        previous = None
        for leg in legs:
            raw = transmissions[leg.transmission_id]
            self.assertEqual((leg.source, leg.target), (raw['source'], raw['target']))
            opens, closes = Fraction(raw['opens']), Fraction(raw['closes'])
            self.assertEqual((leg.departure_window.start, leg.departure_window.end), (opens, closes))
            self.assertLessEqual(opens, leg.departure)
            self.assertLessEqual(leg.departure, closes)
            self.assertEqual(leg.duration, Fraction(raw['duration']))
            self.assertEqual(leg.arrival - leg.departure, Fraction(raw['duration']))
            self.assert_origin(leg.origin, 'transmission', raw, revision)
            if previous is None:
                self.assertIsNone(leg.custody)
            else:
                self.assertIsNotNone(leg.custody)
                turn = turns[leg.custody.turn_id]
                self.assertEqual(previous.target, leg.source)
                self.assertEqual(leg.custody.station, leg.source)
                self.assertEqual(turn['station'], leg.source)
                opens, closes = Fraction(turn['opens']), Fraction(turn['closes'])
                self.assertEqual((leg.custody.window.start, leg.custody.window.end), (opens, closes))
                self.assertLessEqual(opens, previous.arrival)
                self.assertLessEqual(previous.arrival, leg.departure)
                self.assertLessEqual(leg.departure, closes)
                self.assert_origin(leg.custody.origin, 'custody', turn, revision)
            previous = leg

    def assert_origin(self, origin, kind, raw, revision):
        self.assertEqual(origin.kind, kind)
        self.assertEqual(origin.record_id, raw['id'])
        self.assertEqual(origin.location, raw['origin'])
        self.assertEqual((origin.block_id, origin.revision_id), (revision['block_id'], revision['revision_id']))
