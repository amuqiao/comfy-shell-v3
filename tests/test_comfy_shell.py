import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.comfy import archives, envs, models, process, versions
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
            "repo_url": repo_url or "https://github.com/Comfy-Org/ComfyUI.git",
            "host": "127.0.0.1",
            "port": 8188,
            "python": "python",
            "hf_endpoint": "https://huggingface.co",
        },
    )


def make_archive(tmp_path: Path) -> tuple[Path, str]:
    archive_path = tmp_path / "ComfyUI-0.36.0.zip"
    commit = "ee71d5c4993f29086b27fde1629a945ae48425bf"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.comment = commit.encode("utf-8")
        archive.writestr("ComfyUI-0.36.0/main.py", "print('comfy test')\n")
        archive.writestr("ComfyUI-0.36.0/models/configs/demo.yaml", "model: demo\n")
        archive.writestr("ComfyUI-0.36.0/models/checkpoints/put_checkpoints_here", "")
    return archive_path, commit


@pytest.fixture
def fake_comfy_archive(tmp_path, monkeypatch):
    archive_path, commit = make_archive(tmp_path)

    def download_archive(repo_url: str, ref: str, target: Path) -> None:
        assert repo_url == "https://github.com/Comfy-Org/ComfyUI.git"
        assert ref == "v0.36.0"
        shutil.copyfile(archive_path, target)

    monkeypatch.setattr(archives, "download_github_archive", download_archive)
    return commit


@pytest.fixture
def fake_comfy_env(monkeypatch):
    def prepare_env(settings, paths, *, version_name: str, version_dir: Path):
        env_dir = paths.envs / version_name
        python = env_dir / "bin" / "python"
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
        python.chmod(0o755)
        return {
            "version": version_name,
            "env_path": str(env_dir),
            "python": str(python),
            "requirements": str(version_dir / "requirements.txt"),
            "pypi_index_url": settings.comfy.pypi_index_url,
            "torch_index_url": settings.comfy.torch_index_url,
            "torch_packages": settings.comfy.torch_packages,
            "updated_at": "2026-09-20T00:00:00Z",
        }

    monkeypatch.setattr(envs, "prepare_env_unlocked", prepare_env)


def test_workspace_init_creates_runtime_layout(tmp_path):
    settings = comfy_settings(tmp_path)
    paths = init_workspace(settings)

    assert paths.versions.is_dir()
    assert paths.envs.is_dir()
    assert paths.models.is_dir()
    assert paths.logs.is_dir()
    assert paths.run.is_dir()
    assert json.loads(paths.state_file.read_text(encoding="utf-8")) == {}


def test_fetch_use_version_links_current_models_and_env(tmp_path, fake_comfy_archive, fake_comfy_env):
    commit = fake_comfy_archive
    settings = comfy_settings(tmp_path)

    fetched = versions.fetch_version(settings, "v0.36.0")
    assert fetched["commit"] == commit
    assert fetched["name"].startswith("ComfyUI-v0.36.0-")

    current = versions.use_version(settings, fetched["name"])
    paths = comfy_paths(settings)

    assert current["commit"] == commit
    assert paths.current.is_symlink()
    assert paths.current.resolve() == paths.versions / fetched["name"]
    assert paths.current_env.is_symlink()
    assert paths.current_env.resolve() == paths.envs / fetched["name"]
    assert (paths.current_env / "bin" / "python").is_file()
    assert (paths.current / "models").is_symlink()
    assert (paths.current / "models").resolve() == paths.models.resolve()
    assert (paths.models / "configs" / "demo.yaml").read_text(encoding="utf-8") == "model: demo\n"
    assert (paths.models / "checkpoints" / "put_checkpoints_here").is_file()
    state = json.loads(paths.state_file.read_text(encoding="utf-8"))
    assert state["current_version"] == fetched["name"]
    assert state["current_commit"] == commit


def test_link_models_refuses_seed_file_conflict(tmp_path, fake_comfy_archive, fake_comfy_env):
    settings = comfy_settings(tmp_path)
    fetched = versions.fetch_version(settings, "v0.36.0")
    paths = comfy_paths(settings)
    conflict = paths.models / "configs" / "demo.yaml"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("model: different\n", encoding="utf-8")

    with pytest.raises(AppError) as exc:
        versions.use_version(settings, fetched["name"])

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["reason"] == "models_seed_conflict"


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
