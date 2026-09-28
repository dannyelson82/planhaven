"""Contacts, quotes and costs (ARCHITECTURE.md §7.1; phase 0.2 milestone 5).

- Contacts (contractors, suppliers) are shared one by one, like assets: their own members
  and roles; an owner is always kept.
- Quotes and cost entries belong to a project: members read, editors write.
- A quote may name a contact (only one you can see; checked by a trigger) and a document
  (an attachment of the same project). Project members who can't see the contact see the
  quote without the contact's details.
- A cost entry may point at the quote it paid (same project).
- Money is stored in cents; Canadian dollars (CAD) by default.
- The trash purge (migration 0015) now also removes these after 30 days.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-28
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE contacts (
            id          uuid PRIMARY KEY DEFAULT uuidv7(),
            name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
            company     text NOT NULL DEFAULT '' CHECK (length(company) <= 200),
            kind        text NOT NULL DEFAULT 'contractor'
                        CHECK (kind IN ('contractor', 'supplier', 'other')),
            phone       text NOT NULL DEFAULT '' CHECK (length(phone) <= 50),
            email       text NOT NULL DEFAULT '' CHECK (length(email) <= 254),
            website     text NOT NULL DEFAULT '' CHECK (length(website) <= 500),
            notes       text NOT NULL DEFAULT '' CHECK (length(notes) <= 20000),
            created_by  uuid NOT NULL REFERENCES users (id),
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            version     integer NOT NULL DEFAULT 1,
            deleted_at  timestamptz
        );

        CREATE TABLE contact_members (
            contact_id uuid NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            role       text NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (contact_id, user_id)
        );
        CREATE INDEX contact_members_user_idx ON contact_members (user_id);

        CREATE TABLE quotes (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            project_id    uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            contact_id    uuid REFERENCES contacts (id) ON DELETE SET NULL,
            title         text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
            amount_cents  bigint CHECK (amount_cents BETWEEN 0 AND 100000000000),
            status        text NOT NULL DEFAULT 'requested'
                          CHECK (status IN ('requested', 'received', 'accepted', 'declined')),
            attachment_id uuid REFERENCES attachments (id) ON DELETE SET NULL,
            notes         text NOT NULL DEFAULT '' CHECK (length(notes) <= 20000),
            created_by    uuid NOT NULL REFERENCES users (id),
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            version       integer NOT NULL DEFAULT 1,
            deleted_at    timestamptz
        );
        CREATE INDEX quotes_project_idx ON quotes (project_id) WHERE deleted_at IS NULL;
        CREATE INDEX quotes_contact_idx ON quotes (contact_id) WHERE deleted_at IS NULL;

        CREATE TABLE cost_entries (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            project_id   uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            description  text NOT NULL CHECK (length(description) BETWEEN 1 AND 300),
            amount_cents bigint NOT NULL
                         CHECK (amount_cents BETWEEN -100000000000 AND 100000000000),
            spent_on     date NOT NULL DEFAULT current_date,
            quote_id     uuid REFERENCES quotes (id) ON DELETE SET NULL,
            created_by   uuid NOT NULL REFERENCES users (id),
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            version      integer NOT NULL DEFAULT 1,
            deleted_at   timestamptz
        );
        CREATE INDEX cost_entries_project_idx ON cost_entries (project_id, spent_on DESC)
            WHERE deleted_at IS NULL;

        -- ---------------------------------------------------------- contact roles
        CREATE POLICY contact_members_definer_read ON contact_members FOR SELECT
            TO planhaven_owner USING (true);
        CREATE FUNCTION app.contact_role(p_contact uuid) RETURNS text
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
                SELECT role FROM contact_members
                WHERE contact_id = p_contact AND user_id = app.current_user_id()
            $$;
        CREATE FUNCTION app.contact_has_members(p_contact uuid) RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$ SELECT EXISTS (SELECT 1 FROM contact_members WHERE contact_id = p_contact) $$;
        REVOKE ALL ON FUNCTION app.contact_role(uuid), app.contact_has_members(uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.contact_role(uuid), app.contact_has_members(uuid)
            TO planhaven_app;

        -- ---------------------------------------------------------- contacts
        ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE contacts FORCE ROW LEVEL SECURITY;
        CREATE POLICY contacts_insert ON contacts FOR INSERT TO planhaven_app
            WITH CHECK (created_by = app.current_user_id());
        CREATE POLICY contacts_select ON contacts FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.contact_role(id) IS NOT NULL
                   OR (created_by = app.current_user_id() AND NOT app.contact_has_members(id)));
        CREATE POLICY contacts_update ON contacts FOR UPDATE TO planhaven_app
            USING (app.contact_role(id) IN ('owner', 'editor'))
            WITH CHECK (app.contact_role(id) IN ('owner', 'editor'));
        REVOKE ALL ON contacts FROM PUBLIC;
        GRANT SELECT, INSERT ON contacts TO planhaven_app;
        GRANT UPDATE (name, company, kind, phone, email, website, notes, updated_at, version,
                      deleted_at) ON contacts TO planhaven_app;

        CREATE FUNCTION app.contacts_guard_owner_fields() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog
            AS $$
            BEGIN
                IF NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
                   AND app.contact_role(OLD.id) IS DISTINCT FROM 'owner' THEN
                    RAISE EXCEPTION 'only the contact owner can change this'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER contacts_guard_owner_fields BEFORE UPDATE ON contacts
            FOR EACH ROW EXECUTE FUNCTION app.contacts_guard_owner_fields();

        ALTER TABLE contact_members ENABLE ROW LEVEL SECURITY;
        ALTER TABLE contact_members FORCE ROW LEVEL SECURITY;
        CREATE POLICY contact_members_select ON contact_members FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.contact_role(contact_id) IS NOT NULL);
        CREATE POLICY contact_members_insert ON contact_members FOR INSERT TO planhaven_app
            WITH CHECK (
                (NOT app.contact_has_members(contact_id) AND user_id = app.current_user_id()
                 AND role = 'owner'
                 AND EXISTS (SELECT 1 FROM contacts c WHERE c.id = contact_id
                             AND c.created_by = app.current_user_id()))
                OR app.contact_role(contact_id) = 'owner'
            );
        CREATE POLICY contact_members_update ON contact_members FOR UPDATE TO planhaven_app
            USING (app.contact_role(contact_id) = 'owner')
            WITH CHECK (app.contact_role(contact_id) = 'owner');
        CREATE POLICY contact_members_delete ON contact_members FOR DELETE TO planhaven_app
            USING (app.contact_role(contact_id) = 'owner' OR user_id = app.current_user_id());
        REVOKE ALL ON contact_members FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON contact_members TO planhaven_app;
        GRANT UPDATE (role) ON contact_members TO planhaven_app;

        CREATE FUNCTION app.contact_members_keep_an_owner() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT app.is_system()
                   AND NOT EXISTS (SELECT 1 FROM contact_members m
                                   WHERE m.contact_id = OLD.contact_id AND m.role = 'owner') THEN
                    RAISE EXCEPTION 'a contact must keep at least one owner'
                        USING ERRCODE = 'check_violation';
                END IF;
                RETURN NULL;
            END
            $$;
        CREATE CONSTRAINT TRIGGER contact_members_keep_an_owner
            AFTER UPDATE OR DELETE ON contact_members DEFERRABLE INITIALLY IMMEDIATE
            FOR EACH ROW EXECUTE FUNCTION app.contact_members_keep_an_owner();

        -- ---------------------------------------------------------- quotes and costs
        ALTER TABLE quotes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE quotes FORCE ROW LEVEL SECURITY;
        CREATE POLICY quotes_select ON quotes FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY quotes_insert ON quotes FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND created_by = app.current_user_id());
        CREATE POLICY quotes_update ON quotes FOR UPDATE TO planhaven_app
            USING (app.can_write(project_id)) WITH CHECK (app.can_write(project_id));
        REVOKE ALL ON quotes FROM PUBLIC;
        GRANT SELECT, INSERT ON quotes TO planhaven_app;
        GRANT UPDATE (contact_id, title, amount_cents, status, attachment_id, notes, updated_at,
                      version, deleted_at) ON quotes TO planhaven_app;

        ALTER TABLE cost_entries ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cost_entries FORCE ROW LEVEL SECURITY;
        CREATE POLICY cost_entries_select ON cost_entries FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.can_read(project_id));
        CREATE POLICY cost_entries_insert ON cost_entries FOR INSERT TO planhaven_app
            WITH CHECK (app.can_write(project_id) AND created_by = app.current_user_id());
        CREATE POLICY cost_entries_update ON cost_entries FOR UPDATE TO planhaven_app
            USING (app.can_write(project_id)) WITH CHECK (app.can_write(project_id));
        REVOKE ALL ON cost_entries FROM PUBLIC;
        GRANT SELECT, INSERT ON cost_entries TO planhaven_app;
        GRANT UPDATE (description, amount_cents, spent_on, quote_id, updated_at, version,
                      deleted_at) ON cost_entries TO planhaven_app;

        -- A quote names a contact you can see, and a document from the same project; a cost
        -- entry points at a quote from the same project. The system context is exempt
        -- (cascades from purges set these to NULL).
        CREATE FUNCTION app.quotes_check_links() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF app.is_system() THEN
                    RETURN NEW;
                END IF;
                IF NEW.contact_id IS NOT NULL
                   AND (TG_OP = 'INSERT' OR NEW.contact_id IS DISTINCT FROM OLD.contact_id)
                   AND app.contact_role(NEW.contact_id) IS NULL THEN
                    RAISE EXCEPTION 'contact not found' USING ERRCODE = 'insufficient_privilege';
                END IF;
                IF NEW.attachment_id IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.id = NEW.attachment_id
                                   AND a.project_id = NEW.project_id) THEN
                    RAISE EXCEPTION 'attachment not in this project'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER quotes_check_links BEFORE INSERT OR UPDATE ON quotes
            FOR EACH ROW EXECUTE FUNCTION app.quotes_check_links();

        CREATE FUNCTION app.cost_entries_check_quote() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public
            AS $$
            BEGIN
                IF NOT app.is_system() AND NEW.quote_id IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM quotes q WHERE q.id = NEW.quote_id
                                   AND q.project_id = NEW.project_id) THEN
                    RAISE EXCEPTION 'quote not in this project'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER cost_entries_check_quote BEFORE INSERT OR UPDATE ON cost_entries
            FOR EACH ROW EXECUTE FUNCTION app.cost_entries_check_quote();

        -- ---------------------------------------------------------- trash purge
        CREATE POLICY quotes_purge_read ON quotes FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY quotes_purge ON quotes FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY cost_entries_purge_read ON cost_entries FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY cost_entries_purge ON cost_entries FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY contacts_purge_read ON contacts FOR SELECT TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');
        CREATE POLICY contacts_purge ON contacts FOR DELETE TO planhaven_owner
            USING (deleted_at < now() - interval '30 days');

        CREATE OR REPLACE FUNCTION app.purge_trash() RETURNS integer
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            DECLARE
                removed integer := 0;
                n integer;
            BEGIN
                IF NOT app.is_system() THEN
                    RAISE EXCEPTION 'purge_trash is a system job'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                DELETE FROM list_items WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM tasks WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM lists WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM notes WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM cost_entries WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM quotes WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM attachments WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM projects WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM assets WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                DELETE FROM contacts WHERE deleted_at < now() - interval '30 days';
                GET DIAGNOSTICS n = ROW_COUNT; removed := removed + n;
                RETURN removed;
            END
            $$;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
