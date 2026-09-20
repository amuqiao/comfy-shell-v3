from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.core.config.env_manifest import ENV_KEY_MANIFEST
from app.core.config.settings import AppSettings, validate_app_env_key_drift

KEY_PATTERN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_keys(path: Path) -> list[tuple[int, str]]:
    keys: list[tuple[int, str]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = KEY_PATTERN.match(line)
        if match:
            keys.append((line_no, match.group(1)))
    return keys


def check_env_file(path: Path) -> list[str]:
    issues: list[str] = []
    allowed = ENV_KEY_MANIFEST.example_keys
    for line_no, key in parse_keys(path):
        if key != key.upper():
            issues.append(f"{path}:{line_no}: config key must be uppercase: {key}")
        elif key in ENV_KEY_MANIFEST.deprecated_keys:
            issues.append(f"{path}:{line_no}: deprecated config key: {key}")
        elif key in ENV_KEY_MANIFEST.derived_keys:
            issues.append(f"{path}:{line_no}: derived config key must not be set: {key}")
        elif key not in allowed:
            issues.append(f"{path}:{line_no}: unknown config key: {key}")
    return issues


def check_example_alignment(path: Path) -> list[str]:
    issues: list[str] = []
    actual = frozenset(key for _line, key in parse_keys(path))
    missing = sorted(ENV_KEY_MANIFEST.example_keys - actual)
    extra = sorted(actual - ENV_KEY_MANIFEST.example_keys)
    for key in missing:
        issues.append(f"{path}: missing config key from .env.example: {key}")
    for key in extra:
        issues.append(f"{path}: key is not defined by env manifest: {key}")
    return issues


def validate_profiles() -> list[str]:
    issues: list[str] = []
    try:
        validate_app_env_key_drift()
        AppSettings()
    except Exception as exc:
        issues.append(f"local settings failed: {type(exc).__name__}: {exc}")
    try:
        AppSettings(
            runtime={"app_env": "prd"},
            security={"service_api_key": "prd-secret-token-123456", "disable_auth": False},
            storage={"backend": "disabled"},
        )
    except Exception as exc:
        issues.append(f"release settings failed: {type(exc).__name__}: {exc}")
    return issues


def main() -> int:
    example_path = ROOT_DIR / ".env.example"
    local_env_path = ROOT_DIR / ".env"
    issues = []
    issues.extend(check_env_file(example_path))
    issues.extend(check_example_alignment(example_path))
    if local_env_path.exists():
        issues.extend(check_env_file(local_env_path))
    issues.extend(validate_profiles())
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    print("OK env-config")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
