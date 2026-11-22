"""Build the export sidecar's font bundle, services/pptx-emit-huashu/fonts-liberation.tar.gz.

The sidecar's Chromium on Databricks Apps lays out every font stack with no loaded
webfont in the container's own faces. This bundle gives it the Liberation fonts,
metric-compatible with Arial, Times New Roman and Courier New (and so Helvetica,
Times and Courier), and the fontconfig that makes Chromium use them
(fonts.conf.in, beside this script). setup.sh extracts it at boot and writes
fonts/fonts.conf from the template; the export's wrapper points FONTCONFIG_FILE
at it (src/services/pptx_from_html_huashu.py).

    python scripts/sidecar_fonts/build_fonts_tarball.py [--release-tarball PATH] [--out PATH]

The faces come from one pinned upstream release, checked against its SHA-256: the
download, or a copy of it given with --release-tarball. The bundle holds, under
fonts/: the twelve faces (regular, bold, italic and bold italic of Sans, Serif and
Mono) in liberation/, the release's LICENSE (SIL Open Font License 1.1),
fonts.conf.in, and SOURCE, naming the release and its checksum.

It is reproducible: every member has a fixed mtime, owner and mode, the members
are in a fixed order, and the gzip header carries no name or time, so two builds
from the same release are byte-identical. Standard library only.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).resolve().parent / "fonts.conf.in"
OUT = REPO_ROOT / "services" / "pptx-emit-huashu" / "fonts-liberation.tar.gz"

RELEASE = "2.1.5"
RELEASE_URL = (
    "https://github.com/liberationfonts/liberation-fonts/files/7261482/"
    "liberation-fonts-ttf-2.1.5.tar.gz"
)
RELEASE_SHA256 = "7191c669bf38899f73a2094ed00f7b800553364f90e2637010a69c0e268f25d0"
RELEASE_DIR = f"liberation-fonts-ttf-{RELEASE}"
FACES = tuple(
    f"Liberation{family}-{style}.ttf"
    for family in ("Sans", "Serif", "Mono")
    for style in ("Regular", "Bold", "Italic", "BoldItalic")
)
LICENSE = "LICENSE"

BUNDLE_DIR = "fonts"
# Every member's mtime: the release's date (2021-09-30), so the bundle's bytes
# do not depend on when it was built.
MEMBER_MTIME = 1632960000
FILE_MODE = 0o644
DIR_MODE = 0o755


def release_bytes(path: Path | None) -> bytes:
    """The pinned release tarball, from ``path`` or downloaded; checked against RELEASE_SHA256."""
    if path is not None:
        data = path.read_bytes()
    else:
        with urllib.request.urlopen(RELEASE_URL, timeout=120) as response:
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != RELEASE_SHA256:
        raise ValueError(
            f"the Liberation {RELEASE} release's SHA-256 is {digest}, "
            f"not the pinned {RELEASE_SHA256}"
        )
    return data


def release_members(data: bytes) -> dict[str, bytes]:
    """The faces and the licence, by their name in the release."""
    wanted = {f"{RELEASE_DIR}/{name}": name for name in (*FACES, LICENSE)}
    found: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as release:
        for member in release.getmembers():
            if member.name in wanted and member.isfile():
                extracted = release.extractfile(member)
                if extracted is not None:
                    found[wanted[member.name]] = extracted.read()
    missing = sorted(set(wanted.values()) - set(found))
    if missing:
        raise ValueError(f"the Liberation {RELEASE} release lacks {missing}")
    return found


def source_note() -> bytes:
    """SOURCE: where the faces came from."""
    return (
        f"Liberation fonts {RELEASE}, TTF release\n"
        f"{RELEASE_URL}\n"
        f"sha256 {RELEASE_SHA256}\n"
        f"Built by scripts/sidecar_fonts/build_fonts_tarball.py.\n"
    ).encode("utf-8")


def bundle_files(members: dict[str, bytes], template: bytes) -> list[tuple[str, bytes]]:
    """(path in the bundle, bytes) for every file, in the bundle's order."""
    files = [
        (f"{BUNDLE_DIR}/{LICENSE}", members[LICENSE]),
        (f"{BUNDLE_DIR}/SOURCE", source_note()),
        (f"{BUNDLE_DIR}/fonts.conf.in", template),
    ]
    files.extend((f"{BUNDLE_DIR}/liberation/{name}", members[name]) for name in sorted(FACES))
    return files


def _member(name: str, size: int, *, directory: bool) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.size = 0 if directory else size
    info.mode = DIR_MODE if directory else FILE_MODE
    info.mtime = MEMBER_MTIME
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def bundle_bytes(files: list[tuple[str, bytes]]) -> bytes:
    """The bundle as gzip bytes: its directories, then its files, every header fixed."""
    directories = sorted({str(Path(name).parent) for name, _ in files} | {BUNDLE_DIR})
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
        for directory in directories:
            bundle.addfile(_member(directory + "/", 0, directory=True))
        for name, data in files:
            bundle.addfile(_member(name, len(data), directory=False), io.BytesIO(data))
    gzip_buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=gzip_buffer, mtime=0, compresslevel=9
    ) as stream:
        stream.write(tar_buffer.getvalue())
    return gzip_buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--release-tarball", type=Path, help="a copy of the pinned release, not downloaded"
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    try:
        members = release_members(release_bytes(args.release_tarball))
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    data = bundle_bytes(bundle_files(members, TEMPLATE.read_bytes()))
    args.out.write_bytes(data)
    print(f"{args.out}: {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
