"""add voice events

Revision ID: 010_add_voice_event_models
Revises: 009_add_event_models
Create Date: 2026-07-09 13:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '010_add_voice_event_models'
down_revision = '009_add_event_models'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE IF NOT EXISTS voice_events (
            id INTEGER NOT NULL,
            match_id INTEGER,
            intent VARCHAR,
            raw_transcript TEXT,
            normalized_text TEXT,
            parsed_slots TEXT,
            confidence FLOAT DEFAULT '0.0',
            asr_latency_ms FLOAT,
            noise_rms FLOAT,
            score_before VARCHAR,
            score_after VARCHAR,
            status VARCHAR,
            disposition VARCHAR,
            source VARCHAR DEFAULT 'asr',
            speaker_label VARCHAR,
            created_at DATETIME,
            undone_by INTEGER,
            PRIMARY KEY (id),
            FOREIGN KEY(match_id) REFERENCES matches (id),
            FOREIGN KEY(undone_by) REFERENCES voice_events (id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_voice_events_id ON voice_events (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_voice_events_match_id ON voice_events (match_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_voice_events_status ON voice_events (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_voice_events_intent ON voice_events (intent)")

    op.execute(
        """CREATE TABLE IF NOT EXISTS voice_commands (
            id INTEGER NOT NULL,
            match_id INTEGER,
            transcript TEXT,
            parsed_intent VARCHAR,
            expected_intent VARCHAR,
            matched BOOLEAN,
            correction VARCHAR,
            match_context TEXT,
            mic_type VARCHAR,
            noise_condition VARCHAR,
            audio_stored BOOLEAN DEFAULT '0',
            created_at DATETIME,
            PRIMARY KEY (id),
            FOREIGN KEY(match_id) REFERENCES matches (id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_voice_commands_id ON voice_commands (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_voice_commands_match_id ON voice_commands (match_id)")


def downgrade() -> None:
    op.drop_index('ix_voice_commands_match_id', table_name='voice_commands')
    op.drop_index('ix_voice_commands_id', table_name='voice_commands')
    op.drop_table('voice_commands')
    op.drop_index('ix_voice_events_intent', table_name='voice_events')
    op.drop_index('ix_voice_events_status', table_name='voice_events')
    op.drop_index('ix_voice_events_match_id', table_name='voice_events')
    op.drop_index('ix_voice_events_id', table_name='voice_events')
    op.drop_table('voice_events')
