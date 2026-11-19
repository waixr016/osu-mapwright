"""Install wheels by unzipping them, bypassing pip.

``pip`` cannot run in this sandbox: it creates its scratch directories with
``tempfile.mkdtemp``, whose DACL the sandbox denies, so every install fails at
the "move into place" step. A wheel is just a zip, so extracting it is enough.

Usage::

    python scripts/install_wheels.py build/wheels .deps
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def install(wheel: Path, target: Path) -> int:
    written = 0
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            parts = member.filename.split("/")
            if len(parts) >= 3 and parts[1] == "data":
                bucket, rest = parts[2], parts[3:]
                if bucket in ("purelib", "platlib"):
                    destination = target.joinpath(*rest)
                elif bucket == "scripts":
                    destination = target.joinpath("Scripts", *rest)
                else:
                    continue
            else:
                destination = target.joinpath(*parts)

            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as sink:
                sink.write(source.read())
            written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheels", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--only", default=None, help="glob filter, e.g. 'torch-2.14*'")
    args = parser.parse_args(argv)

    args.target.mkdir(parents=True, exist_ok=True)
    pattern = args.only or "*.whl"
    files = sorted(args.wheels.glob(pattern))
    if not files:
        raise SystemExit(f"no wheels matching {pattern} in {args.wheels}")

    for wheel in files:
        count = install(wheel, args.target)
        print(f"  {wheel.name:55s} {count:5d} files")
    print(f"\ninstalled {len(files)} wheels into {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
