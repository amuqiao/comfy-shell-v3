import json
import io
import shutil
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.comfy import archives, catalog, envs, models, process, runtimes, versions
from app.comfy.lock import WorkspaceLock
from app.comfy.paths import comfy_paths
from app.comfy.workspace import init_workspace
from app.core.config import AppSettings
from app.core.exceptions import AppError
from app.main import create_app

ROOT_DIR = Path(__file__).resolve().parents[1]


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


@pytest.fixture
def fake_runtime_source(tmp_path):
    source = tmp_path / "source"
    comfy_dir = source / "ComfyUI"
    venv_dir = source / ".venv"
    (comfy_dir / "models" / "configs").mkdir(parents=True)
    (comfy_dir / "main.py").write_text("print('runtime')\n", encoding="utf-8")
    (comfy_dir / "models" / "configs" / "demo.yaml").write_text("model: runtime\n", encoding="utf-8")
    python = venv_dir / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    python.chmod(0o755)
    return comfy_dir, venv_dir


@pytest.fixture
def fake_runtime_copy(monkeypatch):
    def copy_tree(source: Path, target: Path) -> None:
        shutil.copytree(source, target)

    monkeypatch.setattr(runtimes, "copy_tree", copy_tree)


def write_plugin_catalog(catalog_dir: Path, plugin_body: str) -> None:
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    (catalog_dir / "models" / "demo.toml").write_text(
        """
schema_version = 1

[models.demo_model]
name = "demo_model"
summary = "测试模型。"
kind = "other"
source = "local"
path = "/tmp/demo_model.safetensors"
filename = "demo_model.safetensors"
target = "checkpoints"
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(plugin_body, encoding="utf-8")
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["demo_model"]
""",
        encoding="utf-8",
    )


def write_model_lifecycle_catalog(catalog_dir: Path, source_model: Path) -> None:
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    (catalog_dir / "models" / "demo.toml").write_text(
        f"""
schema_version = 1

[models.exists_model]
name = "exists_model"
summary = "已存在模型。"
kind = "other"
source = "local"
path = "{source_model}"
filename = "exists.safetensors"
target = "checkpoints"
size_hint = "4B"
size_bytes = 4

[models.missing_model]
name = "missing_model"
summary = "缺失模型。"
kind = "other"
source = "url"
url = "https://hf-mirror.com/org/repo/resolve/main/missing.safetensors"
filename = "missing.safetensors"
target = "checkpoints"
size_hint = "10B"
size_bytes = 10

[models.downloading_model]
name = "downloading_model"
summary = "下载中的模型。"
kind = "other"
source = "url"
url = "https://hf-mirror.com/org/repo/resolve/main/downloading.safetensors"
filename = "downloading.safetensors"
target = "checkpoints"

[models.bad_size_model]
name = "bad_size_model"
summary = "大小不一致模型。"
kind = "other"
source = "url"
url = "https://hf-mirror.com/org/repo/resolve/main/bad-size.safetensors"
filename = "bad-size.safetensors"
target = "checkpoints"
size_bytes = 99
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(
        """
schema_version = 1

[plugins.demo_plugin]
name = "demo_plugin"
summary = "测试插件。"
source = "manual"
install_hint = "manual"
target = "custom_nodes/demo_plugin"
scope = "per-runtime"
status = "planned"
""",
        encoding="utf-8",
    )
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["exists_model", "missing_model", "downloading_model", "bad_size_model"]
""",
        encoding="utf-8",
    )


def test_workspace_init_creates_runtime_layout(tmp_path):
    settings = comfy_settings(tmp_path)
    paths = init_workspace(settings)

    assert paths.versions.is_dir()
    assert paths.envs.is_dir()
    assert paths.runtimes.is_dir()
    assert paths.staging.is_dir()
    assert paths.models.is_dir()
    assert paths.logs.is_dir()
    assert paths.run.is_dir()
    assert json.loads(paths.state_file.read_text(encoding="utf-8")) == {}


def test_catalog_validates_example_workflow():
    catalog_dir = ROOT_DIR / "catalog"

    summary = catalog.catalog_summary(catalog_dir)
    workflow = catalog.show_workflow("video_wan2_2_14b_animate", catalog_dir)
    plugin = catalog.show_plugin("comfyui_manager", catalog_dir)

    assert summary == {"models": 6, "workflows": 1, "plugins": 14}
    assert workflow["name"] == "video_wan2_2_14B_animate"
    assert workflow["workflow_file"] == "workflow-files/video_wan2_2_14b_animate.json"
    assert plugin["target"] == "custom_nodes/ComfyUI-Manager"
    assert [item["id"] for item in workflow["resolved_models"]] == [
        "lightx2v_i2v_14b_480p_cfg_step_distill_rank64_bf16",
        "wananimate_relight_lora_fp16",
        "wan_2_1_vae",
        "umt5_xxl_fp8_e4m3fn_scaled",
        "wan2_2_animate_14b_fp8_e4m3fn_scaled_kj",
        "clip_vision_h",
    ]


def test_catalog_download_workflow_uses_explicit_models_dir(tmp_path):
    catalog_dir = tmp_path / "catalog"
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    source_model = tmp_path / "source.safetensors"
    source_model.write_text("model-data", encoding="utf-8")
    (catalog_dir / "models" / "demo.toml").write_text(
        f"""
schema_version = 1

[models.demo_model]
name = "demo_model"
summary = "测试模型。"
kind = "other"
source = "local"
path = "{source_model}"
filename = "demo_model.safetensors"
target = "checkpoints"
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(
        """
schema_version = 1

[plugins.demo_plugin]
name = "demo_plugin"
summary = "测试插件。"
source = "manual"
install_hint = "manual"
target = "custom_nodes/demo_plugin"
scope = "per-runtime"
status = "planned"
""",
        encoding="utf-8",
    )
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["demo_model"]
""",
        encoding="utf-8",
    )
    settings = comfy_settings(tmp_path)
    models_dir = tmp_path / "external-models"

    result = catalog.download_workflow_models(
        settings,
        "demo_workflow",
        models_dir=str(models_dir),
        catalog_dir=catalog_dir,
    )

    target = models_dir / "checkpoints" / "demo_model.safetensors"
    assert result["workflow"] == "demo_workflow"
    assert result["items"][0]["status"] == "downloaded"
    assert result["items"][0]["source"] == "local"
    assert result["items"][0]["source_path"] == str(source_model)
    assert result["items"][0]["filename"] == "demo_model.safetensors"
    assert result["items"][0]["target_path"] == "checkpoints/demo_model.safetensors"
    assert target.read_text(encoding="utf-8") == "model-data"


def test_catalog_inspect_workflow_explains_model_states(tmp_path):
    catalog_dir = tmp_path / "catalog"
    source_model = tmp_path / "source.safetensors"
    source_model.write_text("data", encoding="utf-8")
    write_model_lifecycle_catalog(catalog_dir, source_model)
    settings = comfy_settings(tmp_path)
    models_dir = tmp_path / "models"
    (models_dir / "checkpoints").mkdir(parents=True)
    (models_dir / "checkpoints" / "exists.safetensors").write_text("data", encoding="utf-8")
    (models_dir / "checkpoints" / ".downloading.safetensors.tmp").write_text("partial", encoding="utf-8")
    (models_dir / "checkpoints" / "bad-size.safetensors").write_text("bad", encoding="utf-8")

    result = catalog.inspect_workflow_models(
        settings,
        "demo_workflow",
        models_dir=str(models_dir),
        catalog_dir=catalog_dir,
    )

    assert result["summary"] == {
        "exists": 1,
        "missing": 1,
        "downloading": 1,
        "size_mismatch": 1,
        "sha_mismatch": 0,
        "path_conflict": 0,
        "total": 4,
    }
    by_id = {item["id"]: item for item in result["items"]}
    assert by_id["exists_model"]["status"] == "exists"
    assert by_id["exists_model"]["reason"] == "final_file_exists"
    assert by_id["exists_model"]["local_size"] == 4
    assert by_id["exists_model"]["size_bytes"] == 4
    assert by_id["missing_model"]["status"] == "missing"
    assert by_id["missing_model"]["reason"] == "final_file_missing"
    assert by_id["downloading_model"]["status"] == "downloading"
    assert by_id["downloading_model"]["reason"] == "temporary_download_file_exists"
    assert by_id["downloading_model"]["tmp_files"] == [str(models_dir / "checkpoints" / ".downloading.safetensors.tmp")]
    assert by_id["bad_size_model"]["status"] == "size_mismatch"
    assert by_id["bad_size_model"]["reason"] == "local_size_does_not_match_size_bytes"
    assert by_id["bad_size_model"]["local_size"] == 3
    assert by_id["bad_size_model"]["target_path"] == "checkpoints/bad-size.safetensors"


def test_catalog_missing_workflow_returns_actionable_model_ids(tmp_path):
    catalog_dir = tmp_path / "catalog"
    source_model = tmp_path / "source.safetensors"
    source_model.write_text("data", encoding="utf-8")
    write_model_lifecycle_catalog(catalog_dir, source_model)
    settings = comfy_settings(tmp_path)
    models_dir = tmp_path / "models"
    (models_dir / "checkpoints").mkdir(parents=True)
    (models_dir / "checkpoints" / "exists.safetensors").write_text("data", encoding="utf-8")
    (models_dir / "checkpoints" / ".downloading.safetensors.tmp").write_text("partial", encoding="utf-8")
    (models_dir / "checkpoints" / "bad-size.safetensors").write_text("bad", encoding="utf-8")

    result = catalog.missing_workflow_models(
        settings,
        "demo_workflow",
        models_dir=str(models_dir),
        catalog_dir=catalog_dir,
    )

    assert result["model_ids"] == ["missing_model", "bad_size_model"]
    assert [item["status"] for item in result["items"]] == ["missing", "size_mismatch"]


def test_catalog_probe_model_reports_link_metadata(tmp_path, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    source_model = tmp_path / "source.safetensors"
    source_model.write_text("data", encoding="utf-8")
    write_model_lifecycle_catalog(catalog_dir, source_model)

    def fake_probe_url(url: str) -> dict[str, object]:
        return {
            "probe_status": "ok",
            "http_status": 200,
            "content_length": 10,
            "effective_url": f"{url}?resolved=1",
            "etag": "demo-etag",
            "error": None,
        }

    monkeypatch.setattr(catalog, "probe_url", fake_probe_url)

    result = catalog.probe_model_by_id(comfy_settings(tmp_path), "missing_model", catalog_dir=catalog_dir)

    assert result["id"] == "missing_model"
    assert result["path"] is None
    assert result["probe_status"] == "ok"
    assert result["http_status"] == 200
    assert result["content_length"] == 10
    assert result["size_bytes"] == 10
    assert result["size_matches"] is True
    assert result["suggested_size_bytes"] == 10
    assert result["suggested_size_hint"] == "10B"
    assert result["effective_url"].endswith("?resolved=1")


def test_catalog_download_rejects_existing_size_mismatch(tmp_path):
    catalog_dir = tmp_path / "catalog"
    source_model = tmp_path / "source.safetensors"
    source_model.write_text("data", encoding="utf-8")
    write_model_lifecycle_catalog(catalog_dir, source_model)
    settings = comfy_settings(tmp_path)
    models_dir = tmp_path / "models"
    target = models_dir / "checkpoints" / "bad-size.safetensors"
    target.parent.mkdir(parents=True)
    target.write_text("bad", encoding="utf-8")

    with pytest.raises(AppError) as exc:
        catalog.download_model_by_id(settings, "bad_size_model", models_dir=str(models_dir), catalog_dir=catalog_dir)

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["reason"] == "size_mismatch"
    assert exc.value.details["actual"] == 3
    assert exc.value.details["expected"] == 99


def test_catalog_download_url_removes_temp_and_keeps_final_missing_on_size_mismatch(tmp_path, monkeypatch):
    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(catalog, "urlopen", lambda request: FakeResponse(b"bad"))
    destination = tmp_path / "models" / "checkpoints" / "demo.safetensors"
    destination.parent.mkdir(parents=True)

    with pytest.raises(AppError) as exc:
        catalog.download_url("https://example.com/demo.safetensors", destination, size_bytes=99)

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["reason"] == "size_mismatch"
    assert not destination.exists()
    assert not (destination.parent / ".demo.safetensors.tmp").exists()


def test_catalog_copy_local_removes_temp_and_keeps_final_missing_on_size_mismatch(tmp_path):
    source = tmp_path / "source.safetensors"
    source.write_text("bad", encoding="utf-8")
    destination = tmp_path / "models" / "checkpoints" / "demo.safetensors"
    destination.parent.mkdir(parents=True)

    with pytest.raises(AppError) as exc:
        catalog.copy_local_model(source, destination, size_bytes=99)

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["reason"] == "size_mismatch"
    assert not destination.exists()
    assert not (destination.parent / ".demo.safetensors.tmp").exists()


def test_catalog_probe_failed_source_reports_unknown_size_check(tmp_path):
    catalog_dir = tmp_path / "catalog"
    missing_source = tmp_path / "missing.safetensors"
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    (catalog_dir / "models" / "demo.toml").write_text(
        f"""
schema_version = 1

[models.demo_model]
name = "demo_model"
summary = "缺失本地来源模型。"
kind = "other"
source = "local"
path = "{missing_source}"
filename = "demo_model.safetensors"
target = "checkpoints"
size_bytes = 10
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(
        """
schema_version = 1

[plugins.demo_plugin]
name = "demo_plugin"
summary = "测试插件。"
source = "manual"
install_hint = "manual"
target = "custom_nodes/demo_plugin"
scope = "per-runtime"
status = "planned"
""",
        encoding="utf-8",
    )
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["demo_model"]
""",
        encoding="utf-8",
    )

    result = catalog.probe_model_by_id(comfy_settings(tmp_path), "demo_model", catalog_dir=catalog_dir)

    assert result["probe_status"] == "failed"
    assert result["size_matches"] is None
    assert result["size_check_status"] == "unknown"
    assert result["suggested_size_bytes"] is None


def test_catalog_download_url_source_uses_direct_url(tmp_path, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    (catalog_dir / "models" / "demo.toml").write_text(
        """
schema_version = 1

[models.demo_model]
name = "demo_model"
summary = "测试 hf-mirror 直链模型。"
kind = "other"
source = "url"
url = "https://hf-mirror.com/org/repo/resolve/main/demo_model.safetensors"
filename = "demo_model.safetensors"
target = "checkpoints"
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(
        """
schema_version = 1

[plugins.demo_plugin]
name = "demo_plugin"
summary = "测试插件。"
source = "manual"
install_hint = "manual"
target = "custom_nodes/demo_plugin"
scope = "per-runtime"
status = "planned"
""",
        encoding="utf-8",
    )
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["demo_model"]
""",
        encoding="utf-8",
    )
    calls: list[tuple[str, Path]] = []

    def fake_download_url(url: str, destination: Path, **kwargs) -> None:
        calls.append((url, destination))
        destination.write_text("url-model", encoding="utf-8")

    monkeypatch.setattr(catalog, "download_url", fake_download_url)
    settings = comfy_settings(tmp_path)
    models_dir = tmp_path / "external-models"

    result = catalog.download_model_by_id(settings, "demo_model", models_dir=str(models_dir), catalog_dir=catalog_dir)

    target = models_dir / "checkpoints" / "demo_model.safetensors"
    assert result["status"] == "downloaded"
    assert result["source"] == "url"
    assert result["url"] == "https://hf-mirror.com/org/repo/resolve/main/demo_model.safetensors"
    assert result["filename"] == "demo_model.safetensors"
    assert result["target_path"] == "checkpoints/demo_model.safetensors"
    assert calls == [("https://hf-mirror.com/org/repo/resolve/main/demo_model.safetensors", target)]
    assert target.read_text(encoding="utf-8") == "url-model"


def test_catalog_download_rejects_duplicate_download_for_same_target(tmp_path, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    (catalog_dir / "models" / "demo.toml").write_text(
        """
schema_version = 1

[models.demo_model]
name = "demo_model"
summary = "测试重复下载锁。"
kind = "other"
source = "url"
url = "https://hf-mirror.com/org/repo/resolve/main/demo_model.safetensors"
filename = "demo_model.safetensors"
target = "checkpoints"
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(
        """
schema_version = 1

[plugins.demo_plugin]
name = "demo_plugin"
summary = "测试插件。"
source = "manual"
install_hint = "manual"
target = "custom_nodes/demo_plugin"
scope = "per-runtime"
status = "planned"
""",
        encoding="utf-8",
    )
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["demo_model"]
""",
        encoding="utf-8",
    )
    calls: list[tuple[str, Path]] = []

    def fake_download_url(url: str, destination: Path, **kwargs) -> None:
        calls.append((url, destination))
        destination.write_text("url-model", encoding="utf-8")

    monkeypatch.setattr(catalog, "download_url", fake_download_url)
    settings = comfy_settings(tmp_path)
    models_dir = tmp_path / "external-models"
    destination = models_dir / "checkpoints" / "demo_model.safetensors"
    lock_file = catalog.model_download_lock_path(models_dir, destination)

    with WorkspaceLock(lock_file):
        with pytest.raises(AppError) as exc:
            catalog.download_model_by_id(settings, "demo_model", models_dir=str(models_dir), catalog_dir=catalog_dir)

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["resource"] == "model"
    assert exc.value.details["id"] == "demo_model"
    assert exc.value.details["reason"] == "model_download_in_progress"
    assert exc.value.details["path"] == str(destination)
    assert exc.value.details["lock_file"] == str(lock_file)
    assert calls == []


def test_models_hf_download_rejects_duplicate_download_for_same_target(tmp_path, monkeypatch):
    calls = []

    def fake_hf_hub_download(**kwargs):
        calls.append(kwargs)
        target = Path(kwargs["local_dir"]) / kwargs["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("hf-model", encoding="utf-8")
        return str(target)

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(hf_hub_download=fake_hf_hub_download))
    settings = comfy_settings(tmp_path)
    paths = init_workspace(settings)
    lock_file = models.model_download_lock_path(paths.models, "checkpoints", "demo_model.safetensors", "org/repo")

    with WorkspaceLock(lock_file):
        with pytest.raises(AppError) as exc:
            models.hf_download(settings, "org/repo", "demo_model.safetensors", "checkpoints")

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["resource"] == "model"
    assert exc.value.details["reason"] == "model_download_in_progress"
    assert exc.value.details["repo_id"] == "org/repo"
    assert exc.value.details["filename"] == "demo_model.safetensors"
    assert exc.value.details["target"] == "checkpoints"
    assert exc.value.details["lock_file"] == str(lock_file)
    assert calls == []


def test_model_download_lock_path_matches_catalog_and_legacy_entrypoints(tmp_path):
    models_dir = tmp_path / "models"
    assert catalog.model_download_lock_path(models_dir, models_dir / "checkpoints" / "demo.safetensors") == models.model_download_lock_path(
        models_dir,
        "checkpoints",
        "demo.safetensors",
    )
    assert catalog.model_download_lock_path(models_dir, models_dir / "checkpoints" / "nested" / "demo.safetensors") == models.model_download_lock_path(
        models_dir,
        "checkpoints",
        "nested/demo.safetensors",
    )


def test_models_hf_download_rejects_invalid_target_path(tmp_path, monkeypatch):
    calls = []

    def fake_hf_hub_download(**kwargs):
        calls.append(kwargs)
        return "/tmp/should-not-run"

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(hf_hub_download=fake_hf_hub_download))
    settings = comfy_settings(tmp_path)

    with pytest.raises(AppError) as exc:
        models.hf_download(settings, "org/repo", "demo_model.safetensors", "/tmp/checkpoints")

    assert exc.value.code == "REQUEST_INVALID"
    assert exc.value.details["resource"] == "model"
    assert "target must be a relative path" in exc.value.details["error"]
    assert calls == []


def test_models_hf_download_rejects_invalid_filename_path(tmp_path, monkeypatch):
    calls = []

    def fake_hf_hub_download(**kwargs):
        calls.append(kwargs)
        return "/tmp/should-not-run"

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(hf_hub_download=fake_hf_hub_download))
    settings = comfy_settings(tmp_path)

    with pytest.raises(AppError) as exc:
        models.hf_download(settings, "org/repo", "../demo_model.safetensors", "checkpoints")

    assert exc.value.code == "REQUEST_INVALID"
    assert exc.value.details["resource"] == "model"
    assert "filename must be a relative path" in exc.value.details["error"]
    assert calls == []


def test_catalog_download_huggingface_source_uses_hf_endpoint(tmp_path, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    (catalog_dir / "models" / "demo.toml").write_text(
        """
schema_version = 1

[models.demo_model]
name = "demo_model"
summary = "测试 Hugging Face repo 模型。"
kind = "other"
source = "huggingface"
repo_id = "org/repo"
filename = "nested/demo_model.safetensors"
target = "checkpoints"
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(
        """
schema_version = 1

[plugins.demo_plugin]
name = "demo_plugin"
summary = "测试插件。"
source = "manual"
install_hint = "manual"
target = "custom_nodes/demo_plugin"
scope = "per-runtime"
status = "planned"
""",
        encoding="utf-8",
    )
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["demo_model"]
""",
        encoding="utf-8",
    )
    calls: list[tuple[str, str, str, Path]] = []

    def fake_download_huggingface(settings, entry, destination: Path) -> None:
        calls.append((settings.comfy.hf_endpoint, entry.repo_id, entry.filename, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("hf-model", encoding="utf-8")

    monkeypatch.setattr(catalog, "download_huggingface", fake_download_huggingface)
    settings = comfy_settings(tmp_path)
    models_dir = tmp_path / "external-models"

    result = catalog.download_model_by_id(settings, "demo_model", models_dir=str(models_dir), catalog_dir=catalog_dir)

    target = models_dir / "checkpoints" / "nested" / "demo_model.safetensors"
    assert result["status"] == "downloaded"
    assert result["source"] == "huggingface"
    assert result["repo_id"] == "org/repo"
    assert result["hf_endpoint"] == "https://huggingface.co"
    assert result["filename"] == "nested/demo_model.safetensors"
    assert result["target_path"] == "checkpoints/nested/demo_model.safetensors"
    assert calls == [("https://huggingface.co", "org/repo", "nested/demo_model.safetensors", target)]
    assert target.read_text(encoding="utf-8") == "hf-model"


def test_catalog_huggingface_local_dir_matches_nested_filename():
    assert catalog.huggingface_local_dir(
        Path("/workspace/models/checkpoints/demo_model.safetensors"),
        "demo_model.safetensors",
    ) == Path("/workspace/models/checkpoints")
    assert catalog.huggingface_local_dir(
        Path("/workspace/models/checkpoints/nested/demo_model.safetensors"),
        "nested/demo_model.safetensors",
    ) == Path("/workspace/models/checkpoints")


def test_catalog_rejects_unknown_top_level_keys(tmp_path):
    catalog_dir = tmp_path / "catalog"
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    (catalog_dir / "models" / "bad.toml").write_text(
        """
schema_version = 1
unexpected = true

[models.demo_model]
name = "demo_model"
summary = "测试模型。"
kind = "other"
source = "local"
path = "/tmp/demo"
filename = "demo_model.safetensors"
target = "checkpoints"
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(
        """
schema_version = 1

[plugins.demo_plugin]
name = "demo_plugin"
summary = "测试插件。"
source = "manual"
install_hint = "manual"
target = "custom_nodes/demo_plugin"
scope = "per-runtime"
status = "planned"
""",
        encoding="utf-8",
    )
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["demo_model"]
""",
        encoding="utf-8",
    )

    with pytest.raises(AppError) as exc:
        catalog.catalog_summary(catalog_dir)

    assert exc.value.code == "REQUEST_INVALID"
    assert exc.value.details["reason"] == "unknown_top_level_keys"
    assert exc.value.details["keys"] == ["unexpected"]


def test_catalog_rejects_model_filename_path_escape(tmp_path):
    catalog_dir = tmp_path / "catalog"
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    (catalog_dir / "models" / "bad.toml").write_text(
        """
schema_version = 1

[models.demo_model]
name = "demo_model"
summary = "测试模型。"
kind = "other"
source = "url"
url = "https://hf-mirror.com/org/repo/resolve/main/demo_model.safetensors"
filename = "../demo_model.safetensors"
target = "checkpoints"
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(
        """
schema_version = 1

[plugins.demo_plugin]
name = "demo_plugin"
summary = "测试插件。"
source = "manual"
install_hint = "manual"
target = "custom_nodes/demo_plugin"
scope = "per-runtime"
status = "planned"
""",
        encoding="utf-8",
    )
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["demo_model"]
""",
        encoding="utf-8",
    )

    with pytest.raises(AppError) as exc:
        catalog.catalog_summary(catalog_dir)

    assert exc.value.code == "REQUEST_INVALID"
    assert exc.value.details["resource"] == "catalog"


def test_catalog_download_rejects_destination_directory(tmp_path):
    catalog_dir = tmp_path / "catalog"
    (catalog_dir / "models").mkdir(parents=True)
    (catalog_dir / "plugins").mkdir()
    (catalog_dir / "workflows").mkdir()
    source_model = tmp_path / "source.safetensors"
    source_model.write_text("model-data", encoding="utf-8")
    (catalog_dir / "models" / "demo.toml").write_text(
        f"""
schema_version = 1

[models.demo_model]
name = "demo_model"
summary = "测试模型。"
kind = "other"
source = "local"
path = "{source_model}"
filename = "demo_model.safetensors"
target = "checkpoints"
""",
        encoding="utf-8",
    )
    (catalog_dir / "plugins" / "demo.toml").write_text(
        """
schema_version = 1

[plugins.demo_plugin]
name = "demo_plugin"
summary = "测试插件。"
source = "manual"
install_hint = "manual"
target = "custom_nodes/demo_plugin"
scope = "per-runtime"
status = "planned"
""",
        encoding="utf-8",
    )
    (catalog_dir / "workflows" / "demo.toml").write_text(
        """
schema_version = 1

[workflows.demo_workflow]
name = "demo_workflow"
summary = "测试工作流。"
status = "planned"
models = ["demo_model"]
""",
        encoding="utf-8",
    )
    settings = comfy_settings(tmp_path)
    models_dir = tmp_path / "external-models"
    (models_dir / "checkpoints" / "demo_model.safetensors").mkdir(parents=True)

    with pytest.raises(AppError) as exc:
        catalog.download_model_by_id(settings, "demo_model", models_dir=str(models_dir), catalog_dir=catalog_dir)

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["reason"] == "destination_not_file"


def test_catalog_install_plugin_clones_to_current_custom_nodes(tmp_path, fake_runtime_source, fake_runtime_copy, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    write_plugin_catalog(
        catalog_dir,
        """
schema_version = 1

[plugins.demo_plugin]
name = "DemoPlugin"
summary = "测试插件。"
source = "git"
repo = "https://example.com/demo-plugin"
branch = "main"
target = "custom_nodes/DemoPlugin"
scope = "per-runtime"
status = "approved"
""",
    )
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source
    runtimes.import_runtime(settings, "demo-runtime", str(source_comfy_dir), str(source_venv_dir))
    runtimes.use_runtime(settings, "demo-runtime")
    calls: list[list[str]] = []

    def fake_run_git(args: list[str]) -> str:
        calls.append(args)
        if args[:2] == ["clone", "--branch"]:
            destination = Path(args[-1])
            (destination / ".git").mkdir(parents=True)
            (destination / "requirements.txt").write_text("demo\n", encoding="utf-8")
        return ""

    monkeypatch.setattr(catalog, "run_git", fake_run_git)

    result = catalog.install_plugin_by_id(settings, "demo_plugin", catalog_dir)

    target = comfy_paths(settings).current.resolve() / "custom_nodes" / "DemoPlugin"
    assert result["status"] == "installed"
    assert result["path"] == str(target)
    assert result["repo"] == "https://example.com/demo-plugin"
    assert result["branch"] == "main"
    assert result["requirements"] == str(target / "requirements.txt")
    assert calls == [
        ["clone", "--branch", "main", "https://example.com/demo-plugin", str(target)],
        ["-C", str(target), "checkout", "main"],
    ]


def test_catalog_update_plugin_fetches_and_pulls_branch(tmp_path, fake_runtime_source, fake_runtime_copy, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    write_plugin_catalog(
        catalog_dir,
        """
schema_version = 1

[plugins.demo_plugin]
name = "DemoPlugin"
summary = "测试插件。"
source = "git"
repo = "https://example.com/demo-plugin"
branch = "main"
target = "custom_nodes/DemoPlugin"
scope = "per-runtime"
status = "approved"
""",
    )
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source
    runtimes.import_runtime(settings, "demo-runtime", str(source_comfy_dir), str(source_venv_dir))
    runtimes.use_runtime(settings, "demo-runtime")
    target = comfy_paths(settings).current.resolve() / "custom_nodes" / "DemoPlugin"
    (target / ".git").mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run_git(args: list[str]) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(catalog, "run_git", fake_run_git)

    result = catalog.update_plugin_by_id(settings, "demo_plugin", catalog_dir)

    assert result["status"] == "updated"
    assert calls == [
        ["-C", str(target), "fetch", "--all", "--tags", "--prune"],
        ["-C", str(target), "checkout", "main"],
        ["-C", str(target), "pull", "--ff-only", "origin", "main"],
    ]


def test_catalog_update_all_plugins_reports_missing_without_failing(tmp_path, fake_runtime_source, fake_runtime_copy, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    write_plugin_catalog(
        catalog_dir,
        """
schema_version = 1

[plugins.demo_plugin]
name = "DemoPlugin"
summary = "测试插件。"
source = "git"
repo = "https://example.com/demo-plugin"
branch = "main"
target = "custom_nodes/DemoPlugin"
scope = "per-runtime"
status = "approved"

[plugins.missing_plugin]
name = "MissingPlugin"
summary = "测试未安装插件。"
source = "git"
repo = "https://example.com/missing-plugin"
branch = "main"
target = "custom_nodes/MissingPlugin"
scope = "per-runtime"
status = "approved"
""",
    )
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source
    runtimes.import_runtime(settings, "demo-runtime", str(source_comfy_dir), str(source_venv_dir))
    runtimes.use_runtime(settings, "demo-runtime")
    custom_nodes = comfy_paths(settings).current.resolve() / "custom_nodes"
    (custom_nodes / "DemoPlugin" / ".git").mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run_git(args: list[str]) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(catalog, "run_git", fake_run_git)

    result = catalog.update_all_plugins(settings, catalog_dir)

    assert [item["id"] for item in result["items"]] == ["demo_plugin", "missing_plugin"]
    assert [item["status"] for item in result["items"]] == ["updated", "missing"]
    assert calls == [
        ["-C", str(custom_nodes / "DemoPlugin"), "fetch", "--all", "--tags", "--prune"],
        ["-C", str(custom_nodes / "DemoPlugin"), "checkout", "main"],
        ["-C", str(custom_nodes / "DemoPlugin"), "pull", "--ff-only", "origin", "main"],
    ]


def test_catalog_rejects_plugin_target_without_plugin_dir(tmp_path):
    catalog_dir = tmp_path / "catalog"
    write_plugin_catalog(
        catalog_dir,
        """
schema_version = 1

[plugins.demo_plugin]
name = "DemoPlugin"
summary = "测试插件。"
source = "git"
repo = "https://example.com/demo-plugin"
branch = "main"
target = "custom_nodes"
scope = "per-runtime"
status = "approved"
""",
    )

    with pytest.raises(AppError) as exc:
        catalog.catalog_summary(catalog_dir)

    assert exc.value.code == "REQUEST_INVALID"
    assert exc.value.details["resource"] == "catalog"


def test_catalog_installed_plugins_reports_git_state_and_unmanaged(tmp_path, fake_runtime_source, fake_runtime_copy, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    write_plugin_catalog(
        catalog_dir,
        """
schema_version = 1

[plugins.demo_plugin]
name = "DemoPlugin"
summary = "测试插件。"
source = "git"
repo = "https://example.com/demo-plugin"
branch = "main"
target = "custom_nodes/DemoPlugin"
scope = "per-runtime"
status = "approved"
""",
    )
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source
    runtimes.import_runtime(settings, "demo-runtime", str(source_comfy_dir), str(source_venv_dir))
    runtimes.use_runtime(settings, "demo-runtime")
    custom_nodes = comfy_paths(settings).current.resolve() / "custom_nodes"
    (custom_nodes / "DemoPlugin" / ".git").mkdir(parents=True)
    (custom_nodes / "OtherPlugin").mkdir()

    def fake_run_git(args: list[str]) -> str:
        if args[-1] == "--show-current":
            return "main"
        if args[-2:] == ["--short", "HEAD"]:
            return "abc1234"
        return ""

    monkeypatch.setattr(catalog, "run_git", fake_run_git)

    result = catalog.list_installed_plugins(settings, catalog_dir)

    assert result["unmanaged"] == ["OtherPlugin"]
    assert result["items"][0]["id"] == "demo_plugin"
    assert result["items"][0]["status"] == "installed"
    assert result["items"][0]["git"] is True
    assert result["items"][0]["current_branch"] == "main"
    assert result["items"][0]["current_ref"] == "abc1234"


def test_catalog_install_plugin_rejects_running_comfyui(tmp_path, fake_runtime_source, fake_runtime_copy, monkeypatch):
    catalog_dir = tmp_path / "catalog"
    write_plugin_catalog(
        catalog_dir,
        """
schema_version = 1

[plugins.demo_plugin]
name = "DemoPlugin"
summary = "测试插件。"
source = "git"
repo = "https://example.com/demo-plugin"
branch = "main"
target = "custom_nodes/DemoPlugin"
scope = "per-runtime"
status = "approved"
""",
    )
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source
    runtimes.import_runtime(settings, "demo-runtime", str(source_comfy_dir), str(source_venv_dir))
    runtimes.use_runtime(settings, "demo-runtime")
    monkeypatch.setattr(process, "is_running", lambda _paths: True)

    with pytest.raises(AppError) as exc:
        catalog.install_plugin_by_id(settings, "demo_plugin", catalog_dir)

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["reason"] == "comfyui_running"


def test_import_use_runtime_links_current_models_and_env(tmp_path, fake_runtime_source, fake_runtime_copy):
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source

    imported = runtimes.import_runtime(settings, "comfyui-0.27.0", str(source_comfy_dir), str(source_venv_dir))
    current = runtimes.use_runtime(settings, "comfyui-0.27.0")
    paths = comfy_paths(settings)

    assert imported["name"] == "comfyui-0.27.0"
    assert current["name"] == "comfyui-0.27.0"
    assert paths.current.is_symlink()
    assert paths.current.resolve() == paths.runtimes / "comfyui-0.27.0" / "ComfyUI"
    assert paths.current_env.is_symlink()
    assert paths.current_env.resolve() == paths.runtimes / "comfyui-0.27.0" / ".venv"
    assert (paths.current_env / "bin" / "python").is_file()
    assert (paths.current / "models").is_symlink()
    assert (paths.current / "models").resolve() == paths.models.resolve()
    assert (paths.models / "configs" / "demo.yaml").read_text(encoding="utf-8") == "model: runtime\n"
    state = json.loads(paths.state_file.read_text(encoding="utf-8"))
    assert state["current_runtime"] == "comfyui-0.27.0"
    assert state["current_env_python"].endswith("/runtimes/comfyui-0.27.0/.venv/bin/python")


def test_stage_runtime_from_zip_copies_seed_env_and_writes_registry(tmp_path, fake_runtime_source, fake_runtime_copy):
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source
    archive_path, commit = make_archive(tmp_path)

    runtimes.import_runtime(settings, "comfyui-0.27.0", str(source_comfy_dir), str(source_venv_dir))
    staged = runtimes.stage_runtime_from_zip(
        settings,
        "comfyui-0.36.0",
        str(archive_path),
        "comfyui-0.27.0",
    )
    paths = comfy_paths(settings)

    assert staged["name"] == "comfyui-0.36.0"
    assert staged["commit"] == commit
    assert staged["seed_runtime"] == "comfyui-0.27.0"
    assert Path(staged["comfy_dir"]) == paths.runtimes / "comfyui-0.36.0" / "ComfyUI"
    assert Path(staged["venv_dir"]) == paths.runtimes / "comfyui-0.36.0" / ".venv"
    assert Path(staged["venv_dir"]).resolve() != Path(staged["seed_venv_dir"]).resolve()
    assert (Path(staged["comfy_dir"]) / "main.py").is_file()
    assert (Path(staged["venv_dir"]) / "bin" / "python").is_file()
    registry = json.loads(paths.runtime_registry_file.read_text(encoding="utf-8"))
    assert registry["comfyui-0.36.0"]["source_archive"] == str(archive_path)
    assert not paths.current.exists()


def test_stage_runtime_from_zip_cleans_target_when_registry_write_fails(
    tmp_path,
    fake_runtime_source,
    fake_runtime_copy,
    monkeypatch,
):
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source
    archive_path, _commit = make_archive(tmp_path)
    runtimes.import_runtime(settings, "comfyui-0.27.0", str(source_comfy_dir), str(source_venv_dir))
    paths = comfy_paths(settings)

    def failing_write_registry(_paths, _registry):
        raise OSError("disk full")

    monkeypatch.setattr(runtimes, "write_registry", failing_write_registry)

    with pytest.raises(OSError):
        runtimes.stage_runtime_from_zip(settings, "comfyui-0.36.0", str(archive_path), "comfyui-0.27.0")

    assert not (paths.runtimes / "comfyui-0.36.0").exists()


def test_stage_runtime_from_zip_reports_bad_archive(tmp_path, fake_runtime_source, fake_runtime_copy):
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source
    bad_archive = tmp_path / "bad.zip"
    bad_archive.write_text("not a zip", encoding="utf-8")
    runtimes.import_runtime(settings, "comfyui-0.27.0", str(source_comfy_dir), str(source_venv_dir))
    paths = comfy_paths(settings)

    with pytest.raises(AppError) as exc:
        runtimes.stage_runtime_from_zip(settings, "comfyui-0.36.0", str(bad_archive), "comfyui-0.27.0")

    assert exc.value.code == "DEPENDENCY_UNAVAILABLE"
    assert exc.value.details["reason"] == "invalid_archive"
    assert not (paths.runtimes / "comfyui-0.36.0").exists()


def test_stage_runtime_from_zip_requires_seed_runtime(tmp_path):
    settings = comfy_settings(tmp_path)
    archive_path, _commit = make_archive(tmp_path)

    with pytest.raises(AppError) as exc:
        runtimes.stage_runtime_from_zip(settings, "comfyui-0.36.0", str(archive_path), "missing-seed")

    assert exc.value.code == "RESOURCE_NOT_FOUND"
    assert exc.value.details["resource"] == "seed_runtime"


def test_import_runtime_requires_executable_python(tmp_path, fake_runtime_source, fake_runtime_copy):
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source
    python = source_venv_dir / "bin" / "python"
    python.chmod(0o644)

    with pytest.raises(AppError) as exc:
        runtimes.import_runtime(settings, "bad-runtime", str(source_comfy_dir), str(source_venv_dir))

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["reason"] == "runtime_python_not_executable"


def test_import_runtime_cleans_partial_copy_on_failure(tmp_path, fake_runtime_source, monkeypatch):
    settings = comfy_settings(tmp_path)
    source_comfy_dir, source_venv_dir = fake_runtime_source

    def failing_copy_tree(source: Path, target: Path) -> None:
        target.mkdir(parents=True)
        raise AppError("DEPENDENCY_UNAVAILABLE", details={"dependency": "rsync"})

    monkeypatch.setattr(runtimes, "copy_tree", failing_copy_tree)

    with pytest.raises(AppError):
        runtimes.import_runtime(settings, "partial-runtime", str(source_comfy_dir), str(source_venv_dir))

    paths = comfy_paths(settings)
    assert not (paths.runtimes / "partial-runtime").exists()


def test_use_runtime_model_conflict_does_not_switch_current(tmp_path, fake_runtime_copy):
    settings = comfy_settings(tmp_path)

    def make_source(name: str, model_text: str) -> tuple[Path, Path]:
        source = tmp_path / name
        comfy_dir = source / "ComfyUI"
        venv_dir = source / ".venv"
        (comfy_dir / "models" / "configs").mkdir(parents=True)
        (comfy_dir / "main.py").write_text("print('runtime')\n", encoding="utf-8")
        (comfy_dir / "models" / "configs" / "demo.yaml").write_text(model_text, encoding="utf-8")
        python = venv_dir / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
        python.chmod(0o755)
        return comfy_dir, venv_dir

    first_comfy, first_venv = make_source("first", "model: first\n")
    second_comfy, second_venv = make_source("second", "model: second\n")
    runtimes.import_runtime(settings, "first", str(first_comfy), str(first_venv))
    runtimes.import_runtime(settings, "second", str(second_comfy), str(second_venv))
    runtimes.use_runtime(settings, "first")
    paths = comfy_paths(settings)
    first_current = paths.current.resolve()
    first_env = paths.current_env.resolve()

    with pytest.raises(AppError) as exc:
        runtimes.use_runtime(settings, "second")

    assert exc.value.code == "RESOURCE_CONFLICT"
    assert exc.value.details["reason"] == "models_seed_conflict"
    assert paths.current.resolve() == first_current
    assert paths.current_env.resolve() == first_env


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
