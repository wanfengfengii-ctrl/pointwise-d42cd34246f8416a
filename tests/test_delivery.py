import json
from dataclasses import replace
from fractions import Fraction

from adjudicate.verdict import check
from issue.releases import issue_package
from receive.holdings import accept, load_received
from receive.survey_check import SurveyRef
from reports.history import read_report
from reports.receipts import load_first_receipt
from tests.fixtures import (
    WorkflowCase, custody, encode_fixture_package, faithful_fixture_package,
    read_sample, revision_document, transmission,
)


class DeliveryTests(WorkflowCase):
    def test_single_custody(self):
        request = self.sample_request('single')
        report = check(self.offline, 'report', request)
        self.assertEqual(report.arrival, Fraction(4))
        self.assertEqual([leg.origin.location for leg in report.witness.legs], ['dispatch/10', 'dispatch/11'])
        self.assertEqual(report.witness.legs[1].custody.turn_id, 'steady')
        self.assert_witness(report, read_sample('single')['revision'], request)
        self.assertEqual(read_report(self.offline, 'report'), report)

    def test_fractional_endpoint(self):
        edges = [transmission('in', 'S', 'M', '1/3', '1/3', '1/3'),
                 transmission('out', 'M', 'T', '4/3', '4/3', '1/3')]
        turns = [custody('edge-of-turn', 'M', '2/3', '4/3')]
        revision = revision_document(('S', 'M', 'T'), edges, turns)
        request = self.delivered_package(revision, window=(1, '5/3'))
        report = check(self.offline, 'fraction', request)
        self.assertEqual(report.arrival, Fraction(5, 3))
        self.assertEqual([(leg.departure, leg.arrival) for leg in report.witness.legs],
                         [(Fraction(1, 3), Fraction(2, 3)), (Fraction(4, 3), Fraction(5, 3))])
        self.assert_witness(report, revision, request)
        self.assertEqual(read_report(self.offline, 'fraction').to_document()['arrival'], '5/3')

    def test_window_choice(self):
        edges = [transmission('direct', 'S', 'T', '1/3', 2, '1/3')]
        revision = revision_document(('T', 'S'), edges)
        request = self.delivered_package(revision, window=('5/3', 2))
        report = check(self.offline, 'window', request)
        self.assertEqual(report.arrival, Fraction(5, 3))
        self.assertEqual(report.witness.legs[0].departure, Fraction(4, 3))
        self.assert_witness(report, revision, request)

    def test_actual_arrival_cannot_wait_into_receipt_window(self):
        light = transmission('early', 'S', 'T', 0, 0, 1)
        request = self.delivered_package(revision_document(('S', 'T'), [light]), window=(2, 3))
        self.assert_unreachable(check(self.offline, 'missed-window', request))

    def test_shared_transfer(self):
        edges = [transmission('first', 'S', 'A', 0, 0, 1), transmission('middle', 'A', 'B', 2, 5, 1),
                 transmission('last', 'B', 'T', 7, 7, 1)]
        turns = [custody('a-turn', 'A', 1, 2), custody('b-turn', 'B', 6, 7)]
        blocked = revision_document(('B', 'T', 'S', 'A'), edges, turns)
        initial = self.delivered_package(blocked, name='blocked', window=(8, 8))
        turns[0] = custody('a-turn', 'A', 1, 5)
        feasible = revision_document(('B', 'T', 'S', 'A'), edges, turns, revision_id='R2')
        extended = self.delivered_package(feasible, name='extended', window=(8, 8))
        self.disconnect_source()
        self.assert_unreachable(check(self.offline, 'blocked', initial))
        report = check(self.offline, 'extended', extended)
        self.assertEqual(report.arrival, Fraction(8))
        middle = report.witness.legs[1]
        self.assertEqual((middle.transmission_id, middle.departure, middle.arrival), ('middle', 5, 6))
        self.assert_witness(report, feasible, extended)

    def test_bad_package(self):
        reference = self.frozen(read_sample('single')['revision'], 'survey')
        issued = issue_package(self.source, reference.survey_id, 'release')
        corrupt = json.loads(issued.payload)
        corrupt['evidence']['transmissions'][0]['opens'] = '0'
        bad_digest = json.dumps(corrupt).encode()
        dangling = json.loads(issued.payload)
        del dangling['digest']
        dangling['evidence']['transmissions'][0]['origin_key'] = 'transmission:out'
        for index, (payload, expected) in enumerate((
            (b'{invalid', reference), (bad_digest, reference), (encode_fixture_package(dangling), reference),
            (issued.payload, replace(reference, survey_id='wrong')),
        )):
            with self.subTest(index=index):
                receipt_id = f'invalid-{index}'
                with self.assertRaises(ValueError):
                    accept(self.offline, receipt_id, payload, expected)
                with self.assertRaises(KeyError):
                    load_received(self.offline, receipt_id)
        accepted = accept(self.offline, 'valid', issued.payload, reference)
        self.assertEqual(accepted, load_received(self.offline, 'valid'))

    def test_wrong_revision_accept(self):
        reference = self.frozen(read_sample('single')['revision'], 'survey')
        issued = issue_package(self.source, reference.survey_id, 'release')
        with self.assertRaises(ValueError):
            accept(self.offline, 'wrong-revision', issued.payload, replace(reference, revision_id='R2'))
        self.reopen_offline()
        with self.assertRaises(KeyError):
            load_received(self.offline, 'wrong-revision')
        accepted = accept(self.offline, 'right-revision', issued.payload, reference)
        self.assertEqual(accepted.survey.revision_id, 'R1')

    def test_wrong_revision_check(self):
        request = self.sample_request('single')
        original = check(self.offline, 'old-report', request)
        wrong = replace(request, survey=replace(request.survey, revision_id='R2'))
        with self.assertRaises(ValueError):
            check(self.offline, 'wrong-report', wrong)
        self.assertEqual(self.signed_counts(), (1, 1))
        with self.assertRaises(KeyError):
            read_report(self.offline, 'wrong-report')
        with self.assertRaises(KeyError):
            load_first_receipt(self.offline, 'wrong-report')
        self.assertEqual(read_report(self.offline, 'old-report'), original)

    def test_custody_gap(self):
        request = self.sample_request('gap')
        self.disconnect_source()
        report = check(self.offline, 'gap', request)
        self.assert_unreachable(report)
        self.assertEqual(read_report(self.offline, 'gap'), report)

    def test_touching_turns(self):
        revision = read_sample('gap')['revision']
        revision['custody_turns'][0]['closes'] = '4'
        revision['custody_turns'][1]['opens'] = '4'
        request = self.sample_request('gap', registration=revision)
        self.assert_unreachable(check(self.offline, 'touch', request))

    def test_later_arrival(self):
        request = self.sample_request('later')
        self.disconnect_source()
        report = check(self.offline, 'later', request)
        self.assert_later_witness(report, request)
        self.assertEqual(read_report(self.offline, 'later'), report)

    def test_faithful_package(self):
        sample = read_sample('later')
        revision = sample['revision']
        reference = SurveyRef('independent-survey', revision['block_id'], revision['revision_id'])
        payload = faithful_fixture_package(revision, reference, 'independent-release')
        accepted = accept(self.offline, 'faithful', payload, reference)
        self.assertEqual(accepted.payload, payload)
        self.disconnect_source()
        self.reopen_offline()
        from adjudicate.request import DeliveryRequest
        from records.times import ClosedWindow

        request = DeliveryRequest('faithful', reference, 'S', 'T', ClosedWindow(8, 8))
        report = check(self.offline, 'faithful-report', request)
        self.assert_later_witness(report, request)

    def assert_later_witness(self, report, request):
        self.assertEqual(report.arrival, Fraction(8))
        inbound, outbound = report.witness.legs
        self.assertEqual((inbound.transmission_id, inbound.departure, inbound.arrival), ('late', 5, 6))
        self.assertEqual((outbound.transmission_id, outbound.departure, outbound.arrival), ('out', 7, 8))
        self.assertEqual(outbound.custody.turn_id, 'after-restart')
        self.assertEqual(outbound.custody.origin.location, 'relay/51')
        self.assert_witness(report, read_sample('later')['revision'], request)
