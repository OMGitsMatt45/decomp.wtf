"""Only passing application and five-console Windows checks authorize publication."""

import pytest

from tools import release_gate


@pytest.fixture
def qualification(tmp_path, monkeypatch):
    notes, output = tmp_path / 'notes.md', tmp_path / 'published.md'
    notes.write_text('Release notes', encoding='utf-8')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setattr('sys.argv', ['release_gate', '--sha', 'tested', '--notes', str(notes),
                                   '--output', str(output)])
    runs, jobs = [], {}
    for index, (path, job) in enumerate(release_gate.REQUIRED.items(), 1):
        runs.append(dict(id=index, path=path, head_sha='tested', head_branch='main',
                         event='workflow_dispatch', status='completed', conclusion='success',
                         html_url=f'https://example.test/run/{index}'))
        jobs[index] = [dict(name=job, conclusion='success')]

    def get(path):
        if '/jobs?' in path:
            return dict(jobs=jobs[int(path.split('/runs/')[1].split('/')[0])])
        assert 'head_sha=tested' in path
        return dict(workflow_runs=runs)

    monkeypatch.setattr(release_gate, 'get', get)
    return runs, jobs, output


@pytest.mark.parametrize('event', ['push', 'workflow_dispatch'])
def test_successful_exact_main_windows_checks_authorize_release(qualification, event):
    runs, jobs, output = qualification
    for run in runs:
        run['event'] = event
        jobs[run['id']].append(dict(name='linux (ubuntu-24.04)', conclusion='failure'))
    release_gate.main()
    text = output.read_text()
    assert 'Tested commit: `tested`' in text
    assert len(runs) == 6
    assert all(run['html_url'] in text for run in runs)


@pytest.mark.parametrize('index', range(6))
def test_every_console_and_application_check_is_required(qualification, index):
    runs, _, output = qualification
    runs.pop(index)
    with pytest.raises(SystemExit, match='release blocked'):
        release_gate.main()
    assert not output.exists()


@pytest.mark.parametrize('field,value', [
    ('head_sha', 'other'), ('head_branch', 'feature'), ('event', 'pull_request'),
    ('status', 'in_progress'), ('conclusion', 'failure'), ('conclusion', 'cancelled'),
    ('path', '.github/workflows/retired-operational.yml'),
])
def test_unqualified_runs_cannot_authorize_release(qualification, field, value):
    runs, _, output = qualification
    runs[0][field] = value
    with pytest.raises(SystemExit, match='release blocked'):
        release_gate.main()
    assert not output.exists()


@pytest.mark.parametrize('status', ['failure', 'skipped', 'cancelled'])
def test_missing_windows_job_cannot_be_replaced_by_linux(qualification, status):
    runs, jobs, output = qualification
    jobs[runs[0]['id']][0]['conclusion'] = status
    jobs[runs[0]['id']].append(dict(name='foundation (ubuntu-24.04)', conclusion='success'))
    with pytest.raises(SystemExit, match='release blocked'):
        release_gate.main()
    assert not output.exists()


def test_later_failure_supersedes_old_success(qualification):
    runs, jobs, output = qualification
    runs.insert(0, {**runs[0], 'id': 99, 'conclusion': 'failure'})
    jobs[99] = []
    with pytest.raises(SystemExit, match='release blocked'):
        release_gate.main()
    assert not output.exists()
