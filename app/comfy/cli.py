from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.comfy import catalog, envs, models, process, runtimes, versions
from app.comfy.workspace import init_workspace
from app.core.config import get_settings
from app.core.exceptions import AppError


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comfyctl")
    subparsers = parser.add_subparsers(dest="domain", required=True)

    workspace = subparsers.add_parser("workspace")
    workspace_subparsers = workspace.add_subparsers(dest="action", required=True)
    workspace_subparsers.add_parser("init")

    version = subparsers.add_parser("versions")
    version_subparsers = version.add_subparsers(dest="action", required=True)
    version_fetch = version_subparsers.add_parser("fetch")
    version_fetch.add_argument("ref")
    version_use = version_subparsers.add_parser("use")
    version_use.add_argument("name")
    version_subparsers.add_parser("list")
    version_subparsers.add_parser("current")

    env = subparsers.add_parser("envs")
    env_subparsers = env.add_subparsers(dest="action", required=True)
    env_prepare = env_subparsers.add_parser("prepare")
    env_prepare.add_argument("name")
    env_subparsers.add_parser("list")
    env_subparsers.add_parser("current")

    runtime = subparsers.add_parser("runtimes")
    runtime_subparsers = runtime.add_subparsers(dest="action", required=True)
    runtime_import = runtime_subparsers.add_parser("import")
    runtime_import.add_argument("name")
    runtime_import.add_argument("--comfy-dir", required=True)
    runtime_import.add_argument("--venv-dir", required=True)
    runtime_stage_zip = runtime_subparsers.add_parser("stage-zip")
    runtime_stage_zip.add_argument("name")
    runtime_stage_zip.add_argument("--archive", required=True)
    runtime_stage_zip.add_argument("--seed-runtime", required=True)
    runtime_use = runtime_subparsers.add_parser("use")
    runtime_use.add_argument("name")
    runtime_subparsers.add_parser("list")
    runtime_subparsers.add_parser("current")

    model = subparsers.add_parser("models")
    model_subparsers = model.add_subparsers(dest="action", required=True)
    model_subparsers.add_parser("link")
    model_subparsers.add_parser("list")
    model_download = model_subparsers.add_parser("download")
    model_download.add_argument("repo_id")
    model_download.add_argument("--filename")
    model_download.add_argument("--target", default="checkpoints")

    catalog_parser = subparsers.add_parser("catalog")
    catalog_parser.add_argument("--catalog-dir")
    catalog_subparsers = catalog_parser.add_subparsers(dest="action", required=True)
    catalog_subparsers.add_parser("validate")
    catalog_list = catalog_subparsers.add_parser("list")
    catalog_list.add_argument("kind", choices=["models", "workflows", "plugins", "assets"])
    catalog_show = catalog_subparsers.add_parser("show")
    catalog_show.add_argument("kind", choices=["model", "workflow", "plugin", "asset"])
    catalog_show.add_argument("id")
    catalog_inspect = catalog_subparsers.add_parser("inspect")
    catalog_inspect.add_argument("kind", choices=["model", "workflow"])
    catalog_inspect.add_argument("id")
    catalog_inspect.add_argument("--models-dir")
    catalog_probe = catalog_subparsers.add_parser("probe")
    catalog_probe.add_argument("kind", choices=["model", "workflow"])
    catalog_probe.add_argument("id")
    catalog_missing = catalog_subparsers.add_parser("missing")
    catalog_missing.add_argument("kind", choices=["workflow"])
    catalog_missing.add_argument("id")
    catalog_missing.add_argument("--models-dir")
    catalog_metadata = catalog_subparsers.add_parser("metadata")
    catalog_metadata.add_argument("kind", choices=["model", "workflow"])
    catalog_metadata.add_argument("id")
    catalog_metadata.add_argument("--models-dir")
    catalog_enrich = catalog_subparsers.add_parser("enrich")
    catalog_enrich.add_argument("kind", choices=["model", "workflow"])
    catalog_enrich.add_argument("id")
    catalog_enrich.add_argument("--models-dir")
    catalog_enrich.add_argument("--write", action="store_true")
    catalog_enrich.add_argument("--overwrite", action="store_true")
    catalog_download = catalog_subparsers.add_parser("download")
    catalog_download.add_argument("kind", choices=["model", "workflow"])
    catalog_download.add_argument("id")
    catalog_download.add_argument("--models-dir")
    catalog_install = catalog_subparsers.add_parser("install")
    catalog_install.add_argument("kind", choices=["plugin", "plugins"])
    catalog_install.add_argument("id", nargs="?")
    catalog_update = catalog_subparsers.add_parser("update")
    catalog_update.add_argument("kind", choices=["plugin", "plugins"])
    catalog_update.add_argument("id", nargs="?")
    catalog_installed = catalog_subparsers.add_parser("installed")
    catalog_installed.add_argument("kind", choices=["plugin", "plugins"])
    catalog_installed.add_argument("id", nargs="?")

    service = subparsers.add_parser("service")
    service_subparsers = service.add_subparsers(dest="action", required=True)
    service_subparsers.add_parser("start")
    service_subparsers.add_parser("stop")
    service_subparsers.add_parser("status")
    service_logs = service_subparsers.add_parser("logs")
    service_logs.add_argument("--lines", type=int, default=80)

    return parser


def run(args: argparse.Namespace) -> Any:
    settings = get_settings()
    if args.domain == "workspace" and args.action == "init":
        paths = init_workspace(settings)
        return {"workspace": str(paths.root)}
    if args.domain == "versions" and args.action == "fetch":
        return versions.fetch_version(settings, args.ref)
    if args.domain == "versions" and args.action == "use":
        return versions.use_version(settings, args.name)
    if args.domain == "versions" and args.action == "list":
        return {"items": versions.list_versions(settings)}
    if args.domain == "versions" and args.action == "current":
        return versions.current_version(settings)
    if args.domain == "envs" and args.action == "prepare":
        return envs.prepare_env(settings, args.name)
    if args.domain == "envs" and args.action == "list":
        return {"items": envs.list_envs(settings)}
    if args.domain == "envs" and args.action == "current":
        return envs.current_env(settings)
    if args.domain == "runtimes" and args.action == "import":
        return runtimes.import_runtime(settings, args.name, args.comfy_dir, args.venv_dir)
    if args.domain == "runtimes" and args.action == "stage-zip":
        return runtimes.stage_runtime_from_zip(settings, args.name, args.archive, args.seed_runtime)
    if args.domain == "runtimes" and args.action == "use":
        return runtimes.use_runtime(settings, args.name)
    if args.domain == "runtimes" and args.action == "list":
        return {"items": runtimes.list_runtimes(settings)}
    if args.domain == "runtimes" and args.action == "current":
        return runtimes.current_runtime(settings)
    if args.domain == "models" and args.action == "link":
        return models.link_models(settings)
    if args.domain == "models" and args.action == "list":
        return {"items": models.list_models(settings)}
    if args.domain == "models" and args.action == "download":
        return models.hf_download(settings, args.repo_id, args.filename, args.target)
    catalog_dir = Path(args.catalog_dir).expanduser().resolve() if getattr(args, "catalog_dir", None) else None
    if args.domain == "catalog" and args.action == "validate":
        return catalog.catalog_summary(catalog_dir)
    if args.domain == "catalog" and args.action == "list":
        return {"items": catalog.list_entries(args.kind, catalog_dir)}
    if args.domain == "catalog" and args.action == "show" and args.kind == "model":
        return catalog.show_model(args.id, catalog_dir)
    if args.domain == "catalog" and args.action == "show" and args.kind == "plugin":
        return catalog.show_plugin(args.id, catalog_dir)
    if args.domain == "catalog" and args.action == "show" and args.kind == "asset":
        return catalog.show_asset(args.id, catalog_dir)
    if args.domain == "catalog" and args.action == "show" and args.kind == "workflow":
        return catalog.show_workflow(args.id, catalog_dir)
    if args.domain == "catalog" and args.action == "inspect" and args.kind == "model":
        return catalog.inspect_model_by_id(settings, args.id, models_dir=args.models_dir, catalog_dir=catalog_dir)
    if args.domain == "catalog" and args.action == "inspect" and args.kind == "workflow":
        return catalog.inspect_workflow_models(settings, args.id, models_dir=args.models_dir, catalog_dir=catalog_dir)
    if args.domain == "catalog" and args.action == "probe" and args.kind == "model":
        return catalog.probe_model_by_id(settings, args.id, catalog_dir=catalog_dir)
    if args.domain == "catalog" and args.action == "probe" and args.kind == "workflow":
        return catalog.probe_workflow_models(settings, args.id, catalog_dir=catalog_dir)
    if args.domain == "catalog" and args.action == "missing" and args.kind == "workflow":
        return catalog.missing_workflow_models(settings, args.id, models_dir=args.models_dir, catalog_dir=catalog_dir)
    if args.domain == "catalog" and args.action == "metadata" and args.kind == "model":
        return catalog.metadata_model_by_id(settings, args.id, models_dir=args.models_dir, catalog_dir=catalog_dir)
    if args.domain == "catalog" and args.action == "metadata" and args.kind == "workflow":
        return catalog.metadata_workflow_models(settings, args.id, models_dir=args.models_dir, catalog_dir=catalog_dir)
    if args.domain == "catalog" and args.action == "enrich" and args.kind == "model":
        return catalog.enrich_model_by_id(
            settings,
            args.id,
            models_dir=args.models_dir,
            catalog_dir=catalog_dir,
            write=args.write,
            overwrite=args.overwrite,
        )
    if args.domain == "catalog" and args.action == "enrich" and args.kind == "workflow":
        return catalog.enrich_workflow_models(
            settings,
            args.id,
            models_dir=args.models_dir,
            catalog_dir=catalog_dir,
            write=args.write,
            overwrite=args.overwrite,
        )
    if args.domain == "catalog" and args.action == "download" and args.kind == "model":
        return catalog.download_model_by_id(settings, args.id, models_dir=args.models_dir, catalog_dir=catalog_dir)
    if args.domain == "catalog" and args.action == "download" and args.kind == "workflow":
        return catalog.download_workflow_models(settings, args.id, models_dir=args.models_dir, catalog_dir=catalog_dir)
    if args.domain == "catalog" and args.action == "install" and args.kind == "plugin":
        require_cli_id(args, "usage: comfyctl catalog install plugin <id>")
        return catalog.install_plugin_by_id(settings, args.id, catalog_dir)
    if args.domain == "catalog" and args.action == "install" and args.kind == "plugins":
        reject_cli_id(args, "usage: comfyctl catalog install plugins")
        return catalog.install_all_plugins(settings, catalog_dir)
    if args.domain == "catalog" and args.action == "update" and args.kind == "plugin":
        require_cli_id(args, "usage: comfyctl catalog update plugin <id>")
        return catalog.update_plugin_by_id(settings, args.id, catalog_dir)
    if args.domain == "catalog" and args.action == "update" and args.kind == "plugins":
        reject_cli_id(args, "usage: comfyctl catalog update plugins")
        return catalog.update_all_plugins(settings, catalog_dir)
    if args.domain == "catalog" and args.action == "installed" and args.kind == "plugin":
        require_cli_id(args, "usage: comfyctl catalog installed plugin <id>")
        return catalog.show_installed_plugin(settings, args.id, catalog_dir)
    if args.domain == "catalog" and args.action == "installed" and args.kind == "plugins":
        reject_cli_id(args, "usage: comfyctl catalog installed plugins")
        return catalog.list_installed_plugins(settings, catalog_dir)
    if args.domain == "service" and args.action == "start":
        return process.start(settings)
    if args.domain == "service" and args.action == "stop":
        return process.stop(settings)
    if args.domain == "service" and args.action == "status":
        return process.status(settings)
    if args.domain == "service" and args.action == "logs":
        print(process.tail_log(settings, lines=args.lines))
        return None
    raise AppError("REQUEST_INVALID", details={"reason": "unknown_cli_command"})


def require_cli_id(args: argparse.Namespace, usage: str) -> None:
    if not getattr(args, "id", None):
        raise AppError("REQUEST_INVALID", details={"reason": "missing_id", "usage": usage})


def reject_cli_id(args: argparse.Namespace, usage: str) -> None:
    if getattr(args, "id", None):
        raise AppError("REQUEST_INVALID", details={"reason": "unexpected_id", "usage": usage})


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except AppError as exc:
        print_json({"code": exc.code, "details": exc.details})
        return 1
    except ValidationError as exc:
        print_json({"code": "REQUEST_INVALID", "details": {"errors": exc.errors(include_context=False)}})
        return 2
    if result is not None:
        print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
