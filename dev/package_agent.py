from __future__ import annotations

import argparse
import gzip
import os
import tarfile
import tempfile
from pathlib import Path

from common import ROOT, get_agent_spec


DEFAULT_ARTIFACT_DIR = ROOT / "artifacts"
REQUIREMENTS_FILENAME = "requirements.txt"
GZIP_HEADER_FILENAME = ""
GZIP_MTIME = 0
TAR_MTIME = 0
NORMALIZED_UID = 0
NORMALIZED_GID = 0
NORMALIZED_FILE_MODE = 0o644
NORMALIZED_DIRECTORY_MODE = 0o755


def _normalized_tarinfo(path: Path, arcname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(arcname)
    info.uid = NORMALIZED_UID
    info.gid = NORMALIZED_GID
    info.uname = ""
    info.gname = ""
    info.mtime = TAR_MTIME

    if path.is_file():
        info.mode = NORMALIZED_FILE_MODE
        info.size = path.stat().st_size
        info.type = tarfile.REGTYPE
    else:
        info.mode = NORMALIZED_DIRECTORY_MODE
        info.type = tarfile.DIRTYPE
    return info


def _add_path(archive: tarfile.TarFile, source: Path, arcname: str) -> None:
    if source.is_dir():
        archive.addfile(_normalized_tarinfo(source, arcname))
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _add_path(archive, child, f"{arcname}/{child.name}")
        return

    info = _normalized_tarinfo(source, arcname)
    with source.open("rb") as handle:
        archive.addfile(info, handle)


def package_agent(agent_name: str, output: Path) -> Path:
    spec = get_agent_spec(agent_name)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="agent-package-") as temp_dir:
        requirements_path = Path(temp_dir) / REQUIREMENTS_FILENAME
        requirements_path.write_text(
            "\n".join(spec.requirements) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        with output.open("wb") as raw:
            with gzip.GzipFile(
                filename=GZIP_HEADER_FILENAME,
                mode="wb",
                fileobj=raw,
                mtime=GZIP_MTIME,
            ) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    _add_path(archive, requirements_path, REQUIREMENTS_FILENAME)
                    for package_path in spec.extra_packages:
                        source = ROOT / package_path
                        if not source.exists():
                            raise FileNotFoundError(source)
                        _add_path(archive, source, source.name)

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
        else DEFAULT_ARTIFACT_DIR / f"{args.agent}.tar.gz"
    )
    archive = package_agent(args.agent, output)
    print(f"AGENT_ARCHIVE={archive}")


if __name__ == "__main__":
    main()
