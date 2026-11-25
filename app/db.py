"""Estado no SQLite. O processo do app não guarda a crônica."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.missions import mission_by_id
from app.plans import trial_ends
from app.story import Character

PBKDF2_ROUNDS = 60_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$", 1)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), PBKDF2_ROUNDS)
    return hmac.compare_digest(digest.hex(), digest_hex)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class User:
    id: str
    username: str
    plan: str
    trial_started_at: int
    trial_ends_at: int
    created_at: int


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self._migrate()

    def close(self) -> None:
        with self._lock:
            if self._db is None:
                return
            self._db.close()
            self._db = None

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                plan TEXT NOT NULL,
                trial_started_at INTEGER NOT NULL,
                trial_ends_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tokens (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS characters (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                name TEXT NOT NULL,
                origin TEXT NOT NULL,
                archetype TEXT NOT NULL,
                concept TEXT NOT NULL,
                attributes_json TEXT NOT NULL,
                sheet_json TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sagas (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                character_id TEXT NOT NULL REFERENCES characters(id),
                title TEXT NOT NULL,
                world_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'missao',
                script_id TEXT,
                recommended_level INTEGER,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                saga_id TEXT NOT NULL REFERENCES sagas(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_saga ON messages(saga_id, created_at);
            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                saga_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                route TEXT NOT NULL,
                model TEXT NOT NULL,
                estimated_prompt_tokens INTEGER NOT NULL,
                estimated_completion_tokens INTEGER NOT NULL,
                provider_prompt_tokens INTEGER,
                provider_completion_tokens INTEGER,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fights (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                race TEXT NOT NULL,
                class_id TEXT NOT NULL,
                stage INTEGER NOT NULL,
                level INTEGER NOT NULL,
                opponent TEXT NOT NULL,
                result TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rolls (
                saga_id TEXT NOT NULL,
                turn_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (saga_id, turn_key)
            );
            CREATE TABLE IF NOT EXISTS daily_turns (
                user_id TEXT NOT NULL,
                day TEXT NOT NULL,
                turns INTEGER NOT NULL,
                PRIMARY KEY (user_id, day)
            );
            """
        )
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(sagas)")}
        if "kind" not in columns:
            self._db.execute("ALTER TABLE sagas ADD COLUMN kind TEXT NOT NULL DEFAULT 'missao'")
        if "script_id" not in columns:
            self._db.execute("ALTER TABLE sagas ADD COLUMN script_id TEXT")
        if "recommended_level" not in columns:
            self._db.execute("ALTER TABLE sagas ADD COLUMN recommended_level INTEGER")
        if "archived" not in columns:
            self._db.execute("ALTER TABLE sagas ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        character_columns = {row[1] for row in self._db.execute("PRAGMA table_info(characters)")}
        if "sheet_json" not in character_columns:
            self._db.execute("ALTER TABLE characters ADD COLUMN sheet_json TEXT")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS fights (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                race TEXT NOT NULL,
                class_id TEXT NOT NULL,
                stage INTEGER NOT NULL,
                level INTEGER NOT NULL,
                opponent TEXT NOT NULL,
                result TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )

    def _user_from(self, row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            plan=row["plan"],
            trial_started_at=row["trial_started_at"],
            trial_ends_at=row["trial_ends_at"],
            created_at=row["created_at"],
        )

    def create_user(self, username: str, password: str, now: int, trial_days: int) -> tuple[User, str]:
        user_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    """
                    INSERT INTO users (id, username, password_hash, plan, trial_started_at, trial_ends_at, created_at)
                    VALUES (?, ?, ?, 'trial', ?, ?, ?)
                    """,
                    (user_id, username, hash_password(password), now, trial_ends(now, trial_days), now),
                )
                self._db.execute(
                    "INSERT INTO tokens (token_hash, user_id, created_at) VALUES (?, ?, ?)",
                    (hash_token(token), user_id, now),
                )
                self._db.execute("COMMIT")
            except sqlite3.IntegrityError:
                self._db.execute("ROLLBACK")
                raise
            row = self._db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_from(row), token

    def login(self, username: str, password: str, now: int) -> tuple[User, str] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
            if row is None or not verify_password(password, row["password_hash"]):
                return None
            token = secrets.token_urlsafe(32)
            self._db.execute(
                "INSERT INTO tokens (token_hash, user_id, created_at) VALUES (?, ?, ?)",
                (hash_token(token), row["id"], now),
            )
            self._db.commit()
        return self._user_from(row), token

    def user_by_token(self, token: str) -> User | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT users.* FROM tokens
                JOIN users ON users.id = tokens.user_id
                WHERE tokens.token_hash = ?
                """,
                (hash_token(token),),
            ).fetchone()
        return self._user_from(row) if row else None

    def set_plan(self, user_id: str, plan: str) -> None:
        if plan not in {"trial", "free", "paid"}:
            raise ValueError("Plano desconhecido.")
        with self._lock:
            self._db.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))
            self._db.commit()

    def create_character(
        self,
        user_id: str,
        name: str,
        origin: str,
        archetype: str,
        concept: str,
        attributes: dict[str, int],
        now: int,
        sheet: dict | None = None,
    ) -> Character:
        character_id = str(uuid.uuid4())
        with self._lock:
            self._db.execute(
                """
                INSERT INTO characters (id, user_id, name, origin, archetype, concept, attributes_json, sheet_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    character_id,
                    user_id,
                    name,
                    origin,
                    archetype,
                    concept,
                    json.dumps(attributes),
                    json.dumps(sheet or {}, ensure_ascii=False),
                    now,
                ),
            )
            self._db.commit()
        return Character(character_id, user_id, name, origin, archetype, concept, attributes, sheet or {})

    def list_characters(self, user_id: str) -> list[Character]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM characters WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        return [self._character(row) for row in rows]

    def get_character(self, user_id: str, character_id: str) -> Character | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM characters WHERE id = ? AND user_id = ?",
                (character_id, user_id),
            ).fetchone()
        return self._character(row) if row else None

    def update_character(self, character: Character) -> None:
        with self._lock:
            self._db.execute(
                """
                UPDATE characters
                SET name = ?, origin = ?, archetype = ?, concept = ?, attributes_json = ?, sheet_json = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    character.name,
                    character.origin,
                    character.archetype,
                    character.concept,
                    json.dumps(character.attributes),
                    json.dumps(character.sheet or {}, ensure_ascii=False),
                    character.id,
                    character.user_id,
                ),
            )
            self._db.commit()

    def record_fight(self, user_id: str, sheet: dict, opponent: str, result: str, kind: str, now: int) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO fights (id, user_id, race, class_id, stage, level, opponent, result, kind, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    sheet.get("racaId") or "",
                    sheet.get("classeId") or "",
                    int(sheet.get("estagio") or 0),
                    int(sheet.get("nivel") or 1),
                    opponent,
                    result,
                    kind,
                    now,
                ),
            )
            self._db.commit()

    def fight_rates(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT race, class_id, COUNT(*) AS lutas,
                       SUM(CASE WHEN result = 'jogador' THEN 1 ELSE 0 END) AS vitorias
                FROM fights
                GROUP BY race, class_id
                ORDER BY lutas DESC
                """
            ).fetchall()
        return [
            {
                "raca": row["race"],
                "classe": row["class_id"],
                "lutas": row["lutas"],
                "vitorias": row["vitorias"],
                "taxa": round(100 * row["vitorias"] / row["lutas"]) if row["lutas"] else 0,
            }
            for row in rows
        ]

    def save_world(self, user_id: str, saga_id: str, world: dict) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE sagas SET world_json = ? WHERE id = ? AND user_id = ?",
                (json.dumps(world, ensure_ascii=False), saga_id, user_id),
            )
            self._db.commit()

    def save_roll(self, saga_id: str, turn_key: str, payload: dict) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO rolls (saga_id, turn_key, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(saga_id, turn_key) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (saga_id, turn_key, json.dumps(payload, ensure_ascii=False)),
            )
            self._db.commit()

    def get_roll(self, saga_id: str, turn_key: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload_json FROM rolls WHERE saga_id = ? AND turn_key = ?",
                (saga_id, turn_key),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def _character(self, row: sqlite3.Row) -> Character:
        attributes = json.loads(row["attributes_json"])
        raw_sheet = row["sheet_json"] if "sheet_json" in row.keys() else None
        sheet = json.loads(raw_sheet) if raw_sheet else {}
        changed = False
        if sheet.get("escala") != "5e":
            from app.engine.sheet import migrate_legacy

            attributes, sheet = migrate_legacy(attributes, row["archetype"])
            changed = True
        from app.catalog import rename_subclass

        if rename_subclass(sheet):
            changed = True
        if changed:
            self._db.execute(
                "UPDATE characters SET attributes_json = ?, sheet_json = ? WHERE id = ?",
                (json.dumps(attributes), json.dumps(sheet, ensure_ascii=False), row["id"]),
            )
            self._db.commit()
        return Character(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            origin=row["origin"],
            archetype=row["archetype"],
            concept=row["concept"],
            attributes=attributes,
            sheet=sheet,
        )

    def create_saga(
        self,
        user_id: str,
        character: Character,
        world: dict,
        now: int,
        *,
        title: str | None = None,
        kind: str = "missao",
        script_id: str | None = None,
        recommended_level: int | None = None,
    ) -> dict:
        saga_id = str(uuid.uuid4())
        stored_title = title or f"Saga de {character.name}"
        with self._lock:
            self._db.execute(
                """
                INSERT INTO sagas (
                    id, user_id, character_id, title, world_json, summary,
                    kind, script_id, recommended_level, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)
                """,
                (
                    saga_id,
                    user_id,
                    character.id,
                    stored_title,
                    json.dumps(world, ensure_ascii=False),
                    kind,
                    script_id,
                    recommended_level,
                    now,
                    now,
                ),
            )
            self._db.commit()
        return self.get_saga(user_id, saga_id)

    def list_sagas(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT s.id, s.title, s.updated_at, s.character_id, s.kind, s.world_json, s.script_id,
                       c.name AS character_name,
                       (SELECT COUNT(*) FROM messages m WHERE m.saga_id = s.id) AS turns
                FROM sagas s
                JOIN characters c ON c.id = s.character_id
                WHERE s.user_id = ? AND COALESCE(s.archived, 0) = 0
                ORDER BY s.updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        seen: set[str] = set()
        items = []
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            world = json.loads(row["world_json"])
            turns = int(row["turns"] or 0)
            items.append(
                {
                    "id": row["id"],
                    "titulo": row["title"],
                    "atualizadaEm": row["updated_at"],
                    "personagemId": row["character_id"],
                    "personagemNome": row["character_name"],
                    "tipo": row["kind"] or "missao",
                    "objetivoStatus": world.get("objetivoStatus") or "ativa",
                    "vida": world.get("vida"),
                    "vidaMax": world.get("vidaMax"),
                    "turnos": turns,
                    "vazia": turns == 0,
                }
            )
        return items

    def archive_saga(self, user_id: str, saga_id: str) -> bool:
        with self._lock:
            cursor = self._db.execute(
                "UPDATE sagas SET archived = 1 WHERE id = ? AND user_id = ? AND COALESCE(archived, 0) = 0",
                (saga_id, user_id),
            )
            self._db.commit()
            return cursor.rowcount > 0

    def get_saga(self, user_id: str, saga_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM sagas WHERE id = ? AND user_id = ?",
                (saga_id, user_id),
            ).fetchone()
            if row is None:
                return None
            messages = self._db.execute(
                """
                SELECT role, content, created_at FROM messages
                WHERE saga_id = ? ORDER BY created_at DESC LIMIT 200
                """,
                (saga_id,),
            ).fetchall()
        ordered = list(reversed(messages))
        payload = self._saga_fields(row)
        payload["mensagens"] = [
            {"papel": item["role"], "texto": item["content"], "em": item["created_at"]} for item in ordered
        ]
        return payload

    def saga_memory(self, user_id: str, saga_id: str) -> dict | None:
        """Estado usado pelo narrador, incluindo o histórico que cabe na janela."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM sagas WHERE id = ? AND user_id = ?",
                (saga_id, user_id),
            ).fetchone()
            if row is None:
                return None
            messages = self._db.execute(
                "SELECT role, content FROM messages WHERE saga_id = ? ORDER BY created_at",
                (saga_id,),
            ).fetchall()
        payload = self._saga_fields(row)
        payload["mensagens"] = [{"role": item["role"], "content": item["content"]} for item in messages]
        return payload

    def _saga_fields(self, row: sqlite3.Row) -> dict:
        keys = row.keys()
        script_id = row["script_id"] if "script_id" in keys else None
        mission = mission_by_id(script_id)
        world = json.loads(row["world_json"])
        original = world.get("objetivoOriginal") or (mission.objective if mission else None)
        current = world.get("objetivo") or original
        return {
            "id": row["id"],
            "titulo": row["title"],
            "personagemId": row["character_id"],
            "tipo": row["kind"] if "kind" in keys else "missao",
            "roteiroId": script_id,
            "nivelSugerido": row["recommended_level"] if "recommended_level" in keys else None,
            "objetivo": current,
            "objetivoStatus": world.get("objetivoStatus") or "ativa",
            "objetivoOriginal": original,
            "mundo": world,
            "resumo": row["summary"],
            "criadaEm": row["created_at"],
            "atualizadaEm": row["updated_at"],
        }

    def save_turn(
        self,
        *,
        user_id: str,
        saga_id: str,
        player_text: str | None,
        narrative: str,
        world: dict,
        summary: str,
        title: str,
        route: str,
        model: str,
        estimated_prompt_tokens: int,
        estimated_completion_tokens: int,
        provider_prompt_tokens: int | None,
        provider_completion_tokens: int | None,
        now: int,
    ) -> None:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                if player_text:
                    self._db.execute(
                        "INSERT INTO messages (id, saga_id, role, content, created_at) VALUES (?, ?, 'player', ?, ?)",
                        (str(uuid.uuid4()), saga_id, player_text, now),
                    )
                self._db.execute(
                    "INSERT INTO messages (id, saga_id, role, content, created_at) VALUES (?, ?, 'narrator', ?, ?)",
                    (str(uuid.uuid4()), saga_id, narrative, now),
                )
                self._db.execute(
                    """
                    UPDATE sagas
                    SET world_json = ?, summary = ?, title = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (json.dumps(world, ensure_ascii=False), summary, title, now, saga_id, user_id),
                )
                self._db.execute(
                    """
                    INSERT INTO turns (
                        id, saga_id, user_id, route, model,
                        estimated_prompt_tokens, estimated_completion_tokens,
                        provider_prompt_tokens, provider_completion_tokens, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        saga_id,
                        user_id,
                        route,
                        model,
                        estimated_prompt_tokens,
                        estimated_completion_tokens,
                        provider_prompt_tokens,
                        provider_completion_tokens,
                        now,
                    ),
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def daily_turns(self, user_id: str, day: str) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT turns FROM daily_turns WHERE user_id = ? AND day = ?",
                (user_id, day),
            ).fetchone()
        return int(row["turns"]) if row else 0

    def consume_turn(self, user_id: str, day: str, limit: int | None) -> tuple[bool, int]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT turns FROM daily_turns WHERE user_id = ? AND day = ?",
                    (user_id, day),
                ).fetchone()
                used = int(row["turns"]) if row else 0
                if limit is not None and used >= limit:
                    self._db.execute("COMMIT")
                    return False, used
                updated = used + 1
                if row:
                    self._db.execute(
                        "UPDATE daily_turns SET turns = ? WHERE user_id = ? AND day = ?",
                        (updated, user_id, day),
                    )
                else:
                    self._db.execute(
                        "INSERT INTO daily_turns (user_id, day, turns) VALUES (?, ?, ?)",
                        (user_id, day, updated),
                    )
                self._db.execute("COMMIT")
                return True, updated
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def refund_turn(self, user_id: str, day: str) -> None:
        with self._lock:
            self._db.execute(
                """
                UPDATE daily_turns SET turns = turns - 1
                WHERE user_id = ? AND day = ? AND turns > 0
                """,
                (user_id, day),
            )
            self._db.commit()
