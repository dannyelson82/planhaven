"""Messages between people, and online status (ADR 0018).

- conversations: one-to-one (`direct_key`, the two user ids in order, so there's one per
  pair) or a named group. conversation_members: who's in it, when they last read it, and
  whether they left. messages: text, deleted by their sender (the text is removed, not
  hidden).
- Only current members see a conversation, its members and its messages; admins have no
  access (A§7.2). Membership is checked by a security-definer function so the policies don't
  recurse.
- people_settings: "hide my online status", own row; read in system context to build the
  people list.
- Message notifications carry the message id, so a deleted message's preview is removed from
  them too.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-02
"""

from app.db.schema_migrations.sqlscript import execute_script

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    execute_script("""
        CREATE TABLE conversations (
            id               uuid PRIMARY KEY DEFAULT uuidv7(),
            title            text CHECK (length(title) BETWEEN 1 AND 100),
            direct_key       text UNIQUE CHECK (length(direct_key) = 73),
            created_by       uuid NOT NULL REFERENCES users (id),
            created_at       timestamptz NOT NULL DEFAULT now(),
            last_message_at  timestamptz,
            CHECK ((direct_key IS NULL) <> (title IS NULL))
        );

        CREATE TABLE conversation_members (
            conversation_id uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
            user_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            joined_at       timestamptz NOT NULL DEFAULT now(),
            last_read_at    timestamptz NOT NULL DEFAULT now(),
            left_at         timestamptz,
            PRIMARY KEY (conversation_id, user_id)
        );
        CREATE INDEX conversation_members_user_idx ON conversation_members (user_id)
            WHERE left_at IS NULL;

        CREATE TABLE messages (
            id               uuid PRIMARY KEY DEFAULT uuidv7(),
            conversation_id  uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
            sender_id        uuid NOT NULL REFERENCES users (id),
            body             text NOT NULL CHECK (length(body) <= 4000),
            created_at       timestamptz NOT NULL DEFAULT now(),
            deleted_at       timestamptz,
            CHECK (deleted_at IS NOT NULL OR length(body) >= 1),
            CHECK (deleted_at IS NULL OR body = '')
        );
        CREATE INDEX messages_conversation_idx ON messages (conversation_id, created_at DESC);

        CREATE TABLE people_settings (
            user_id        uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
            hide_presence  boolean NOT NULL DEFAULT false,
            updated_at     timestamptz NOT NULL DEFAULT now()
        );

        -- ---------------------------------------------------------- membership check
        CREATE POLICY conversation_members_definer_read ON conversation_members FOR SELECT
            TO planhaven_owner USING (true);
        CREATE FUNCTION app.in_conversation(p_conversation uuid) RETURNS boolean
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
                SELECT EXISTS (SELECT 1 FROM conversation_members
                               WHERE conversation_id = p_conversation
                                 AND user_id = app.current_user_id() AND left_at IS NULL)
            $$;
        REVOKE ALL ON FUNCTION app.in_conversation(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.in_conversation(uuid) TO planhaven_app;

        -- Starting a conversation: the conversation and all its first members in one step,
        -- always including the person starting it. One-to-one: exactly one other active
        -- person, and the existing conversation if there is one (joined again if left).
        CREATE POLICY users_definer_read ON users FOR SELECT TO planhaven_owner USING (true);
        CREATE POLICY conversations_definer ON conversations FOR ALL TO planhaven_owner
            USING (true) WITH CHECK (true);
        CREATE POLICY conversation_members_definer ON conversation_members FOR ALL
            TO planhaven_owner USING (true) WITH CHECK (true);
        CREATE FUNCTION app.start_conversation(p_title text, p_others uuid[]) RETURNS uuid
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
            AS $$
            DECLARE
                me uuid := app.current_user_id();
                people uuid[];
                key text;
                conv uuid;
            BEGIN
                IF me IS NULL THEN
                    RAISE EXCEPTION 'no user' USING ERRCODE = 'insufficient_privilege';
                END IF;
                SELECT array_agg(DISTINCT u.id) INTO people FROM users u
                WHERE u.id = ANY(p_others) AND u.id <> me AND u.disabled_at IS NULL;
                IF people IS NULL OR cardinality(people) <> cardinality(
                       ARRAY(SELECT DISTINCT x FROM unnest(p_others) x WHERE x <> me))
                   OR cardinality(people) > 49 THEN
                    RAISE EXCEPTION 'unknown person' USING ERRCODE = 'foreign_key_violation';
                END IF;
                IF p_title IS NULL THEN
                    IF cardinality(people) <> 1 THEN
                        RAISE EXCEPTION 'one-to-one needs one other person'
                            USING ERRCODE = 'check_violation';
                    END IF;
                    key := least(me::text, people[1]::text) || ':'
                           || greatest(me::text, people[1]::text);
                    INSERT INTO conversations (title, direct_key, created_by)
                    VALUES (NULL, key, me) ON CONFLICT (direct_key) DO NOTHING
                    RETURNING id INTO conv;
                    IF conv IS NULL THEN
                        SELECT id INTO conv FROM conversations WHERE direct_key = key;
                    END IF;
                ELSE
                    INSERT INTO conversations (title, created_by) VALUES (p_title, me)
                    RETURNING id INTO conv;
                END IF;
                INSERT INTO conversation_members (conversation_id, user_id)
                SELECT conv, x FROM unnest(people || me) x
                ON CONFLICT (conversation_id, user_id) DO UPDATE SET left_at = NULL
                    WHERE conversation_members.user_id = me;
                RETURN conv;
            END
            $$;
        REVOKE ALL ON FUNCTION app.start_conversation(text, uuid[]) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app.start_conversation(text, uuid[]) TO planhaven_app;

        -- ---------------------------------------------------------- conversations
        ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
        CREATE POLICY conversations_select ON conversations FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.in_conversation(id));
        CREATE POLICY conversations_update ON conversations FOR UPDATE TO planhaven_app
            USING (app.in_conversation(id)) WITH CHECK (app.in_conversation(id));
        REVOKE ALL ON conversations FROM PUBLIC;
        GRANT SELECT ON conversations TO planhaven_app;
        GRANT UPDATE (title, last_message_at) ON conversations TO planhaven_app;

        -- ---------------------------------------------------------- members
        ALTER TABLE conversation_members ENABLE ROW LEVEL SECURITY;
        ALTER TABLE conversation_members FORCE ROW LEVEL SECURITY;
        CREATE POLICY conversation_members_select ON conversation_members FOR SELECT
            TO planhaven_app
            USING (app.is_system() OR app.in_conversation(conversation_id));
        -- Current members add people to a group (never to a one-to-one conversation).
        CREATE POLICY conversation_members_insert ON conversation_members FOR INSERT
            TO planhaven_app
            WITH CHECK (app.in_conversation(conversation_id)
                        AND EXISTS (SELECT 1 FROM conversations c
                                    WHERE c.id = conversation_id AND c.direct_key IS NULL));
        -- Your own row: when you last read it, leaving; a group's members can bring back
        -- someone who left.
        CREATE POLICY conversation_members_update ON conversation_members FOR UPDATE
            TO planhaven_app
            USING (user_id = app.current_user_id() OR app.in_conversation(conversation_id))
            WITH CHECK (user_id = app.current_user_id() OR app.in_conversation(conversation_id));
        REVOKE ALL ON conversation_members FROM PUBLIC;
        GRANT SELECT, INSERT ON conversation_members TO planhaven_app;
        GRANT UPDATE (last_read_at, left_at) ON conversation_members TO planhaven_app;

        -- Someone else can only clear left_at (re-add); last_read_at and leaving are yours.
        CREATE FUNCTION app.conversation_members_guard() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog
            AS $$
            BEGIN
                IF NEW.user_id <> app.current_user_id()
                   AND (NEW.last_read_at IS DISTINCT FROM OLD.last_read_at
                        OR NEW.left_at IS NOT NULL) THEN
                    RAISE EXCEPTION 'only you can change this'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END
            $$;
        CREATE TRIGGER conversation_members_guard BEFORE UPDATE ON conversation_members
            FOR EACH ROW EXECUTE FUNCTION app.conversation_members_guard();

        -- ---------------------------------------------------------- messages
        ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
        ALTER TABLE messages FORCE ROW LEVEL SECURITY;
        CREATE POLICY messages_select ON messages FOR SELECT TO planhaven_app
            USING (app.is_system() OR app.in_conversation(conversation_id));
        CREATE POLICY messages_insert ON messages FOR INSERT TO planhaven_app
            WITH CHECK (sender_id = app.current_user_id()
                        AND app.in_conversation(conversation_id));
        CREATE POLICY messages_update ON messages FOR UPDATE TO planhaven_app
            USING (sender_id = app.current_user_id())
            WITH CHECK (sender_id = app.current_user_id());
        REVOKE ALL ON messages FROM PUBLIC;
        GRANT SELECT, INSERT ON messages TO planhaven_app;
        GRANT UPDATE (body, deleted_at) ON messages TO planhaven_app;

        -- ---------------------------------------------------------- online status
        ALTER TABLE people_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE people_settings FORCE ROW LEVEL SECURITY;
        CREATE POLICY people_settings_own ON people_settings FOR ALL TO planhaven_app
            USING (app.is_system() OR user_id = app.current_user_id())
            WITH CHECK (user_id = app.current_user_id());
        REVOKE ALL ON people_settings FROM PUBLIC;
        GRANT SELECT, INSERT ON people_settings TO planhaven_app;
        GRANT UPDATE (hide_presence, updated_at) ON people_settings TO planhaven_app;

        -- A deleted message's preview leaves notifications too (system context).
        CREATE INDEX notifications_message_idx ON notifications ((data->>'message_id'))
            WHERE kind = 'message';
        GRANT UPDATE (data) ON notifications TO planhaven_app;
    """)


def downgrade() -> None:
    raise NotImplementedError("Downgrades are not supported; restore from backup.")
