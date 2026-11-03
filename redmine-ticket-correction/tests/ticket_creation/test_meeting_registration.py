import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ticket_tools.ticket_creation import meeting_registration as reg
from ticket_tools.ticket_creation import redmine_meeting_importer as imp


@pytest.mark.parametrize('value', [None, ''])
def test_empty_description_fields_are_omitted(value):
    assert imp.build_item_description(dict(description=value, rationale=value, expected_state=value), imp.TextFormatter('markdown')) == ''


def test_evidence_separate_from_background_and_values_preserved():
    item = dict(description='本文', rationale='背景', expected_state='完了条件', evidence=[dict(timestamp='00:01-00:03',speaker='S1',summary='発言')])
    text = imp.build_item_description(item, imp.TextFormatter('textile'))
    assert '背景\n\n根拠：00:01-00:03 / S1 / 発言\n\n期待状態:\n完了条件' in text
    item['rationale'] += '\n\n根拠：00:01-00:03 / S1 / 発言'
    assert imp.build_item_description(item, imp.TextFormatter('markdown')).count('根拠：') == 1
    item['rationale'] = '背景 根拠：00:01-00:03 / S1 / 発言'
    assert '背景\n\n根拠：' in imp.build_item_description(item, imp.TextFormatter('markdown'))


@pytest.mark.parametrize('separator', [' ', '。', '\n'])
def test_embedded_evidence_with_different_notation_is_separated(separator):
    original = 'VTT 00:01-00:03、S1。'
    item = dict(
        description='本文', rationale='背景' + separator + '根拠：' + original,
        expected_state=None,
        evidence=[dict(timestamp='00:01-00:03', speaker='S1', summary='発言')],
    )
    text = imp.build_item_description(item, imp.TextFormatter('markdown'))
    assert text.count('根拠：') == 1
    assert '\n\n根拠：' in text
    assert original in text
    assert '00:01-00:03 / S1 / 発言' in text
    assert '期待状態:' not in text


def test_embedded_evidence_without_structured_rows_is_preserved():
    item = dict(description='本文', rationale='背景 根拠:VTT 00:01、S1。')
    text = imp.build_item_description(item, imp.TextFormatter('markdown'))
    assert '理由・背景:\n背景\n\n根拠：VTT 00:01、S1。' in text


@pytest.mark.parametrize('rationale', ['「根拠：」は表示名の説明です。', '「根拠：発言」は引用です。'])
def test_quoted_evidence_label_is_not_reinterpreted(rationale):
    item = dict(rationale=rationale, evidence=[dict(summary='発言')])
    text = imp.build_item_description(item, imp.TextFormatter('markdown'))
    assert '理由・背景:\n' + rationale in text
    assert '\n\n根拠：発言' in text


class Client:
    def __init__(self): self.calls = []
    def request_json(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        assert method == 'GET'
        if path == '/projects.json':
            projects = [dict(id=1,name='A',identifier='a'),dict(id=2,name='A',identifier='b',parent={'id':1})]
            return dict(projects=projects[payload['offset']:payload['offset']+1],total_count=2)
        return dict(project=dict(id=2,trackers=[dict(id=6,name='議事録'),dict(id=7,name='課題')]))


def test_candidates_pages_ambiguity_and_project_trackers():
    c = Client()
    with pytest.raises(ValueError,match='exactly one'): reg.registration_candidates(c,'https://example.test/redmine',project_name='A')
    result = reg.registration_candidates(c,'https://example.test/redmine',project_id='b',parent_tracker_name='議事録',child_tracker_name='課題')
    assert result['project']['id'] == 2 and result['child_tracker']['id'] == 7
    assert result['projects'][1]['parent']['id'] == 1
    with pytest.raises(ValueError): reg.exact_choice(result['trackers'],'未登録')
    with pytest.raises(ValueError): reg.exact_choice([dict(id=1,name='同名'),dict(id=2,name='同名')],'同名')


@pytest.mark.parametrize('response', [dict(projects=[],total_count=1),dict(projects=[dict(id=1)],total_count=2)])
def test_bad_pagination_fails(response):
    class Bad:
        def request_json(self,*args): return response
    with pytest.raises(ValueError): reg.paged_projects(Bad())


@pytest.mark.parametrize('error', [PermissionError,TimeoutError,ConnectionError])
def test_candidate_failure_is_not_retried(error):
    class Bad:
        calls = 0
        def request_json(self,*args):
            self.calls += 1
            raise error()
    c = Bad()
    with pytest.raises(error): reg.registration_candidates(c,'https://example.test')
    assert c.calls == 1


def test_labels_must_match_destination(tmp_path):
    labels = reg.registration_candidates(Client(),'https://example.test',project_id='b',parent_tracker_name='議事録',child_tracker_name='課題')
    path = tmp_path/'candidates.json'
    path.write_text(json.dumps(labels),encoding='utf-8')
    assert reg.load_labels(path,'https://example.test','b',6,7)['project']['name'] == 'A'
    for args in [('https://other.test','b',6,7),('https://example.test','a',6,7),('https://example.test','b',7,6)]:
        with pytest.raises(ValueError): reg.load_labels(path,*args)


def test_preview_escapes_exact_payload_and_does_not_leak_config():
    payload = dict(subject='<script>alert(1)</script>',description='背景\n\n根拠：発言',project_id='a',tracker_id=6,assigned_to_id=8,due_date='2026-11-04')
    result = dict(parent={'payload':payload},children=[dict(item_id='I1',payload_template=dict(payload,tracker_id=7))],warnings=['不足'],unresolved_mappings=[{'field':'担当者'}])
    original = json.dumps(result)
    page = reg.render_registration_preview(result,'https://example.test/redmine',{},dict(user_ids={'担当A':8},api_key='SECRET',proxy='SECRET_PROXY'))
    assert '<script>' not in page and '&lt;script&gt;' in page
    assert 'SECRET' not in page and '担当A' in page and '2026-11-04' in page
    assert 'まだRedmineには登録されていません' in page and '不足' in page
    assert '背景\n\n根拠：発言' in page and json.dumps(result) == original


def test_dry_run_writes_sibling_html_without_network(tmp_path,monkeypatch):
    monkeypatch.setattr(imp,'RedmineClient',lambda *a,**k: pytest.fail('offline dry-run accessed API'))
    data = dict(meeting={'title':'架空会議'},meeting_summary={},redmine_meeting_fields={},summary={},human_review_required=[],items=[])
    source = tmp_path/'input.json';config = tmp_path/'config.json';output = tmp_path/'draft.json'
    source.write_text(json.dumps(data),encoding='utf-8');config.write_text(json.dumps({'redmine_url':'https://example.test','verify_ssl':False}),encoding='utf-8')
    assert imp.run([str(source),'--config',str(config),'--project-id','a','--parent-tracker-id','6','--child-tracker-id','7','--output',str(output)]) == 0
    assert output.with_suffix('.html').is_file()
    assert json.loads(output.read_text(encoding='utf-8'))['children'] == []


@pytest.mark.parametrize('filename', ['draft.html', 'draft.HTML'])
def test_preview_path_collision_is_rejected_before_writes(tmp_path, monkeypatch, filename):
    monkeypatch.setattr(imp, 'RedmineClient', lambda *args, **kwargs: pytest.fail('API accessed'))
    monkeypatch.setattr(imp, 'safe_write_json', lambda *args, **kwargs: pytest.fail('JSON written'))
    source = tmp_path / 'input.json'
    config = tmp_path / 'config.json'
    output = tmp_path / filename
    data = dict(meeting={'title': '架空会議'}, meeting_summary={}, redmine_meeting_fields={},
                summary={}, human_review_required=[], items=[])
    source.write_text(json.dumps(data), encoding='utf-8')
    config.write_text(json.dumps({'redmine_url': 'https://example.test'}), encoding='utf-8')
    output.write_text('Existing artifact', encoding='utf-8')
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='JSON output and HTML preview paths must differ'):
        imp.run([str(source), '--config', str(config), '--project-id', 'a',
                 '--parent-tracker-id', '6', '--child-tracker-id', '7', '--output', str(output)])
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.skipif(os.name != 'nt',reason='Windows BAT')
def test_batch_from_other_directory_with_optional_labels(tmp_path):
    app = Path(__file__).resolve().parents[2]
    options = reg.registration_candidates(Client(),'https://example.test',project_id='b',parent_tracker_name='議事録',child_tracker_name='課題')
    labels = tmp_path/'candidate labels.json'
    labels.write_text(json.dumps(options),encoding='utf-8')
    config = tmp_path/'config.json'
    config.write_text(json.dumps(dict(redmine_url='https://example.test')),encoding='utf-8')
    source = tmp_path/'input.json'
    source.write_text(json.dumps(dict(meeting={'title':'会議'},meeting_summary={},redmine_meeting_fields={},summary={},human_review_required=[],items=[])),encoding='utf-8')
    output = tmp_path/'result.json'
    env = dict(os.environ, PATH=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH'])
    run = subprocess.run(['cmd','/d','/c',str(app/'scripts/run_meeting_importer.bat'),'dry-run',str(source),str(config),'b','6','7',str(output),'',str(labels)],cwd=tmp_path,env=env,capture_output=True,timeout=30)
    assert run.returncode == 0,run.stderr.decode(errors='replace')
    assert '議事録 (ID: 6)' in output.with_suffix('.html').read_text(encoding='utf-8')
    help_result = subprocess.run(['cmd','/d','/c',str(app/'scripts/run_meeting_options.bat'),'--help'],cwd=tmp_path,env=env,capture_output=True,timeout=30)
    assert help_result.returncode == 0 and b'--project-name' in help_result.stdout
