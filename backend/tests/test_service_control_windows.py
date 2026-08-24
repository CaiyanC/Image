from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE_SCRIPT = ROOT / "deploy" / "scripts" / "service_control_windows.ps1"
HEALTH_SCRIPT = ROOT / "deploy" / "scripts" / "health_check_windows.ps1"
PREPARE_SCRIPT = ROOT / "deploy" / "scripts" / "prepare_production_release.ps1"
START_PROD = ROOT / "start-prod.bat"
STOP_PROD = ROOT / "stop-prod.bat"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_backend_stop_is_identity_checked_and_has_explicit_legacy_transition():
    script = _text(SERVICE_SCRIPT)

    assert "function Stop-ProcessTreeBestEffort" in script
    assert "function Stop-BackendListeners" in script
    assert "Wait-PortReleased -Port $ProdBackendPort" in script
    assert "Test-ProductionBackendProcess" in script
    assert "[switch]$AllowLegacySharedProcess" in script
    assert "$executable -eq $ProdPython" in script
    assert "$executable -eq $LegacyPython" in script
    assert "multiprocessing.spawn" in script


def test_all_action_enforces_release_identity_health_and_commit_gates():
    script = _text(SERVICE_SCRIPT)

    assert "$ProdPython" in script
    assert "$ExpectedBackendRoot" in script
    assert "Test-BackendListenerIntegrity" in script
    assert "Test-BackendHealthEndpoints" in script
    assert '/api/health/live"' in script
    assert "Test-BackendVersion -Commit $ExpectedCommit" in script
    assert "backend commit mismatch" in script
    assert "backend environment mismatch" in script
    assert '$env:APP_BRANCH = "master"' in script


def test_worker_and_frontend_use_release_code_with_persistent_runtime_paths():
    script = _text(SERVICE_SCRIPT)

    assert '$ProdLogDir = Join-Path $RuntimeRoot "logs\\prod"' in script
    assert '$ProdUploadDir = [System.IO.Path]::GetFullPath((Join-Path $RuntimeRoot "backend\\uploads"))' in script
    assert '$env:CAIYAN_RUNTIME_UPLOAD_DIR = $ProdUploadDir' in script
    assert '$cmd -like "*$ExpectedBackendRoot*"' in script
    assert '$executable -eq $ProdPython' in script
    assert '$ProdFrontendDir = Join-Path $RepoRoot "frontend"' in script
    assert '$ProdServeCommand' in script
    assert '@("-s", "dist", "-l", "$ProdFrontendPort", "-c", "serve.json")' in script
    assert "5276" not in script
    assert "8001" not in script


def test_release_preparation_requires_master_clean_tree_and_detached_worktree():
    script = _text(PREPARE_SCRIPT)

    assert '$branch -ne "master"' in script
    assert "git -C $SourceRepo diff --quiet" in script
    assert "git -C $SourceRepo diff --cached --quiet" in script
    assert "worktree add --detach" in script
    assert "npm" in script and "ci" in script and "run build" in script
    assert "backend\\runtime\\prod-venv" in script
    assert "production-release.json" in script


def test_start_and_stop_resolve_the_immutable_release_pointer():
    start_script = _text(START_PROD)
    stop_script = _text(STOP_PROD)

    assert "prepare_production_release.ps1" in start_script
    assert '-RepoRoot "%RELEASE_ROOT%"' in start_script
    assert '-ExpectedCommit "%RELEASE_COMMIT%"' in start_script
    assert "-AllowLegacySharedProcess" in start_script
    assert "production-release.json" in stop_script
    assert '-RepoRoot "%ACTIVE_RELEASE_ROOT%"' in stop_script
    assert '-ExpectedCommit "%ACTIVE_RELEASE_COMMIT%"' in stop_script


def test_health_watchdog_recovers_the_active_release_not_the_mutable_source_tree():
    script = _text(HEALTH_SCRIPT)

    assert "function Get-ActiveProductionRelease" in script
    assert "production-release.json" in script
    assert "function Test-BackendReleaseVersion" in script
    assert '"-RepoRoot", $release.root' in script
    assert '"-ExpectedCommit", $release.commit' in script
    assert "$releaseVersion.ok" in script
