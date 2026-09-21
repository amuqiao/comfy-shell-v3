from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator, model_validator

from app.comfy.lock import WorkspaceLock
from app.comfy.model_paths import model_download_lock_path as shared_model_download_lock_path
from app.comfy.paths import ComfyPaths, comfy_paths
from app.comfy.workspace import init_workspace
from app.core.config import AppSettings
from app.core.exceptions import AppError

CATALOG_SCHEMA_VERSION = 1
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

ModelKind = Literal[
    "diffusion_model",
    "lora",
    "vae",
    "text_encoder",
    "clip_vision",
    "controlnet",
    "ipadapter",
    "other",
]
ModelSource = Literal["huggingface", "url", "local"]
ModelInspectStatus = Literal["exists", "missing", "downloading", "size_mismatch", "sha_mismatch", "path_conflict"]
ModelProbeStatus = Literal["ok", "failed"]
WorkflowStatus = Literal["planned", "testing", "ready", "deprecated"]
PluginSource = Literal["git", "registry", "manual"]
PluginScope = Literal["per-runtime", "shared"]
PluginStatus = Literal["planned", "approved", "installed", "deprecated"]
AssetKind = Literal["plugin_ckpt", "plugin_model", "plugin_weight", "other"]


class StrictCatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelEntry(StrictCatalogModel):
    name: str
    summary: str
    kind: ModelKind
    source: ModelSource
    target: str
    filename: str | None = None
    repo_id: str | None = None
    url: HttpUrl | None = None
    path: str | None = None
    sha256: str | None = None
    size_hint: str | None = None
    size_bytes: int | None = None
    license: str | None = None
    homepage: HttpUrl | None = None
    mirror_url: HttpUrl | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    warning: str | None = None

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        return validate_relative_catalog_path(value, "target")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_relative_catalog_path(value, "filename", allow_trailing_slash=False)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("sha256 must be 64 hex characters")
        return value.lower() if value is not None else None

    @field_validator("size_bytes")
    @classmethod
    def validate_size_bytes(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("size_bytes must be greater than 0")
        return value

    @model_validator(mode="after")
    def validate_source_fields(self) -> "ModelEntry":
        if self.source == "huggingface" and (not self.repo_id or not self.filename):
            raise ValueError("huggingface source requires repo_id and filename")
        if self.source == "url" and (self.url is None or not self.filename):
            raise ValueError("url source requires url and filename")
        if self.source == "local" and (not self.path or not self.filename):
            raise ValueError("local source requires path and filename")
        return self


class WorkflowEntry(StrictCatalogModel):
    name: str
    summary: str
    status: WorkflowStatus
    models: list[str]
    source_url: HttpUrl | None = None
    workflow_file: str | None = None
    runtime_hint: str | None = None
    assets: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    warning: str | None = None

    @field_validator("models")
    @classmethod
    def validate_references(cls, value: list[str]) -> list[str]:
        for item in value:
            validate_catalog_id(item)
        return value

    @field_validator("assets")
    @classmethod
    def validate_asset_references(cls, value: list[str]) -> list[str]:
        for item in value:
            validate_catalog_id(item)
        return value

    @field_validator("workflow_file")
    @classmethod
    def validate_workflow_file(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_relative_catalog_path(value, "workflow_file", allow_trailing_slash=False)


class PluginEntry(StrictCatalogModel):
    name: str
    summary: str
    source: PluginSource
    target: str
    scope: PluginScope
    status: PluginStatus
    repo: HttpUrl | None = None
    registry_id: str | None = None
    branch: str | None = None
    ref: str | None = None
    install_hint: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    warning: str | None = None

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        target = validate_relative_catalog_path(value, "target")
        parts = PurePosixPath(target).parts
        if len(parts) < 2 or parts[0] != "custom_nodes":
            raise ValueError("target must be under custom_nodes")
        return target

    @model_validator(mode="after")
    def validate_source_fields(self) -> "PluginEntry":
        if self.source == "git" and self.repo is None:
            raise ValueError("git source requires repo")
        if self.source == "registry" and not self.registry_id:
            raise ValueError("registry source requires registry_id")
        if self.source == "manual" and not self.install_hint:
            raise ValueError("manual source requires install_hint")
        return self


class AssetEntry(StrictCatalogModel):
    name: str
    summary: str
    kind: AssetKind
    plugin: str
    source: ModelSource
    target: str
    filename: str
    repo_id: str | None = None
    url: HttpUrl | None = None
    path: str | None = None
    sha256: str | None = None
    size_hint: str | None = None
    size_bytes: int | None = None
    license: str | None = None
    homepage: HttpUrl | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    warning: str | None = None

    @field_validator("plugin")
    @classmethod
    def validate_plugin(cls, value: str) -> str:
        return validate_catalog_id(value)

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        target = validate_relative_catalog_path(value, "target")
        parts = PurePosixPath(target).parts
        if len(parts) < 2 or parts[0] != "custom_nodes":
            raise ValueError("target must be under custom_nodes")
        return target

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return validate_relative_catalog_path(value, "filename", allow_trailing_slash=False)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError("sha256 must be 64 hex characters")
        return value.lower() if value is not None else None

    @field_validator("size_bytes")
    @classmethod
    def validate_size_bytes(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("size_bytes must be greater than 0")
        return value

    @model_validator(mode="after")
    def validate_source_fields(self) -> "AssetEntry":
        if self.source == "huggingface" and not self.repo_id:
            raise ValueError("huggingface source requires repo_id")
        if self.source == "url" and self.url is None:
            raise ValueError("url source requires url")
        if self.source == "local" and not self.path:
            raise ValueError("local source requires path")
        return self


class ModelsCatalog(StrictCatalogModel):
    schema_version: int
    models: dict[str, ModelEntry]

    @model_validator(mode="after")
    def validate_catalog(self) -> "ModelsCatalog":
        validate_schema_version(self.schema_version)
        validate_id_map(self.models, "models")
        return self


class WorkflowsCatalog(StrictCatalogModel):
    schema_version: int
    workflows: dict[str, WorkflowEntry]

    @model_validator(mode="after")
    def validate_catalog(self) -> "WorkflowsCatalog":
        validate_schema_version(self.schema_version)
        validate_id_map(self.workflows, "workflows")
        return self


class PluginsCatalog(StrictCatalogModel):
    schema_version: int
    plugins: dict[str, PluginEntry]

    @model_validator(mode="after")
    def validate_catalog(self) -> "PluginsCatalog":
        validate_schema_version(self.schema_version)
        validate_id_map(self.plugins, "plugins")
        return self


class AssetsCatalog(StrictCatalogModel):
    schema_version: int
    assets: dict[str, AssetEntry]

    @model_validator(mode="after")
    def validate_catalog(self) -> "AssetsCatalog":
        validate_schema_version(self.schema_version)
        validate_id_map(self.assets, "assets")
        return self


class CatalogBundle(StrictCatalogModel):
    models: dict[str, ModelEntry]
    workflows: dict[str, WorkflowEntry]
    plugins: dict[str, PluginEntry]
    assets: dict[str, AssetEntry]


def validate_schema_version(value: int) -> None:
    if value != CATALOG_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {CATALOG_SCHEMA_VERSION}")


def validate_catalog_id(value: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise ValueError("catalog id must be lower snake_case and start with a letter")
    return value


def validate_relative_catalog_path(value: str, field: str, *, allow_trailing_slash: bool = True) -> str:
    if "\\" in value:
        raise ValueError(f"{field} must use POSIX path separators")
    normalized = value.strip().strip("/")
    path = PurePosixPath(value.strip())
    if not normalized or path.is_absolute() or ".." in path.parts or path.parts == (".",):
        raise ValueError(f"{field} must be a relative path")
    if not allow_trailing_slash and value.strip().endswith("/"):
        raise ValueError(f"{field} must be a file path")
    return normalized


def validate_id_map(values: dict[str, Any], section: str) -> None:
    for key in values:
        try:
            validate_catalog_id(key)
        except ValueError as exc:
            raise ValueError(f"{section}.{key}: {exc}") from exc


def default_catalog_dir() -> Path:
    return Path.cwd() / "catalog"


def read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "catalog_file", "path": str(path)})
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise AppError("REQUEST_INVALID", details={"resource": "catalog_file", "path": str(path), "error": str(exc)}) from exc


def read_catalog_section(catalog_dir: Path, dirname: str, section: str) -> dict[str, Any]:
    section_dir = catalog_dir / dirname
    if not section_dir.is_dir():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "catalog_dir", "path": str(section_dir)})
    return read_catalog_section_from_dir(section_dir, section, required=True)


def read_optional_catalog_section(catalog_dir: Path, dirname: str, section: str) -> dict[str, Any]:
    section_dir = catalog_dir / dirname
    if not section_dir.is_dir():
        return {"schema_version": CATALOG_SCHEMA_VERSION, section: {}}
    return read_catalog_section_from_dir(section_dir, section, required=False)


def read_catalog_section_from_dir(section_dir: Path, section: str, *, required: bool) -> dict[str, Any]:
    merged: dict[str, Any] = {"schema_version": CATALOG_SCHEMA_VERSION, section: {}}
    files = sorted(section_dir.glob("*.toml"))
    if required and not files:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "catalog_section", "path": str(section_dir), "section": section})
    for path in files:
        raw = read_toml(path)
        unknown_keys = sorted(set(raw) - {"schema_version", section})
        if unknown_keys:
            raise AppError(
                "REQUEST_INVALID",
                details={
                    "resource": "catalog_file",
                    "path": str(path),
                    "reason": "unknown_top_level_keys",
                    "keys": unknown_keys,
                },
            )
        version = raw.get("schema_version")
        if version != CATALOG_SCHEMA_VERSION:
            raise AppError(
                "REQUEST_INVALID",
                details={"resource": "catalog_file", "path": str(path), "reason": f"schema_version must be {CATALOG_SCHEMA_VERSION}"},
            )
        entries = raw.get(section)
        if not isinstance(entries, dict):
            raise AppError("REQUEST_INVALID", details={"resource": "catalog_file", "path": str(path), "reason": f"missing section {section}"})
        for entry_id, entry in entries.items():
            if entry_id in merged[section]:
                raise AppError(
                    "REQUEST_INVALID",
                    details={"resource": "catalog", "reason": "duplicate_id", "section": section, "id": entry_id, "path": str(path)},
                )
            merged[section][entry_id] = entry
    return merged


def load_models_catalog(catalog_dir: Path) -> ModelsCatalog:
    return ModelsCatalog.model_validate(read_catalog_section(catalog_dir, "models", "models"))


def load_workflows_catalog(catalog_dir: Path) -> WorkflowsCatalog:
    return WorkflowsCatalog.model_validate(read_catalog_section(catalog_dir, "workflows", "workflows"))


def load_plugins_catalog(catalog_dir: Path) -> PluginsCatalog:
    return PluginsCatalog.model_validate(read_catalog_section(catalog_dir, "plugins", "plugins"))


def load_assets_catalog(catalog_dir: Path) -> AssetsCatalog:
    return AssetsCatalog.model_validate(read_optional_catalog_section(catalog_dir, "assets", "assets"))


def load_catalog(catalog_dir: Path | None = None) -> CatalogBundle:
    root = (catalog_dir or default_catalog_dir()).resolve()
    try:
        models_catalog = load_models_catalog(root)
        workflows_catalog = load_workflows_catalog(root)
        plugins_catalog = load_plugins_catalog(root)
        assets_catalog = load_assets_catalog(root)
        bundle = CatalogBundle(
            models=models_catalog.models,
            workflows=workflows_catalog.workflows,
            plugins=plugins_catalog.plugins,
            assets=assets_catalog.assets,
        )
        validate_cross_references(bundle, root)
        return bundle
    except ValidationError as exc:
        raise AppError("REQUEST_INVALID", details={"resource": "catalog", "errors": exc.errors(include_context=False)}) from exc
    except ValueError as exc:
        raise AppError("REQUEST_INVALID", details={"resource": "catalog", "error": str(exc)}) from exc


def validate_cross_references(bundle: CatalogBundle, catalog_dir: Path) -> None:
    for workflow_id, workflow in bundle.workflows.items():
        missing_models = [model_id for model_id in workflow.models if model_id not in bundle.models]
        if missing_models:
            raise AppError(
                "REQUEST_INVALID",
                details={
                    "resource": "workflow",
                    "id": workflow_id,
                    "missing_models": missing_models,
                },
            )
        missing_assets = [asset_id for asset_id in workflow.assets if asset_id not in bundle.assets]
        if missing_assets:
            raise AppError(
                "REQUEST_INVALID",
                details={
                    "resource": "workflow",
                    "id": workflow_id,
                    "missing_assets": missing_assets,
                },
            )
        if workflow.workflow_file is not None and not (catalog_dir / workflow.workflow_file).is_file():
            raise AppError(
                "RESOURCE_NOT_FOUND",
                details={"resource": "workflow_file", "id": workflow_id, "path": workflow.workflow_file},
            )
    for asset_id, asset in bundle.assets.items():
        if asset.plugin not in bundle.plugins:
            raise AppError(
                "REQUEST_INVALID",
                details={"resource": "asset", "id": asset_id, "missing_plugin": asset.plugin},
            )


def catalog_summary(catalog_dir: Path | None = None) -> dict[str, int]:
    bundle = load_catalog(catalog_dir)
    return {
        "models": len(bundle.models),
        "workflows": len(bundle.workflows),
        "plugins": len(bundle.plugins),
        "assets": len(bundle.assets),
    }


def list_entries(kind: str, catalog_dir: Path | None = None) -> list[dict[str, str]]:
    bundle = load_catalog(catalog_dir)
    if kind == "models":
        return [{"id": key, "name": value.name, "kind": value.kind, "target": value.target} for key, value in sorted(bundle.models.items())]
    if kind == "workflows":
        return [
            {"id": key, "name": value.name, "status": value.status, "runtime_hint": value.runtime_hint or ""}
            for key, value in sorted(bundle.workflows.items())
        ]
    if kind == "plugins":
        return [{"id": key, "name": value.name, "status": value.status, "scope": value.scope} for key, value in sorted(bundle.plugins.items())]
    if kind == "assets":
        return [{"id": key, "name": value.name, "kind": value.kind, "plugin": value.plugin} for key, value in sorted(bundle.assets.items())]
    raise AppError("REQUEST_INVALID", details={"field": "kind", "reason": "expected models, workflows, plugins, or assets"})


def show_model(model_id: str, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if model_id not in bundle.models:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "model", "id": model_id})
    return bundle.models[model_id].model_dump(mode="json")


def show_plugin(plugin_id: str, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if plugin_id not in bundle.plugins:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "plugin", "id": plugin_id})
    return bundle.plugins[plugin_id].model_dump(mode="json")


def show_asset(asset_id: str, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if asset_id not in bundle.assets:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "asset", "id": asset_id})
    return bundle.assets[asset_id].model_dump(mode="json")


def list_installed_plugins(settings: AppSettings, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    custom_nodes = current_custom_nodes_dir(settings)
    items = [
        plugin_install_state(plugin_id, entry, plugin_destination(custom_nodes, entry))
        for plugin_id, entry in sorted(bundle.plugins.items())
    ]
    known_targets = {PurePosixPath(entry.target).parts[-1] for entry in bundle.plugins.values()}
    unmanaged = []
    if custom_nodes.exists():
        unmanaged = sorted(
            item.name
            for item in custom_nodes.iterdir()
            if item.is_dir() and not item.name.startswith(".") and item.name not in known_targets
        )
    return {"custom_nodes": str(custom_nodes), "items": items, "unmanaged": unmanaged}


def show_installed_plugin(settings: AppSettings, plugin_id: str, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if plugin_id not in bundle.plugins:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "plugin", "id": plugin_id})
    custom_nodes = current_custom_nodes_dir(settings)
    entry = bundle.plugins[plugin_id]
    return plugin_install_state(plugin_id, entry, plugin_destination(custom_nodes, entry))


def install_plugin_by_id(settings: AppSettings, plugin_id: str, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if plugin_id not in bundle.plugins:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "plugin", "id": plugin_id})
    return install_plugin_entry(settings, plugin_id, bundle.plugins[plugin_id])


def install_all_plugins(settings: AppSettings, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    return {
        "items": [install_plugin_entry(settings, plugin_id, entry) for plugin_id, entry in sorted(bundle.plugins.items())],
    }


def update_plugin_by_id(settings: AppSettings, plugin_id: str, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if plugin_id not in bundle.plugins:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "plugin", "id": plugin_id})
    return update_plugin_entry(settings, plugin_id, bundle.plugins[plugin_id])


def update_all_plugins(settings: AppSettings, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    paths = init_workspace(settings)
    with WorkspaceLock(paths.lock_file):
        ensure_comfyui_stopped(paths, "plugins")
        custom_nodes = current_custom_nodes_dir(settings)
        items = []
        for plugin_id, entry in sorted(bundle.plugins.items()):
            require_git_plugin(plugin_id, entry)
            destination = plugin_destination(custom_nodes, entry)
            if not destination.exists():
                items.append(plugin_install_result(plugin_id, entry, destination, "missing"))
                continue
            items.append(update_plugin_entry_unlocked(plugin_id, entry, destination))
        return {"items": items}


def show_workflow(workflow_id: str, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if workflow_id not in bundle.workflows:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "workflow", "id": workflow_id})
    workflow = bundle.workflows[workflow_id]
    return {
        "id": workflow_id,
        **workflow.model_dump(mode="json"),
        "resolved_models": [
            {"id": model_id, "name": bundle.models[model_id].name, "target": bundle.models[model_id].target, "filename": bundle.models[model_id].filename}
            for model_id in workflow.models
        ],
        "resolved_assets": [
            {
                "id": asset_id,
                "name": bundle.assets[asset_id].name,
                "plugin": bundle.assets[asset_id].plugin,
                "target": bundle.assets[asset_id].target,
                "filename": bundle.assets[asset_id].filename,
            }
            for asset_id in workflow.assets
        ],
    }


def current_custom_nodes_dir(settings: AppSettings) -> Path:
    paths = comfy_paths(settings)
    if not paths.current.is_symlink():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "current_runtime", "path": str(paths.current)})
    current = paths.current.resolve()
    if not (current / "main.py").is_file():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "comfy_main", "path": str(current / "main.py")})
    return current / "custom_nodes"


def plugin_destination(custom_nodes: Path, entry: PluginEntry) -> Path:
    relative = PurePosixPath(entry.target)
    if relative.parts[0] != "custom_nodes" or len(relative.parts) < 2:
        raise AppError("REQUEST_INVALID", details={"resource": "plugin", "reason": "target_must_be_under_custom_nodes", "target": entry.target})
    return custom_nodes.joinpath(*relative.parts[1:])


def require_git_plugin(plugin_id: str, entry: PluginEntry) -> None:
    if entry.source != "git":
        raise AppError("REQUEST_INVALID", details={"resource": "plugin", "id": plugin_id, "reason": "only_git_plugins_supported"})
    if entry.repo is None:
        raise AppError("REQUEST_INVALID", details={"resource": "plugin", "id": plugin_id, "reason": "repo_required"})


def install_plugin_entry(settings: AppSettings, plugin_id: str, entry: PluginEntry) -> dict[str, Any]:
    require_git_plugin(plugin_id, entry)
    paths = init_workspace(settings)
    with WorkspaceLock(paths.lock_file):
        ensure_comfyui_stopped(paths, plugin_id)
        custom_nodes = current_custom_nodes_dir(settings)
        destination = plugin_destination(custom_nodes, entry)
        return install_plugin_entry_unlocked(plugin_id, entry, destination)


def update_plugin_entry(settings: AppSettings, plugin_id: str, entry: PluginEntry) -> dict[str, Any]:
    require_git_plugin(plugin_id, entry)
    paths = init_workspace(settings)
    with WorkspaceLock(paths.lock_file):
        ensure_comfyui_stopped(paths, plugin_id)
        custom_nodes = current_custom_nodes_dir(settings)
        destination = plugin_destination(custom_nodes, entry)
        return update_plugin_entry_unlocked(plugin_id, entry, destination)


def ensure_comfyui_stopped(paths: ComfyPaths, plugin_id: str) -> None:
    from app.comfy import process

    if process.is_running(paths):
        raise AppError("RESOURCE_CONFLICT", details={"resource": "plugin", "id": plugin_id, "reason": "comfyui_running"})


def install_plugin_entry_unlocked(plugin_id: str, entry: PluginEntry, destination: Path) -> dict[str, Any]:
    if destination.exists():
        if not destination.is_dir():
            raise AppError(
                "RESOURCE_CONFLICT",
                details={"resource": "plugin", "id": plugin_id, "reason": "destination_not_dir", "path": str(destination)},
            )
        return plugin_install_result(plugin_id, entry, destination, "exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        clone_plugin(entry, destination)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return plugin_install_result(plugin_id, entry, destination, "installed")


def update_plugin_entry_unlocked(plugin_id: str, entry: PluginEntry, destination: Path) -> dict[str, Any]:
    if not destination.is_dir():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "plugin", "id": plugin_id, "path": str(destination)})
    if not (destination / ".git").is_dir():
        raise AppError("RESOURCE_CONFLICT", details={"resource": "plugin", "id": plugin_id, "reason": "destination_not_git_repo", "path": str(destination)})
    run_git(["-C", str(destination), "fetch", "--all", "--tags", "--prune"])
    checkout_plugin_ref(entry, destination)
    if entry.ref is None and entry.branch is not None:
        run_git(["-C", str(destination), "pull", "--ff-only", "origin", entry.branch])
    return plugin_install_result(plugin_id, entry, destination, "updated")


def clone_plugin(entry: PluginEntry, destination: Path) -> None:
    if entry.repo is None:
        raise AppError("REQUEST_INVALID", details={"resource": "plugin", "reason": "repo_required"})
    command = ["clone", str(entry.repo), str(destination)]
    if entry.branch is not None:
        command = ["clone", "--branch", entry.branch, str(entry.repo), str(destination)]
    run_git(command)
    checkout_plugin_ref(entry, destination)


def checkout_plugin_ref(entry: PluginEntry, destination: Path) -> None:
    if entry.ref is not None:
        run_git(["-C", str(destination), "checkout", entry.ref])
    elif entry.branch is not None:
        run_git(["-C", str(destination), "checkout", entry.branch])


def run_git(args: list[str]) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise AppError("DEPENDENCY_UNAVAILABLE", details={"dependency": "git"})
    result = subprocess.run(
        [executable, *args],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise AppError(
            "DEPENDENCY_UNAVAILABLE",
            details={
                "dependency": "git",
                "returncode": result.returncode,
                "command": ["git", *args],
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
    return result.stdout.strip()


def plugin_install_state(plugin_id: str, entry: PluginEntry, destination: Path) -> dict[str, Any]:
    status = "installed" if destination.is_dir() else "missing"
    return {**plugin_install_result(plugin_id, entry, destination, status), **plugin_git_state(destination)}


def plugin_install_result(plugin_id: str, entry: PluginEntry, destination: Path, status: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": plugin_id,
        "name": entry.name,
        "status": status,
        "source": entry.source,
        "target": entry.target,
        "path": str(destination),
        "repo": str(entry.repo) if entry.repo is not None else None,
        "branch": entry.branch,
        "ref": entry.ref,
    }
    requirements = destination / "requirements.txt"
    result["requirements"] = str(requirements) if requirements.is_file() else None
    return result


def plugin_git_state(destination: Path) -> dict[str, Any]:
    if not destination.is_dir():
        return {"git": False, "current_branch": None, "current_ref": None}
    if not (destination / ".git").is_dir():
        return {"git": False, "current_branch": None, "current_ref": None}
    return {
        "git": True,
        "current_branch": run_git(["-C", str(destination), "branch", "--show-current"]),
        "current_ref": run_git(["-C", str(destination), "rev-parse", "--short", "HEAD"]),
    }


def resolve_models_dir(settings: AppSettings, models_dir: str | None) -> Path:
    if models_dir:
        return Path(models_dir).expanduser().resolve()
    paths = init_workspace(settings)
    return paths.models.resolve()


def destination_for_model(models_dir: Path, entry: ModelEntry) -> Path:
    if entry.filename is None:
        raise AppError("REQUEST_INVALID", details={"resource": "model", "reason": "filename_required"})
    return models_dir / entry.target / entry.filename


def model_download_lock_path(models_dir: Path, destination: Path) -> Path:
    relative = destination.relative_to(models_dir)
    return shared_model_download_lock_path(models_dir, str(relative.parent), relative.name)


def inspect_model_by_id(
    settings: AppSettings,
    model_id: str,
    *,
    models_dir: str | None = None,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if model_id not in bundle.models:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "model", "id": model_id})
    root = resolve_models_dir(settings, models_dir)
    return inspect_model_entry(model_id, bundle.models[model_id], root)


def inspect_workflow_models(
    settings: AppSettings,
    workflow_id: str,
    *,
    models_dir: str | None = None,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if workflow_id not in bundle.workflows:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "workflow", "id": workflow_id})
    root = resolve_models_dir(settings, models_dir)
    workflow = bundle.workflows[workflow_id]
    items = [inspect_model_entry(model_id, bundle.models[model_id], root) for model_id in workflow.models]
    return {
        "workflow": workflow_id,
        "models_dir": str(root),
        "summary": summarize_inspection(items),
        "items": items,
    }


def missing_workflow_models(
    settings: AppSettings,
    workflow_id: str,
    *,
    models_dir: str | None = None,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    inspected = inspect_workflow_models(settings, workflow_id, models_dir=models_dir, catalog_dir=catalog_dir)
    actionable = [
        item
        for item in inspected["items"]
        if item["status"] in {"missing", "size_mismatch", "sha_mismatch", "path_conflict"}
    ]
    return {
        "workflow": workflow_id,
        "models_dir": inspected["models_dir"],
        "model_ids": [item["id"] for item in actionable],
        "items": actionable,
    }


def metadata_model_by_id(
    settings: AppSettings,
    model_id: str,
    *,
    models_dir: str | None = None,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if model_id not in bundle.models:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "model", "id": model_id})
    root = resolve_models_dir(settings, models_dir)
    return metadata_model_entry(model_id, bundle.models[model_id], root)


def metadata_workflow_models(
    settings: AppSettings,
    workflow_id: str,
    *,
    models_dir: str | None = None,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if workflow_id not in bundle.workflows:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "workflow", "id": workflow_id})
    root = resolve_models_dir(settings, models_dir)
    workflow = bundle.workflows[workflow_id]
    return {
        "workflow": workflow_id,
        "models_dir": str(root),
        "items": [metadata_model_entry(model_id, bundle.models[model_id], root) for model_id in workflow.models],
    }


def metadata_model_entry(model_id: str, entry: ModelEntry, models_dir: Path) -> dict[str, Any]:
    destination = destination_for_model(models_dir, entry)
    if not destination.is_file():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "model_file", "id": model_id, "path": str(destination)})
    local_size = destination.stat().st_size
    return {
        **model_contract_result(model_id, entry, destination),
        "local_size": local_size,
        "computed_size_hint": format_size_hint(local_size),
        "computed_size_bytes": local_size,
        "computed_sha256": file_sha256(destination),
    }


def enrich_model_by_id(
    settings: AppSettings,
    model_id: str,
    *,
    models_dir: str | None = None,
    catalog_dir: Path | None = None,
    write: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    catalog_root = (catalog_dir or default_catalog_dir()).resolve()
    bundle = load_catalog(catalog_root)
    if model_id not in bundle.models:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "model", "id": model_id})
    root = resolve_models_dir(settings, models_dir)
    result = build_enrich_result(
        model_id,
        bundle.models[model_id],
        metadata_model_entry(model_id, bundle.models[model_id], root),
        find_model_catalog_file(catalog_root, model_id),
        write=write,
        overwrite=overwrite,
    )
    updates = result["updates"]
    if write and updates:
        apply_model_catalog_updates(Path(result["catalog_file"]), {model_id: updates})
        load_catalog(catalog_root)
    return result


def enrich_workflow_models(
    settings: AppSettings,
    workflow_id: str,
    *,
    models_dir: str | None = None,
    catalog_dir: Path | None = None,
    write: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    catalog_root = (catalog_dir or default_catalog_dir()).resolve()
    bundle = load_catalog(catalog_root)
    if workflow_id not in bundle.workflows:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "workflow", "id": workflow_id})
    root = resolve_models_dir(settings, models_dir)
    workflow = bundle.workflows[workflow_id]
    items = [
        build_enrich_result(
            model_id,
            bundle.models[model_id],
            metadata_model_entry(model_id, bundle.models[model_id], root),
            find_model_catalog_file(catalog_root, model_id),
            write=write,
            overwrite=overwrite,
        )
        for model_id in workflow.models
    ]
    if write:
        updates_by_file: dict[Path, dict[str, dict[str, Any]]] = {}
        for item in items:
            if item["updates"]:
                path = Path(item["catalog_file"])
                updates_by_file.setdefault(path, {})[item["id"]] = item["updates"]
        for path, updates in updates_by_file.items():
            apply_model_catalog_updates(path, updates)
        if updates_by_file:
            load_catalog(catalog_root)
    return {
        "workflow": workflow_id,
        "write": write,
        "overwrite": overwrite,
        "changed": any(item["changed"] for item in items),
        "changed_count": sum(1 for item in items if item["changed"]),
        "items": items,
    }


def build_enrich_result(
    model_id: str,
    entry: ModelEntry,
    metadata: dict[str, Any],
    catalog_file: Path,
    *,
    write: bool,
    overwrite: bool,
) -> dict[str, Any]:
    updates = enrich_updates(entry, metadata, overwrite=overwrite)
    return {
        "id": model_id,
        "catalog_file": str(catalog_file),
        "write": write,
        "overwrite": overwrite,
        "current": {
            "size_hint": entry.size_hint,
            "size_bytes": entry.size_bytes,
            "sha256": entry.sha256,
        },
        "observed": {
            "local_size": metadata["local_size"],
            "size_hint": metadata["computed_size_hint"],
            "size_bytes": metadata["computed_size_bytes"],
            "sha256": metadata["computed_sha256"],
        },
        "updates": updates,
        "changed": bool(write and updates),
    }


def enrich_updates(entry: ModelEntry, metadata: dict[str, Any], *, overwrite: bool) -> dict[str, Any]:
    candidates = {
        "size_hint": metadata["computed_size_hint"],
        "size_bytes": metadata["computed_size_bytes"],
        "sha256": metadata["computed_sha256"],
    }
    current = {
        "size_hint": entry.size_hint,
        "size_bytes": entry.size_bytes,
        "sha256": entry.sha256,
    }
    updates: dict[str, Any] = {}
    for key, value in candidates.items():
        if value is None:
            continue
        if overwrite or current[key] is None:
            if current[key] != value:
                updates[key] = value
    return updates


def find_model_catalog_file(catalog_dir: Path, model_id: str) -> Path:
    models_dir = catalog_dir / "models"
    for path in sorted(models_dir.glob("*.toml")):
        raw = read_toml(path)
        models = raw.get("models", {})
        if isinstance(models, dict) and model_id in models:
            return path
    raise AppError("RESOURCE_NOT_FOUND", details={"resource": "model_catalog_file", "id": model_id, "path": str(models_dir)})


def update_model_catalog_fields(path: Path, model_id: str, updates: dict[str, Any]) -> None:
    apply_model_catalog_updates(path, {model_id: updates})


def apply_model_catalog_updates(path: Path, updates_by_model: dict[str, dict[str, Any]]) -> None:
    text = path.read_text(encoding="utf-8")
    updated = update_model_catalog_text(text, path=path, updates_by_model=updates_by_model)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(updated, encoding="utf-8")
    os.replace(tmp, path)


def update_model_catalog_text(text: str, *, path: Path, updates_by_model: dict[str, dict[str, Any]]) -> str:
    lines = text.splitlines()
    for model_id, updates in updates_by_model.items():
        lines = update_model_catalog_lines(lines, model_id, updates, path=path)
    updated = "\n".join(lines) + "\n"
    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise AppError("REQUEST_INVALID", details={"resource": "catalog_file", "path": str(path), "error": str(exc)}) from exc
    return updated


def update_model_catalog_lines(lines: list[str], model_id: str, updates: dict[str, Any], *, path: Path) -> list[str]:
    section_header = f"[models.{model_id}]"
    section_start = next((index for index, line in enumerate(lines) if line.strip() == section_header), None)
    if section_start is None:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "model_section", "id": model_id, "path": str(path)})
    section_end = len(lines)
    for index in range(section_start + 1, len(lines)):
        if lines[index].strip().startswith("[") and lines[index].strip().endswith("]"):
            section_end = index
            break

    updated_lines = list(lines)
    insert_at = section_end
    for key, value in updates.items():
        replacement = f"{key} = {format_toml_value(value)}"
        key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        found = False
        for index in range(section_start + 1, section_end):
            if key_pattern.match(updated_lines[index]):
                updated_lines[index] = replacement
                found = True
                break
        if not found:
            updated_lines.insert(insert_at, replacement)
            insert_at += 1
            section_end += 1

    return updated_lines


def format_toml_value(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise AppError("REQUEST_INVALID", details={"resource": "toml_value", "reason": "unsupported_value_type", "value": value})


def inspect_model_entry(model_id: str, entry: ModelEntry, models_dir: Path) -> dict[str, Any]:
    destination = destination_for_model(models_dir, entry)
    base = model_contract_result(model_id, entry, destination)
    tmp_files = model_temp_files(destination)
    if destination.exists() and not destination.is_file():
        return {
            **base,
            "status": "path_conflict",
            "reason": "destination_exists_but_is_not_file",
            "local_size": None,
            "tmp_files": [str(path) for path in tmp_files],
        }
    if destination.is_file():
        local_size = destination.stat().st_size
        if entry.size_bytes is not None and local_size != entry.size_bytes:
            return {
                **base,
                "status": "size_mismatch",
                "reason": "local_size_does_not_match_size_bytes",
                "local_size": local_size,
                "tmp_files": [str(path) for path in tmp_files],
            }
        if entry.sha256 is not None:
            actual = file_sha256(destination)
            if actual != entry.sha256:
                return {
                    **base,
                    "status": "sha_mismatch",
                    "reason": "local_sha256_does_not_match_catalog_sha256",
                    "local_size": local_size,
                    "actual_sha256": actual,
                    "tmp_files": [str(path) for path in tmp_files],
                }
        return {
            **base,
            "status": "exists",
            "reason": "final_file_exists",
            "local_size": local_size,
            "tmp_files": [str(path) for path in tmp_files],
        }
    if tmp_files:
        return {
            **base,
            "status": "downloading",
            "reason": "temporary_download_file_exists",
            "local_size": None,
            "tmp_files": [str(path) for path in tmp_files],
        }
    return {
        **base,
        "status": "missing",
        "reason": "final_file_missing",
        "local_size": None,
        "tmp_files": [],
    }


def summarize_inspection(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {status: 0 for status in ("exists", "missing", "downloading", "size_mismatch", "sha_mismatch", "path_conflict")}
    for item in items:
        summary[item["status"]] += 1
    summary["total"] = len(items)
    return summary


def model_temp_files(destination: Path) -> list[Path]:
    if not destination.parent.is_dir():
        return []
    candidates = [
        path
        for path in destination.parent.iterdir()
        if path.is_file()
        and (
            path.name == f".{destination.name}.tmp"
            or path.name.startswith(f".{destination.name}.tmp.")
            or path.name == f"{destination.name}.part"
        )
    ]
    return sorted(candidates)


def probe_model_by_id(
    settings: AppSettings,
    model_id: str,
    *,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if model_id not in bundle.models:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "model", "id": model_id})
    return probe_model_entry(settings, model_id, bundle.models[model_id])


def probe_workflow_models(settings: AppSettings, workflow_id: str, *, catalog_dir: Path | None = None) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if workflow_id not in bundle.workflows:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "workflow", "id": workflow_id})
    workflow = bundle.workflows[workflow_id]
    items = [probe_model_entry(settings, model_id, bundle.models[model_id]) for model_id in workflow.models]
    return {
        "workflow": workflow_id,
        "summary": {
            "total": len(items),
            "ok": sum(1 for item in items if item["probe_status"] == "ok"),
            "failed": sum(1 for item in items if item["probe_status"] == "failed"),
            "size_matched": sum(1 for item in items if item["size_check_status"] == "matched"),
            "size_mismatched": sum(1 for item in items if item["size_check_status"] == "mismatched"),
            "size_unknown": sum(1 for item in items if item["size_check_status"] == "unknown"),
            "size_not_configured": sum(1 for item in items if item["size_check_status"] == "not_configured"),
        },
        "items": items,
    }


def probe_model_entry(settings: AppSettings, model_id: str, entry: ModelEntry) -> dict[str, Any]:
    base = model_contract_result(model_id, entry, None)
    if entry.source == "url":
        if entry.url is None:
            raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "url_required"})
        probe = probe_url(str(entry.url))
    elif entry.source == "local":
        if entry.path is None:
            raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "path_required"})
        probe = probe_local_file(Path(entry.path).expanduser())
    elif entry.source == "huggingface":
        probe = probe_huggingface(settings, entry)
    else:
        raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "unsupported_source"})
    expected = entry.size_bytes
    actual = probe.get("content_length")
    size_check = probe_size_check_status(expected, actual if isinstance(actual, int) else None)
    return {
        **base,
        **probe,
        "size_matches": True if size_check == "matched" else False if size_check == "mismatched" else None,
        "size_check_status": size_check,
        "suggested_size_bytes": actual,
        "suggested_size_hint": format_size_hint(actual) if actual is not None else None,
    }


def probe_url(url: str) -> dict[str, Any]:
    try:
        request = Request(url, headers={"User-Agent": "comfy-shell-v3"}, method="HEAD")
        with urlopen(request, timeout=20) as response:
            content_length = response.headers.get("Content-Length")
            return {
                "probe_status": "ok",
                "http_status": response.status,
                "content_length": int(content_length) if content_length and content_length.isdigit() else None,
                "effective_url": response.geturl(),
                "etag": response.headers.get("ETag"),
                "error": None,
            }
    except HTTPError as exc:
        return {
            "probe_status": "failed",
            "http_status": exc.code,
            "content_length": None,
            "effective_url": url,
            "etag": None,
            "error": str(exc),
        }
    except URLError as exc:
        return {
            "probe_status": "failed",
            "http_status": None,
            "content_length": None,
            "effective_url": url,
            "etag": None,
            "error": str(exc),
        }


def probe_local_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "probe_status": "failed",
            "content_length": None,
            "effective_url": str(path),
            "etag": None,
            "error": "local source file not found",
        }
    return {
        "probe_status": "ok",
        "content_length": path.stat().st_size,
        "effective_url": str(path),
        "etag": None,
        "error": None,
    }


def probe_huggingface(settings: AppSettings, entry: ModelEntry) -> dict[str, Any]:
    try:
        from huggingface_hub import get_hf_file_metadata, hf_hub_url
    except ImportError as exc:
        raise AppError("DEPENDENCY_UNAVAILABLE", details={"dependency": "huggingface_hub"}) from exc
    if entry.repo_id is None or entry.filename is None:
        raise AppError("REQUEST_INVALID", details={"resource": "model", "reason": "repo_id_and_filename_required"})
    token = settings.comfy.hf_token.get_secret_value() or None
    url = hf_hub_url(repo_id=entry.repo_id, filename=entry.filename, endpoint=settings.comfy.hf_endpoint)
    try:
        metadata = get_hf_file_metadata(url, token=token)
        return {
            "probe_status": "ok",
            "http_status": 200,
            "content_length": metadata.size,
            "effective_url": metadata.location,
            "etag": metadata.etag,
            "error": None,
        }
    except Exception as exc:
        return {
            "probe_status": "failed",
            "http_status": None,
            "content_length": None,
            "effective_url": url,
            "etag": None,
            "error": str(exc),
        }


def format_size_hint(size: int | None) -> str | None:
    if size is None:
        return None
    units = [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]
    for suffix, factor in units:
        if size >= factor:
            return f"{size / factor:.2f}{suffix}"
    return f"{size}B"


def probe_size_check_status(expected: int | None, actual: int | None) -> str:
    if expected is None:
        return "not_configured"
    if actual is None:
        return "unknown"
    if expected == actual:
        return "matched"
    return "mismatched"


def model_contract_result(model_id: str, entry: ModelEntry, destination: Path | None) -> dict[str, Any]:
    if entry.filename is None:
        raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "filename_required"})
    result: dict[str, Any] = {
        "id": model_id,
        "name": entry.name,
        "source": entry.source,
        "target": entry.target,
        "filename": entry.filename,
        "target_path": str(PurePosixPath(entry.target) / entry.filename),
        "path": str(destination) if destination is not None else None,
        "size_hint": entry.size_hint,
        "size_bytes": entry.size_bytes,
        "sha256": entry.sha256,
    }
    if entry.source == "url":
        result["url"] = str(entry.url) if entry.url is not None else None
    elif entry.source == "huggingface":
        result["repo_id"] = entry.repo_id
    elif entry.source == "local":
        result["source_path"] = entry.path
    return result


def download_model_by_id(
    settings: AppSettings,
    model_id: str,
    *,
    models_dir: str | None = None,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if model_id not in bundle.models:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "model", "id": model_id})
    root = resolve_models_dir(settings, models_dir)
    return download_model_entry(settings, model_id, bundle.models[model_id], root)


def download_workflow_models(
    settings: AppSettings,
    workflow_id: str,
    *,
    models_dir: str | None = None,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    bundle = load_catalog(catalog_dir)
    if workflow_id not in bundle.workflows:
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "workflow", "id": workflow_id})
    root = resolve_models_dir(settings, models_dir)
    workflow = bundle.workflows[workflow_id]
    return {
        "workflow": workflow_id,
        "models_dir": str(root),
        "items": [download_model_entry(settings, model_id, bundle.models[model_id], root) for model_id in workflow.models],
    }


def download_model_entry(settings: AppSettings, model_id: str, entry: ModelEntry, models_dir: Path) -> dict[str, Any]:
    destination = destination_for_model(models_dir, entry)
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = existing_model_download_result(settings, model_id, entry, destination)
    if existing is not None:
        return existing
    lock_file = shared_model_download_lock_path(models_dir, entry.target, entry.filename)
    with WorkspaceLock(
        lock_file,
        details={
            "resource": "model",
            "id": model_id,
            "reason": "model_download_in_progress",
            "path": str(destination),
            "lock_file": str(lock_file),
        },
    ):
        existing = existing_model_download_result(settings, model_id, entry, destination)
        if existing is not None:
            return existing
        if entry.source == "url":
            if entry.url is None:
                raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "url_required"})
            download_url(str(entry.url), destination, size_bytes=entry.size_bytes, sha256=entry.sha256)
        elif entry.source == "huggingface":
            download_huggingface(settings, entry, destination)
        elif entry.source == "local":
            if entry.path is None:
                raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "path_required"})
            copy_local_model(Path(entry.path).expanduser(), destination, size_bytes=entry.size_bytes, sha256=entry.sha256)
        else:
            raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "unsupported_source"})
        verify_size_bytes(destination, entry.size_bytes)
        verify_sha256(destination, entry.sha256)
        return model_download_result(settings, model_id, entry, destination, "downloaded")


def existing_model_download_result(settings: AppSettings, model_id: str, entry: ModelEntry, destination: Path) -> dict[str, Any] | None:
    if destination.exists():
        if not destination.is_file():
            raise AppError(
                "RESOURCE_CONFLICT",
                details={"resource": "model", "id": model_id, "reason": "destination_not_file", "path": str(destination)},
            )
        verify_size_bytes(destination, entry.size_bytes)
        verify_sha256(destination, entry.sha256)
        return model_download_result(settings, model_id, entry, destination, "exists")
    return None


def model_download_result(settings: AppSettings, model_id: str, entry: ModelEntry, destination: Path, status: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        **model_contract_result(model_id, entry, destination),
        "status": status,
        "local_size": destination.stat().st_size if destination.is_file() else None,
    }
    if entry.source == "url":
        result["url"] = str(entry.url) if entry.url is not None else None
    elif entry.source == "huggingface":
        result["repo_id"] = entry.repo_id
        result["hf_endpoint"] = settings.comfy.hf_endpoint
    elif entry.source == "local":
        result["source_path"] = entry.path
    return result


def download_url(url: str, destination: Path, *, size_bytes: int | None = None, sha256: str | None = None) -> None:
    tmp = destination.with_name(f".{destination.name}.tmp")
    tmp.unlink(missing_ok=True)
    try:
        request = Request(url, headers={"User-Agent": "comfy-shell-v3"})
        with urlopen(request) as response, tmp.open("wb") as output:
            shutil.copyfileobj(response, output)
        verify_size_bytes(tmp, size_bytes)
        verify_sha256(tmp, sha256)
        os.replace(tmp, destination)
    except AppError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise AppError("DEPENDENCY_UNAVAILABLE", details={"dependency": "url_download", "url": url, "error": str(exc)}) from exc


def download_huggingface(settings: AppSettings, entry: ModelEntry, destination: Path) -> None:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise AppError("DEPENDENCY_UNAVAILABLE", details={"dependency": "huggingface_hub"}) from exc
    if entry.repo_id is None or entry.filename is None:
        raise AppError("REQUEST_INVALID", details={"resource": "model", "reason": "repo_id_and_filename_required"})
    token = settings.comfy.hf_token.get_secret_value() or None
    try:
        downloaded = hf_hub_download(
            repo_id=entry.repo_id,
            filename=entry.filename,
            local_dir=huggingface_local_dir(destination, entry.filename),
            endpoint=settings.comfy.hf_endpoint,
            token=token,
        )
        downloaded_path = Path(downloaded)
        if downloaded_path.resolve() != destination.resolve():
            verify_size_bytes(downloaded_path, entry.size_bytes)
            verify_sha256(downloaded_path, entry.sha256)
            os.replace(downloaded_path, destination)
        else:
            try:
                verify_size_bytes(destination, entry.size_bytes)
                verify_sha256(destination, entry.sha256)
            except AppError:
                destination.unlink(missing_ok=True)
                raise
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            "DEPENDENCY_UNAVAILABLE",
            details={"dependency": "huggingface_hub", "repo_id": entry.repo_id, "filename": entry.filename, "error": str(exc)},
        ) from exc


def huggingface_local_dir(destination: Path, filename: str) -> Path:
    root = destination
    for _part in PurePosixPath(filename).parts:
        root = root.parent
    return root


def copy_local_model(source: Path, destination: Path, *, size_bytes: int | None = None, sha256: str | None = None) -> None:
    if not source.is_file():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "local_model", "path": str(source)})
    tmp = destination.with_name(f".{destination.name}.tmp")
    tmp.unlink(missing_ok=True)
    try:
        shutil.copyfile(source, tmp)
        verify_size_bytes(tmp, size_bytes)
        verify_sha256(tmp, sha256)
        os.replace(tmp, destination)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def verify_sha256(path: Path, expected: str | None) -> None:
    if expected is None:
        return
    actual = file_sha256(path)
    if actual != expected:
        raise AppError("RESOURCE_CONFLICT", details={"reason": "sha256_mismatch", "path": str(path), "actual": actual, "expected": expected})


def verify_size_bytes(path: Path, expected: int | None) -> None:
    if expected is None:
        return
    actual = path.stat().st_size
    if actual != expected:
        raise AppError("RESOURCE_CONFLICT", details={"reason": "size_mismatch", "path": str(path), "actual": actual, "expected": expected})


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
