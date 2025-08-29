from databricks.labs.blueprint.tui import Prompts
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import ResourceAlreadyExists, BadRequest
from databricks.sdk.errors.platform import PermissionDenied
from databricks.sdk.service.apps import App
from databricks.sdk.service.sql import (
    CreateWarehouseRequestWarehouseType,
    WarehouseAccessControlRequest,
    WarehousePermissionLevel,
)
from databricks.sdk.service.catalog import VolumeType
from databricks.sdk.service.workspace import ObjectType, WorkspaceObjectAccessControlRequest, WorkspaceObjectPermissionLevel, ImportFormat, Language
import logging
w = WorkspaceClient()
prompts = Prompts()

config={
    "DEPLOYMENT_PATH": "",
    "APP": "",
}

logger = logging.getLogger(__name__)

# this is a decorator to handle errors and do a retry where user is asked to choose an existing resource
def _handle_errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PermissionDenied:
            logging.error(
                "You do not have permission to create the requested resource. Please ask your admin to grant"
                " you permission or choose an existing resource."
            )
            return func(*args, **kwargs)
        except ResourceAlreadyExists:
            logging.error(
                "Resource already exists. Please choose an alternative resource."
            )
            return func(*args, **kwargs)
        except BadRequest as e:
            if "Cannot write secrets" in str(e):
                logging.error(
                    "Cannot write secrets to Azure KeyVault-backed scope. Please choose an alternative "
                    "secret scope."
                )
                return func(*args, **kwargs)
            else:
                raise e

    return wrapper


def create_or_select(
        entity: str,
        list_all: Callable[[], list[str]],
        create: Callable[[str], None],
        default: str,
) -> str:
    """
    User choose a Entity that can be selected from existing ones or created new
    """
    create_new = (
            prompts.choice(
                f"Create a new {entity} or use existing?",
                ["Create new", "Use existing"],
            )
            == "Create new"
    )
    if not create_new:
        all_entities = list_all()

        choices = all_entities + ["Create a new one"]

        question = f"Choose a {entity}: please enter the number of the {entity} you would like to use."
        choice = prompts.choice(question, choices, sort=False)

        if "Create a new one" in choice:
            create_new = True
        else:
            return choice
    if create_new:
        new_name = prompts.question(f"Choose a {entity} name", default=default)

        print(f"Creating a new {entity} {new_name}.")
        create(new_name)
        return new_name


@_handle_errors
def setup_app():
    def create(name: str):
        print("Creating new app")
        w.apps.create_and_wait(app=App(name))
        print("Created new app")

    def list_all():
        return [x.name for x in w.apps.list()]

    app_name = create_or_select(
        entity="app",
        list_all=list_all,
        create=create,
        default="ai-slide-generator",
    )
    app = w.apps.get(app_name)
    return app


@_handle_errors
def setup_deployment_dir(app):
    if app.default_source_code_path == "":
        deployment_path = prompts.question(
            "Choose a workspace directory to deploy the code",
            default=f"/Workspace/Users/{w.current_user.me().user_name}/ai-slide-generator",
        )
    else:
        deployment_path = app.default_source_code_path
    config["DEPLOYMENT_PATH"] = deployment_path

    w.workspace.mkdirs(deployment_path)

    # give app SP permissions on workspace location
    try:
        directory = w.workspace.get_status(config.get("DEPLOYMENT_PATH"))
        w.workspace.update_permissions(
            workspace_object_type="directories", #directory.object_type, ObjectType.DIRECTORY# incorrect docs again
            workspace_object_id=str(directory.object_id),
            access_control_list=[
                WorkspaceObjectAccessControlRequest(
                    service_principal_name=app.service_principal_client_id,
                    permission_level=WorkspaceObjectPermissionLevel.CAN_MANAGE,
                )
            ],
        )
    except Exception as e:
        logger.warning(
            f"Could not set permissions for Directory {config.get('DEPLOYMENT_PATH')}: and service_principal {app.service_principal_name}"
        )
        logger.warning(e)



if __name__ == "__main__":
    setup_app()