from fastapi.testclient import TestClient

from app import main


def test_public_health_version_returns_only_non_sensitive_identity(monkeypatch):
    monkeypatch.setattr(
        main,
        "STARTUP_RUNTIME_INFO",
        {
            "version": "1.0.0",
            "startup_commit": "startup-commit-123",
            "startup_branch": "dev",
            "code_root": main.BACKEND_ROOT,
            "cwd": "D:/CaiYan/Image-n065-audit/backend",
            "python_executable": "python.exe",
            "pid": 4321,
            "started_at": "2026-07-04T00:00:00+00:00",
            "env": "dev",
            "backend_port": 8001,
        },
    )
    response = TestClient(main.app).get("/api/health/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "1.0.0"
    assert payload["commit"] == "startup-commit-123"
    assert payload["env"] == "dev"
    assert set(payload) == {"version", "commit", "env"}


def test_admin_runtime_payload_keeps_detailed_diagnostics(monkeypatch):
    monkeypatch.setattr(main, "_get_current_git_head", lambda: "current-head-456")
    monkeypatch.setattr(main, "_get_current_git_branch", lambda: "dev")
    payload = main._runtime_version_payload()
    assert payload["current_git_head"] == "current-head-456"
    assert payload["current_git_branch"] == "dev"
    assert payload["code_root"]
    assert payload["pid"]


def test_runtime_version_payload_keeps_startup_commit_when_current_head_changes(monkeypatch):
    monkeypatch.setattr(
        main,
        "STARTUP_RUNTIME_INFO",
        {
            "version": "1.0.0",
            "startup_commit": "startup-old-head",
            "startup_branch": "dev",
            "code_root": main.BACKEND_ROOT,
            "cwd": "D:/CaiYan/Image-n065-audit/backend",
            "python_executable": "python.exe",
            "pid": 9876,
            "started_at": "2026-07-04T01:23:45+00:00",
            "env": "dev",
            "backend_port": 8001,
        },
    )
    monkeypatch.setattr(main, "_get_current_git_head", lambda: "current-new-head")
    monkeypatch.setattr(main, "_get_current_git_branch", lambda: "feature/test-head")

    payload = main._runtime_version_payload()

    assert payload["startup_commit"] == "startup-old-head"
    assert payload["current_git_head"] == "current-new-head"
    assert payload["commit"] == "startup-old-head"
    assert payload["commit_source"] == "startup_commit"
    assert payload["branch"] == "dev"
    assert payload["current_git_branch"] == "feature/test-head"
    assert payload["started_at"] == "2026-07-04T01:23:45+00:00"
