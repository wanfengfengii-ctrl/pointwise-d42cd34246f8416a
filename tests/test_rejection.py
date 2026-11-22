import json
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

from adjudicate.attachment import decode_rejection_attachment
from adjudicate.verdict import check, check_with_rejection, verify_rejection
from receive.holdings import load_received
from records.times import ClosedWindow
from reports.history import read_rejection, read_report
from tests.fixtures import SigningInterrupted, WorkflowCase, read_sample, revision_document, transmission


class RejectionCase(WorkflowCase):
    def rejection_sample_request(self, case_index, *, receipt_name=None):
        sample = read_sample('rejection')
        case = sample['cases'][case_index]
        query = case['query']
        request = self.delivered_package(
            sample['revision'], name=receipt_name or f'reject-{case_index}',
            source=query['source'], destination=query['destination'],
            window=tuple(query['receipt_window']),
        )
        return sample, case, request


class RejectionSigningTests(RejectionCase):
    def test_unreachable_report_carries_attachment_and_persists_across_reopen(self):
        sample, case, request = self.rejection_sample_request(0)
        self.disconnect_source()
        report = check_with_rejection(self.offline, 'report-reject', request)
        self.assertFalse(report.reachable)
        self.assertIsNotNone(report.attachment_digest)
        attachment = read_rejection(self.offline, 'report-reject')
        self.assertIsInstance(attachment, bytes)
        document = decode_rejection_attachment(attachment)
        self.assertEqual(document['report_id'], 'report-reject')
        self.assertEqual(document['receipt_id'], request.receipt_id)
        self.assertEqual(set(document['station_sets']), {'S', 'T'})
        # early leaves at 3 -> arrival 4; late leaves at 5 -> arrival 6.
        self.assertEqual(document['station_sets']['S'], (ClosedWindow(3, 3), ClosedWindow(5, 5)))
        self.assertEqual(document['station_sets']['T'], (ClosedWindow(4, 4), ClosedWindow(6, 6)))
        # Round-trip byte identity: the same attachment is handed back later.
        self.reopen_offline()
        restored_report = read_report(self.offline, 'report-reject')
        restored_attachment = read_rejection(self.offline, 'report-reject')
        self.assertEqual(restored_report, report)
        self.assertEqual(restored_attachment, attachment)
        self.assertTrue(verify_rejection(restored_report,
                                         load_received(self.offline, request.receipt_id),
                                         restored_attachment))

    def test_reachable_report_has_no_attachment(self):
        sample, case, request = self.rejection_sample_request(1)
        self.disconnect_source()
        report = check_with_rejection(self.offline, 'report-receive', request)
        self.assertTrue(report.reachable)
        self.assertIsNone(report.attachment_digest)
        self.assertIsNone(read_rejection(self.offline, 'report-receive'))
        self.assertEqual(report.arrival, Fraction(6))
        self.assertEqual([leg.transmission_id for leg in report.witness.legs], ['late'])
        with self.assertRaises(ValueError):
            verify_rejection(report, load_received(self.offline, request.receipt_id), b'{}')

    def test_legacy_check_report_has_no_attachment(self):
        sample, case, request = self.rejection_sample_request(0)
        self.disconnect_source()
        report = check(self.offline, 'legacy', request)
        self.assertFalse(report.reachable)
        self.assertIsNone(report.attachment_digest)
        self.assertIsNone(read_rejection(self.offline, 'legacy'))
        with self.assertRaises(ValueError):
            verify_rejection(report, load_received(self.offline, request.receipt_id), b'{}')

    def test_unknown_report_raises_key_error(self):
        with self.assertRaises(KeyError):
            read_rejection(self.offline, 'never-issued')

    def test_declared_attachment_that_is_missing_or_orphaned_raises_value_error(self):
        sample, case, request = self.rejection_sample_request(0)
        check_with_rejection(self.offline, 'bound', request)
        self.offline.execute('DELETE FROM rejections WHERE report_id = ?', ('bound',))
        self.offline.commit()
        with self.assertRaises(ValueError):
            read_rejection(self.offline, 'bound')
        # An orphan row without a snapshot declaration is also rejected.
        _, _, reachable_request = self.rejection_sample_request(1, receipt_name='reach')
        reachable_report = check_with_rejection(self.offline, 'plain', reachable_request)
        self.assertIsNone(reachable_report.attachment_digest)
        orphan = b'{"v": 1}'
        from adjudicate.attachment import attachment_digest

        self.offline.execute('INSERT INTO rejections VALUES (?, ?, ?)',
                             ('plain', orphan, attachment_digest(orphan)))
        self.offline.commit()
        with self.assertRaises(ValueError):
            read_rejection(self.offline, 'plain')

    def test_report_id_conflict_and_input_rules_are_unchanged(self):
        sample, case, request = self.rejection_sample_request(0)
        first = check_with_rejection(self.offline, 'same-id', request)
        with self.assertRaises(ValueError):
            check_with_rejection(self.offline, 'same-id', request)
        with self.assertRaises(KeyError):
            check_with_rejection(self.offline, 'missing-receipt', replace(request, receipt_id='absent'))
        self.assertEqual(read_report(self.offline, 'same-id'), first)

    def test_signing_failure_persists_nothing(self):
        sample, case, request = self.rejection_sample_request(0)

        def interrupt():
            self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM reports').fetchone()[0], 2)
            self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM first_receipts').fetchone()[0], 2)
            self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM rejections').fetchone()[0], 2)
            raise SigningInterrupted('shift ended before commit')

        check_with_rejection(self.offline, 'kept', request)
        with self.assertRaises(SigningInterrupted):
            check_with_rejection(self.offline, 'rolled-back', request, before_commit=interrupt)
        self.reopen_offline()
        self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM reports').fetchone()[0], 1)
        self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM first_receipts').fetchone()[0], 1)
        self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM rejections').fetchone()[0], 1)
        with self.assertRaises(KeyError):
            read_report(self.offline, 'rolled-back')
        self.assertIsNotNone(read_rejection(self.offline, 'kept'))


class RejectionReviewTests(RejectionCase):
    def setUp(self):
        super().setUp()
        sample, case, request = self.rejection_sample_request(0)
        self.sample = sample
        self.request = request
        self.report = check_with_rejection(self.offline, 'signed', request)
        self.attachment = read_rejection(self.offline, 'signed')
        self.received = load_received(self.offline, request.receipt_id)

    def test_valid_evidence_returns_true(self):
        self.assertTrue(verify_rejection(self.report, self.received, self.attachment))

    def test_wrong_receipt_is_rejected(self):
        other = read_sample('rejection')['revision']
        request = self.delivered_package(other, name='other-package', window=(5, 5))
        wrong = load_received(self.offline, request.receipt_id)
        with self.assertRaises(ValueError):
            verify_rejection(self.report, wrong, self.attachment)

    def test_missing_attachment_bytes_are_rejected(self):
        for payload in (b'', b'not-json', b'{"version": 1}', None, 'text'):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    verify_rejection(self.report, self.received, payload)

    def test_tampered_attachment_fails_binding(self):
        document = json.loads(self.attachment.decode('utf-8'))
        document['station_sets']['T'] = [['5', '5']]
        tampered = json.dumps(document, sort_keys=True, separators=(',', ':')).encode('ascii')
        with self.assertRaises(ValueError):
            verify_rejection(self.report, self.received, tampered)

    def test_attachment_bound_to_another_report_fails(self):
        second = check_with_rejection(self.offline, 'second', self.request)
        second_attachment = read_rejection(self.offline, 'second')
        with self.assertRaises(ValueError):
            verify_rejection(self.report, self.received, second_attachment)
        with self.assertRaises(ValueError):
            verify_rejection(second, self.received, self.attachment)

    def test_undercoverage_is_rejected(self):
        document = json.loads(self.attachment.decode('utf-8'))
        # Drop the late (6) arrival: the declaration misses a real moment at T.
        document['station_sets']['T'] = [['4', '4']]
        report, attachment = self.resign_with(document)
        with self.assertRaises(ValueError):
            verify_rejection(report, self.received, attachment)

    def test_conservative_overcoverage_still_excludes_delivery(self):
        document = json.loads(self.attachment.decode('utf-8'))
        document['station_sets']['S'].append(['7', '9'])
        document['station_sets']['T'].append(['8', '9'])
        report, attachment = self.resign_with(document)
        self.assertTrue(verify_rejection(report, self.received, attachment))

    def test_exclusion_failure_is_rejected(self):
        document = json.loads(self.attachment.decode('utf-8'))
        # Declaring 5 at the destination would permit delivery in [5,5].
        document['station_sets']['T'].append(['5', '5'])
        report, attachment = self.resign_with(document)
        with self.assertRaises(ValueError):
            verify_rejection(report, self.received, attachment)

    def test_unknown_station_declaration_is_rejected(self):
        document = json.loads(self.attachment.decode('utf-8'))
        document['station_sets']['GHOST'] = [['1', '2']]
        report, attachment = self.resign_with(document)
        with self.assertRaises(ValueError):
            verify_rejection(report, self.received, attachment)

    def test_missing_station_declaration_is_rejected(self):
        document = json.loads(self.attachment.decode('utf-8'))
        del document['station_sets']['T']
        report, attachment = self.resign_with(document)
        with self.assertRaises(ValueError):
            verify_rejection(report, self.received, attachment)

    def test_binding_field_mismatch_is_rejected(self):
        document = json.loads(self.attachment.decode('utf-8'))
        for field in ('receipt_id', 'survey_id', 'release_id', 'package_digest'):
            corrupted = deepcopy(document)
            corrupted[field] = corrupted[field] + 'x'
            report, rebuilt = self.resign_with(corrupted)
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    verify_rejection(report, self.received, rebuilt)

    def resign_with(self, document: dict):
        """Resign a fresh report whose snapshot binds these modified bytes."""
        from adjudicate.attachment import attachment_digest
        from reports.export import decode_report_snapshot, encode_report_snapshot
        from reports.receipts import load_first_receipt, make_first_receipt

        report_id = f'mutated-{self.offline.execute("SELECT COUNT(*) FROM reports").fetchone()[0]}'
        document['report_id'] = report_id
        payload = self._rebind(document)
        digest = attachment_digest(payload)
        snapshot = encode_report_snapshot(
            report_id, self.report.request, self.report.release_id, self.report.package_digest,
            None, None, digest)
        receipt = make_first_receipt(report_id, snapshot)
        with self.offline:
            self.offline.execute('INSERT INTO reports VALUES (?, ?, ?)',
                                 (report_id, self.request.receipt_id, snapshot))
            self.offline.execute('INSERT INTO first_receipts VALUES (?, ?, ?)',
                                 (report_id, receipt.receipt_id, receipt.snapshot_digest))
            self.offline.execute('INSERT INTO rejections VALUES (?, ?, ?)', (report_id, payload, digest))
        return decode_report_snapshot(snapshot, load_first_receipt(self.offline, report_id)), payload

    def _rebind(self, document: dict) -> bytes:
        # Re-encode the modified declaration as canonical attachment bytes.
        return json.dumps(document, sort_keys=True, separators=(',', ':')).encode('ascii')


class RejectionRelayTests(RejectionCase):
    def test_named_custody_time_sets_on_relay(self):
        edges = [
            transmission('early', 'S', 'M', 1, 1, 1),
            transmission('out', 'M', 'T', 7, 7, 1),
        ]
        turns = [
            {'id': 'before-power-loss', 'station': 'M', 'opens': '2', 'closes': '3',
             'origin': 'relay/50'},
            {'id': 'after-restart', 'station': 'M', 'opens': '6', 'closes': '8',
             'origin': 'relay/51'},
        ]
        revision = revision_document(('S', 'M', 'T'), edges, turns)
        request = self.delivered_package(revision, name='relay', window=(8, 8))
        self.disconnect_source()
        report = check_with_rejection(self.offline, 'relay-reject', request)
        self.assertFalse(report.reachable)
        attachment = read_rejection(self.offline, 'relay-reject')
        document = decode_rejection_attachment(attachment)
        # Arrival at M is 2; neither named turn reaches the 7 departure because
        # the arrival at 2 cannot wait inside a turn that closes at 3 and the
        # later turn opens at 6.
        self.assertEqual(document['station_sets']['M'], (ClosedWindow(2, 2),))
        self.assertEqual(document['station_sets']['T'], ())
        self.assertTrue(verify_rejection(report, load_received(self.offline, request.receipt_id), attachment))

    def test_fractional_seconds_use_exact_closed_endpoints(self):
        edges = [
            transmission('in', 'S', 'M', '1/3', '1/3', '1/3'),
            transmission('out', 'M', 'T', '4/3', '4/3', '1/3'),
        ]
        turns = [{'id': 'turn', 'station': 'M', 'opens': '2/3', 'closes': '2/3',
                  'origin': 'relay/t'}]
        revision = revision_document(('S', 'M', 'T'), edges, turns)
        request = self.delivered_package(revision, name='fraction', window=('5/3', '5/3'))
        self.disconnect_source()
        report = check_with_rejection(self.offline, 'fraction-reject', request)
        self.assertFalse(report.reachable)
        attachment = read_rejection(self.offline, 'fraction-reject')
        document = decode_rejection_attachment(attachment)
        self.assertEqual(document['station_sets']['M'], (ClosedWindow(Fraction(2, 3), Fraction(2, 3)),))
        self.assertEqual(document['station_sets']['T'], ())
        self.assertTrue(verify_rejection(report, load_received(self.offline, request.receipt_id), attachment))

    def test_direct_network_with_empty_destination_set(self):
        edges = [transmission('only', 'S', 'T', 1, 1, 1)]
        revision = revision_document(('S', 'T'), edges)
        request = self.delivered_package(revision, name='empty', window=(3, 3))
        report = check_with_rejection(self.offline, 'empty-reject', request)
        attachment = read_rejection(self.offline, 'empty-reject')
        document = decode_rejection_attachment(attachment)
        self.assertEqual(document['station_sets']['T'], (ClosedWindow(2, 2),))
        self.assertTrue(verify_rejection(report, load_received(self.offline, request.receipt_id), attachment))

    def test_attachment_digest_field_is_canonical_sha256(self):
        import hashlib

        from reports.export import encode_report_snapshot

        sample, case, request = self.rejection_sample_request(0)
        report = check_with_rejection(self.offline, 'digest', request)
        attachment = read_rejection(self.offline, 'digest')
        self.assertEqual(report.attachment_digest, hashlib.sha256(attachment).hexdigest())
        expected_snapshot = encode_report_snapshot(
            report.report_id, report.request, report.release_id, report.package_digest,
            report.arrival, report.witness, report.attachment_digest)
        self.assertEqual(report.first_receipt.snapshot_digest,
                         hashlib.sha256(expected_snapshot.encode('utf-8')).hexdigest())
