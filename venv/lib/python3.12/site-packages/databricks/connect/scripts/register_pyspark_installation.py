import os
import shutil
import subprocess
import sys
import sysconfig

from ..debug import logger
from ..version import __pyspark_version__, __dbconnect_version__


def _custom_pyspark_version():
    """Construct a version string with a local identifier including Databricks Connect
    version following PEP 440 standard.
    """
    return f"{__pyspark_version__}+databricks.connect.{__dbconnect_version__}"


METADATA = f"""
Metadata-Version: 2.4
Name: pyspark
Version: {_custom_pyspark_version()}
Summary: Custom version of Apache Spark Python API bundled with Databricks Connect.
""".lstrip()

WHEEL = """
Wheel-Version: 1.0
Generator: databricks-connect
Root-Is-Purelib: true
Tag: py3-none-any
""".lstrip()

INSTALLER = "databricks-connect\n"
TOP_LEVEL_TXT = "pyspark\n"
RECORD = ""


def _get_pyspark_dist_info_dir() -> str:
    site_packages_path = sysconfig.get_path('purelib')
    pyspark_dist_info_dir_name = f"pyspark-{_custom_pyspark_version()}.dist-info"
    return os.path.join(site_packages_path, pyspark_dist_info_dir_name)


def _create_pyspark_dist_info():
    try:
        dist_info_dir = _get_pyspark_dist_info_dir()
        logger.debug(f"Creating .dist-info directory for pyspark at: {dist_info_dir}")
        os.makedirs(dist_info_dir, exist_ok=True)
        with open(os.path.join(dist_info_dir, "METADATA"), "w") as f:
            f.write(METADATA)
        with open(os.path.join(dist_info_dir, "WHEEL"), "w") as f:
            f.write(WHEEL)
        with open(os.path.join(dist_info_dir, "top_level.txt"), "w") as f:
            f.write(TOP_LEVEL_TXT)
        with open(os.path.join(dist_info_dir, "RECORD"), "w") as f:
            f.write(RECORD)
        with open(os.path.join(dist_info_dir, "INSTALLER"), "w") as f:
            f.write(INSTALLER)
        logger.debug(f"Created and populated .dist-info directory for pyspark at: {dist_info_dir}")
    except Exception as e:
        raise RuntimeError(f"Failed to create .dist-info directory.") from e


def _delete_pyspark_dist_info():
    dist_info_dir = _get_pyspark_dist_info_dir()
    if os.path.exists(dist_info_dir):
        shutil.rmtree(dist_info_dir)
        logger.debug(f"Deleted existing .dist-info directory for pyspark at: {dist_info_dir}")
    else:
        logger.debug(f"Directory .dist-info for pyspark at '{dist_info_dir}' does not exist")


def _verify_pip_show():
    """Verify that pip recognizes pyspark."""
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'show', 'pyspark'],
        capture_output=True,
        text=True,
        timeout=10
    )
    if result.returncode == 0 and f"Version: {_custom_pyspark_version()}" in result.stdout:
        logger.debug("✓ pip show recognizes pyspark")
        # Show name and version line
        for line in result.stdout.split('\n'):
            if line.startswith('Name:') or line.startswith('Version:'):
                logger.debug(f"  {line}")
    else:
        raise RuntimeError("✗ pip show does not recognize pyspark. Something went wrong during registration.")


def _verify_pip_install():
    """Verify that `pip install pyspark` recognizes pyspark as installed."""
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', 'pyspark', '--dry-run'],
        capture_output=True,
        text=True,
        timeout=10
    )
    if result.returncode == 0 and "Requirement already satisfied" in result.stdout:
        logger.debug("✓ pip install recognizes pyspark as already installed")
    else:
        raise RuntimeError("✗ pip install does not recognize pyspark as installed. "
                           "Something went wrong during registration.")


def _verify_registration():
    logger.debug("Running verification.")
    _verify_pip_show()
    _verify_pip_install()
    logger.debug("Verification succeeded. PySpark is now registered with pip.")
    logger.debug("You can verify with: pip list | grep pyspark")


def main():
    try:
        _create_pyspark_dist_info()
        _verify_registration()
    except Exception as e:
        logger.error("Pyspark registration was not successful. Running cleanup.")
        _delete_pyspark_dist_info()
        raise e


if __name__ == "__main__":
    main()
