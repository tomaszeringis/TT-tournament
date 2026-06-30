"""Add multimodal AI models for dataset registry and session management.

Revision ID: 008_add_multimodal_models
Revises: 007_add_operator_workflow
Create Date: 2026-06-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_add_multimodal_models'
down_revision = '007_add_operator_workflow'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    """Check if a table exists."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return table_name in inspector.get_table_names()


def _index_exists(index_name, table_name):
    """Check if an index exists."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    # Create datasets table
    if not _table_exists('datasets'):
        op.create_table(
            'datasets',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('dataset_id', sa.String(), nullable=True),
            sa.Column('name', sa.String(), nullable=True),
            sa.Column('modality', sa.String(), nullable=True),
            sa.Column('task', sa.String(), nullable=True),
            sa.Column('license', sa.String(), nullable=True),
            sa.Column('commercial_allowed', sa.Boolean(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=True),
            sa.Column('local_raw_path', sa.String(), nullable=True),
            sa.Column('local_processed_path', sa.String(), nullable=True),
            sa.Column('required_for_phase', sa.String(), nullable=True),
            sa.Column('notes', sa.String(), nullable=True),
            sa.Column('size_gb', sa.Float(), nullable=True),
            sa.Column('version', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_datasets_id', 'datasets'):
        op.create_index('ix_datasets_id', 'datasets', ['id'], unique=False)
    if not _index_exists('ix_datasets_dataset_id', 'datasets'):
        op.create_index('ix_datasets_dataset_id', 'datasets', ['dataset_id'], unique=True)

    # Create dataset_artifacts table
    if not _table_exists('dataset_artifacts'):
        op.create_table(
            'dataset_artifacts',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('dataset_id', sa.Integer(), nullable=True),
            sa.Column('artifact_type', sa.String(), nullable=True),
            sa.Column('path', sa.String(), nullable=True),
            sa.Column('checksum', sa.String(), nullable=True),
            sa.Column('size_bytes', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_dataset_artifacts_id', 'dataset_artifacts'):
        op.create_index('ix_dataset_artifacts_id', 'dataset_artifacts', ['id'], unique=False)

    # Create data_samples table
    if not _table_exists('data_samples'):
        op.create_table(
            'data_samples',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('dataset_id', sa.Integer(), nullable=True),
            sa.Column('sample_key', sa.String(), nullable=True),
            sa.Column('timestamp', sa.DateTime(), nullable=True),
            sa.Column('duration_seconds', sa.Float(), nullable=True),
            sa.Column('metadata_json', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_data_samples_id', 'data_samples'):
        op.create_index('ix_data_samples_id', 'data_samples', ['id'], unique=False)
    if not _index_exists('ix_data_samples_sample_key', 'data_samples'):
        op.create_index('ix_data_samples_sample_key', 'data_samples', ['sample_key'], unique=False)

    # Create annotations table
    if not _table_exists('annotations'):
        op.create_table(
            'annotations',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('data_sample_id', sa.Integer(), nullable=True),
            sa.Column('annotator_id', sa.String(), nullable=True),
            sa.Column('label', sa.String(), nullable=True),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['data_sample_id'], ['data_samples.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_annotations_id', 'annotations'):
        op.create_index('ix_annotations_id', 'annotations', ['id'], unique=False)

    # Create multimodal_sessions table
    if not _table_exists('multimodal_sessions'):
        op.create_table(
            'multimodal_sessions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_name', sa.String(), nullable=True),
            sa.Column('start_time', sa.DateTime(), nullable=True),
            sa.Column('end_time', sa.DateTime(), nullable=True),
            sa.Column('player1_id', sa.Integer(), nullable=True),
            sa.Column('player2_id', sa.Integer(), nullable=True),
            sa.Column('metadata_json', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['player1_id'], ['players.id'], ),
            sa.ForeignKeyConstraint(['player2_id'], ['players.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_multimodal_sessions_id', 'multimodal_sessions'):
        op.create_index('ix_multimodal_sessions_id', 'multimodal_sessions', ['id'], unique=False)

    # Create sensor_streams table
    if not _table_exists('sensor_streams'):
        op.create_table(
            'sensor_streams',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_id', sa.Integer(), nullable=True),
            sa.Column('sensor_type', sa.String(), nullable=True),
            sa.Column('start_time', sa.DateTime(), nullable=True),
            sa.Column('end_time', sa.DateTime(), nullable=True),
            sa.Column('sample_rate', sa.Float(), nullable=True),
            sa.Column('data_path', sa.String(), nullable=True),
            sa.ForeignKeyConstraint(['session_id'], ['multimodal_sessions.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_sensor_streams_id', 'sensor_streams'):
        op.create_index('ix_sensor_streams_id', 'sensor_streams', ['id'], unique=False)

    # Create video_segments table
    if not _table_exists('video_segments'):
        op.create_table(
            'video_segments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_id', sa.Integer(), nullable=True),
            sa.Column('start_time', sa.DateTime(), nullable=True),
            sa.Column('end_time', sa.DateTime(), nullable=True),
            sa.Column('video_path', sa.String(), nullable=True),
            sa.Column('frame_count', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['session_id'], ['multimodal_sessions.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_video_segments_id', 'video_segments'):
        op.create_index('ix_video_segments_id', 'video_segments', ['id'], unique=False)

    # Create audio_segments table
    if not _table_exists('audio_segments'):
        op.create_table(
            'audio_segments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_id', sa.Integer(), nullable=True),
            sa.Column('start_time', sa.DateTime(), nullable=True),
            sa.Column('end_time', sa.DateTime(), nullable=True),
            sa.Column('audio_path', sa.String(), nullable=True),
            sa.Column('sample_rate', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['session_id'], ['multimodal_sessions.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_audio_segments_id', 'audio_segments'):
        op.create_index('ix_audio_segments_id', 'audio_segments', ['id'], unique=False)

    # Create ball_trajectories table
    if not _table_exists('ball_trajectories'):
        op.create_table(
            'ball_trajectories',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_id', sa.Integer(), nullable=True),
            sa.Column('frame_data_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['session_id'], ['multimodal_sessions.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_ball_trajectories_id', 'ball_trajectories'):
        op.create_index('ix_ball_trajectories_id', 'ball_trajectories', ['id'], unique=False)

    # Create stroke_events table
    if not _table_exists('stroke_events'):
        op.create_table(
            'stroke_events',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_id', sa.Integer(), nullable=True),
            sa.Column('stroke_type', sa.String(), nullable=True),
            sa.Column('start_time', sa.DateTime(), nullable=True),
            sa.Column('end_time', sa.DateTime(), nullable=True),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.ForeignKeyConstraint(['session_id'], ['multimodal_sessions.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_stroke_events_id', 'stroke_events'):
        op.create_index('ix_stroke_events_id', 'stroke_events', ['id'], unique=False)

    # Create coaching_feedback table
    if not _table_exists('coaching_feedback'):
        op.create_table(
            'coaching_feedback',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_id', sa.Integer(), nullable=True),
            sa.Column('feedback_text', sa.Text(), nullable=True),
            sa.Column('recommendations_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['session_id'], ['multimodal_sessions.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_coaching_feedback_id', 'coaching_feedback'):
        op.create_index('ix_coaching_feedback_id', 'coaching_feedback', ['id'], unique=False)

    # Create model_experiments table
    if not _table_exists('model_experiments'):
        op.create_table(
            'model_experiments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=True),
            sa.Column('model_config_json', sa.Text(), nullable=True),
            sa.Column('dataset_combination', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_model_experiments_id', 'model_experiments'):
        op.create_index('ix_model_experiments_id', 'model_experiments', ['id'], unique=False)

    # Create evaluation_runs table
    if not _table_exists('evaluation_runs'):
        op.create_table(
            'evaluation_runs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('experiment_id', sa.Integer(), nullable=True),
            sa.Column('metric_name', sa.String(), nullable=True),
            sa.Column('metric_value', sa.Float(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['experiment_id'], ['model_experiments.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
    if not _index_exists('ix_evaluation_runs_id', 'evaluation_runs'):
        op.create_index('ix_evaluation_runs_id', 'evaluation_runs', ['id'], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order
    if _table_exists('evaluation_runs'):
        if _index_exists('ix_evaluation_runs_id', 'evaluation_runs'):
            op.drop_index('ix_evaluation_runs_id', table_name='evaluation_runs')
        op.drop_table('evaluation_runs')
    
    if _table_exists('model_experiments'):
        if _index_exists('ix_model_experiments_id', 'model_experiments'):
            op.drop_index('ix_model_experiments_id', table_name='model_experiments')
        op.drop_table('model_experiments')
    
    if _table_exists('coaching_feedback'):
        if _index_exists('ix_coaching_feedback_id', 'coaching_feedback'):
            op.drop_index('ix_coaching_feedback_id', table_name='coaching_feedback')
        op.drop_table('coaching_feedback')
    
    if _table_exists('stroke_events'):
        if _index_exists('ix_stroke_events_id', 'stroke_events'):
            op.drop_index('ix_stroke_events_id', table_name='stroke_events')
        op.drop_table('stroke_events')
    
    if _table_exists('ball_trajectories'):
        if _index_exists('ix_ball_trajectories_id', 'ball_trajectories'):
            op.drop_index('ix_ball_trajectories_id', table_name='ball_trajectories')
        op.drop_table('ball_trajectories')
    
    if _table_exists('audio_segments'):
        if _index_exists('ix_audio_segments_id', 'audio_segments'):
            op.drop_index('ix_audio_segments_id', table_name='audio_segments')
        op.drop_table('audio_segments')
    
    if _table_exists('video_segments'):
        if _index_exists('ix_video_segments_id', 'video_segments'):
            op.drop_index('ix_video_segments_id', table_name='video_segments')
        op.drop_table('video_segments')
    
    if _table_exists('multimodal_sessions'):
        if _index_exists('ix_multimodal_sessions_id', 'multimodal_sessions'):
            op.drop_index('ix_multimodal_sessions_id', table_name='multimodal_sessions')
        op.drop_table('multimodal_sessions')
    
    if _table_exists('annotations'):
        if _index_exists('ix_annotations_id', 'annotations'):
            op.drop_index('ix_annotations_id', table_name='annotations')
        op.drop_table('annotations')
    
    if _table_exists('data_samples'):
        if _index_exists('ix_data_samples_sample_key', 'data_samples'):
            op.drop_index('ix_data_samples_sample_key', table_name='data_samples')
        if _index_exists('ix_data_samples_id', 'data_samples'):
            op.drop_index('ix_data_samples_id', table_name='data_samples')
        op.drop_table('data_samples')
    
    if _table_exists('dataset_artifacts'):
        if _index_exists('ix_dataset_artifacts_id', 'dataset_artifacts'):
            op.drop_index('ix_dataset_artifacts_id', table_name='dataset_artifacts')
        op.drop_table('dataset_artifacts')
    
    if _table_exists('datasets'):
        if _index_exists('ix_datasets_dataset_id', 'datasets'):
            op.drop_index('ix_datasets_dataset_id', table_name='datasets')
        if _index_exists('ix_datasets_id', 'datasets'):
            op.drop_index('ix_datasets_id', table_name='datasets')
        op.drop_table('datasets')