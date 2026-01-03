"""Create admins and admin_sessions tables

Revision ID: 001_create_admins
Revises: 948144f2b5be
Create Date: 2026-01-03 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_create_admins'
down_revision = '948144f2b5be'
branch_labels = None
depends_on = None


def upgrade():
    # Создаем таблицу admins
    op.create_table(
        'admins',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_admins_id'), 'admins', ['id'], unique=False)
    op.create_index(op.f('ix_admins_username'), 'admins', ['username'], unique=True)
    op.create_index(op.f('ix_admins_is_active'), 'admins', ['is_active'], unique=False)
    
    # Создаем таблицу admin_sessions
    op.create_table(
        'admin_sessions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('admin_id', sa.BigInteger(), nullable=False),
        sa.Column('token', sa.String(length=512), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['admin_id'], ['admins.id'], ondelete='CASCADE')
    )
    op.create_index(op.f('ix_admin_sessions_id'), 'admin_sessions', ['id'], unique=False)
    op.create_index(op.f('ix_admin_sessions_admin_id'), 'admin_sessions', ['admin_id'], unique=False)
    op.create_index(op.f('ix_admin_sessions_token'), 'admin_sessions', ['token'], unique=True)
    op.create_index(op.f('ix_admin_sessions_expires_at'), 'admin_sessions', ['expires_at'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_admin_sessions_expires_at'), table_name='admin_sessions')
    op.drop_index(op.f('ix_admin_sessions_token'), table_name='admin_sessions')
    op.drop_index(op.f('ix_admin_sessions_admin_id'), table_name='admin_sessions')
    op.drop_index(op.f('ix_admin_sessions_id'), table_name='admin_sessions')
    op.drop_table('admin_sessions')
    op.drop_index(op.f('ix_admins_is_active'), table_name='admins')
    op.drop_index(op.f('ix_admins_username'), table_name='admins')
    op.drop_index(op.f('ix_admins_id'), table_name='admins')
    op.drop_table('admins')

