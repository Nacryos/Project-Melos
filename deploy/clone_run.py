"""Start a container with the same mounts, environment and command as an existing one, plus extras.

Release T layers on whatever release is live (S once S is live) without copying its recipe:

    python3 clone_run.py --from melos-api --name melos-api-canary-t --port 8792 --image melos-api:20261009t \
        --mount /host/file:/container/file:ro --env NAME=value

Resource and isolation flags are the standing ones of every Melos API release (release_r.sh).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

STANDING = ["--restart", "unless-stopped", "--cpus=2", "--cpu-shares=256", "--memory=8g", "--memory-swap=8g",
            "--pids-limit=128", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--user=1000:1000", "--log-driver=local", "--log-opt", "max-size=10m",
            "--log-opt", "max-file=3"]


def inspect(name: str) -> dict:
    return json.loads(subprocess.run(["docker", "inspect", name], check=True, capture_output=True, text=True).stdout)[0]


def build_args(source: dict, name: str, port: int, image: str, mounts: list[str], env: list[str]) -> list[str]:
    extra_targets = {m.split(":")[1] for m in mounts}
    extra_names = {e.split("=", 1)[0] for e in env}
    image_env = set(inspect(source["Config"]["Image"])["Config"].get("Env") or [])
    args = ["docker", "run", "-d", "--name", name, *STANDING]
    networks = list((source["NetworkSettings"].get("Networks") or {}).keys())
    if networks:
        args += ["--network", networks[0]]
    args += ["-p", f"127.0.0.1:{port}:8791"]
    for item in source["Config"].get("Env") or []:
        if item in image_env or item.split("=", 1)[0] in extra_names:
            continue
        args += ["-e", item]
    for item in env:
        args += ["-e", item]
    for bind in source["HostConfig"].get("Binds") or []:
        if bind.split(":")[1] in extra_targets:
            continue
        args += ["-v", bind]
    for item in mounts:
        args += ["-v", item]
    args.append(image)
    args += source["Config"]["Cmd"]
    return args


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--mount", action="append", default=[])
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    argv = build_args(inspect(args.source), args.name, args.port, args.image, args.mount, args.env)
    printable = [a if not a.startswith(("TYPESAFE", "JEV_")) else a.split("=")[0] + "=…" for a in argv]
    print(" ".join(printable), file=sys.stderr)
    if not args.dry_run:
        subprocess.run(argv, check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
