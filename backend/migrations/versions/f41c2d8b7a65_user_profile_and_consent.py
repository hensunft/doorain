"""user profile (first/last name, unique e-mail) and consent evidence

Revision ID: f41c2d8b7a65
Revises: e3b7a91c4d20
Create Date: 2026-09-24 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f41c2d8b7a65'
down_revision: str | None = 'e3b7a91c4d20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Все новые поля необязательны: у прежних учётных записей (владелец и ранее приглашённые пользователи) имя и фамилия остаются пустыми —
    интерфейс показывает логин, ничего не выдумывается. Согласие на обработку у них не проставляется задним числом: его нет в данных.
    Существующие e-mail приводятся к нижнему регистру, чтобы уникальность не зависела от регистра."""
    op.add_column('users', sa.Column('first_name', sa.String(length=80), nullable=True))
    op.add_column('users', sa.Column('last_name', sa.String(length=80), nullable=True))
    op.add_column('users', sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('pd_consent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('legal_version', sa.String(length=20), nullable=True))
    op.execute("update users set email = lower(trim(email)) where email is not null")
    op.execute("update users set email = null where email = ''")
    op.create_unique_constraint('users_email_key', 'users', ['email'])


def downgrade() -> None:
    op.drop_constraint('users_email_key', 'users', type_='unique')
    op.drop_column('users', 'legal_version')
    op.drop_column('users', 'pd_consent_at')
    op.drop_column('users', 'terms_accepted_at')
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name')
