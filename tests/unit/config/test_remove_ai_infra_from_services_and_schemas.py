"""Tests verifying ai_infra has been removed from profile service, config service, and API schemas."""
import ast
import os


PROFILE_SERVICE = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "services", "profile_service.py",
)

CONFIG_SERVICE = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "services", "config_service.py",
)

SCHEMAS_REQUESTS = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "api", "schemas", "settings", "requests.py",
)

SCHEMAS_RESPONSES = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "api", "schemas", "settings", "responses.py",
)

SCHEMAS_INIT = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "src", "api", "schemas", "settings", "__init__.py",
)


# --- Task 8: Profile service ---

def test_profile_service_no_ai_infra_references():
    """profile_service.py should have no references to ai_infra or ConfigAIInfra."""
    source = open(PROFILE_SERVICE).read()
    assert "ConfigAIInfra" not in source
    assert "ai_infra" not in source


def test_profile_service_no_joinedload_ai_infra():
    """profile_service.py should not joinedload ai_infra."""
    source = open(PROFILE_SERVICE).read()
    assert "joinedload(ConfigProfile.ai_infra)" not in source


def test_create_profile_with_config_no_ai_infra_param():
    """create_profile_with_config should not accept ai_infra parameter."""
    source = open(PROFILE_SERVICE).read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "create_profile_with_config":
            param_names = [arg.arg for arg in node.args.args]
            assert "ai_infra" not in param_names, "ai_infra should be removed from signature"


# --- Task 9: Config service ---

def test_config_service_no_ai_infra_references():
    """config_service.py should have no references to ai_infra or ConfigAIInfra."""
    source = open(CONFIG_SERVICE).read()
    assert "ConfigAIInfra" not in source
    assert "ai_infra" not in source
    assert "get_ai_infra_config" not in source
    assert "update_ai_infra_config" not in source
    assert "get_available_endpoints" not in source


def test_config_service_imports_ok():
    """Config service should import cleanly."""
    from src.services.config_service import ConfigService
    assert ConfigService is not None


# --- Task 10: API schemas ---

def test_schemas_requests_no_ai_infra():
    """Request schemas should not contain AI infra classes or fields."""
    source = open(SCHEMAS_REQUESTS).read()
    assert "AIInfraCreateInline" not in source
    assert "AIInfraConfigUpdate" not in source
    assert "ai_infra" not in source


def test_schemas_responses_no_ai_infra():
    """Response schemas should not contain AI infra classes or fields."""
    source = open(SCHEMAS_RESPONSES).read()
    assert "AIInfraConfig" not in source
    assert "EndpointsList" not in source
    assert "ai_infra" not in source


def test_schemas_init_no_ai_infra():
    """Schema __init__.py should not export AI infra types."""
    source = open(SCHEMAS_INIT).read()
    assert "AIInfraConfig" not in source
    assert "AIInfraConfigUpdate" not in source
    assert "EndpointsList" not in source


def test_schemas_import_ok():
    """Key schema classes should import cleanly after removal."""
    from src.api.schemas.settings import ProfileDetail, ProfileCreateWithConfig
    assert ProfileDetail is not None
    assert ProfileCreateWithConfig is not None
