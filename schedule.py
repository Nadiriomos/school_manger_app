# attendance.py
"""
Attendance / Schedule DB tables for El Najah School.

This file contains ONLY database table creation (schema).
No UI. No business logic.

Tables created:
- group_schedules                (date range per group)
- group_schedule_days            (weekday rules + per-day time)
- group_schedule_exclusions      (excluded dates per group)
- sessions                       (generated lesson instances)
- attendance                     (presence records: session_id + student_id)

Presence rule (as requested):
- If (session_id, student_id) row exists => Present
- If missing => Absent
"""

from __future__ import annotations

import sqlite3

from DB import DB_PATH  # uses the same DB file as the rest of the app


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_attendance_tables() -> None:
    """
    Create attendance/schedule tables if they do not exist.
    Call once at app startup (after DB.init_db()).
    """
    conn = _get_conn()
    c = conn.cursor()

    # 1) Schedule range per group (optional schedule)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS group_schedules (
            group_id    INTEGER PRIMARY KEY,
            start_date  TEXT NOT NULL,   -- YYYY-MM-DD
            end_date    TEXT NOT NULL,   -- YYYY-MM-DD
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """
    )

    # 2) Weekday rules (0=Mon .. 6=Sun) with per-day times
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS group_schedule_days (
            group_id    INTEGER NOT NULL,
            weekday     INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
            start_time  TEXT NOT NULL,   -- HH:MM
            end_time    TEXT NOT NULL,   -- HH:MM
            UNIQUE(group_id, weekday),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """
    )

    # 3) Excluded dates (just dates, no reason)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS group_schedule_exclusions (
            group_id    INTEGER NOT NULL,
            date        TEXT NOT NULL,   -- YYYY-MM-DD
            UNIQUE(group_id, date),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """
    )

    # 4) Generated sessions (lesson instances)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id    INTEGER NOT NULL,
            date        TEXT NOT NULL,   -- YYYY-MM-DD
            start_time  TEXT NOT NULL,   -- HH:MM
            end_time    TEXT NOT NULL,   -- HH:MM
            UNIQUE(group_id, date, start_time, end_time),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """
    )

    # Helpful index for queries like "sessions for group between dates"
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_group_date
        ON sessions(group_id, date)
        """
    )

    # 5) Attendance (presence only): row exists => present
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            session_id  INTEGER NOT NULL,
            student_id  INTEGER NOT NULL,
            UNIQUE(session_id, student_id),
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    # Helpful index for analytics later (per student)
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attendance_student
        ON attendance(student_id)
        """
    )

    conn.commit()
    conn.close()