# Phase 8: Documentation & Deployment

**Duration:** Days 18-19  
**Status:** Not Started  
**Prerequisites:** Phase 7 Complete (History & Polish)

## Objectives

- Complete user documentation
- Write technical documentation
- Create migration guide from YAML to database
- Implement database migration script
- Set up deployment configuration
- Create backup and restore procedures
- Write operations runbook
- Prepare rollout plan

## Files to Create/Modify

```
docs/
├── user-guide/
│   ├── config-management.md
│   ├── profile-management.md
│   └── quickstart.md
├── technical/
│   ├── database-schema.md
│   ├── api-reference.md
│   └── configuration-architecture.md
├── operations/
│   ├── deployment.md
│   ├── backup-restore.md
│   └── troubleshooting.md
└── migration/
    └── yaml-to-database.md
scripts/
├── migrate_yaml_to_db.py
├── backup_config.py
└── restore_config.py
```

## Implementation Summary

### Step 1: User Documentation

**File:** `docs/user-guide/config-management.md`

Content:
- Overview of configuration management
- How to access configuration UI
- Explanation of each configuration domain
- Screenshots and examples
- Best practices
- Common workflows

**File:** `docs/user-guide/profile-management.md`

Content:
- What are profiles
- Creating and managing profiles
- Setting default profiles
- Loading profiles for sessions
- Duplicating profiles
- Use cases (dev/staging/prod profiles)

**File:** `docs/user-guide/quickstart.md`

Quick start guide:
1. Access configuration panel
2. Review default profile
3. Create first custom profile
4. Configure AI settings
5. Test with a query
6. Advanced customization

### Step 2: Technical Documentation

**File:** `docs/technical/database-schema.md`

Complete schema documentation:
- All tables with field descriptions
- Relationships and foreign keys
- Constraints and triggers
- Indexes
- Migration history

**File:** `docs/technical/api-reference.md`

API documentation:
- All endpoints with descriptions
- Request/response schemas
- Error codes
- Authentication requirements
- Example requests with curl
- Rate limiting (if applicable)

**File:** `docs/technical/configuration-architecture.md`

Architecture documentation:
- How configuration flows through the system
- Settings loading and caching
- Agent reinitialization process
- Session management
- Multi-profile support
- Database transaction patterns

### Step 3: Migration Guide and Script

**File:** `docs/migration/yaml-to-database.md`

Migration guide:
- Why we're migrating
- What changes for users
- Pre-migration checklist
- Step-by-step migration process
- Rollback plan
- FAQ

**File:** `scripts/migrate_yaml_to_db.py`

```python
"""
Migrate YAML configurations to database.

This script:
1. Reads existing YAML files
2. Creates profiles in database
3. Migrates all configurations
4. Validates migration
5. Creates backup of YAML files
"""

import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import get_db_session
from src.models.config import (
    ConfigProfile,
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigPrompts,
)


def load_yaml_configs(config_dir: Path):
    """Load all YAML configuration files."""
    configs = {}

    yaml_files = ['settings.yaml', 'mlflow.yaml', 'prompts.yaml']
    for yaml_file in yaml_files:
        path = config_dir / yaml_file
        if path.exists():
            with open(path) as f:
                configs[yaml_file] = yaml.safe_load(f)

    return configs


def create_profile_from_yaml(db, configs, profile_name="default"):
    """Create database profile from YAML configs."""

    # Create profile
    profile = ConfigProfile(
        name=profile_name,
        description=f"Migrated from YAML on {datetime.now().isoformat()}",
        is_default=True,
        created_by="migration_script",
        updated_by="migration_script",
    )
    db.add(profile)
    db.flush()

    # Migrate AI infrastructure
    llm_config = configs['settings.yaml'].get('llm', {})
    ai_infra = ConfigAIInfra(
        profile_id=profile.id,
        llm_endpoint=llm_config.get('endpoint', 'databricks-claude-sonnet-4-5'),
        llm_temperature=llm_config.get('temperature', 0.7),
        llm_max_tokens=llm_config.get('max_tokens', 60000),
    )
    db.add(ai_infra)

    # Migrate Genie space
    genie_config = configs['settings.yaml'].get('genie', {})
    genie_space = ConfigGenieSpace(
        profile_id=profile.id,
        space_id=genie_config.get('space_id', ''),
        space_name=genie_config.get('space_name', 'Default Space'),
        description=genie_config.get('description'),
        is_default=True,
    )
    db.add(genie_space)

    # Migrate MLflow
    mlflow_config = configs['mlflow.yaml'].get('mlflow', {})
    mlflow = ConfigMLflow(
        profile_id=profile.id,
        experiment_name=mlflow_config.get('experiment_name', '/default'),
    )
    db.add(mlflow)

    # Migrate prompts
    prompts_config = configs['prompts.yaml'].get('prompts', {})
    prompts = ConfigPrompts(
        profile_id=profile.id,
        system_prompt=prompts_config.get('system_prompt', ''),
        slide_editing_instructions=prompts_config.get('slide_editing_instructions', ''),
        user_prompt_template=prompts_config.get('user_prompt_template', '{question}'),
    )
    db.add(prompts)

    db.commit()
    return profile


def backup_yaml_files(config_dir: Path):
    """Create backup of YAML files before migration."""
    backup_dir = config_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(exist_ok=True)

    for yaml_file in config_dir.glob('*.yaml'):
        import shutil
        shutil.copy2(yaml_file, backup_dir / yaml_file.name)

    print(f"✓ Backed up YAML files to {backup_dir}")


def main():
    """Run migration."""
    print("=" * 60)
    print("YAML to Database Configuration Migration")
    print("=" * 60)

    # Locate settings directory
    project_root = Path(__file__).parent.parent
    config_dir = project_root / "settings"

    if not config_dir.exists():
        print("✗ Config directory not found")
        sys.exit(1)

    # Load YAML configs
    print("\n1. Loading YAML configurations...")
    configs = load_yaml_configs(config_dir)
    print(f"   Loaded {len(configs)} YAML files")

    # Backup YAML files
    print("\n2. Creating backup of YAML files...")
    backup_yaml_files(config_dir)

    # Migrate to database
    print("\n3. Migrating to database...")
    with get_db_session() as db:
        # Check if already migrated
        existing = db.query(ConfigProfile).first()
        if existing:
            print("   ⚠️  Database already has profiles")
            response = input("   Continue and create additional profile? (y/N): ")
            if response.lower() != 'y':
                print("   Migration cancelled")
                return

        profile = create_profile_from_yaml(db, configs, profile_name="default")
        print(f"   ✓ Created profile: {profile.name}")

    # Validation
    print("\n4. Validating migration...")
    with get_db_session() as db:
        profile = db.query(ConfigProfile).filter_by(name="default").first()
        if not profile:
            print("   ✗ Validation failed: Profile not found")
            sys.exit(1)

        if not profile.ai_infra:
            print("   ✗ Validation failed: AI db_app_deployment missing")
            sys.exit(1)

        if not profile.mlflow:
            print("   ✗ Validation failed: MLflow settings missing")
            sys.exit(1)

        if not profile.prompts:
            print("   ✗ Validation failed: Prompts settings missing")
            sys.exit(1)

        print("   ✓ All configurations migrated successfully")

    print("\n" + "=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Review the migrated configuration in the UI")
    print("2. Test the application")
    print("3. YAML files are backed up and no longer used at runtime")
    print("4. You can archive or delete the YAML files if desired")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
```

### Step 4: Backup and Restore Scripts

**File:** `scripts/backup_config.py`

```python
"""Backup configuration database to JSON."""

import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import get_db_session
from src.models.config import ConfigProfile


def backup_config(output_file: Path):
    """Export all configuration to JSON."""
    with get_db_session() as db:
        profiles = db.query(ConfigProfile).all()

        backup_data = {
            "backup_date": datetime.now().isoformat(),
            "profiles": []
        }

        for profile in profiles:
            profile_data = {
                "name": profile.name,
                "description": profile.description,
                "is_default": profile.is_default,
                "ai_infra": {
                    "llm_endpoint": profile.ai_infra.llm_endpoint,
                    "llm_temperature": float(profile.ai_infra.llm_temperature),
                    "llm_max_tokens": profile.ai_infra.llm_max_tokens,
                },
                "genie_spaces": [
                    {
                        "space_id": space.space_id,
                        "space_name": space.space_name,
                        "description": space.description,
                        "is_default": space.is_default,
                    }
                    for space in profile.genie_spaces
                ],
                "mlflow": {
                    "experiment_name": profile.mlflow.experiment_name,
                },
                "prompts": {
                    "system_prompt": profile.prompts.system_prompt,
                    "slide_editing_instructions": profile.prompts.slide_editing_instructions,
                    "user_prompt_template": profile.prompts.user_prompt_template,
                },
            }
            backup_data["profiles"].append(profile_data)

        with open(output_file, 'w') as f:
            json.dump(backup_data, f, indent=2)

        print(f"✓ Backed up {len(profiles)} profiles to {output_file}")


if __name__ == "__main__":
    output = Path(f"config_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    backup_config(output)
```

**File:** `scripts/restore_config.py`

```python
"""Restore configuration from JSON backup."""
# Implementation similar to migration script
```

### Step 5: Operations Runbook

**File:** `docs/operations/deployment.md`

Deployment guide:
- Environment variables required
- Database setup instructions
- Migration steps for production
- Rollback procedures
- Health checks
- Monitoring setup

**File:** `docs/operations/backup-restore.md`

Backup/restore procedures:
- Scheduled backup recommendations
- Manual backup process
- Restore from backup
- Disaster recovery

**File:** `docs/operations/troubleshooting.md`

Common issues and solutions:
- Database connection errors
- Migration failures
- Configuration not loading
- Agent initialization failures
- Performance issues
- Debugging tips

### Step 6: Update README and Tech Docs

**Update:** `README.md`

Add sections:
- Configuration Management overview
- Link to user guide
- Migration instructions for existing users

**Update:** `docs/technical/*.md`

Ensure all technical docs reflect new database-backed approach.

### Step 7: Deployment Checklist

Create pre-deployment checklist:

```markdown
## Pre-Deployment Checklist

- [ ] Database migrations tested in staging
- [ ] Backup procedures tested
- [ ] Restore procedures tested
- [ ] All tests passing
- [ ] Performance benchmarks acceptable
- [ ] Security review completed
- [ ] Documentation reviewed
- [ ] User guide published
- [ ] Operations team trained
- [ ] Rollback plan prepared
- [ ] Monitoring configured
- [ ] Backup schedule configured

## Deployment Steps

1. [ ] Backup existing database
2. [ ] Run database migrations
3. [ ] Run YAML migration script
4. [ ] Verify configuration in UI
5. [ ] Test core functionality
6. [ ] Monitor for errors
7. [ ] Update documentation links
8. [ ] Announce to users

## Post-Deployment

- [ ] Monitor error rates
- [ ] Check database performance
- [ ] Verify backups working
- [ ] Gather user feedback
- [ ] Address any issues
```

## Deliverables

- [ ] Complete user documentation
- [ ] Complete technical documentation
- [ ] API reference documentation
- [ ] Migration guide and script
- [ ] Backup and restore scripts
- [ ] Operations runbook
- [ ] Deployment checklist
- [ ] Updated README
- [ ] All documentation reviewed and polished

## Success Criteria

1. Users can easily understand how to use configuration management
2. Developers can understand the architecture
3. Operations team can deploy and maintain the system
4. Migration from YAML is smooth and documented
5. Backup/restore procedures are clear
6. Troubleshooting guide addresses common issues

## Final Steps

1. Run full end-to-end testing
2. Conduct user acceptance testing
3. Perform security audit
4. Get stakeholder approval
5. Schedule deployment
6. Execute deployment plan
7. Monitor post-deployment
8. Collect feedback for improvements

## Rollout Strategy

**Phase 1: Internal Testing**
- Deploy to dev environment
- Test with development team
- Gather feedback

**Phase 2: Staging**
- Deploy to staging environment
- Run migration script
- Full integration testing

**Phase 3: Production**
- Schedule maintenance window
- Execute deployment
- Monitor closely
- Be ready to rollback if needed

**Phase 4: Post-Deployment**
- Monitor for 48 hours
- Address any issues
- Collect user feedback
- Plan improvements

---

**Congratulations! You've completed all phases of the configuration management implementation.**

