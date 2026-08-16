"""Initial schema for LinkPlease Instagram Automation

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-08-16 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rules table
    op.create_table(
        'rules',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('keyword', sa.String(length=255), nullable=False),
        sa.Column('dm_message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_rules_keyword', 'rules', ['keyword'])

    # 2. Webhook Events table
    op.create_table(
        'webhook_events',
        sa.Column('event_id', sa.String(length=64), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint('event_id')
    )

    # 3. Comments table
    op.create_table(
        'comments',
        sa.Column('comment_id', sa.String(length=64), nullable=False),
        sa.Column('post_id', sa.String(length=64), nullable=True),
        sa.Column('user_id', sa.String(length=64), nullable=True),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, default=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('comment_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('comment_id')
    )
    op.create_index('idx_comments_user_id', 'comments', ['user_id'])

    # 4. Deliveries table
    op.create_table(
        'deliveries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('rule_id', sa.String(length=36), nullable=False),
        sa.Column('comment_id', sa.String(length=64), nullable=False),
        sa.Column('dm_id', sa.String(length=64), nullable=True),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('max_retries', sa.Integer(), nullable=False, default=5),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['rule_id'], ['rules.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key'),
        sa.UniqueConstraint('user_id', 'rule_id', name='uq_deliveries_user_rule')
    )
    op.create_index('idx_deliveries_dm_id', 'deliveries', ['dm_id'])
    op.create_index('idx_deliveries_status', 'deliveries', ['status'])

    # 5. Blocked Duplicates table
    op.create_table(
        'blocked_duplicates',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('rule_id', sa.String(length=36), nullable=False),
        sa.Column('comment_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', 'rule_id', name='uq_blocked_dup_event_rule')
    )
    op.create_index('idx_blocked_dup_user_rule', 'blocked_duplicates', ['user_id', 'rule_id'])


def downgrade() -> None:
    op.drop_table('blocked_duplicates')
    op.drop_table('deliveries')
    op.drop_table('comments')
    op.drop_table('webhook_events')
    op.drop_table('rules')
