import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.comfy import archives, catalog, envs, models, process, runtimes, versions
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
    assert target.read_text(encoding="utf-8") == "model-data"


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

    def fake_download_url(url: str, destination: Path) -> None:
        calls.append((url, destination))
        destination.write_text("url-model", encoding="utf-8")

    monkeypatch.setattr(catalog, "download_url", fake_download_url)
    settings = comfy_settings(tmp_path)
    models_dir = tmp_path / "external-models"

    result = catalog.download_model_by_id(settings, "demo_model", models_dir=str(models_dir), catalog_dir=catalog_dir)

    target = models_dir / "checkpoints" / "demo_model.safetensors"
    assert result["status"] == "downloaded"
    assert calls == [("https://hf-mirror.com/org/repo/resolve/main/demo_model.safetensors", target)]
    assert target.read_text(encoding="utf-8") == "url-model"


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
