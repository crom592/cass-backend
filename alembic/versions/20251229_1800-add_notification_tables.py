"""Add notification tables

Revision ID: add_notification_tables
Revises: 94fe0c1c096e
Create Date: 2025-12-29 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_notification_tables'
down_revision = '94fe0c1c096e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create user_notification_preferences table
    op.create_table(
        'user_notification_preferences',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),

        # Global toggles
        sa.Column('email_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('sms_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('in_app_enabled', sa.Boolean(), nullable=False, server_default='true'),

        # Email preferences
        sa.Column('email_on_ticket_created', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('email_on_ticket_assigned', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('email_on_ticket_status_changed', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('email_on_ticket_comment', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('email_on_sla_breach', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('email_on_sla_warning', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('email_on_worklog_added', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('email_on_assignment_due', sa.Boolean(), nullable=False, server_default='true'),

        # SMS preferences
        sa.Column('sms_on_ticket_created', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sms_on_ticket_assigned', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('sms_on_ticket_status_changed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sms_on_ticket_comment', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sms_on_sla_breach', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('sms_on_sla_warning', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sms_on_worklog_added', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sms_on_assignment_due', sa.Boolean(), nullable=False, server_default='true'),

        # Quiet hours
        sa.Column('quiet_hours_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('quiet_hours_start', sa.String(), nullable=True),
        sa.Column('quiet_hours_end', sa.String(), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index('ix_user_notification_preferences_user_id', 'user_notification_preferences', ['user_id'])

    # Create tenant_notification_settings table
    op.create_table(
        'tenant_notification_settings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),

        # Global tenant toggles
        sa.Column('email_notifications_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('sms_notifications_enabled', sa.Boolean(), nullable=False, server_default='true'),

        # Custom from email/name
        sa.Column('custom_from_email', sa.String(), nullable=True),
        sa.Column('custom_from_name', sa.String(), nullable=True),

        # Default preferences (JSON)
        sa.Column('default_user_preferences', sa.JSON(), nullable=True),

        # Throttling
        sa.Column('throttle_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('max_notifications_per_hour', sa.String(), server_default='100'),

        # SLA warning
        sa.Column('sla_warning_threshold_minutes', sa.String(), server_default='30'),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('tenant_id')
    )
    op.create_index('ix_tenant_notification_settings_tenant_id', 'tenant_notification_settings', ['tenant_id'])

    # Create notification_logs table
    op.create_table(
        'notification_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),

        # Target
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('recipient_email', sa.String(), nullable=True),
        sa.Column('recipient_phone', sa.String(), nullable=True),

        # Notification details
        sa.Column('event_type', sa.Enum(
            'ticket_created', 'ticket_assigned', 'ticket_status_changed',
            'ticket_comment_added', 'sla_breach', 'sla_warning',
            'worklog_added', 'assignment_due',
            name='notificationeventtype'
        ), nullable=False),
        sa.Column('channel', sa.Enum('email', 'sms', 'in_app', name='notificationchannel'), nullable=False),
        sa.Column('status', sa.Enum(
            'pending', 'sent', 'delivered', 'failed', 'cancelled',
            name='notificationstatus'
        ), nullable=False, server_default='pending'),

        # Content
        sa.Column('subject', sa.String(), nullable=True),
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('body_html', sa.Text(), nullable=True),

        # Related entity
        sa.Column('related_ticket_id', sa.String(), nullable=True),
        sa.Column('related_entity_type', sa.String(), nullable=True),
        sa.Column('related_entity_id', sa.String(), nullable=True),

        # Delivery metadata
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('provider_message_id', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.String(), server_default='0'),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('failed_at', sa.DateTime(), nullable=True),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['related_ticket_id'], ['tickets.id'], ondelete='SET NULL')
    )
    op.create_index('ix_notification_logs_tenant_id', 'notification_logs', ['tenant_id'])
    op.create_index('ix_notification_logs_user_id', 'notification_logs', ['user_id'])
    op.create_index('ix_notification_logs_recipient_email', 'notification_logs', ['recipient_email'])
    op.create_index('ix_notification_logs_event_type', 'notification_logs', ['event_type'])
    op.create_index('ix_notification_logs_channel', 'notification_logs', ['channel'])
    op.create_index('ix_notification_logs_status', 'notification_logs', ['status'])
    op.create_index('ix_notification_logs_related_ticket_id', 'notification_logs', ['related_ticket_id'])
    op.create_index('ix_notification_logs_created_at', 'notification_logs', ['created_at'])


def downgrade() -> None:
    # Drop notification_logs table
    op.drop_index('ix_notification_logs_created_at', table_name='notification_logs')
    op.drop_index('ix_notification_logs_related_ticket_id', table_name='notification_logs')
    op.drop_index('ix_notification_logs_status', table_name='notification_logs')
    op.drop_index('ix_notification_logs_channel', table_name='notification_logs')
    op.drop_index('ix_notification_logs_event_type', table_name='notification_logs')
    op.drop_index('ix_notification_logs_recipient_email', table_name='notification_logs')
    op.drop_index('ix_notification_logs_user_id', table_name='notification_logs')
    op.drop_index('ix_notification_logs_tenant_id', table_name='notification_logs')
    op.drop_table('notification_logs')

    # Drop tenant_notification_settings table
    op.drop_index('ix_tenant_notification_settings_tenant_id', table_name='tenant_notification_settings')
    op.drop_table('tenant_notification_settings')

    # Drop user_notification_preferences table
    op.drop_index('ix_user_notification_preferences_user_id', table_name='user_notification_preferences')
    op.drop_table('user_notification_preferences')

    # Drop enum types
    op.execute('DROP TYPE IF EXISTS notificationstatus')
    op.execute('DROP TYPE IF EXISTS notificationchannel')
    op.execute('DROP TYPE IF EXISTS notificationeventtype')
