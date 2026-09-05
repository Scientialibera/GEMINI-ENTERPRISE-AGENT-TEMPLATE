from __future__ import annotations

import argparse
import gzip
import os
from pathlib import Path
import tarfile

from common import ROOT, get_agent_spec


def _normalized_tarinfo(path: Path, arcname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(arcname)
    stat = path.stat()
    info.mode = stat.st_mode & 0o777
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    if path.is_file():
        info.size = stat.st_size
        info.type = tarfile.REGTYPE
    else:
        info.type = tarfile.DIRTYPE
    return info


def _add_path(tar: tarfile.TarFile, source: Path, arcname: str) -> None:
    if source.is_dir():
        tar.addfile(_normalized_tarinfo(source, arcname))
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _add_path(tar, child, f"{arcname}/{child.name}")
        return

    info = _normalized_tarinfo(source, arcname)
    with source.open("rb") as handle:
        tar.addfile(info, handle)


def package(agent_name: str, output: Path) -> Path:
    spec = get_agent_spec(agent_name)
    output.parent.mkdir(parents=True, exist_ok=True)

    requirements = "\n".join(spec.requirements) + "\n"
    requirements_path = ROOT / ".package-requirements.tmp"
    requirements_path.write_text(requirements, encoding="utf-8", newline="\n")

    try:
        with output.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w") as tar:
                    _add_path(tar, requirements_path, "requirements.txt")
                    for package_path in spec.extra_packages:
                        source = ROOT / package_path
                        if not source.exists():
                            raise FileNotFoundError(source)
                        _add_path(tar, source, source.name)
    finally:
        requirements_path.unlink(missing_ok=True)

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a deterministic Agent Engine source archive for Terraform."
    )
    parser.add_argument("--agent", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    os.chdir(ROOT)
    output = (
        Path(args.output)
        if args.output
        else ROOT / "artifacts" / f"{args.agent}.tar.gz"
    )
    archive = package(args.agent, output.resolve())
    print(f"AGENT_ARCHIVE={archive}")


if __name__ == "__main__":
    main()
