"""Local adapter safeguards; does not launch Fluent."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock
import pytest

spec=importlib.util.spec_from_file_location('fluent_post_adapter',Path(__file__).with_name('server.py'))
post=importlib.util.module_from_spec(spec)
spec.loader.exec_module(post)


@pytest.fixture
def case(tmp_path,monkeypatch):
    source=tmp_path/'case.cas.h5';source.write_bytes(b'case')
    (tmp_path/'case.dat.h5').write_bytes(b'data')
    monkeypatch.setattr(post,'OUTPUT',tmp_path/'output')
    monkeypatch.setattr(post.session_manager,'_sessions',{})
    monkeypatch.setattr(post,'_locks',{})
    return source


def test_disallowed_cpu_never_launches(case,monkeypatch):
    launch=Mock();monkeypatch.setattr(post.pyfluent,'launch_fluent',launch)
    with pytest.raises(ValueError,match='one CPU'):post.open_session(str(case),processor_count=2)
    launch.assert_not_called()


def test_missing_data_never_launches(case,monkeypatch):
    case.with_name('case.dat.h5').unlink()
    launch=Mock();monkeypatch.setattr(post.pyfluent,'launch_fluent',launch)
    with pytest.raises(ValueError,match='matching'):post.open_session(str(case))
    launch.assert_not_called()


def test_busy_worker_never_launches(case,monkeypatch):
    lock=Mock();lock.__enter__=Mock(side_effect=ValueError('busy'))
    monkeypatch.setattr(post,'worker_lock',Mock(return_value=lock))
    launch=Mock();monkeypatch.setattr(post.pyfluent,'launch_fluent',launch)
    with pytest.raises(ValueError,match='busy'):post.open_session(str(case))
    launch.assert_not_called()


def test_load_failure_exits_and_releases_lock(case,monkeypatch):
    lock=Mock();lock.__enter__=Mock();lock.__exit__=Mock()
    monkeypatch.setattr(post,'worker_lock',Mock(return_value=lock))
    solver=Mock();solver.settings.file.read_case_data.side_effect=ValueError('bad case')
    monkeypatch.setattr(post.pyfluent,'launch_fluent',Mock(return_value=solver))
    with pytest.raises(ValueError,match='bad case'):post.open_session(str(case))
    solver.exit.assert_called_once();lock.__exit__.assert_called_once()
    assert not post.session_manager._sessions


def test_close_failure_retains_session_and_lock(case):
    solver=Mock();solver.exit.side_effect=ValueError('exit uncertain')
    post.session_manager._sessions['test']=post.FluentSession('test',solver)
    lock=Mock();lock.__exit__=Mock();post._locks['test']=lock
    with pytest.raises(ValueError,match='uncertain'):post.close_session('test')
    assert 'test' in post.session_manager._sessions
    lock.__exit__.assert_not_called()
    post.session_manager._sessions.clear();post._locks.clear()


def test_catalog_has_no_arbitrary_execution():
    import asyncio
    tools=asyncio.run(post.build_post_server().list_tools())
    names={t.name for t in tools}
    assert 'execute_tui' not in names
    assert {'create_contour','render_view','close_model'}<=names
