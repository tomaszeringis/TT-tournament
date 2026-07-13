"""add commentary events

Revision ID: 014_add_commentary_events
Revises: 013_add_tournament_tie_break_order
Create Date: 2026-07-13 15:04:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '014_add_commentary_events'
down_revision = '013_add_tournament_tie_break_order'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE IF NOT EXISTS commentary_events (
            id INTEGER NOT NULL,
            created_at DATETIME,
            tournament_id INTEGER,
            match_id INTEGER,
            player_a VARCHAR,
            player_b VARCHAR,
            event_type VARCHAR,
            source_event_json TEXT,
            score_before_json TEXT,
            score_after_json TEXT,
            style VARCHAR,
            language VARCHAR,
            frequency_mode VARCHAR,
            intensity VARCHAR,
            template_id VARCHAR,
            generated_text TEXT,
            final_text TEXT,
            used_ollama BOOLEAN DEFAULT '0',
            spoken BOOLEAN DEFAULT '0',
            tts_mode VARCHAR,
            latency_ms FLOAT,
            error TEXT,
            cache_key VARCHAR,
            ollama_model VARCHAR,
            ollama_cache_hit BOOLEAN DEFAULT '0',
            PRIMARY KEY (id),
            FOREIGN KEY(tournament_id) REFERENCES tournaments (id),
            FOREIGN KEY(match_id) REFERENCES matches (id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_commentary_events_id ON commentary_events (id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_commentary_events_match_id ON commentary_events (match_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_commentary_events_event_type ON commentary_events (event_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_commentary_events_cache_key ON commentary_events (cache_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_commentary_events_ollama_model ON commentary_events (ollama_model)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_commentary_events_ollama_cache_hit ON commentary_events (ollama_cache_hit)")


def downgrade() -> None:
    op.drop_index('ix_commentary_events_cache_key', table_name='commentary_events')
    op.drop_index('ix_commentary_events_event_type', table_name='commentary_events')
    op.drop_index('ix_commentary_events_match_id', table_name='commentary_events')
    op.drop_index('ix_commentary_events_id', table_name='commentary_events')
    op.drop_table('commentary_events')
