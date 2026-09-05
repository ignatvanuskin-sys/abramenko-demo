"""init"""
from alembic import op
import sqlalchemy as sa

revision = '001_init'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('branches', sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(120), nullable=False), sa.Column('address', sa.String(255), nullable=False), sa.Column('timezone', sa.String(64), nullable=False), sa.Column('is_active', sa.Boolean))
    op.create_table('masters', sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(120), nullable=False), sa.Column('specialization', sa.String(120)), sa.Column('is_active', sa.Boolean))
    op.create_table('services', sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(120), nullable=False), sa.Column('duration_minutes', sa.Integer, nullable=False), sa.Column('price_min', sa.Integer), sa.Column('price_max', sa.Integer), sa.Column('category', sa.String(64)))
    op.create_table('master_branches', sa.Column('master_id', sa.Integer, sa.ForeignKey('masters.id', ondelete='CASCADE'), primary_key=True), sa.Column('branch_id', sa.Integer, sa.ForeignKey('branches.id', ondelete='CASCADE'), primary_key=True))
    op.create_table('master_services', sa.Column('master_id', sa.Integer, sa.ForeignKey('masters.id', ondelete='CASCADE'), primary_key=True), sa.Column('service_id', sa.Integer, sa.ForeignKey('services.id', ondelete='CASCADE'), primary_key=True))
    op.create_table('working_hours', sa.Column('id', sa.Integer, primary_key=True), sa.Column('master_id', sa.Integer, sa.ForeignKey('masters.id', ondelete='CASCADE'), nullable=False), sa.Column('weekday', sa.Integer, nullable=False), sa.Column('start_time', sa.Time, nullable=False), sa.Column('end_time', sa.Time, nullable=False), sa.UniqueConstraint('master_id','weekday', name='uq_working_hours'))
    op.create_table('schedule_exceptions', sa.Column('id', sa.Integer, primary_key=True), sa.Column('master_id', sa.Integer, sa.ForeignKey('masters.id', ondelete='CASCADE'), nullable=False), sa.Column('date', sa.Date, nullable=False), sa.Column('is_day_off', sa.Boolean), sa.Column('custom_start', sa.Time), sa.Column('custom_end', sa.Time), sa.UniqueConstraint('master_id','date', name='uq_exception'))
    op.create_table('appointments', sa.Column('id', sa.Integer, primary_key=True), sa.Column('branch_id', sa.Integer, sa.ForeignKey('branches.id'), nullable=False), sa.Column('master_id', sa.Integer, sa.ForeignKey('masters.id'), nullable=False), sa.Column('service_id', sa.Integer, sa.ForeignKey('services.id'), nullable=False), sa.Column('client_name', sa.String(120), nullable=False), sa.Column('client_phone', sa.String(32), nullable=False), sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False), sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False), sa.Column('status', sa.String(16), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_appointments_master_starts', 'appointments', ['master_id','starts_at'])
    # EXCLUDE только для Postgres — на SQLite пропустится
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname='btree_gist') THEN
                ALTER TABLE appointments ADD CONSTRAINT no_overlap EXCLUDE USING gist (
                    master_id WITH =,
                    tsrange(starts_at, ends_at) WITH &&
                ) WHERE (status='booked');
            ELSE
                PERFORM 1;
            END IF;
        EXCEPTION WHEN OTHERS THEN PERFORM 1; END $$;
    """))
    try:
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS btree_gist;"))
        op.execute(sa.text("ALTER TABLE appointments ADD CONSTRAINT no_overlap EXCLUDE USING gist (master_id WITH =, tsrange(starts_at, ends_at) WITH &&) WHERE (status='booked');"))
    except Exception:
        pass

def downgrade():
    try:
        op.drop_constraint('no_overlap', 'appointments', type_='exclude')
    except Exception:
        pass
    op.drop_index('ix_appointments_master_starts', table_name='appointments')
    op.drop_table('appointments')
    op.drop_table('schedule_exceptions')
    op.drop_table('working_hours')
    op.drop_table('master_services')
    op.drop_table('master_branches')
    op.drop_table('services')
    op.drop_table('masters')
    op.drop_table('branches')
