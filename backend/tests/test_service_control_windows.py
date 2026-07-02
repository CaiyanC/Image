from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "deploy"
    / "scripts"
    / "service_control_windows.ps1"
)


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_backend_stop_uses_best_effort_process_cleanup_and_final_port_gate():
    script = _script_text()

    assert "function Stop-ProcessTreeBestEffort" in script
    assert "function Stop-BackendListeners" in script
    assert "Wait-PortReleased -Port $ProdBackendPort" in script
    assert "backend port $ProdBackendPort is clear" in script


def test_backend_stop_rejects_unresolved_or_unexpected_remaining_listener():
    script = _script_text()

    assert "cannot be resolved after stop attempt" in script
    assert "is not a production backend after stop attempt" in script
    assert "Test-ProductionBackendProcess" in script


def test_deploy_backend_keeps_runtime_identity_and_commit_gates():
    script = _script_text()

    assert "Test-BackendListenerIntegrity" in script
    assert "Test-BackendHealthEndpoints" in script
    assert '/api/health/live"' in script
    assert "backend health/live/ready check failed after deploy restart" in script
    assert "Test-BackendVersion -Commit $Commit" in script
    assert "backend version pid cannot be resolved" in script
    assert "backend commit mismatch" in script
    assert "backend code_root mismatch" in script
    assert "backend cwd mismatch" in script


def test_frontend_starts_production_dist_with_persistent_logs():
    script = _script_text()

    assert '$ProdFrontendDir = Join-Path $RepoRoot "frontend"' in script
    assert '$ProdFrontendOutLog = Join-Path $ProdLogDir "frontend.out.log"' in script
    assert '$ProdFrontendErrLog = Join-Path $ProdLogDir "frontend.err.log"' in script
    assert 'Test-Path (Join-Path $ProdFrontendDir "dist\\index.html")' in script
    assert 'Start-Process -FilePath "npm.cmd"' in script
    assert '@("run", "serve:prod")' in script
    assert "-WorkingDirectory $ProdFrontendDir" in script
    assert "-RedirectStandardOutput $ProdFrontendOutLog" in script
    assert "-RedirectStandardError $ProdFrontendErrLog" in script
    assert "http://127.0.0.1:$ProdFrontendPort" in script
    assert "5276" not in script
    assert "8001" not in script
