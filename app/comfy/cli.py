from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pydantic import ValidationError

from app.comfy import models, process, versions
from app.comfy.workspace import init_workspace
from app.core.config import get_settings
from app.core.exceptions import AppError


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


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

    model = subparsers.add_parser("models")
    model_subparsers = model.add_subparsers(dest="action", required=True)
    model_subparsers.add_parser("link")
    model_subparsers.add_parser("list")
    model_download = model_subparsers.add_parser("download")
    model_download.add_argument("repo_id")
    model_download.add_argument("--filename")
    model_download.add_argument("--target", default="checkpoints")

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
    if args.domain == "models" and args.action == "link":
        return models.link_models(settings)
    if args.domain == "models" and args.action == "list":
        return {"items": models.list_models(settings)}
    if args.domain == "models" and args.action == "download":
        return models.hf_download(settings, args.repo_id, args.filename, args.target)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except AppError as exc:
        print_json({"code": exc.code, "details": exc.details})
        return 1
    except ValidationError as exc:
        print_json({"code": "REQUEST_INVALID", "details": {"errors": exc.errors()}})
        return 2
    if result is not None:
        print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
