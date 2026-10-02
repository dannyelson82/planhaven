"""Chores: assigned and repeating tasks with proof of completion (ADR 0013, A§21).

- tasks gain who assigned them, what proof is asked for (none, a photo or a note) and a
  repeat rule (daily, weekly on chosen days, every N weeks, monthly) at the task's due time.
  Assignees already see their tasks without being project members (tasks_select, 0010).
- chore_submissions: each "done" by the assignee, with its note and/or photo, waiting for the
  assigner's approval, approved, or sent back with a comment. Readable by the project's
  members and the assignee who sent it (the assigner is an editor of the project). Written by
  the service in system context after the authorization check (the assignee may not be a
  project member, so project write policies don't apply to them).
- Proof photos are blobs (cleaned like any upload); the blob purge keeps them while a
  submission refers to them.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-02
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        ALTER TABLE tasks
            ADD COLUMN assigned_by uuid REFERENCES users (id) ON DELETE SET NULL,
            ADD COLUMN proof text NOT NULL DEFAULT 'none'
                CHECK (proof IN ('none', 'photo', 'note')),
            ADD COLUMN repeat_freq text CHECK (repeat_freq IN ('daily', 'weekly', 'monthly')),
            ADD COLUMN repeat_interval smallint NOT NULL DEFAULT 1
                CHECK (repeat_interval BETWEEN 1 AND 52),
            ADD COLUMN repeat_days smallint[]
                CHECK (repeat_days IS NULL
                       OR (repeat_days <@ ARRAY[0, 1, 2, 3, 4, 5, 6]::smallint[]
                           AND cardinality(repeat_days) BETWEEN 1 AND 7)),
            ADD CONSTRAINT tasks_repeat_needs_due CHECK (repeat_freq IS NULL OR due_at IS NOT NULL);
        GRANT UPDATE (assigned_by, proof, repeat_freq, repeat_interval, repeat_days)
            ON tasks TO planhaven_app;
        -- An assignee's "done" is written in system context (after authz.require_chore).
        CREATE POLICY tasks_system_update ON tasks FOR UPDATE TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());

        CREATE TABLE chore_submissions (
            id                  uuid PRIMARY KEY DEFAULT uuidv7(),
            task_id             uuid NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
            project_id          uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            occurrence_due      timestamptz,
            submitted_by        uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            submitted_at        timestamptz NOT NULL DEFAULT now(),
            note                text NOT NULL DEFAULT '' CHECK (length(note) <= 2000),
            photo_sha256        text CHECK (photo_sha256 ~ '^[0-9a-f]{64}$'),
            photo_thumb_sha256  text CHECK (photo_thumb_sha256 ~ '^[0-9a-f]{64}$'),
            photo_type          text CHECK (length(photo_type) <= 60),
            status              text NOT NULL
                                CHECK (status IN ('awaiting_photo', 'pending', 'approved',
                                                  'sent_back')),
            reviewed_by         uuid REFERENCES users (id) ON DELETE SET NULL,
            reviewed_at         timestamptz,
            comment             text NOT NULL DEFAULT '' CHECK (length(comment) <= 1000)
        );
        CREATE INDEX chore_submissions_task_idx ON chore_submissions (task_id, submitted_at DESC);
        CREATE INDEX chore_submissions_pending_idx ON chore_submissions (project_id)
            WHERE status = 'pending';

        ALTER TABLE chore_submissions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE chore_submissions FORCE ROW LEVEL SECURITY;
        CREATE POLICY chore_submissions_select ON chore_submissions FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id)
                   OR submitted_by = app.current_user_id());
        CREATE POLICY chore_submissions_system ON chore_submissions FOR ALL TO planhaven_app
            USING (app.is_system()) WITH CHECK (app.is_system());
        REVOKE ALL ON chore_submissions FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON chore_submissions TO planhaven_app;
        GRANT UPDATE (note, photo_sha256, photo_thumb_sha256, photo_type, status, reviewed_by,
                      reviewed_at, comment) ON chore_submissions TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
