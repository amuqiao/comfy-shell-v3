import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.comfy import models, process, versions
from app.comfy.paths import comfy_paths
from app.comfy.workspace import init_workspace
from app.core.config import AppSettings
from app.core.exceptions import AppError
from app.main import create_app


def comfy_settings(tmp_path: Path, repo_url: str | None = None) -> AppSettings:
    return AppSettings(
        runtime={"app_env": "local"},
        security={"service_api_key": "test-service-key", "disable_auth": True},
        storage={"backend": "disabled"},
        observability={"access_log_enabled": False},
        comfy={
            "workspace_dir": str(tmp_path / "workspace"),
            "repo_url": repo_url or str(tmp_path / "repo"),
            "host": "127.0.0.1",
            "port": 8188,
            "python": "python",
            "hf_endpoint": "https://huggingface.co",
        },
    )


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    (repo / "main.py").write_text("print('comfy test')\n", encoding="utf-8")
    git(repo, "add", "main.py")
    git(repo, "commit", "-m", "initial")
    commit = git(repo, "rev-parse", "HEAD")
    return repo, commit


def test_workspace_init_creates_runtime_layout(tmp_path):
    settings = comfy_settings(tmp_path)
    paths = init_workspace(settings)

    assert paths.sources.is_dir()
    assert paths.versions.is_dir()
    assert paths.models.is_dir()
    assert paths.logs.is_dir()
    assert paths.run.is_dir()
    assert json.loads(paths.state_file.read_text(encoding="utf-8")) == {}


def test_fetch_use_version_links_current_and_models(tmp_path):
    repo, commit = make_repo(tmp_path)
    settings = comfy_settings(tmp_path, str(repo))

    fetched = versions.fetch_version(settings, "HEAD")
    assert fetched["commit"] == commit
    assert fetched["name"].startswith("ComfyUI-HEAD-")

    current = versions.use_version(settings, fetched["name"])
    paths = comfy_paths(settings)

    assert current["commit"] == commit
    assert paths.current.is_symlink()
    assert paths.current.resolve() == paths.versions / fetched["name"]
    assert (paths.current / "models").is_symlink()
    assert (paths.current / "models").resolve() == paths.models.resolve()
    state = json.loads(paths.state_file.read_text(encoding="utf-8"))
    assert state["current_version"] == fetched["name"]
    assert state["current_commit"] == commit


def test_link_models_refuses_existing_real_models_dir(tmp_path):
    repo, _commit = make_repo(tmp_path)
    settings = comfy_settings(tmp_path, str(repo))
    fetched = versions.fetch_version(settings, "HEAD")
    version_dir = comfy_paths(settings).versions / fetched["name"]
    (version_dir / "models").mkdir()

    with pytest.raises(AppError) as exc:
        versions.use_version(settings, fetched["name"])

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["reason"] == "models_path_is_not_symlink"


def test_list_models_returns_workspace_files(tmp_path):
    settings = comfy_settings(tmp_path)
    paths = init_workspace(settings)
    model_file = paths.models / "checkpoints" / "demo.safetensors"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(b"demo")

    assert models.list_models(settings) == [{"path": "checkpoints/demo.safetensors", "size": 4}]


def test_stop_does_not_kill_unowned_pid(tmp_path):
    settings = comfy_settings(tmp_path)
    paths = init_workspace(settings)
    sleeper = subprocess.Popen(["sleep", "5"])
    try:
        paths.comfyui_pid_file.write_text(f"{sleeper.pid}\n", encoding="utf-8")
        paths.comfyui_meta_file.write_text(
            json.dumps(
                {
                    "pid": sleeper.pid,
                    "service": "comfyui",
                    "cwd": str(paths.root),
                    "workspace": str(paths.root),
                }
            ),
            encoding="utf-8",
        )

        result = process.stop(settings)

        assert result["running"] is False
        assert not paths.comfyui_pid_file.exists()
        assert sleeper.poll() is None
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)


def test_comfy_api_workspace_and_status(tmp_path):
    settings = comfy_settings(tmp_path)
    app = create_app(settings)

    with TestClient(app) as client:
        init_response = client.post("/v1/comfy/workspace/init")
        status_response = client.get("/v1/comfy/service/status")

    assert init_response.status_code == 200
    assert init_response.json()["data"]["data"]["workspace"] == str(tmp_path / "workspace")
    assert status_response.status_code == 200
    assert status_response.json()["data"]["data"]["running"] is False
