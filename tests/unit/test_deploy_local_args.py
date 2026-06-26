import importlib
import inspect

deploy_local = importlib.import_module("scripts.deploy_local")


def test_create_local_accepts_from_pypi_kwarg():
    params = inspect.signature(deploy_local.create_local).parameters
    assert "from_pypi" in params
    assert "from_test_pypi" not in params


def test_update_local_accepts_from_pypi_kwarg():
    params = inspect.signature(deploy_local.update_local).parameters
    assert "from_pypi" in params
    assert "from_test_pypi" not in params
