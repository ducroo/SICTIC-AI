import os
import pytest
from pathlib import Path

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
    monkeypatch.setenv("WORKSPACE_DIR", str(workspace_mock))
    monkeypatch.setenv("DEFAULT_LLM", "ollama/test_model:1b")
    
    return {
        "repository_dir": repository_dir_mock,
        "workspace_dir": workspace_mock,
        "tmp_path": tmp_path
    }
