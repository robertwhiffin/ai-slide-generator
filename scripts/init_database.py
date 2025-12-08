"""Initialize database with profiles from YAML seed file."""
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.database import get_db_session, init_db
from src.database.models import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigProfile,
    ConfigPrompts,
)


def load_seed_profiles():
    """Load seed profiles from YAML file."""
    seed_file = Path(__file__).parent.parent / "config" / "seed_profiles.yaml"
    
    if not seed_file.exists():
        raise FileNotFoundError(f"Seed profiles file not found: {seed_file}")
    
    with open(seed_file, 'r') as f:
        data = yaml.safe_load(f)
    
    return data.get('profiles', [])


def initialize_database():
    """Initialize database with seed profiles from YAML."""
    
    # Ensure tables exist (safe to call multiple times)
    print("Ensuring database tables exist...")
    init_db()
    print("✓ Tables ready")
    
    with get_db_session() as db:
        # Check if any profiles exist
        existing = db.query(ConfigProfile).first()
        if existing:
            print("✓ Database already initialized")
            return
        
        print("Initializing database with seed profiles from YAML...")
        
        # Get username for MLflow experiment
        try:
            from src.core.databricks_client import get_databricks_client
            client = get_databricks_client()
            username = client.current_user.me().user_name
        except Exception:
            username = os.getenv("USER", "default_user")
        
        # Load seed profiles
        try:
            seed_profiles = load_seed_profiles()
        except FileNotFoundError as e:
            print(f"✗ Error: {e}")
            print("  Please ensure config/seed_profiles.yaml exists")
            sys.exit(1)
        
        if not seed_profiles:
            print("✗ No profiles found in seed_profiles.yaml")
            sys.exit(1)
        
        # Create profiles
        for seed in seed_profiles:
            print(f"\n➤ Creating profile: {seed['name']}")
            
            # Create profile
            profile = ConfigProfile(
                name=seed['name'],
                description=seed['description'],
                is_default=seed.get('is_default', False),
                created_by=seed.get('created_by', 'system'),
            )
            db.add(profile)
            db.flush()  # Get profile ID
            
            # Create AI infrastructure
            ai_config = seed.get('ai_infra', {})
            if ai_config:
                ai_infra = ConfigAIInfra(
                    profile_id=profile.id,
                    llm_endpoint=ai_config['llm_endpoint'],
                    llm_temperature=ai_config['llm_temperature'],
                    llm_max_tokens=ai_config['llm_max_tokens'],
                )
                db.add(ai_infra)
                print(f"  ✓ AI settings: {ai_config['llm_endpoint']}")
            
            # Create Genie space
            genie_config = seed.get('genie_space', {})
            if genie_config:
                genie_space = ConfigGenieSpace(
                    profile_id=profile.id,
                    space_id=genie_config['space_id'],
                    space_name=genie_config['space_name'],
                    description=genie_config.get('description', ''),
                )
                db.add(genie_space)
                print(f"  ✓ Genie space: {genie_config['space_name']}")
            
            # Create MLflow settings
            mlflow_config = seed.get('mlflow', {})
            if mlflow_config:
                experiment_name = mlflow_config['experiment_name'].format(username=username)
                mlflow = ConfigMLflow(
                    profile_id=profile.id,
                    experiment_name=experiment_name,
                )
                db.add(mlflow)
                print(f"  ✓ MLflow: {experiment_name}")
            
            # Create prompts
            prompts_config = seed.get('prompts', {})
            if prompts_config:
                prompts = ConfigPrompts(
                    profile_id=profile.id,
                    system_prompt=prompts_config['system_prompt'],
                    slide_editing_instructions=prompts_config['slide_editing_instructions'],
                    user_prompt_template=prompts_config['user_prompt_template'],
                )
                db.add(prompts)
                print(f"  ✓ Prompts settings")
        
        db.commit()
        print(f"\n✓ Successfully created {len(seed_profiles)} profiles")


if __name__ == "__main__":
    try:
        initialize_database()
    except Exception as e:
        print(f"✗ Error initializing database: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
