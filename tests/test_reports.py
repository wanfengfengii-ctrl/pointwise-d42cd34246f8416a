import sqlite3
from copy import deepcopy
from fractions import Fraction

from adjudicate.verdict import check
from receive.holdings import load_received
from reports.history import read_report
from reports.receipts import load_first_receipt
from tests.fixtures import SigningInterrupted, WorkflowCase, read_sample


class ReportTests(WorkflowCase):
    def test_signing_failure(self):
        request = self.sample_request('single')
        old = check(self.offline, 'old', request)
        self.assertEqual(self.signed_counts(), (1, 1))

        def interrupt():
            self.assertTrue(self.offline.in_transaction)
            self.assertEqual(self.signed_counts(), (2, 2))
            self.assertEqual(load_first_receipt(self.offline, 'interrupted').report_id, 'interrupted')
            raise SigningInterrupted('shift ended before report commit')

        with self.assertRaises(SigningInterrupted):
            check(self.offline, 'interrupted', request, before_commit=interrupt)
        self.reopen_offline()
        self.assertEqual(self.signed_counts(), (1, 1))
        with self.assertRaises(KeyError):
            read_report(self.offline, 'interrupted')
        with self.assertRaises(KeyError):
            load_first_receipt(self.offline, 'interrupted')
        self.assertEqual(read_report(self.offline, 'old'), old)
        self.assertEqual(load_first_receipt(self.offline, 'old'), old.first_receipt)

    def test_retry(self):
        request = self.sample_request('single')
        old = check(self.offline, 'old', request)
        self.offline.execute('CREATE TABLE commit_parents (id INTEGER PRIMARY KEY)')
        self.offline.execute('''
            CREATE TABLE commit_children (
                parent_id INTEGER REFERENCES commit_parents(id) DEFERRABLE INITIALLY DEFERRED
            )
        ''')

        def violate_commit_constraint():
            self.offline.execute('INSERT INTO commit_children VALUES (99)')
            self.assertEqual(self.signed_counts(), (2, 2))

        with self.assertRaises(sqlite3.IntegrityError):
            check(self.offline, 'retry', request, before_commit=violate_commit_constraint)
        self.assertFalse(self.offline.in_transaction)
        self.assertEqual(self.signed_counts(), (1, 1))
        self.assertEqual(self.offline.execute('SELECT COUNT(*) FROM commit_children').fetchone()[0], 0)
        with self.assertRaises(KeyError):
            load_first_receipt(self.offline, 'retry')
        self.reopen_offline()
        retry = check(self.offline, 'retry', request)
        self.assertEqual(self.signed_counts(), (2, 2))
        self.assertEqual(read_report(self.offline, 'retry'), retry)
        self.assertEqual(read_report(self.offline, 'old'), old)
        with self.assertRaises(ValueError):
            check(self.offline, 'retry', request)
        self.assertEqual(self.signed_counts(), (2, 2))

    def test_reopen_without_source(self):
        request = self.sample_request('later')
        original = check(self.offline, 'before-correction', request)
        correction = deepcopy(read_sample('later')['revision'])
        correction['revision_id'] = 'R2'
        correction['transmissions'][1]['origin'] = 'dispatch/corrected'
        self.register(correction)
        self.disconnect_source()
        self.reopen_offline()
        restored = read_report(self.offline, 'before-correction')
        self.assertEqual(restored, original)
        self.assertEqual(restored.arrival, Fraction(8))
        self.assertEqual(restored.witness.legs[0].origin.location, 'dispatch/21')
        self.assertEqual(restored.first_receipt, original.first_receipt)

    def test_repeat_init(self):
        request = self.sample_request('single')
        report = check(self.offline, 'kept-report', request)
        package = load_received(self.offline, request.receipt_id)
        self.disconnect_source()
        self.reopen_offline()
        self.initialize_offline()
        self.initialize_offline()
        self.assertEqual(load_received(self.offline, request.receipt_id), package)
        self.assertEqual(read_report(self.offline, 'kept-report'), report)
        self.assertEqual(self.signed_counts(), (1, 1))

    def test_older_report(self):
        old_request = self.sample_request('single')
        old = check(self.offline, 'older', old_request)
        revised = read_sample('single')['revision']
        revised['revision_id'] = 'R2'
        revised['transmissions'][1].update(opens='3', closes='3', duration='2', origin='dispatch/revised')
        new_request = self.delivered_package(revised, name='revised', window=(5, 5))
        new = check(self.offline, 'newer', new_request)
        self.disconnect_source()
        self.reopen_offline()
        restored_old = read_report(self.offline, 'older')
        restored_new = read_report(self.offline, 'newer')
        self.assertEqual(restored_old, old)
        self.assertEqual(restored_new, new)
        self.assertEqual((restored_old.arrival, restored_new.arrival), (Fraction(4), Fraction(5)))
        self.assertEqual(restored_old.witness.legs[-1].origin.location, 'dispatch/11')
        self.assertEqual(restored_new.witness.legs[-1].origin.location, 'dispatch/revised')
        self.assertNotEqual(restored_old.first_receipt, restored_new.first_receipt)

    def test_unknown_report(self):
        request = self.sample_request('single')
        existing = check(self.offline, 'known', request)
        self.reopen_offline()
        with self.assertRaises(KeyError):
            read_report(self.offline, 'unknown')
        self.assertEqual(read_report(self.offline, 'known'), existing)
