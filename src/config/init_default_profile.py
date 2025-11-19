"""
Initialize database with default profile from YAML configuration.

This script creates a default configuration profile in the database using
values from the YAML configuration files. Run this once after database setup.
"""

import logging
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.database import get_db_session
from src.config.defaults import DEFAULT_CONFIG
from src.config.loader import load_config, load_prompts
from src.models.config import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigProfile,
    ConfigPrompts,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_default_profile() -> None:
    """
    Initialize database with default profile from YAML files.
    
    Creates a profile named "default" with configuration from:
    - config/config.yaml
    - config/prompts.yaml
    - src/config/defaults.py (fallback)
    
    Raises:
        Exception: If profile creation fails
    """
    logger.info("Initializing default profile from YAML configuration")
    
    try:
        # Load YAML configuration
        try:
            config = load_config()
            prompts = load_prompts()
            logger.info("Loaded configuration from YAML files")
        except Exception as e:
            logger.warning(f"Failed to load YAML config, using defaults: {e}")
            config = DEFAULT_CONFIG
            prompts = {
                "system_prompt": DEFAULT_CONFIG["prompts"]["system_prompt"],
                "slide_editing_instructions": DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
                "user_prompt_template": DEFAULT_CONFIG["prompts"]["user_prompt_template"],
            }
        
        with get_db_session() as db:
            # Check if default profile already exists
            existing = db.query(ConfigProfile).filter_by(name="default").first()
            if existing:
                logger.info(
                    "Default profile already exists",
                    extra={"profile_id": existing.id},
                )
                print(f"✓ Default profile already exists (ID: {existing.id})")
                return
            
            # Create default profile
            profile = ConfigProfile(
                name="default",
                description="Default configuration profile",
                is_default=True,
                created_by="system",
                updated_by="system",
            )
            db.add(profile)
            db.flush()
            
            logger.info("Created default profile", extra={"profile_id": profile.id})
            
            # Create AI infrastructure config
            ai_infra = ConfigAIInfra(
                profile_id=profile.id,
                llm_endpoint=config["llm"]["endpoint"],
                llm_temperature=config["llm"]["temperature"],
                llm_max_tokens=config["llm"]["max_tokens"],
            )
            db.add(ai_infra)
            logger.info("Created AI infrastructure config")
            
            # Create Genie space config
            genie_space = ConfigGenieSpace(
                profile_id=profile.id,
                space_id=config["genie"]["default_space_id"],
                space_name=config["genie"].get("space_name", "Default Genie Space"),
                description=config["genie"].get("description", "Default Genie data space"),
                is_default=True,
            )
            db.add(genie_space)
            logger.info("Created Genie space config")
            
            # Create MLflow config
            # Get username from Databricks client singleton
            try:
                from src.config.client import get_databricks_client
                client = get_databricks_client()
                username = client.current_user.me().user_name
            except Exception as e:
                # Fallback to environment variable if Databricks not available
                logger.warning(f"Could not get Databricks username: {e}")
                username = os.getenv("USER", "default_user")
            
            experiment_name = "/Users/{username}/slide-generator-experiments"
            if "{username}" in experiment_name:
                experiment_name = experiment_name.format(username=username)
            
            mlflow_config = ConfigMLflow(
                profile_id=profile.id,
                experiment_name=experiment_name,
            )
            db.add(mlflow_config)
            logger.info("Created MLflow config")
            
            # Create prompts config
            prompts_config = ConfigPrompts(
                profile_id=profile.id,
                system_prompt=prompts.get("system_prompt", DEFAULT_CONFIG["prompts"]["system_prompt"]),
                slide_editing_instructions=prompts.get(
                    "slide_editing_instructions",
                    DEFAULT_CONFIG["prompts"]["slide_editing_instructions"]
                ),
                user_prompt_template=prompts.get(
                    "user_prompt_template",
                    DEFAULT_CONFIG["prompts"]["user_prompt_template"]
                ),
            )
            db.add(prompts_config)
            logger.info("Created prompts config")
            
            db.commit()
            
            logger.info(
                "Default profile initialized successfully",
                extra={
                    "profile_id": profile.id,
                    "llm_endpoint": ai_infra.llm_endpoint,
                    "genie_space": genie_space.space_name,
                },
            )
            
            print("\n✓ Default profile initialized successfully")
            print(f"  Profile ID: {profile.id}")
            print(f"  Profile Name: {profile.name}")
            print(f"  LLM Endpoint: {ai_infra.llm_endpoint}")
            print(f"  Genie Space: {genie_space.space_name}")
            print(f"  MLflow Experiment: {mlflow_config.experiment_name}")
            print("\nYou can now start the application with database-backed configuration.")
            
    except Exception as e:
        logger.error(f"Failed to initialize default profile: {e}", exc_info=True)
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("Initializing default configuration profile...")
    print("This will create a 'default' profile in the database from YAML files.\n")
    
    # Check database connection
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("✗ Error: DATABASE_URL environment variable not set")
        print("Please set DATABASE_URL to your PostgreSQL connection string:")
        print("  export DATABASE_URL='postgresql://user:pass@localhost:5432/ai_slide_generator'")
        sys.exit(1)
    
    print(f"Database: {database_url.split('@')[1] if '@' in database_url else database_url}")
    
    init_default_profile()

