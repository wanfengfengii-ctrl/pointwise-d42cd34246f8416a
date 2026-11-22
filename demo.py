import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from adjudicate.attachment import decode_rejection_attachment
from adjudicate.request import DeliveryRequest
from adjudicate.verdict import check, check_with_rejection, verify_rejection
from issue.releases import initialize_releases, issue_package
from receive.holdings import accept, load_received
from receive.survey_check import SurveyRef
from receive.workspace import initialize_holdings, open_workspace
from records.revisions import BlockRevision, initialize_revisions, save_revision
from records.surveys import freeze, initialize_surveys
from records.times import ClosedWindow
from reports.export import ReportView
from reports.history import read_rejection, read_report
from reports.signing import initialize_reports


def delivery_summary(report: ReportView) -> dict:
    document = report.to_document()
    witness = document['witness']
    legs = None
    if witness is not None:
        legs = []
        for leg in witness:
            custody = leg['custody']
            legs.append({
                'id': leg['transmission_id'],
                'departure': leg['departure'],
                'arrival': leg['arrival'],
                'origin': leg['origin']['location'],
                'custody': custody['turn_id'] if custody is not None else None,
                'custody_origin': custody['origin']['location'] if custody is not None else None,
            })
    return {'arrival': document['arrival'], 'legs': legs}


def run_sample(sample: dict, directory: Path) -> dict:
    source_path = directory / 'source.sqlite'
    offline_path = directory / 'offline.sqlite'
    case_id = sample['case_id']
    revision = BlockRevision.from_document(sample['revision'])
    survey = SurveyRef(f'survey-{case_id}', revision.block_id, revision.revision_id)
    with closing(sqlite3.connect(source_path)) as source:
        initialize_revisions(source)
        initialize_surveys(source)
        initialize_releases(source)
        save_revision(source, revision)
        freeze(source, survey.survey_id, survey.block_id, survey.revision_id)
        issued = issue_package(source, survey.survey_id, f'issue-{case_id}')

    query = sample['query']
    receipt_id = f'held-{case_id}'
    report_id = f'report-{case_id}'
    request = DeliveryRequest(receipt_id, survey, query['source'], query['destination'],
                              ClosedWindow.from_document(query['receipt_window']))
    with closing(open_workspace(offline_path)) as workspace:
        initialize_holdings(workspace)
        initialize_reports(workspace)
        accept(workspace, receipt_id, issued.payload, survey)
        source_path.unlink()
        report = check(workspace, report_id, request)
    with closing(open_workspace(offline_path)) as reopened:
        original = read_report(reopened, report_id)

    expected = sample['expected']
    actual = delivery_summary(report)
    downstream_expected = {'delivery': expected, 'first_receipt_id': f'first:{report_id}'}
    downstream_actual = {'delivery': delivery_summary(original), 'first_receipt_id': original.first_receipt.receipt_id}
    if actual != expected or downstream_actual != downstream_expected or original != report:
        raise AssertionError(f'{case_id} delivery or offline history differs from its expected result')
    return {
        'case_id': case_id,
        'input': {'revision': sample['revision'], 'query': query},
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': [
            'records/surveys.py', 'issue/releases.py', 'receive/holdings.py',
            'adjudicate/reachability.py', 'adjudicate/witness.py', 'reports/history.py',
        ],
        'oracle': 'Hand-computed closed-window timing and named custody from the sample, followed by report reread.',
    }


def run_rejection_sample(sample: dict, directory: Path) -> dict:
    source_path = directory / 'source.sqlite'
    offline_path = directory / 'offline.sqlite'
    revision = BlockRevision.from_document(sample['revision'])
    survey = SurveyRef('survey-rejection', revision.block_id, revision.revision_id)
    with closing(sqlite3.connect(source_path)) as source:
        initialize_revisions(source)
        initialize_surveys(source)
        initialize_releases(source)
        save_revision(source, revision)
        freeze(source, survey.survey_id, survey.block_id, survey.revision_id)
        issued = issue_package(source, survey.survey_id, 'issue-rejection')

    receipt_id = 'held-rejection'
    with closing(open_workspace(offline_path)) as workspace:
        initialize_holdings(workspace)
        initialize_reports(workspace)
        accepted = accept(workspace, receipt_id, issued.payload, survey)
        source_path.unlink()
        results = []
        for case in sample['cases']:
            query = case['query']
            request = DeliveryRequest(receipt_id, survey, query['source'], query['destination'],
                                      ClosedWindow.from_document(query['receipt_window']))
            report_id = f"report-{case['case_id']}"
            report = check_with_rejection(workspace, report_id, request)
            attachment = read_rejection(workspace, report_id)
            results.append({
                'case_id': case['case_id'],
                'report_id': report_id,
                'report': report,
                'attachment': attachment,
                'query': query,
                'expected': case['expected'],
            })

    # Reopen after the source ledger is gone: the same attachment is claimed
    # back by its original report number and verified against the actual item.
    review_lines = []
    with closing(open_workspace(offline_path)) as reopened:
        received = load_received(reopened, receipt_id)
        for entry in results:
            report = read_report(reopened, entry['report_id'])
            attachment = read_rejection(reopened, entry['report_id'])
            actual = delivery_summary(report)
            if actual != entry['expected']:
                raise AssertionError(f"rejection case {entry['case_id']} differs from its expected verdict")
            line = {
                'case_id': entry['case_id'],
                'receipt_window': entry['query']['receipt_window'],
                'verdict': actual,
                'has_attachment': report.has_rejection_attachment,
            }
            if attachment is None:
                if report.reachable is False:
                    raise AssertionError('unreachable report must keep its rejection attachment')
                line['review'] = 'no-attachment-reachable'
            else:
                if attachment != entry['attachment']:
                    raise AssertionError('reopened attachment is not the originally signed bytes')
                declaration = decode_rejection_attachment(attachment)['station_sets']
                line['declared_station_sets'] = {
                    station: [window.to_document() for window in windows]
                    for station, windows in declaration.items()
                }
                line['review'] = 'verified' if verify_rejection(report, received, attachment) else 'rejected'
            review_lines.append(line)

        # Reviewer controls: wrong item, missing evidence, invalid binding.
        reject_report = read_report(reopened, f"report-{sample['cases'][0]['case_id']}")
        reject_attachment = read_rejection(reopened, f"report-{sample['cases'][0]['case_id']}")
        controls = []
        wrong_item = replace_received_identity(received)
        controls.append(('wrong-item', _expect_value_error(verify_rejection, reject_report, wrong_item,
                                                           reject_attachment)))
        controls.append(('missing-evidence', _expect_value_error(verify_rejection, reject_report, received,
                                                                 b'')))
        tampered = bytearray(reject_attachment)
        tampered[-1] = tampered[-1] ^ 0x01
        controls.append(('invalid-binding', _expect_value_error(verify_rejection, reject_report, received,
                                                                bytes(tampered))))
        if not all(flag for _, flag in controls):
            raise AssertionError('a rejection review control failed to reject bad evidence')

    return {
        'case_id': 'rejection',
        'input': {'revision': sample['revision'], 'cases': sample['cases']},
        'review': review_lines,
        'review_controls': [{'control': name, 'rejected': flag} for name, flag in controls],
        'receipt_id': receipt_id,
        'package_digest': accepted.package.digest,
        'code_paths': [
            'adjudicate/coverage.py', 'adjudicate/attachment.py', 'adjudicate/rejection_review.py',
            'adjudicate/verdict.py', 'reports/signing.py', 'reports/history.py',
        ],
        'oracle': 'Exact closed time sets per station, coverage plus exclusion review, attachment claimed back by report number offline.',
    }


def replace_received_identity(received):
    wrong_manifest = replace(received.package.manifest, release_id='release-other')
    wrong_package = replace(received.package, manifest=wrong_manifest)
    return replace(received, package=wrong_package)


def _expect_value_error(func, *args) -> bool:
    try:
        func(*args)
    except ValueError:
        return True
    return False


def main() -> None:
    samples = Path(__file__).resolve().parent / 'samples'
    for name in ('single', 'later', 'gap'):
        sample = json.loads((samples / f'{name}.json').read_text(encoding='utf-8'))
        with TemporaryDirectory(prefix='recording-handoff-') as directory:
            scenario = run_sample(sample, Path(directory))
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))
    rejection_sample = json.loads((samples / 'rejection.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='recording-handoff-') as directory:
        scenario = run_rejection_sample(rejection_sample, Path(directory))
    print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
