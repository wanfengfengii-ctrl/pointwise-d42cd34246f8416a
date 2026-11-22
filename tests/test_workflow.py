import json
from dataclasses import replace
from fractions import Fraction

from adjudicate.verdict import check
from demo import delivery_summary
from issue.releases import issue_package
from receive.holdings import accept, load_received
from reports.history import read_report
from tests.fixtures import WorkflowCase, read_sample


class WorkflowTests(WorkflowCase):
    def test_day_and_night_handoff(self):
        samples = {name: read_sample(name) for name in ('single', 'later', 'gap')}
        requests = {}
        for name, sample in samples.items():
            document = sample['revision']
            # Each scenario is a separate investigated original block in this day-long run.
            document['block_id'] = f'bench-{name}'
            requests[name] = self.sample_request(name, registration=document)
        self.disconnect_source()
        reports = {}
        for name, request in requests.items():
            with self.subTest(sample=name):
                report = check(self.offline, f'report-{name}', request)
                reports[name] = report
                self.assertEqual(delivery_summary(report), samples[name]['expected'])
                if report.reachable:
                    self.assert_witness(report, samples[name]['revision'], request)
                else:
                    self.assert_unreachable(report)
        self.assertEqual(self.signed_counts(), (3, 3))
        self.reopen_offline()
        for name, report in reports.items():
            with self.subTest(reopened=name):
                restored = read_report(self.offline, f'report-{name}')
                self.assertEqual(restored, report)
                self.assertEqual(restored.first_receipt.receipt_id, f'first:report-{name}')
                self.assertEqual(load_received(self.offline, restored.request.receipt_id).package.digest,
                                 restored.package_digest)

    def test_designated_holdings_preserve_the_received_bytes(self):
        sample = read_sample('single')
        ref = self.frozen(sample['revision'], 'survey')
        first = issue_package(self.source, 'survey', 'release-first')
        another = issue_package(self.source, 'survey', 'release-second')
        as_delivered = json.dumps(json.loads(first.payload), indent=2).encode('utf-8')
        accepted = accept(self.offline, 'from-bag', as_delivered, ref)
        self.assertEqual(accept(self.offline, 'from-bag', as_delivered, ref), accepted)
        with self.assertRaises(ValueError):
            accept(self.offline, 'from-bag', another.payload, ref)
        accept(self.offline, 'spare', another.payload, ref)
        self.disconnect_source()
        self.reopen_offline()
        from adjudicate.request import DeliveryRequest
        from records.times import ClosedWindow

        request = DeliveryRequest('from-bag', ref, 'S', 'T', ClosedWindow(3, 4))
        with self.assertRaises(KeyError):
            check(self.offline, 'missing', replace(request, receipt_id='absent'))
        report = check(self.offline, 'selected', request)
        self.assertEqual(report.release_id, 'release-first')
        self.assertEqual(report.package_digest, accepted.package.digest)
        self.assertEqual(report.arrival, Fraction(4))
        self.assertEqual(load_received(self.offline, 'from-bag').payload, as_delivered)
        self.assertEqual(self.signed_counts(), (1, 1))
