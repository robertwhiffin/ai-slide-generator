from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from setuptools import find_packages, setup
from setuptools.command.build_py import build_py


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

            super().run()
        finally:
            if frontend_target.exists():
                shutil.rmtree(frontend_target)
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
    package_data={"databricks_tellr_app": ["_assets/**"]},
)
