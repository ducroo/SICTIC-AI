import os
import asyncio
import inspect
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Import once so lib.env loads any local .env before tests force safe values.
import lib.env  # noqa: E402,F401

os.environ["REPO_DIR"] = str(REPO_ROOT)
os.environ["WORKSPACE_DIR"] = str(REPO_ROOT / "skills")
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["STORAGE_PATH"] = str(REPO_ROOT / ".pytest-storage")
os.environ["LLM_MODEL"] = "ollama/test_model:1b"
os.environ["LLM_BASE_URL"] = "http://localhost:11434"
os.environ["LLM_API_KEY"] = ""
os.environ["EMBEDDING_MODEL"] = "ollama/test-embedding:8b"
os.environ["EMBEDDING_BASE_URL"] = "http://localhost:11434"
os.environ["EMBEDDING_API_KEY"] = ""
os.environ["DEFAULT_LLM"] = "ollama/test_model:1b"
os.environ["DEFAULT_VLM"] = "ollama/test-vlm:1b"
os.environ["DEFAULT_EMBEDDINGS"] = "ollama/test-embedding:8b"
os.environ["OLLAMA_HOST"] = "http://localhost:11434"
os.environ["QDRANT_HOST"] = "http://localhost:6333"
os.environ["OLLAMA_NUM_CTX"] = "4096"
os.environ["OLLAMA_NUM_CTX_MAX"] = "8192"
os.environ["APIFY_KEY"] = "test-apify-key"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SICTIC_RUN_LIVE_SMOKE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live smoke tests require SICTIC_RUN_LIVE_SMOKE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: run async test functions with asyncio.run")
    config.addinivalue_line("markers", "live: opt-in tests that require live local services or Google-backed storage")


def pytest_pyfunc_call(pyfuncitem):
    if "asyncio" not in pyfuncitem.keywords:
        return None
    testfunction = pyfuncitem.obj
    if not inspect.iscoroutinefunction(testfunction):
        return None
    funcargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(testfunction(**funcargs))
    return True


@pytest.fixture
def mock_env(monkeypatch, tmp_path):
    """
    Sets up a safe, isolated environment for tests.
    It overrides REPOSITORY_DIR and WORKSPACE_DIR to point to a temporary directory
    so that no real files are ever affected during unit testing.
    """
    # Create mock directories
    repository_dir_mock = tmp_path / "repository_dir_mock"
    repository_dir_mock.mkdir()
    
    workspace_mock = tmp_path / "workspace_mock"
    workspace_mock.mkdir()
    
    # Override environment variables
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("STORAGE_PATH", str(repository_dir_mock))
    monkeypatch.setenv("REPO_DIR", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("WORKSPACE_DIR", str(workspace_mock))
    monkeypatch.setenv("LLM_MODEL", "ollama/test_model:1b")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_MODEL", "ollama/test-embedding:8b")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    monkeypatch.setenv("DEFAULT_LLM", "ollama/test_model:1b")
    monkeypatch.setenv("DEFAULT_VLM", "ollama/test-vlm:1b")
    monkeypatch.setenv("DEFAULT_EMBEDDINGS", "ollama/test-embedding:8b")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("QDRANT_HOST", "http://localhost:6333")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "4096")
    monkeypatch.setenv("OLLAMA_NUM_CTX_MAX", "8192")

    from lib.storage import reset_storage_singleton
    reset_storage_singleton()
    
    return {
        "repository_dir": repository_dir_mock,
        "workspace_dir": workspace_mock,
        "tmp_path": tmp_path
    }
