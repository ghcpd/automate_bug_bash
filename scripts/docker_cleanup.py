#!/usr/bin/env python3
"""Utility to clean up Docker containers and images produced by the tb pipeline.

Patterns cleaned:
  Containers:
    tb-s5-*          S5 agent solver containers
    tb-backfill-*    backfill_frozen_requirements containers
    tb-debug-*       ad-hoc debug containers

  Images:
    tb-verify/*      S3/S5 repo verification images
    tb-harbor/*      Harbor task images (built by S8)

Usage:
    python scripts/docker_cleanup.py             # dry run (shows what would be removed)
    python scripts/docker_cleanup.py --run        # remove stopped containers
    python scripts/docker_cleanup.py --run --images  # containers + images
    python scripts/docker_cleanup.py --run --force   # force-remove running containers too
"""
from __future__ import annotations

import argparse
import subprocess
import sys

CONTAINER_PREFIXES = ("tb-s5-", "tb-backfill-", "tb-debug-")
IMAGE_REPO_PREFIXES = ("tb-verify/", "tb-harbor/")


def _docker(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(["docker"] + args, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def _list_containers(include_running: bool = False) -> list[dict]:
    filters = [] if include_running else [
        "--filter", "status=exited",
        "--filter", "status=created",
        "--filter", "status=dead",
    ]
    rc, out = _docker(["ps", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}"] + filters)
    if rc != 0 or not out:
        return []
    containers = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        cid, name = parts[0], parts[1]
        status = parts[2] if len(parts) > 2 else ""
        if any(name.startswith(p) for p in CONTAINER_PREFIXES):
            containers.append({"id": cid, "name": name, "status": status})
    return containers


def _list_images() -> list[dict]:
    rc, out = _docker(["images", "--format", "{{.ID}}\t{{.Repository}}\t{{.Tag}}\t{{.Size}}"])
    if rc != 0 or not out:
        return []
    images = []
    for line in out.splitlines():
        parts = line.split("\t", 3)
        if len(parts) < 3:
            continue
        iid, repo, tag = parts[0], parts[1], parts[2]
        size = parts[3] if len(parts) > 3 else "?"
        if any(repo.startswith(p) for p in IMAGE_REPO_PREFIXES):
            images.append({"id": iid, "repo": repo, "tag": tag, "size": size})
    return images


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="store_true",
                        help="Actually remove (default: dry-run)")
    parser.add_argument("--images", action="store_true",
                        help="Also remove tb-verify/* and tb-harbor/* images")
    parser.add_argument("--force", action="store_true",
                        help="Force-remove running containers too (implies --run)")
    args = parser.parse_args()

    dry_run = not args.run and not args.force
    include_running = args.force

    if dry_run:
        print("DRY RUN — pass --run to actually remove\n")

    # --- Containers ---
    containers = _list_containers(include_running=include_running)
    running = [c for c in containers if "Up" in c["status"]]
    stopped = [c for c in containers if "Up" not in c["status"]]

    print(f"Containers: {len(containers)} ({len(stopped)} stopped, {len(running)} running)")
    for c in containers:
        tag = " [running]" if "Up" in c["status"] else ""
        print(f"  {c['name']}{tag}")

    if not dry_run and containers:
        ids = [c["id"] for c in containers]
        rm_flags = ["-f"] if args.force else []
        rc, out = _docker(["rm"] + rm_flags + ids)
        if rc == 0:
            print(f"  ✓ Removed {len(ids)} containers")
        else:
            n_ok = out.count("\n") + 1 if out else 0
            print(f"  ~ Removed some containers (errors below):", file=sys.stderr)
            for line in out.splitlines():
                if "Error" in line or "error" in line:
                    print(f"    {line}", file=sys.stderr)

    # --- Images ---
    images = _list_images()
    if args.images or args.force:
        print(f"\nImages: {len(images)}")
        for img in images:
            print(f"  {img['repo']}:{img['tag']}  ({img['size']})")

        if not dry_run and images:
            ids = list({img["id"] for img in images})
            rc, out = _docker(["rmi", "-f"] + ids)
            removed = out.count("Untagged:")
            print(f"  ✓ Untagged {removed}/{len(ids)} images")
            for line in out.splitlines():
                if "Error" in line or "error" in line:
                    print(f"  ✗ {line}", file=sys.stderr)
    else:
        if images:
            print(f"\nImages (skipped): {len(images)} — pass --images to also remove")

    if dry_run:
        print("\nRe-run with --run [--images] [--force] to apply.")


if __name__ == "__main__":
    main()
