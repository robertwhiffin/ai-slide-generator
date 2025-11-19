"""Initial schema with config tables

Revision ID: 001_initial_schema
Revises: 
Create Date: 2025-11-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create config_profiles table
    op.create_table(
        'config_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_config_profiles_name'), 'config_profiles', ['name'], unique=True)
    
    # Create config_ai_infra table
    op.create_table(
        'config_ai_infra',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('llm_endpoint', sa.String(length=255), nullable=False),
        sa.Column('llm_temperature', sa.DECIMAL(precision=3, scale=2), nullable=False),
        sa.Column('llm_max_tokens', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('llm_temperature >= 0 AND llm_temperature <= 1', name='check_temperature_range'),
        sa.CheckConstraint('llm_max_tokens > 0', name='check_max_tokens_positive'),
        sa.ForeignKeyConstraint(['profile_id'], ['config_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('profile_id')
    )
    
    # Create config_genie_spaces table
    op.create_table(
        'config_genie_spaces',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('space_id', sa.String(length=255), nullable=False),
        sa.Column('space_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['config_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_config_genie_spaces_profile', 'config_genie_spaces', ['profile_id'], unique=False)
    op.create_index(
        'idx_config_genie_spaces_default',
        'config_genie_spaces',
        ['profile_id', 'is_default'],
        unique=False,
        postgresql_where=sa.text('is_default = true')
    )
    
    # Create config_mlflow table
    op.create_table(
        'config_mlflow',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('experiment_name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['config_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('profile_id')
    )
    
    # Create config_prompts table
    op.create_table(
        'config_prompts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('slide_editing_instructions', sa.Text(), nullable=False),
        sa.Column('user_prompt_template', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['config_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('profile_id')
    )
    
    # Create config_history table
    op.create_table(
        'config_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('changed_by', sa.String(length=255), nullable=False),
        sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['config_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_config_history_profile', 'config_history', ['profile_id'], unique=False)
    op.create_index(
        'idx_config_history_timestamp',
        'config_history',
        ['timestamp'],
        unique=False,
        postgresql_ops={'timestamp': 'DESC'}
    )
    op.create_index('idx_config_history_domain', 'config_history', ['domain'], unique=False)
    
    # Add constraint: only one default profile
    op.execute("""
        CREATE OR REPLACE FUNCTION check_single_default_profile()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.is_default = TRUE THEN
                IF EXISTS (SELECT 1 FROM config_profiles 
                          WHERE is_default = TRUE AND id != NEW.id) THEN
                    RAISE EXCEPTION 'Only one profile can be default';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    op.execute("""
        CREATE TRIGGER enforce_single_default_profile
        BEFORE INSERT OR UPDATE ON config_profiles
        FOR EACH ROW EXECUTE FUNCTION check_single_default_profile();
    """)
    
    # Add constraint: only one default Genie space per profile
    op.execute("""
        CREATE OR REPLACE FUNCTION check_single_default_genie_space()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.is_default = TRUE THEN
                IF EXISTS (SELECT 1 FROM config_genie_spaces 
                          WHERE profile_id = NEW.profile_id 
                          AND is_default = TRUE 
                          AND id != NEW.id) THEN
                    RAISE EXCEPTION 'Only one Genie space can be default per profile';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    op.execute("""
        CREATE TRIGGER enforce_single_default_genie_space
        BEFORE INSERT OR UPDATE ON config_genie_spaces
        FOR EACH ROW EXECUTE FUNCTION check_single_default_genie_space();
    """)


def downgrade() -> None:
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS enforce_single_default_genie_space ON config_genie_spaces;")
    op.execute("DROP FUNCTION IF EXISTS check_single_default_genie_space();")
    op.execute("DROP TRIGGER IF EXISTS enforce_single_default_profile ON config_profiles;")
    op.execute("DROP FUNCTION IF EXISTS check_single_default_profile();")
    
    # Drop tables in reverse order
    op.drop_index('idx_config_history_domain', table_name='config_history')
    op.drop_index('idx_config_history_timestamp', table_name='config_history')
    op.drop_index('idx_config_history_profile', table_name='config_history')
    op.drop_table('config_history')
    
    op.drop_table('config_prompts')
    op.drop_table('config_mlflow')
    
    op.drop_index('idx_config_genie_spaces_default', table_name='config_genie_spaces')
    op.drop_index('idx_config_genie_spaces_profile', table_name='config_genie_spaces')
    op.drop_table('config_genie_spaces')
    
    op.drop_table('config_ai_infra')
    
    op.drop_index(op.f('ix_config_profiles_name'), table_name='config_profiles')
    op.drop_table('config_profiles')

