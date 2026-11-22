import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from adjudicate.request import DeliveryRequest
from adjudicate.verdict import check
from issue.releases import initialize_releases, issue_package
from receive.holdings import accept
from receive.survey_check import SurveyRef
from receive.workspace import initialize_holdings, open_workspace
from records.revisions import BlockRevision, initialize_revisions, save_revision
from records.surveys import freeze, initialize_surveys
from records.times import ClosedWindow
from reports.export import ReportView
from reports.history import read_report
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


def main() -> None:
    samples = Path(__file__).resolve().parent / 'samples'
    for name in ('single', 'later', 'gap'):
        sample = json.loads((samples / f'{name}.json').read_text(encoding='utf-8'))
        with TemporaryDirectory(prefix='recording-handoff-') as directory:
            scenario = run_sample(sample, Path(directory))
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
