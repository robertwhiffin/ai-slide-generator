from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from setuptools import find_packages, setup
from setuptools.command.build_py import build_py


# Files in services/pptx-emit-huashu/ NOT to ship in the wheel:
#   - node_modules/ and sys-libs/ are bulky uncompressed trees; the wheel
#     instead ships the gzipped tarballs (node_modules.tar.gz and
#     sys-libs-bullseye.tar.gz) which setup.sh extracts at boot. The
#     tarballs are produced by services/pptx-emit-huashu/build-artifacts.sh
#     and are not in _SIDECAR_IGNORE so they DO ship.
#   - package-lock.json is needed at build-artifacts.sh time but not at
#     runtime (the lockfile is consumed when the tarball is built).
#   - build-artifacts.sh is a CI/build helper, never a runtime script.
_SIDECAR_IGNORE = shutil.ignore_patterns(
    "node_modules",
    "sys-libs",
    "sys-libs-bullseye",
    ".databricks",
    "*.log",
    "package-lock.json",
    "build-artifacts.sh",
)


class BuildWithFrontend(build_py):
    """Build the frontend bundle and copy into package assets."""

    def run(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        package_root = Path(__file__).resolve().parent
        frontend_dir = repo_root / "frontend"
        dist_dir = frontend_dir / "dist"
        src_dir = repo_root / "src"
        src_target = package_root / "src"
        assets_root = package_root / "databricks_tellr_app" / "_assets"
        frontend_target = assets_root / "frontend"
        sidecars_root = assets_root / "sidecars"
        records_sidecar_src = repo_root / "services" / "pptx-emit"
        records_sidecar_target = sidecars_root / "pptx-emit"
        huashu_sidecar_src = repo_root / "services" / "pptx-emit-huashu"
        huashu_sidecar_target = sidecars_root / "pptx-emit-huashu"

        try:
            if frontend_dir.exists():
                subprocess.run(["npm", "install"], cwd=frontend_dir, check=True)
                subprocess.run(["npm", "run", "build"], cwd=frontend_dir, check=True)

                if frontend_target.exists():
                    shutil.rmtree(frontend_target)
                assets_root.mkdir(parents=True, exist_ok=True)
                shutil.copytree(dist_dir, frontend_target)

            if src_dir.exists():
                if src_target.exists():
                    shutil.rmtree(src_target)
                shutil.copytree(src_dir, src_target)

            sidecars_root.mkdir(parents=True, exist_ok=True)
            if records_sidecar_src.exists():
                if records_sidecar_target.exists():
                    shutil.rmtree(records_sidecar_target)
                shutil.copytree(
                    records_sidecar_src,
                    records_sidecar_target,
                    ignore=_SIDECAR_IGNORE,
                )
            if huashu_sidecar_src.exists():
                if huashu_sidecar_target.exists():
                    shutil.rmtree(huashu_sidecar_target)
                shutil.copytree(
                    huashu_sidecar_src,
                    huashu_sidecar_target,
                    ignore=_SIDECAR_IGNORE,
                )

            super().run()
        finally:
            if frontend_target.exists():
                shutil.rmtree(frontend_target)
            if records_sidecar_target.exists():
                shutil.rmtree(records_sidecar_target)
            if huashu_sidecar_target.exists():
                shutil.rmtree(huashu_sidecar_target)
            if sidecars_root.exists() and not any(sidecars_root.iterdir()):
                sidecars_root.rmdir()
            if assets_root.exists() and not any(assets_root.iterdir()):
                assets_root.rmdir()
            if src_target.exists():
                shutil.rmtree(src_target)


package_root = Path(__file__).resolve().parent

app_packages = find_packages(
    where=".",
    include=["databricks_tellr_app", "databricks_tellr_app.*", "src", "src.*"],
)

setup(
    cmdclass={"build_py": BuildWithFrontend},
    packages=app_packages,
    package_dir={
        "": ".",
    },
    include_package_data=False,
    package_data={
        "databricks_tellr_app": ["_assets/**"],
        "src.api": ["fixtures/*.json"],
    },
)
