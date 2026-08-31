from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parent / "aioff.db"


def column_names(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


with sqlite3.connect(DB_PATH) as conn:
    cols = column_names(conn, "off_results")

    if not cols:
        conn.execute(
            """
            CREATE TABLE off_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER,
                session_id TEXT NOT NULL,
                skill TEXT NOT NULL,
                answer TEXT NOT NULL,
                score INTEGER,
                level TEXT,
                feedback TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        added = ["off_results table"]
    else:
        migrations = {
            "question_id": "ALTER TABLE off_results ADD COLUMN question_id INTEGER",
            "score": "ALTER TABLE off_results ADD COLUMN score INTEGER",
            "level": "ALTER TABLE off_results ADD COLUMN level TEXT",
            "feedback": "ALTER TABLE off_results ADD COLUMN feedback TEXT",
        }
        added = []
        for name, sql in migrations.items():
            if name not in cols:
                conn.execute(sql)
                added.append(name)

    conn.commit()

print("DB MIGRATION OK", ", ".join(added) if added else "no changes")
