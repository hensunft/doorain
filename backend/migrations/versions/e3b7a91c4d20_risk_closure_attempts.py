"""risk closure attempts: аудит проверки ответа о закрытии риска

Revision ID: e3b7a91c4d20
Revises: d72cf3dda2ec
Create Date: 2026-09-24 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e3b7a91c4d20'
down_revision: str | None = 'd72cf3dda2ec'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    """Только новая таблица: уже закрытые риски не пересматриваются, их resolved_by сохраняется как был."""
    op.create_table('risk_closure_attempts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('risk_id', sa.Uuid(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=120), nullable=False),
    sa.Column('source', sa.String(length=12), nullable=False),
    sa.Column('user_answer', sa.Text(), nullable=False),
    sa.Column('initiated_by', sa.String(length=64), nullable=False),
    sa.Column('risk_version', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=10), nullable=False),
    sa.Column('decision', sa.String(length=12), nullable=True),
    sa.Column('resolution_kind', sa.String(length=16), nullable=True),
    sa.Column('verification', sa.String(length=12), nullable=True),
    sa.Column('confidence', sa.String(length=8), nullable=True),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('question', sa.Text(), nullable=True),
    sa.Column('quote', sa.Text(), nullable=True),
    sa.Column('facts', JSON, nullable=False),
    sa.Column('citation_ids', JSON, nullable=False),
    sa.Column('model_info', JSON, nullable=False),
    sa.Column('error', sa.String(length=300), nullable=True),
    sa.Column('applied', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['risk_id'], ['risks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('risk_id', 'idempotency_key')
    )
    op.create_index(op.f('ix_risk_closure_attempts_risk_id'), 'risk_closure_attempts', ['risk_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_risk_closure_attempts_risk_id'), table_name='risk_closure_attempts')
    op.drop_table('risk_closure_attempts')
