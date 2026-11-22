import json
from copy import deepcopy

from issue.releases import issue_package
from records.revisions import load_revision
from records.surveys import freeze, read_frozen_survey
from tests.fixtures import WorkflowCase, read_sample, revision_document, transmission


class SurveyTests(WorkflowCase):
    def test_frozen_reissue(self):
        original = read_sample('single')['revision']
        survey = self.frozen(original, 'original')
        first = issue_package(self.source, survey.survey_id, 'release-original')
        changed = deepcopy(original)
        changed['revision_id'] = 'R2'
        changed['transmissions'][0]['origin'] = 'dispatch/correction'
        correction = self.frozen(changed, 'correction')
        new = issue_package(self.source, correction.survey_id, 'release-correction')
        replay = issue_package(self.source, survey.survey_id, 'release-original')
        self.assertEqual(replay, first)
        self.assertEqual(replay.payload, first.payload)
        self.assertNotEqual(new.payload, first.payload)
        self.assertEqual(new.manifest.revision_id, 'R2')
        old_origin = json.loads(replay.payload)['origins']['transmission:in']
        self.assertEqual(old_origin['location'], 'dispatch/10')

    def test_repeat_init(self):
        first = read_sample('single')['revision']
        reference = self.frozen(first, 'old-survey')
        second = deepcopy(first)
        second['revision_id'] = 'R2'
        second['transmissions'][0]['origin'] = 'dispatch/new'
        self.register(second)
        self.initialize_source()
        self.register(first)
        conflicting = deepcopy(first)
        conflicting['transmissions'][0]['origin'] = 'dispatch/conflict'
        with self.assertRaises(ValueError):
            self.register(conflicting)
        for expected in (first, second):
            loaded = load_revision(self.source, expected['block_id'], expected['revision_id'])
            self.assertEqual(loaded.to_document(), expected)
        repeat = freeze(self.source, reference.survey_id, reference.block_id, reference.revision_id)
        self.assertEqual(repeat.revision_id, 'R1')
        with self.assertRaises(ValueError):
            freeze(self.source, reference.survey_id, reference.block_id, 'R2')

    def test_frozen_snapshot(self):
        first = read_sample('single')['revision']
        reference = self.frozen(first, 'frozen-before-correction')
        correction = deepcopy(first)
        correction['revision_id'] = 'R2'
        correction['transmissions'][0].update(opens='2', closes='2', origin='dispatch/revised')
        self.register(correction)
        package = issue_package(self.source, reference.survey_id, 'first-issue')
        document = json.loads(package.payload)
        self.assertEqual(document['manifest']['revision_id'], 'R1')
        self.assertEqual(document['evidence']['transmissions'][0]['opens'], '1')
        self.assertEqual(document['origins']['transmission:in']['location'], 'dispatch/10')
        self.assertEqual(read_frozen_survey(self.source, reference.survey_id).snapshot(), first)

    def test_release_identity(self):
        document = read_sample('single')['revision']
        self.frozen(document, 'survey-a')
        self.frozen(document, 'survey-b')
        issued = issue_package(self.source, 'survey-a', 'one-release')
        self.assertEqual(issue_package(self.source, 'survey-a', 'one-release'), issued)
        with self.assertRaises(ValueError):
            issue_package(self.source, 'survey-b', 'one-release')
        with self.assertRaises(KeyError):
            issue_package(self.source, 'unknown-survey', 'other-release')
        self.assertEqual(self.source.execute('SELECT release_id FROM releases').fetchall(), [('one-release',)])
        self.assertEqual(issue_package(self.source, 'survey-a', 'one-release'), issued)

    def test_equal_origins(self):
        rows = [transmission(name, 'S', 'T', 1, 1, 1) for name in ('one', 'two')]
        self.frozen(revision_document(('S', 'T'), rows), 'parallel')
        payload = issue_package(self.source, 'parallel', 'release').payload
        package = json.loads(payload)
        edges = package['evidence']['transmissions']
        self.assertEqual([edge['id'] for edge in edges], ['one', 'two'])
        self.assertEqual([edge['opens'] for edge in edges], ['1', '1'])
        self.assertNotEqual(edges[0]['origin_key'], edges[1]['origin_key'])
        self.assertEqual([package['origins'][edge['origin_key']]['location'] for edge in edges],
                         ['dispatch/one', 'dispatch/two'])

    def test_named_custody(self):
        self.frozen(read_sample('later')['revision'], 'named')
        package = json.loads(issue_package(self.source, 'named', 'release').payload)
        rows = package['evidence']['custody_turns']
        self.assertEqual([(row['id'], row['opens'], row['closes']) for row in rows],
                         [('before-power-loss', '2', '3'), ('after-restart', '6', '8')])
        self.assertEqual([package['origins'][row['origin_key']]['location'] for row in rows],
                         ['relay/50', 'relay/51'])

    def assert_cannot_freeze(self, document, survey_id):
        revision = self.register(document)
        with self.assertRaises(ValueError):
            freeze(self.source, survey_id, revision.block_id, revision.revision_id)
        with self.assertRaises(KeyError):
            read_frozen_survey(self.source, survey_id)

    def test_invalid_duration(self):
        edge = transmission('zero', 'S', 'T', 1, 2, 0)
        self.assert_cannot_freeze(revision_document(('S', 'T'), [edge]), 'zero-duration')

    def test_invalid_time(self):
        for index, change in enumerate(({'opens': None}, {'opens': '1/0'}, {'opens': 4},
                                        {'closes': 1.5}, {'closes': True}, {'duration': None}, {})):
            with self.subTest(change=change):
                edge = transmission('edge', 'S', 'T', 1, 2, 1)
                edge.update(change)
                if not change:
                    del edge['duration']
                document = revision_document(('S', 'T'), [edge], revision_id=f'R{index}')
                self.assert_cannot_freeze(document, f'invalid-{index}')

    def test_cyclic_network(self):
        edges = [transmission('one', 'S', 'M', 1, 1, 1), transmission('back', 'M', 'S', 3, 3, 1)]
        self.assert_cannot_freeze(revision_document(('S', 'M'), edges), 'cycle')

    def test_unknown_station_reference(self):
        edge = transmission('unknown', 'S', 'M', 1, 2, 1)
        self.assert_cannot_freeze(revision_document(('S', 'T'), [edge]), 'unknown-station')
