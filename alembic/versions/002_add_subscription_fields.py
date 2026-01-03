"""add_subscription_fields

Revision ID: 002_add_subscription_fields
Revises: 001_create_admins_tables
Create Date: 2025-01-04 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002_add_subscription_fields'
down_revision = '001_create_admins'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поле is_vip в таблицу users
    op.add_column('users', sa.Column('is_vip', sa.Boolean(), nullable=False, server_default='false'))
    op.create_index('idx_users_is_vip', 'users', ['is_vip'])
    
    # Добавляем поля подписки в таблицу crossposting_links
    op.add_column('crossposting_links', sa.Column('subscription_status', sa.String(length=50), nullable=False, server_default='free_trial'))
    op.add_column('crossposting_links', sa.Column('free_trial_end_date', sa.DateTime(), nullable=True))
    op.add_column('crossposting_links', sa.Column('subscription_end_date', sa.DateTime(), nullable=True))
    op.add_column('crossposting_links', sa.Column('is_first_link', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('crossposting_links', sa.Column('last_payment_date', sa.DateTime(), nullable=True))
    op.add_column('crossposting_links', sa.Column('payment_id', sa.String(length=255), nullable=True))
    op.add_column('crossposting_links', sa.Column('payment_status', sa.String(length=50), nullable=True))
    op.add_column('crossposting_links', sa.Column('yookassa_payment_id', sa.String(length=255), nullable=True))
    
    # Создаем индекс для subscription_status
    op.create_index('idx_subscription_status', 'crossposting_links', ['subscription_status'])


def downgrade() -> None:
    # Удаляем индексы
    op.drop_index('idx_subscription_status', table_name='crossposting_links')
    op.drop_index('idx_users_is_vip', table_name='users')
    
    # Удаляем поля из crossposting_links
    op.drop_column('crossposting_links', 'yookassa_payment_id')
    op.drop_column('crossposting_links', 'payment_status')
    op.drop_column('crossposting_links', 'payment_id')
    op.drop_column('crossposting_links', 'last_payment_date')
    op.drop_column('crossposting_links', 'is_first_link')
    op.drop_column('crossposting_links', 'subscription_end_date')
    op.drop_column('crossposting_links', 'free_trial_end_date')
    op.drop_column('crossposting_links', 'subscription_status')
    
    # Удаляем поле is_vip из users
    op.drop_column('users', 'is_vip')

