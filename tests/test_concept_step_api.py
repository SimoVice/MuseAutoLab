"""Revision-bound STEP downloads and optional CAD failure behavior."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from test_concept_design import proposal

import app.api as api
import app.concept_cad as cad
from app.concept_agent import attach_concept
from app.concept_design import compile_concept
from app.domain import new_project


@pytest.fixture
def step_session():
    project = new_project()
    project['workflow']['kind'] = 'general'
    project = attach_concept(project, project.copy(), compile_concept(proposal(), 200))
    api._sessions[project['id']] = api.ProjectSession(project=project)
    yield project
    api._sessions.pop(project['id'], None)


def test_step_downloads_are_revision_bound_and_excluded_from_zip(step_session, tmp_path):
    build123d = pytest.importorskip('build123d')
    base = f"/api/projects/{step_session['id']}/concept"
    revision = step_session['revision']
    with TestClient(api.app) as client:
        for asset in ('machine.step', 'parts/turntable.step'):
            response = client.get(f'{base}/{asset}', params={'revision': revision})
            assert response.status_code == 200, response.text
            assert response.headers['content-type'].startswith('model/step')
            assert b'ISO-10303-21' in response.content[:500]
            path = tmp_path / asset.rsplit('/', 1)[-1]
            path.write_bytes(response.content)
            assert build123d.import_step(path).is_valid
        missing = client.get(f'{base}/parts/not-a-part.step', params={'revision': revision})
        stale = client.get(f'{base}/machine.step', params={'revision': revision + 1})
        assert missing.status_code == 404
        assert stale.status_code == 409
        package = client.get(f'{base}/package.zip', params={'revision': revision})
        assert package.status_code == 200
        names = zipfile.ZipFile(io.BytesIO(package.content)).namelist()
        assert not any(name.endswith('.step') for name in names)


def test_step_failures_have_clear_http_errors(step_session, monkeypatch):
    base = f"/api/projects/{step_session['id']}/concept/machine.step"
    revision = step_session['revision']
    def missing(*_args, **_kwargs):
        raise cad.ConceptCADUnavailable('Optional CAD is missing')
    monkeypatch.setattr(cad, 'concept_step', missing)
    with TestClient(api.app) as client:
        result = client.get(base, params={'revision': revision})
        assert result.status_code == 503
        assert 'optional CAD installation' in result.json()['detail']
        def oversized(*_args, **_kwargs):
            raise ValueError('STEP export supports up to 200 primitives per file.')
        monkeypatch.setattr(cad, 'concept_step', oversized)
        result = client.get(base, params={'revision': revision})
        assert result.status_code == 422
        assert '200 primitives' in result.json()['detail']
