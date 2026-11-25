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
        self._lock = threading.Lock()
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._db.close()

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
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sagas (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                character_id TEXT NOT NULL REFERENCES characters(id),
                title TEXT NOT NULL,
                world_json TEXT NOT NULL,
                summary TEXT NOT NULL,
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
            CREATE TABLE IF NOT EXISTS daily_turns (
                user_id TEXT NOT NULL,
                day TEXT NOT NULL,
                turns INTEGER NOT NULL,
                PRIMARY KEY (user_id, day)
            );
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
    ) -> Character:
        character_id = str(uuid.uuid4())
        with self._lock:
            self._db.execute(
                """
                INSERT INTO characters (id, user_id, name, origin, archetype, concept, attributes_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (character_id, user_id, name, origin, archetype, concept, json.dumps(attributes), now),
            )
            self._db.commit()
        return Character(character_id, user_id, name, origin, archetype, concept, attributes)

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

    def _character(self, row: sqlite3.Row) -> Character:
        return Character(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            origin=row["origin"],
            archetype=row["archetype"],
            concept=row["concept"],
            attributes=json.loads(row["attributes_json"]),
        )

    def create_saga(self, user_id: str, character: Character, world: dict, now: int) -> dict:
        saga_id = str(uuid.uuid4())
        title = f"Saga de {character.name}"
        with self._lock:
            self._db.execute(
                """
                INSERT INTO sagas (id, user_id, character_id, title, world_json, summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, '', ?, ?)
                """,
                (saga_id, user_id, character.id, title, json.dumps(world, ensure_ascii=False), now, now),
            )
            self._db.commit()
        return self.get_saga(user_id, saga_id)

    def list_sagas(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT id, title, updated_at, character_id FROM sagas
                WHERE user_id = ? ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "titulo": row["title"],
                "atualizadaEm": row["updated_at"],
                "personagemId": row["character_id"],
            }
            for row in rows
        ]

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
        return {
            "id": row["id"],
            "titulo": row["title"],
            "personagemId": row["character_id"],
            "mundo": json.loads(row["world_json"]),
            "resumo": row["summary"],
            "criadaEm": row["created_at"],
            "atualizadaEm": row["updated_at"],
            "mensagens": [
                {"papel": item["role"], "texto": item["content"], "em": item["created_at"]} for item in ordered
            ],
        }

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
        return {
            "id": row["id"],
            "titulo": row["title"],
            "personagemId": row["character_id"],
            "mundo": json.loads(row["world_json"]),
            "resumo": row["summary"],
            "mensagens": [{"role": item["role"], "content": item["content"]} for item in messages],
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
