from __future__ import annotations

import argparse
import sys
from urllib.parse import quote, urlsplit


def password_from_args(args: argparse.Namespace) -> str | None:
    if args.password and args.password_stdin:
        raise SystemExit("ERROR: use either --password or --password-stdin, not both")
    if args.password_stdin:
        return sys.stdin.read().rstrip("\n")
    return args.password


def print_summary(url: str) -> None:
    parsed = urlsplit(url)
    database = parsed.path.lstrip("/") if parsed.path else "-"
    print(f"# scheme={parsed.scheme}")
    print(f"# host={parsed.hostname or '-'}")
    print(f"# port={parsed.port or '-'}")
    print(f"# database={database or '-'}")
    print(f"# username={parsed.username or '-'}")
    print(f"# password_present={str(parsed.password is not None).lower()}")


def build_postgres(args: argparse.Namespace) -> str:
    password = password_from_args(args)
    user = quote(args.username, safe="")
    password_part = f":{quote(password, safe='')}" if password is not None else ""
    port_part = f":{args.port}" if args.port else ""
    database = quote(args.database, safe="")
    return f"postgresql+asyncpg://{user}{password_part}@{args.host}{port_part}/{database}"


def build_redis(args: argparse.Namespace) -> str:
    password = password_from_args(args)
    auth = ""
    if args.username and password is None:
        raise SystemExit("ERROR: redis --username requires --password or --password-stdin")
    if args.username:
        auth = f"{quote(args.username, safe='')}:{quote(password or '', safe='')}@"
    elif password is not None:
        auth = f":{quote(password, safe='')}@"
    port_part = f":{args.port}" if args.port else ""
    return f"redis://{auth}{args.host}{port_part}/{args.db}"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Generate encoded DATABASE__URL or REDIS__URL values.")
    subparsers = root.add_subparsers(dest="kind", required=True)

    postgres = subparsers.add_parser("postgres", help="Generate DATABASE__URL.")
    postgres.add_argument("--username", required=True)
    postgres.add_argument("--host", required=True)
    postgres.add_argument("--database", required=True)
    postgres.add_argument("--password")
    postgres.add_argument("--password-stdin", action="store_true")
    postgres.add_argument("--port", type=int)

    redis = subparsers.add_parser("redis", help="Generate REDIS__URL.")
    redis.add_argument("--host", required=True)
    redis.add_argument("--username")
    redis.add_argument("--password")
    redis.add_argument("--password-stdin", action="store_true")
    redis.add_argument("--port", type=int)
    redis.add_argument("--db", type=int, default=0)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.kind == "postgres":
        url = build_postgres(args)
        print(f"DATABASE__URL={url}")
        print_summary(url)
        return 0
    if args.kind == "redis":
        url = build_redis(args)
        print(f"REDIS__URL={url}")
        print_summary(url)
        return 0
    raise AssertionError(args.kind)


if __name__ == "__main__":
    raise SystemExit(main())
