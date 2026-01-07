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

from src.core.database import get_db_session
from src.core.defaults import DEFAULT_CONFIG
from src.core.config_loader import load_config, load_prompts
from src.database.models import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigProfile,
    ConfigPrompts,
    SlideDeckPromptLibrary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Default deck prompt templates for the library
DEFAULT_DECK_PROMPTS = [
    {
        "name": "Consumption Review",
        "description": "Template for consumption review meetings. Analyzes usage trends, identifies key drivers, and highlights areas for optimization.",
        "category": "Review",
        "prompt_content": """PRESENTATION TYPE: Consumption Review

When creating a consumption review presentation, focus on:

1. EXECUTIVE SUMMARY
   - Overall consumption trend (increasing/decreasing/stable)
   - Key highlight metrics (total spend, month-over-month change)
   - Top 3 insights that require attention

2. USAGE ANALYSIS
   - Query for consumption data over the past 6-12 months
   - Break down by major categories (compute, storage, etc.)
   - Identify the top consumers and their growth patterns

3. TREND IDENTIFICATION
   - Look for seasonal patterns or anomalies
   - Compare current period to previous periods
   - Highlight significant changes (>10% movement)

4. OPTIMIZATION OPPORTUNITIES
   - Identify underutilized resources
   - Highlight cost-saving opportunities
   - Recommend actions based on data

5. FORWARD OUTLOOK
   - Project future consumption based on trends
   - Flag any concerns or risks
   - Provide actionable recommendations

Structure the deck with clear data visualizations showing trends over time.""",
    },
    {
        "name": "Quarterly Business Review",
        "description": "Template for QBR presentations. Covers performance metrics, achievements, challenges, and strategic recommendations.",
        "category": "Report",
        "prompt_content": """PRESENTATION TYPE: Quarterly Business Review (QBR)

When creating a QBR presentation, structure it as follows:

1. QUARTER OVERVIEW
   - Executive summary of the quarter
   - Key performance indicators vs. targets
   - Major achievements and milestones

2. METRICS DEEP DIVE
   - Query for all relevant metrics for the quarter
   - Compare to previous quarter and same quarter last year
   - Use charts to visualize performance trends

3. SUCCESS STORIES
   - Highlight specific wins with data
   - Quantify impact where possible
   - Include growth or improvement percentages

4. CHALLENGES & LEARNINGS
   - Acknowledge areas that didn't meet expectations
   - Provide context with supporting data
   - Share lessons learned

5. NEXT QUARTER OUTLOOK
   - Goals and targets for upcoming quarter
   - Strategic initiatives planned
   - Resource requirements or asks

Use a professional, data-driven approach with clear visualizations for each section.""",
    },
    {
        "name": "Executive Summary",
        "description": "High-level overview format for executive audiences. Focuses on key metrics and strategic insights.",
        "category": "Summary",
        "prompt_content": """PRESENTATION TYPE: Executive Summary

When creating an executive summary presentation:

DESIGN PRINCIPLES:
- Keep it concise - executives have limited time
- Lead with insights, not data
- Use clear, impactful titles that state the takeaway
- Maximum 5-7 slides total

STRUCTURE:
1. HEADLINE SLIDE
   - Single most important insight or conclusion
   - One key metric that supports it

2. SITUATION OVERVIEW
   - Brief context (2-3 bullets max)
   - Current state summary

3. KEY FINDINGS (2-3 slides max)
   - One major insight per slide
   - Support each with 1-2 data points
   - Use simple charts (bar or line)

4. RECOMMENDATIONS
   - Clear, actionable next steps
   - Prioritized list (max 3 items)

5. ASK (if applicable)
   - What decision or action is needed
   - Required resources or support

Keep language simple and avoid jargon. Every data point should support a decision.""",
    },
    {
        "name": "Use Case Analysis",
        "description": "Template for analyzing use case progression and identifying blockers or accelerators.",
        "category": "Analysis",
        "prompt_content": """PRESENTATION TYPE: Use Case Analysis

When analyzing use cases, focus on:

1. PORTFOLIO OVERVIEW
   - Total number of use cases in scope
   - Distribution by stage/status
   - Overall health metrics

2. PROGRESSION ANALYSIS
   - Query for use case movement between stages
   - Identify velocity patterns
   - Calculate average time in each stage

3. BLOCKER IDENTIFICATION
   - Find use cases that are stuck or slowed
   - Categorize blockers (technical, resource, dependency)
   - Quantify impact of each blocker type

4. SUCCESS PATTERNS
   - Identify fast-moving use cases
   - Find common characteristics of successful progression
   - Extract best practices

5. RECOMMENDATIONS
   - Specific actions to unblock stuck use cases
   - Resource allocation suggestions
   - Process improvements

Use funnel charts for progression and bar charts for blocker analysis.""",
    },
]


def _seed_deck_prompts(db) -> None:
    """Seed the deck prompt library with default templates."""
    existing_count = db.query(SlideDeckPromptLibrary).count()
    if existing_count > 0:
        logger.info(f"Deck prompt library already has {existing_count} prompts, skipping seed")
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
        logger.info(f"Created deck prompt: {prompt_data['name']}")

    logger.info(f"Seeded {len(DEFAULT_DECK_PROMPTS)} deck prompts")
    print(f"  ✓ Seeded {len(DEFAULT_DECK_PROMPTS)} deck prompts in library")


def init_default_profile() -> None:
    """
    Initialize database with default profile from YAML files.
    
    Creates a profile named "default" with configuration from:
    - settings/settings.yaml
    - settings/prompts.yaml
    - src/settings/defaults.py (fallback)
    
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
            logger.warning(f"Failed to load YAML settings, using defaults: {e}")
            config = DEFAULT_CONFIG
            prompts = {
                "system_prompt": DEFAULT_CONFIG["prompts"]["system_prompt"],
                "slide_editing_instructions": DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
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

            # Create AI infrastructure settings
            ai_infra = ConfigAIInfra(
                profile_id=profile.id,
                llm_endpoint=config["llm"]["endpoint"],
                llm_temperature=config["llm"]["temperature"],
                llm_max_tokens=config["llm"]["max_tokens"],
            )
            db.add(ai_infra)
            logger.info("Created AI infrastructure settings")

            # Create Genie space settings (one per profile)
            genie_space = ConfigGenieSpace(
                profile_id=profile.id,
                space_id=config["genie"]["default_space_id"],
                space_name=config["genie"].get("space_name", "Default Genie Space"),
                description=config["genie"].get("description", "Default Genie data space"),
            )
            db.add(genie_space)
            logger.info("Created Genie space settings")

            # Create MLflow settings
            # Get username from Databricks client singleton
            try:
                from src.core.databricks_client import get_databricks_client
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
            logger.info("Created MLflow settings")

            # Create prompts settings
            prompts_config = ConfigPrompts(
                profile_id=profile.id,
                system_prompt=prompts.get("system_prompt", DEFAULT_CONFIG["prompts"]["system_prompt"]),
                slide_editing_instructions=prompts.get(
                    "slide_editing_instructions",
                    DEFAULT_CONFIG["prompts"]["slide_editing_instructions"]
                ),
            )
            db.add(prompts_config)
            logger.info("Created prompts settings")

            # Seed deck prompt library (global, not per-profile)
            _seed_deck_prompts(db)

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

