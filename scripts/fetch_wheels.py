"""Download wheels for the optional Beat This! backend.

``pip`` cannot reach PyPI from this sandbox (it hangs before logging anything),
but plain ``urllib`` can, so this script resolves wheels itself and then hands
the directory to ``pip --no-index``.

Usage::

    python scripts/fetch_wheels.py --dest build/wheels --target .deps

After it finishes, run with ``PYTHONPATH=.deps`` (or install the wheels into
your own environment).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_PROXY = os.environ.get("MAPWRIGHT_PROXY", "http://127.0.0.1:7892")

#: everything Beat This! needs, minus numpy (already present in the runtime)
PACKAGES = [
    "torch",
    "torchaudio",
    "filelock",
    "typing-extensions",
    "sympy",
    "mpmath",
    "networkx",
    "jinja2",
    "MarkupSafe",
    "fsspec",
    "setuptools",
    "einops",
    "rotary-embedding-torch",
    "soxr",
    "beat-this",
]

WHEEL_PATTERN = re.compile(r"(?P<name>[^-]+)-(?P<ver>[^-]+)(-(?P<build>[^-]+))?-")


def _opener(proxy: str | None):
    if not proxy:
        return urllib.request.build_opener()
    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    return urllib.request.build_opener(handler)


def _score(filename: str) -> int:
    name = filename.lower()
    if "py3-none-any" in name or "py2.py3-none-any" in name:
        return 10
    if "win_amd64" in name and ("cp312" in name or "abi3" in name):
        return 20 if "cp312" in name else 15
    if "win_amd64" in name:
        return 5
    return 0


def pick_wheel(releases: list[dict]) -> dict | None:
    candidates = [item for item in releases if item["filename"].endswith(".whl")]
    if not candidates:
        return None
    return max(candidates, key=lambda item: _score(item["filename"]))


def fetch(name: str, dest: Path, opener, *, include_prerelease: bool = False) -> Path:
    url = f"https://pypi.org/pypi/{name}/json"
    with opener.open(url, timeout=30) as response:
        data = json.load(response)
    release = pick_wheel(data["urls"])
    if release is None:
        raise SystemExit(f"no wheel available for {name}")

    target = dest / release["filename"]
    if target.exists() and target.stat().st_size == release["size"]:
        print(f"  cached  {release['filename']}")
        return target

    print(f"  get     {release['filename']}  ({release['size'] / 1e6:.1f} MB)")
    with opener.open(release["url"], timeout=120) as response:
        payload = response.read()
    target.write_bytes(payload)
    if len(payload) != release["size"]:
        raise SystemExit(f"size mismatch for {target.name}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", type=Path, default=Path("build/wheels"))
    parser.add_argument("--proxy", default=DEFAULT_PROXY)
    parser.add_argument("--packages", nargs="*", default=PACKAGES)
    args = parser.parse_args(argv)

    args.dest.mkdir(parents=True, exist_ok=True)
    opener = _opener(args.proxy)

    failed: list[str] = []
    for name in args.packages:
        try:
            fetch(name, args.dest, opener)
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"  FAIL    {name}: {error}")
            failed.append(name)

    total = sum(path.stat().st_size for path in args.dest.glob("*.whl"))
    print(f"\n{len(list(args.dest.glob('*.whl')))} wheels, {total / 1e6:.1f} MB in {args.dest}")
    if failed:
        print(f"failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
