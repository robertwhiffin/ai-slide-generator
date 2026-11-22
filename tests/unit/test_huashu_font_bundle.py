"""The export sidecar's font bundle (Task 15 B8, N3).

On Databricks Apps the sidecar's Chromium laid out every font stack with no
loaded webfont in the base image's DejaVu, 10-38 % wider than a desktop's faces,
so text broke differently from the user's machine. The sidecar now ships the
Liberation faces, metric-compatible with Arial, Times New Roman and Courier New,
and the fontconfig that makes Chromium use them:

* ``services/pptx-emit-huashu/fonts-liberation.tar.gz``, built reproducibly by
  ``scripts/sidecar_fonts/build_fonts_tarball.py`` from one pinned upstream
  release, with its OFL licence and ``scripts/sidecar_fonts/fonts.conf.in``;
* ``setup.sh`` extracts it into ``fonts/`` at boot, idempotently, and writes
  ``fonts/fonts.conf`` with the directory's absolute path (the base image's
  fontconfig 2.13 takes absolute dirs only);
* ``sidecar_subprocess_env`` points ``FONTCONFIG_FILE`` at that file, the one
  variable the sidecar's env allowlist gained;
* the wheel ships the tarball (``scripts/verify_app_wheel.py`` requires it) and
  never the extracted ``fonts/``.

The checksums below are the upstream release's own files, read independently of
the build script.
"""

from __future__ import annotations

import ast
import ctypes
import ctypes.util
import fnmatch
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import xml.dom.minidom
from pathlib import Path

import pytest

from scripts.sidecar_fonts import build_fonts_tarball
from scripts.verify_app_wheel import BOOTSTRAP_FILES
from src.services import pptx_from_html_huashu

REPO_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_DIR = REPO_ROOT / "services" / "pptx-emit-huashu"
BUNDLE = SIDECAR_DIR / "fonts-liberation.tar.gz"
TEMPLATE = REPO_ROOT / "scripts" / "sidecar_fonts" / "fonts.conf.in"
APP_SETUP_PY = REPO_ROOT / "packages" / "databricks-tellr-app" / "setup.py"

# sha256 of each file in liberation-fonts-ttf-2.1.5.tar.gz (the pinned release): each face,
# Liberation<name>.ttf, and the licence.
_FACE_SHA256 = {
    "Mono-Bold": "bd62a0672d0b9b6710b01df434c80ad54fa5f0835207eb7b17b7a761463067bb",
    "Mono-BoldItalic": "79451f3c09fe25116098853b7a2ca6e2436220ccc11af022979adbcf195be130",
    "Mono-Italic": "605c01c711b44480a7508d349dfbf3264e81fa43d69e61cfa7d10b86e764c4d1",
    "Mono-Regular": "f2b83c763e8afd21709333370bed4774337fae82267937e2b5aea7e2fbd922c1",
    "Sans-Bold": "788abee4c806d660e8aee46689dd8540cd4bb98da03dcc9d171ce3efd99a9173",
    "Sans-BoldItalic": "698da70fc191cc5f33ad4d6d3fe830fe4624b898ea2e3169955928b7c491f1ee",
    "Sans-Italic": "e5bae5c4cde31f22142753855f4f8fb86da6ff39955ed3c0a11248b0d16948b0",
    "Sans-Regular": "76d04c18ea243f426b7de1f3ad208e927008f961dc5945e5aad352d0dfde8ee8",
    "Serif-Bold": "d754ba427cfe0bca54ae052384baa8f842da5bd6550ad4da024ac441e7a7d5ce",
    "Serif-BoldItalic": "f17db8af71e24d2066b587546021d4f0b296be389512b658dec3c09affeb11a7",
    "Serif-Italic": "0e3dea9f8d613e006ccfa62201f33e265d19167bd0907725c3e145368b04fc2e",
    "Serif-Regular": "058ea80864aef09a23f45cbec2bb5400bc3dfbdea01c3f10538a21fcb497fb74",
}
UPSTREAM_SHA256 = {
    **{f"Liberation{face}.ttf": digest for face, digest in _FACE_SHA256.items()},
    "LICENSE": "93fed46019c38bbe566b479d22148e2e8a1e85ada614accb0211c37b2c61c19b",
}
UPSTREAM_RELEASE_SHA256 = "7191c669bf38899f73a2094ed00f7b800553364f90e2637010a69c0e268f25d0"


def _bundle_members() -> dict[str, tarfile.TarInfo]:
    with tarfile.open(BUNDLE, mode="r:gz") as bundle:
        return {member.name.rstrip("/"): member for member in bundle.getmembers()}


def _bundle_file(name: str) -> bytes:
    with tarfile.open(BUNDLE, mode="r:gz") as bundle:
        extracted = bundle.extractfile(name)
        assert extracted is not None, name
        return extracted.read()


# ---------------------------------------------------------------------------
# The committed bundle
# ---------------------------------------------------------------------------


class TestTheBundle:
    def test_it_holds_the_twelve_faces_their_licence_and_the_fontconfig_template(self) -> None:
        names = set(_bundle_members())

        faces = {f"fonts/liberation/{name}" for name in UPSTREAM_SHA256 if name.endswith(".ttf")}
        assert len(faces) == 12
        assert names == {
            "fonts",
            "fonts/liberation",
            "fonts/LICENSE",
            "fonts/SOURCE",
            "fonts/fonts.conf.in",
            *faces,
        }

    def test_its_faces_and_licence_are_the_pinned_releases_own_bytes(self) -> None:
        for name, digest in UPSTREAM_SHA256.items():
            path = f"fonts/liberation/{name}" if name.endswith(".ttf") else f"fonts/{name}"
            assert hashlib.sha256(_bundle_file(path)).hexdigest() == digest, path

    def test_its_licence_is_the_sil_open_font_licence(self) -> None:
        licence = _bundle_file("fonts/LICENSE").decode("utf-8")

        assert "SIL OPEN FONT LICENSE Version 1.1" in licence
        assert "Reserved Font Name Liberation" in licence

    def test_it_names_its_source_release_and_checksum(self) -> None:
        source = _bundle_file("fonts/SOURCE").decode("utf-8")

        assert "Liberation fonts 2.1.5" in source
        assert UPSTREAM_RELEASE_SHA256 in source
        assert build_fonts_tarball.RELEASE_SHA256 == UPSTREAM_RELEASE_SHA256

    def test_its_template_is_the_committed_one(self) -> None:
        assert _bundle_file("fonts/fonts.conf.in") == TEMPLATE.read_bytes()

    def test_the_build_script_rebuilds_it_byte_for_byte(self) -> None:
        """Reproducible: the release's faces and licence, packed again, are the committed bytes."""
        members = {
            name: _bundle_file(
                f"fonts/liberation/{name}" if name.endswith(".ttf") else f"fonts/{name}"
            )
            for name in UPSTREAM_SHA256
        }

        rebuilt = build_fonts_tarball.bundle_bytes(
            build_fonts_tarball.bundle_files(members, TEMPLATE.read_bytes())
        )

        assert rebuilt == BUNDLE.read_bytes()

    def test_its_headers_carry_no_build_time_or_builder(self) -> None:
        for member in _bundle_members().values():
            assert (member.mtime, member.uid, member.gid, member.uname, member.gname) == (
                build_fonts_tarball.MEMBER_MTIME,
                0,
                0,
                "",
                "",
            ), member.name
        # The gzip header's own time (bytes 4-7) is zero too.
        assert BUNDLE.read_bytes()[4:8] == b"\0\0\0\0"

    def test_the_build_refuses_a_release_that_is_not_the_pinned_one(self, tmp_path: Path) -> None:
        other = tmp_path / "release.tar.gz"
        other.write_bytes(b"not the release")

        with pytest.raises(ValueError, match="SHA-256"):
            build_fonts_tarball.release_bytes(other)


# ---------------------------------------------------------------------------
# setup.sh
# ---------------------------------------------------------------------------


def _sidecar_copy(directory: Path) -> Path:
    """A sidecar directory holding setup.sh and the font bundle alone."""
    directory.mkdir(parents=True)
    shutil.copy2(SIDECAR_DIR / "setup.sh", directory / "setup.sh")
    shutil.copy2(BUNDLE, directory / BUNDLE.name)
    return directory


def _run_setup(directory: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    # No node_modules here: the Chromium step is skipped, nothing is downloaded.
    return subprocess.run(
        ["sh", str(directory / "setup.sh")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )


def _face_digests(directory: Path) -> dict[str, str]:
    """The sha256 of each face extracted into a sidecar directory's fonts/liberation."""
    faces = directory / "fonts" / "liberation"
    if not faces.is_dir():
        return {}
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in faces.iterdir()}


_RELEASE_FACES = {name: digest for name, digest in UPSTREAM_SHA256.items() if name.endswith(".ttf")}


def _truncated_bundle() -> bytes:
    """The bundle cut off halfway, as an interrupted copy or download leaves it: tar extracts
    the members before the cut, part of the next, and then fails."""
    data = BUNDLE.read_bytes()
    truncated = data[: len(data) // 2]
    with pytest.raises((EOFError, tarfile.ReadError)):
        with tarfile.open(fileobj=io.BytesIO(truncated), mode="r:gz") as bundle:
            bundle.getmembers()
    return truncated


def _removable(path: Path) -> bool:
    """Whether the current user can remove ``path`` despite its directory's mode (root can),
    read without removing it: ``os.access`` on the directory for writing."""
    return os.access(path.parent, os.W_OK)


def _later_than(path: Path, seconds: int) -> None:
    """Sets ``path``'s mtime ``seconds`` after now (before it, when negative)."""
    moment = time.time() + seconds
    os.utime(path, (moment, moment))


def _written_config(directory: Path) -> xml.dom.minidom.Document:
    return xml.dom.minidom.parseString((directory / "fonts" / "fonts.conf").read_bytes())


def _dirs(config: xml.dom.minidom.Document) -> list[str]:
    return [node.firstChild.data for node in config.getElementsByTagName("dir")]


@pytest.mark.skipif(shutil.which("sh") is None, reason="requires sh")
class TestSetupScript:
    def test_it_extracts_the_bundle_and_writes_the_config_with_its_own_absolute_dir(
        self, tmp_path: Path
    ) -> None:
        sidecar = _sidecar_copy(tmp_path / "sidecar")

        result = _run_setup(sidecar)

        assert result.returncode == 0, result.stderr
        for name in UPSTREAM_SHA256:
            if name.endswith(".ttf"):
                assert (sidecar / "fonts" / "liberation" / name).is_file(), name
        config_text = (sidecar / "fonts" / "fonts.conf").read_text()
        assert "@FONTS_DIR@" not in config_text
        assert _dirs(_written_config(sidecar))[0] == str(sidecar.resolve() / "fonts" / "liberation")

    def test_a_second_boot_keeps_the_extracted_bundle(self, tmp_path: Path) -> None:
        sidecar = _sidecar_copy(tmp_path / "sidecar")
        assert _run_setup(sidecar).returncode == 0
        marker = sidecar / "fonts" / "liberation" / "kept"
        marker.write_text("")

        assert _run_setup(sidecar).returncode == 0

        assert marker.exists(), "an up-to-date bundle was extracted again"
        assert (sidecar / "fonts" / "fonts.conf").is_file()

    def test_a_newer_bundle_is_extracted_again(self, tmp_path: Path) -> None:
        sidecar = _sidecar_copy(tmp_path / "sidecar")
        assert _run_setup(sidecar).returncode == 0
        marker = sidecar / "fonts" / "liberation" / "stale"
        marker.write_text("")
        later = (sidecar / "fonts").stat().st_mtime + 60
        os.utime(sidecar / BUNDLE.name, (later, later))

        assert _run_setup(sidecar).returncode == 0

        assert not marker.exists(), "a newer bundle was not extracted"
        assert (sidecar / "fonts" / "liberation" / "LiberationSans-Regular.ttf").is_file()

    def test_a_path_with_xml_and_sed_specials_is_written_as_itself(self, tmp_path: Path) -> None:
        sidecar = _sidecar_copy(tmp_path / "a&b#c<d>" / "sidecar")

        assert _run_setup(sidecar).returncode == 0

        assert _dirs(_written_config(sidecar))[0] == str(sidecar.resolve() / "fonts" / "liberation")

    def test_an_interrupted_extraction_is_completed_on_the_next_boot(self, tmp_path: Path) -> None:
        """A boot whose extraction failed part way (the bundle cut off halfway) leaves no config
        pointing at part of a bundle; the next boot, with the whole bundle, whose mtime is older
        than that first boot (an unchanged install), ends with all twelve faces, each the
        release's own bytes, and the config."""
        sidecar = _sidecar_copy(tmp_path / "sidecar")
        (sidecar / BUNDLE.name).write_bytes(_truncated_bundle())

        assert _run_setup(sidecar).returncode == 0

        assert not (sidecar / "fonts" / "fonts.conf").exists(), (
            "a config was written for a bundle that did not extract"
        )
        shutil.copyfile(BUNDLE, sidecar / BUNDLE.name)
        _later_than(sidecar / BUNDLE.name, -3600)

        assert _run_setup(sidecar).returncode == 0

        assert _face_digests(sidecar) == _RELEASE_FACES
        assert _dirs(_written_config(sidecar))[0] == str(sidecar.resolve() / "fonts" / "liberation")

    def test_a_newer_bundle_that_fails_to_extract_leaves_the_whole_one_in_place(
        self, tmp_path: Path
    ) -> None:
        """A newer bundle cut off halfway: the faces and config already in place stay whole."""
        sidecar = _sidecar_copy(tmp_path / "sidecar")
        assert _run_setup(sidecar).returncode == 0
        (sidecar / BUNDLE.name).write_bytes(_truncated_bundle())
        _later_than(sidecar / BUNDLE.name, 3600)

        assert _run_setup(sidecar).returncode == 0

        assert _face_digests(sidecar) == _RELEASE_FACES
        assert _dirs(_written_config(sidecar))[0] == str(sidecar.resolve() / "fonts" / "liberation")

    def test_a_failed_extraction_is_tried_again_on_the_next_boot(self, tmp_path: Path) -> None:
        """Boot 1 (two hours ago) extracted a whole bundle; a newer one, installed an hour ago,
        failed to extract on boot 2, which still wrote the config (moving fonts/'s mtime past
        the bundle's). Boot 3, the bundle intact, extracts it: nothing of boot 1's stays."""
        sidecar = _sidecar_copy(tmp_path / "sidecar")
        assert _run_setup(sidecar).returncode == 0
        marker = sidecar / "fonts" / "liberation" / "from-boot-1"
        marker.write_text("")
        for path in [sidecar / "fonts", *(sidecar / "fonts").rglob("*")]:
            _later_than(path, -7200)
        (sidecar / BUNDLE.name).write_bytes(_truncated_bundle())
        _later_than(sidecar / BUNDLE.name, -3600)
        assert _run_setup(sidecar).returncode == 0
        assert marker.exists(), "fixture drift: boot 2's failed extraction replaced the bundle"
        shutil.copyfile(BUNDLE, sidecar / BUNDLE.name)
        _later_than(sidecar / BUNDLE.name, -3600)

        assert _run_setup(sidecar).returncode == 0

        assert not marker.exists(), "the bundle that failed to extract was not tried again"
        assert _face_digests(sidecar) == _RELEASE_FACES

    def test_a_partial_bundle_an_earlier_setup_left_gets_no_config(self, tmp_path: Path) -> None:
        """A fonts/ holding part of a bundle and a config for it, as a cut-off extraction under
        the earlier setup.sh left it: a boot whose own extraction fails removes the config, so
        the wrapper sets no FONTCONFIG_FILE; the next whole extraction replaces the part."""
        sidecar = _sidecar_copy(tmp_path / "sidecar")
        partial = sidecar / "fonts" / "liberation"
        partial.mkdir(parents=True)
        shutil.copyfile(TEMPLATE, sidecar / "fonts" / "fonts.conf.in")
        (sidecar / "fonts" / "fonts.conf").write_text("<fontconfig/>")
        (partial / "LiberationMono-Bold.ttf").write_bytes(
            _bundle_file("fonts/liberation/LiberationMono-Bold.ttf")
        )
        (sidecar / BUNDLE.name).write_bytes(_truncated_bundle())

        assert _run_setup(sidecar).returncode == 0

        assert not (sidecar / "fonts" / "fonts.conf").exists(), (
            "a config names a bundle that is not whole"
        )
        shutil.copyfile(BUNDLE, sidecar / BUNDLE.name)

        assert _run_setup(sidecar).returncode == 0

        assert _face_digests(sidecar) == _RELEASE_FACES
        assert _dirs(_written_config(sidecar))[0] == str(sidecar.resolve() / "fonts" / "liberation")

    @pytest.mark.parametrize("failing", ["rm", "touch"])
    def test_a_failing_command_in_the_font_step_still_reaches_the_chromium_step(
        self, tmp_path: Path, failing: str
    ) -> None:
        """The font step is a warning, never a stop, under setup.sh's ``set -e``: with ``rm``
        unable to clear a stale fonts/ directory, or ``touch`` failing, setup still runs the
        Chromium install (here a stand-in ``node`` that records its arguments)."""
        sidecar = _sidecar_copy(tmp_path / "sidecar")
        (sidecar / "node_modules" / "playwright").mkdir(parents=True)
        (sidecar / "node_modules" / "playwright" / "cli.js").write_text("")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        record = tmp_path / "node-arguments"
        commands = {"node": f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{record}"\n'}
        locked = sidecar / "fonts" / "locked"
        if failing == "touch":
            commands["touch"] = "#!/bin/sh\nexit 1\n"
        else:
            locked.mkdir(parents=True)
            (locked / "face.ttf").write_text("")
            locked.chmod(0o555)
        for name, script in commands.items():
            (bin_dir / name).write_text(script)
            (bin_dir / name).chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        try:
            if failing == "rm" and _removable(locked / "face.ttf"):
                pytest.skip("rm cannot fail here: the tests run as a user no mode stops")

            result = _run_setup(sidecar, env)
        finally:
            # Wherever setup left it, so the temporary directory can be removed.
            for directory in sidecar.rglob(locked.name):
                directory.chmod(0o755)

        assert result.returncode == 0, result.stderr
        assert record.is_file() and record.read_text().splitlines() == [
            "node_modules/playwright/cli.js install chromium"
        ], "setup stopped before the Chromium step"

    def test_without_the_bundle_setup_still_finishes(self, tmp_path: Path) -> None:
        sidecar = tmp_path / "sidecar"
        sidecar.mkdir()
        shutil.copy2(SIDECAR_DIR / "setup.sh", sidecar / "setup.sh")

        result = _run_setup(sidecar)

        assert result.returncode == 0, result.stderr
        assert not (sidecar / "fonts").exists()


# ---------------------------------------------------------------------------
# What the written config resolves (where a fontconfig library is loadable)
# ---------------------------------------------------------------------------

_FONTCONFIG = ctypes.util.find_library("fontconfig")


@pytest.mark.skipif(_FONTCONFIG is None, reason="requires the fontconfig library (Linux)")
@pytest.mark.skipif(shutil.which("sh") is None, reason="requires sh")
def test_the_config_resolves_each_core_font_and_generic_to_its_liberation_face(
    tmp_path: Path,
) -> None:
    """Through the library Chromium itself uses: each core name and generic is a Liberation face."""
    sidecar = _sidecar_copy(tmp_path / "sidecar")
    assert _run_setup(sidecar).returncode == 0
    script = f"""
import ctypes, json, os, sys
os.environ["FONTCONFIG_FILE"] = {str(sidecar / "fonts" / "fonts.conf")!r}
lib = ctypes.CDLL({_FONTCONFIG!r})
lib.FcInitLoadConfigAndFonts.restype = ctypes.c_void_p
lib.FcNameParse.restype = ctypes.c_void_p
lib.FcNameParse.argtypes = [ctypes.c_char_p]
lib.FcConfigSubstitute.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
lib.FcDefaultSubstitute.argtypes = [ctypes.c_void_p]
lib.FcFontMatch.restype = ctypes.c_void_p
lib.FcFontMatch.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
lib.FcPatternFormat.restype = ctypes.c_char_p
lib.FcPatternFormat.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
config = lib.FcInitLoadConfigAndFonts()
out = {{}}
for family in json.loads(sys.argv[1]):
    pattern = lib.FcNameParse(family.encode())
    lib.FcConfigSubstitute(config, pattern, 0)
    lib.FcDefaultSubstitute(pattern)
    result = ctypes.c_int(0)
    match = lib.FcFontMatch(config, pattern, ctypes.byref(result))
    out[family] = lib.FcPatternFormat(match, b"%{{family[0]}}").decode()
print(json.dumps(out))
"""
    families = {
        "Arial": "Liberation Sans",
        "Helvetica": "Liberation Sans",
        "sans-serif": "Liberation Sans",
        "Times New Roman": "Liberation Serif",
        "Times": "Liberation Serif",
        "serif": "Liberation Serif",
        "Courier New": "Liberation Mono",
        "Courier": "Liberation Mono",
        "monospace": "Liberation Mono",
    }
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(list(families))],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(result.stdout) == families


# ---------------------------------------------------------------------------
# The sidecar's environment
# ---------------------------------------------------------------------------


class TestSidecarEnvironment:
    def test_fontconfig_file_is_the_sidecars_own_config_where_it_is_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "fonts" / "fonts.conf"
        config.parent.mkdir()
        config.write_text("<fontconfig/>")
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_FONTCONFIG_FILE", config)
        monkeypatch.setenv("FONTCONFIG_FILE", "/etc/fonts/other.conf")

        env = pptx_from_html_huashu.sidecar_subprocess_env()

        assert env["FONTCONFIG_FILE"] == str(config)

    def test_without_the_bundle_the_sidecar_gets_no_config_of_its_own(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_FONTCONFIG_FILE", tmp_path / "fonts" / "fonts.conf"
        )
        monkeypatch.delenv("FONTCONFIG_FILE", raising=False)

        env = pptx_from_html_huashu.sidecar_subprocess_env()

        assert "FONTCONFIG_FILE" not in env

    def test_the_config_is_the_sidecars_fonts_directory(self) -> None:
        assert pptx_from_html_huashu.SIDECAR_FONTCONFIG_FILE == (
            pptx_from_html_huashu.SIDECAR_DIR / "fonts" / "fonts.conf"
        )

    def test_fontconfig_file_is_the_one_variable_the_allowlist_gained(self) -> None:
        """The allowlist before the bundle, plus FONTCONFIG_FILE alone (the brief's amendment)."""
        before = {
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TMPDIR",
            "LD_LIBRARY_PATH",
            "PLAYWRIGHT_BROWSERS_PATH",
            "XDG_CACHE_HOME",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "NODE_EXTRA_CA_CERTS",
        }

        assert set(pptx_from_html_huashu._SIDECAR_ENV_ALLOWLIST) == before | {"FONTCONFIG_FILE"}


# ---------------------------------------------------------------------------
# The wheel
# ---------------------------------------------------------------------------


def _sidecar_ignore_patterns() -> list[str]:
    """The patterns packages/databricks-tellr-app/setup.py leaves out of the wheel's sidecar."""
    tree = ast.parse(APP_SETUP_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_SIDECAR_IGNORE"
            for target in node.targets
        ):
            call = node.value
            assert isinstance(call, ast.Call)
            return [arg.value for arg in call.args if isinstance(arg, ast.Constant)]
    raise AssertionError("no _SIDECAR_IGNORE in setup.py")


class TestTheWheel:
    def test_the_publish_guard_requires_the_bundle(self) -> None:
        assert "fonts-liberation.tar.gz" in BOOTSTRAP_FILES

    def test_the_wheel_ships_the_bundle_but_never_its_extracted_fonts(self) -> None:
        """Nor the staging directory an interrupted extraction leaves (setup.sh)."""
        patterns = _sidecar_ignore_patterns()

        assert not any(fnmatch.fnmatch(BUNDLE.name, pattern) for pattern in patterns)
        for extracted in ("fonts", "fonts-staging"):
            assert any(fnmatch.fnmatch(extracted, pattern) for pattern in patterns), extracted

    def test_the_extracted_fonts_are_never_committed_or_uploaded(self) -> None:
        for ignore_file in (".gitignore", ".databricksignore"):
            lines = (REPO_ROOT / ignore_file).read_text().splitlines()
            for extracted in ("fonts", "fonts-staging"):
                assert f"services/pptx-emit-huashu/{extracted}/" in lines, (ignore_file, extracted)

    def test_the_publish_check_verifies_the_bundle(self) -> None:
        result = subprocess.run(
            ["sh", str(SIDECAR_DIR / "build-artifacts.sh")],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "fonts-liberation.tar.gz" in result.stdout


def test_the_bundle_is_small_beside_the_other_bootstrap_tarballs() -> None:
    """Under 3 MB: Liberation's twelve faces compressed (CJK and emoji faces are out of scope)."""
    assert BUNDLE.stat().st_size < 3 * 1024 * 1024
    with tarfile.open(fileobj=io.BytesIO(BUNDLE.read_bytes()), mode="r:gz") as bundle:
        assert len(bundle.getnames()) == 17
