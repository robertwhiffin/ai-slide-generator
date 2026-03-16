"""Initialize database with profiles from YAML seed file.

LOCAL DEVELOPMENT ONLY
----------------------
This script is for local development and testing. It seeds the database with:
- All deck prompts (generic + Databricks-specific)
- All slide styles (System Default + Databricks Brand)
- Sample profiles from config/seed_profiles.yaml

For Databricks App deployments, use deploy.sh instead which:
- Only seeds generic deck prompts and System Default style by default
- Does NOT create any profiles (users create their own)
- Optionally includes Databricks content with --include-databricks-prompts flag
"""
import argparse
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.database import get_db_session, init_db, Base, get_engine
from src.core.defaults import DEFAULT_CONFIG
from src.database.models import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigProfile,
    ConfigPrompts,
    SlideDeckPromptLibrary,
    SlideStyleLibrary,
)


def load_seed_profiles():
    """Load seed profiles from YAML file."""
    seed_file = Path(__file__).parent.parent / "config" / "seed_profiles.yaml"
    
    if not seed_file.exists():
        raise FileNotFoundError(f"Seed profiles file not found: {seed_file}")
    
    with open(seed_file, 'r') as f:
        data = yaml.safe_load(f)
    
    return data.get('profiles', [])


def reset_database():
    """Drop all tables and recreate them."""
    print("⚠️  Resetting database (dropping all tables)...")
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    print("✓ Tables dropped")
    
    print("Creating tables with new schema...")
    Base.metadata.create_all(bind=engine)
    print("✓ Tables created")


def seed_deck_prompts(db):
    """Seed the deck prompt library with default templates."""
    from src.core.init_default_profile import DEFAULT_DECK_PROMPTS
    
    existing_count = db.query(SlideDeckPromptLibrary).count()
    if existing_count > 0:
        print(f"  ✓ Deck prompts already exist ({existing_count} prompts)")
        return
    
    for prompt_data in DEFAULT_DECK_PROMPTS:
        prompt = SlideDeckPromptLibrary(
            name=prompt_data["name"],
            description=prompt_data["description"],
            category=prompt_data["category"],
            prompt_content=prompt_data["prompt_content"],
            is_active=True,
            created_by="system",
            updated_by="system",
        )
        db.add(prompt)
    
    print(f"  ✓ Seeded {len(DEFAULT_DECK_PROMPTS)} deck prompts")


def seed_slide_styles(db) -> int | None:
    """Seed the slide style library with default styles.
    
    Returns:
        ID of the default style (Databricks Brand) if created, None otherwise
    """
    from src.core.init_default_profile import DEFAULT_SLIDE_STYLES
    
    existing_count = db.query(SlideStyleLibrary).count()
    if existing_count > 0:
        print(f"  ✓ Slide styles already exist ({existing_count} styles)")
        # Return the ID of Databricks Brand if it exists
        default_style = db.query(SlideStyleLibrary).filter_by(name="Databricks Brand").first()
        return default_style.id if default_style else None
    
    default_style_id = None
    for style_data in DEFAULT_SLIDE_STYLES:
        style = SlideStyleLibrary(
            name=style_data["name"],
            description=style_data["description"],
            category=style_data["category"],
            style_content=style_data["style_content"],
            is_active=True,
            is_system=style_data.get("is_system", False),
            created_by="system",
            updated_by="system",
        )
        db.add(style)
        db.flush()  # Get the ID
        
        # Track the default style ID
        if style_data["name"] == "Databricks Brand":
            default_style_id = style.id
    
    print(f"  ✓ Seeded {len(DEFAULT_SLIDE_STYLES)} slide styles")
    return default_style_id


def initialize_database(reset: bool = False):
    """Initialize database with seed profiles from YAML."""
    
    if reset:
        reset_database()
    else:
        # Ensure tables exist (safe to call multiple times)
        print("Ensuring database tables exist...")
        init_db()
        print("✓ Tables ready")
    
    with get_db_session() as db:
        # Seed global libraries first (they check internally if already seeded)
        seed_deck_prompts(db)
        default_style_id = seed_slide_styles(db)
        db.commit()
        
        # Check if any profiles exist
        existing = db.query(ConfigProfile).first()
        if existing and not reset:
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
            
            # Create prompts with default slide style
            # Handle "USE_DEFAULT" values by substituting from defaults.py
            prompts_config = seed.get('prompts', {})
            system_prompt = prompts_config.get('system_prompt', 'USE_DEFAULT')
            slide_editing = prompts_config.get('slide_editing_instructions', 'USE_DEFAULT')
            
            # Substitute defaults if USE_DEFAULT is specified
            if system_prompt == 'USE_DEFAULT':
                system_prompt = DEFAULT_CONFIG['prompts']['system_prompt']
            if slide_editing == 'USE_DEFAULT':
                slide_editing = DEFAULT_CONFIG['prompts']['slide_editing_instructions']
            
            prompts = ConfigPrompts(
                profile_id=profile.id,
                selected_slide_style_id=default_style_id,
                system_prompt=system_prompt,
                slide_editing_instructions=slide_editing,
            )
            db.add(prompts)
            print(f"  ✓ Prompts settings (with default slide style)")
        
        db.commit()
        print(f"\n✓ Successfully created {len(seed_profiles)} profiles")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize database with seed profiles")
    parser.add_argument(
        "--reset", 
        action="store_true", 
        help="Drop all tables and recreate (WARNING: destroys all data)"
    )
    args = parser.parse_args()
    
    if args.reset:
        print("\n⚠️  WARNING: This will DELETE ALL DATA in the database!")
        confirm = input("Type 'yes' to confirm: ")
        if confirm.lower() != 'yes':
            print("Aborted.")
            sys.exit(0)
    
    try:
        initialize_database(reset=args.reset)
    except Exception as e:
        print(f"✗ Error initializing database: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
