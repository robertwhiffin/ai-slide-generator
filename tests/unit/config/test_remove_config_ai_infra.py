"""Tests verifying ConfigAIInfra has been removed from the models package."""
import ast
import os


MODELS_INIT = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "database", "models", "__init__.py",
)

PROFILE_PY = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "database", "models", "profile.py",
)

AI_INFRA_PY = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "database", "models", "ai_infra.py",
)


def test_ai_infra_file_deleted():
    """The ai_infra.py model file should no longer exist."""
    assert not os.path.exists(AI_INFRA_PY), "ai_infra.py should be deleted"


def test_config_ai_infra_not_in_all():
    """ConfigAIInfra should not appear in models.__all__."""
    source = open(MODELS_INIT).read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    names = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
                    assert "ConfigAIInfra" not in names


def test_config_ai_infra_not_imported_in_init():
    """ConfigAIInfra should not be imported in models __init__.py."""
    source = open(MODELS_INIT).read()
    assert "ConfigAIInfra" not in source


def test_profile_has_no_ai_infra_relationship():
    """ConfigProfile model should not have an ai_infra relationship."""
    source = open(PROFILE_PY).read()
    assert "ai_infra" not in source
    assert "ConfigAIInfra" not in source
