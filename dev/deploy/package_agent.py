from __future__ import annotations

import sys
from pathlib import Path

# Runnable directly as well as imported by release_dev.py, so dev/ has to be
# on sys.path either way: running this file puts only its own folder there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import gzip
import os
import tarfile
import tempfile
from pathlib import Path

from paths import ROOT
from registry import get_agent_spec

from deploy.dependencies import export_requirements
from deploy.sources import source_entries

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


def package_agent(agent_name: str, output: Path) -> Path:
    spec = get_agent_spec(agent_name)
    entries = source_entries(spec)
    requirements = export_requirements(spec)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="agent-package-") as temp_dir:
        requirements_path = Path(temp_dir) / REQUIREMENTS_FILENAME
        requirements_path.write_text(
            "\n".join(requirements) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        with (
            output.open("wb") as raw,
            gzip.GzipFile(
                filename=GZIP_HEADER_FILENAME,
                mode="wb",
                fileobj=raw,
                mtime=GZIP_MTIME,
            ) as compressed,
            tarfile.open(fileobj=compressed, mode="w") as archive,
        ):
            sources = [(requirements_path, REQUIREMENTS_FILENAME)]
            sources.extend((entry.path, entry.archive_name) for entry in entries)
            for source, name in sources:
                info = _normalized_tarinfo(source, name)
                if source.is_file():
                    with source.open("rb") as handle:
                        archive.addfile(info, handle)
                else:
                    archive.addfile(info)

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a deterministic source archive for one Agent Engine application."
    )
    parser.add_argument("--agent", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    os.chdir(ROOT)
    output = Path(args.output) if args.output else DEFAULT_ARTIFACT_DIR / f"{args.agent}.tar.gz"
    archive = package_agent(args.agent, output)
    print(f"AGENT_ARCHIVE={archive}")


if __name__ == "__main__":
    main()
