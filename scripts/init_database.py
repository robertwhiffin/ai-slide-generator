"""Initialize database with default profile."""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config.database import get_db_session
from src.config.defaults import DEFAULT_CONFIG
from src.models.config import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigProfile,
    ConfigPrompts,
)


def initialize_database():
    """Initialize database with default profile on first run."""
    
    with get_db_session() as db:
        # Check if any profiles exist
        existing = db.query(ConfigProfile).first()
        if existing:
            print("✓ Database already initialized")
            return
        
        print("Initializing database with default profile...")
        
        # Create default profile
        profile = ConfigProfile(
            name="default",
            description="Default configuration profile",
            is_default=True,
            created_by="system",
        )
        db.add(profile)
        db.flush()
        
        # Create AI infrastructure config
        ai_infra = ConfigAIInfra(
            profile_id=profile.id,
            llm_endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
            llm_temperature=DEFAULT_CONFIG["llm"]["temperature"],
            llm_max_tokens=DEFAULT_CONFIG["llm"]["max_tokens"],
        )
        db.add(ai_infra)
        
        # Create default Genie space
        genie_space = ConfigGenieSpace(
            profile_id=profile.id,
            space_id=DEFAULT_CONFIG["genie"]["space_id"],
            space_name=DEFAULT_CONFIG["genie"]["space_name"],
            description=DEFAULT_CONFIG["genie"]["description"],
            is_default=True,
        )
        db.add(genie_space)
        
        # Create MLflow config
        # Replace {username} with actual username from environment
        username = os.getenv("USER", "default_user")
        experiment_name = DEFAULT_CONFIG["mlflow"]["experiment_name"].format(username=username)
        
        mlflow = ConfigMLflow(
            profile_id=profile.id,
            experiment_name=experiment_name,
        )
        db.add(mlflow)
        
        # Create prompts config
        prompts = ConfigPrompts(
            profile_id=profile.id,
            system_prompt=DEFAULT_CONFIG["prompts"]["system_prompt"],
            slide_editing_instructions=DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
            user_prompt_template=DEFAULT_CONFIG["prompts"]["user_prompt_template"],
        )
        db.add(prompts)
        
        db.commit()
        print(f"✓ Created default profile: {profile.name}")


if __name__ == "__main__":
    try:
        initialize_database()
    except Exception as e:
        print(f"✗ Error initializing database: {e}")
        sys.exit(1)

