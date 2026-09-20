from __future__ import annotations

import hashlib
import os
import re
import shutil
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator, model_validator

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
WorkflowStatus = Literal["planned", "testing", "ready", "deprecated"]
PluginSource = Literal["git", "registry", "manual"]
PluginScope = Literal["per-runtime", "shared"]
PluginStatus = Literal["planned", "approved", "installed", "deprecated"]


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
        return validate_relative_catalog_path(value, "target")

    @model_validator(mode="after")
    def validate_source_fields(self) -> "PluginEntry":
        if self.source == "git" and self.repo is None:
            raise ValueError("git source requires repo")
        if self.source == "registry" and not self.registry_id:
            raise ValueError("registry source requires registry_id")
        if self.source == "manual" and not self.install_hint:
            raise ValueError("manual source requires install_hint")
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


class CatalogBundle(StrictCatalogModel):
    models: dict[str, ModelEntry]
    workflows: dict[str, WorkflowEntry]
    plugins: dict[str, PluginEntry]


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
    merged: dict[str, Any] = {"schema_version": CATALOG_SCHEMA_VERSION, section: {}}
    files = sorted(section_dir.glob("*.toml"))
    if not files:
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


def load_catalog(catalog_dir: Path | None = None) -> CatalogBundle:
    root = (catalog_dir or default_catalog_dir()).resolve()
    try:
        models_catalog = load_models_catalog(root)
        workflows_catalog = load_workflows_catalog(root)
        plugins_catalog = load_plugins_catalog(root)
        bundle = CatalogBundle(
            models=models_catalog.models,
            workflows=workflows_catalog.workflows,
            plugins=plugins_catalog.plugins,
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
        if workflow.workflow_file is not None and not (catalog_dir / workflow.workflow_file).is_file():
            raise AppError(
                "RESOURCE_NOT_FOUND",
                details={"resource": "workflow_file", "id": workflow_id, "path": workflow.workflow_file},
            )


def catalog_summary(catalog_dir: Path | None = None) -> dict[str, int]:
    bundle = load_catalog(catalog_dir)
    return {
        "models": len(bundle.models),
        "workflows": len(bundle.workflows),
        "plugins": len(bundle.plugins),
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
    raise AppError("REQUEST_INVALID", details={"field": "kind", "reason": "expected models, workflows, or plugins"})


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
    if destination.exists():
        if not destination.is_file():
            raise AppError(
                "RESOURCE_CONFLICT",
                details={"resource": "model", "id": model_id, "reason": "destination_not_file", "path": str(destination)},
            )
        verify_sha256(destination, entry.sha256)
        return {"id": model_id, "status": "exists", "path": str(destination), "target": entry.target}
    if entry.source == "url":
        if entry.url is None:
            raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "url_required"})
        download_url(str(entry.url), destination)
    elif entry.source == "huggingface":
        download_huggingface(settings, entry, destination)
    elif entry.source == "local":
        if entry.path is None:
            raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "path_required"})
        copy_local_model(Path(entry.path).expanduser(), destination)
    else:
        raise AppError("REQUEST_INVALID", details={"resource": "model", "id": model_id, "reason": "unsupported_source"})
    verify_sha256(destination, entry.sha256)
    return {"id": model_id, "status": "downloaded", "path": str(destination), "target": entry.target}


def download_url(url: str, destination: Path) -> None:
    tmp = destination.with_name(f".{destination.name}.tmp")
    tmp.unlink(missing_ok=True)
    try:
        request = Request(url, headers={"User-Agent": "comfy-shell-v3"})
        with urlopen(request) as response, tmp.open("wb") as output:
            shutil.copyfileobj(response, output)
        os.replace(tmp, destination)
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
        if Path(downloaded).resolve() != destination.resolve():
            os.replace(downloaded, destination)
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


def copy_local_model(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise AppError("RESOURCE_NOT_FOUND", details={"resource": "local_model", "path": str(source)})
    tmp = destination.with_name(f".{destination.name}.tmp")
    tmp.unlink(missing_ok=True)
    shutil.copyfile(source, tmp)
    os.replace(tmp, destination)


def verify_sha256(path: Path, expected: str | None) -> None:
    if expected is None:
        return
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise AppError("RESOURCE_CONFLICT", details={"reason": "sha256_mismatch", "path": str(path), "actual": actual, "expected": expected})
