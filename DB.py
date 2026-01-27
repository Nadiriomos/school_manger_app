from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, date
from typing import Iterable, Optional, Sequence

DB_PATH = "elnajah.db"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DBError(Exception):
    """Base class for all DB-related errors."""


class NotFoundError(DBError):
    """Raised when a requested row does not exist."""


class AlreadyExistsError(DBError):
    """Raised when trying to create something that violates a uniqueness rule."""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _get_conn(row_factory: bool = False) -> sqlite3.Connection:
    """
    Return a new sqlite3 connection with foreign keys enabled.

    If row_factory is True we use sqlite3.Row so columns can be accessed by name.
    """
    conn = sqlite3.connect(DB_PATH)
    if row_factory:
        conn.row_factory = sqlite3.Row
    # Make sure ON DELETE CASCADE etc. actually work
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _today_str() -> str:
    """Return today's date as YYYY-MM-DD."""
    return date.today().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create all tables if they do not exist.

    Call this once when your program starts (before using any other function).
    """
    conn = _get_conn()
    c = conn.cursor()

    # Students table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            join_date TEXT NOT NULL DEFAULT (date('now'))
        )
        """
    )

    # Groups table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        """
    )

    # Junction: which student belongs to which group(s)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS student_group (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            UNIQUE(student_id, group_id),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """
    )

    # Payments: one row per (student, year, month)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            paid TEXT CHECK(paid IN ('paid', 'unpaid')) NOT NULL,
            payment_date TEXT NOT NULL,  -- store as YYYY-MM-DD
            UNIQUE(student_id, year, month),  -- only one payment record per student per month
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Dataclasses used as return types (optional, but nice)
# ---------------------------------------------------------------------------

@dataclass
class Student:
    id: int
    name: str
    join_date: str  # YYYY-MM-DD


@dataclass
class Group:
    id: int
    name: str


@dataclass
class Payment:
    id: int
    student_id: int
    year: int
    month: int
    paid: str            # 'paid' or 'unpaid'
    payment_date: str    # 'YYYY-MM-DD'


# ---------------------------------------------------------------------------
# Student operations
# ---------------------------------------------------------------------------

def create_student(
    name: str,
    join_date: Optional[str] = None,
    student_id: Optional[int] = None,
) -> int:
    """
    Create a new student.

    If student_id is provided we try to insert with that ID (manual IDs).
    Otherwise SQLite will auto-assign one.

    Returns the student's ID.

    Raises:
        AlreadyExistsError if the provided ID is already in use.
    """
    if not name.strip():
        raise DBError("Student name cannot be empty.")

    join_date = join_date or _today_str()

    conn = _get_conn()
    c = conn.cursor()
    try:
        if student_id is not None:
            # Check manually to give a nicer error
            c.execute("SELECT 1 FROM students WHERE id = ?", (student_id,))
            if c.fetchone():
                raise AlreadyExistsError(f"Student ID {student_id} already exists.")

            c.execute(
                "INSERT INTO students (id, name, join_date) VALUES (?, ?, ?)",
                (student_id, name.strip(), join_date),
            )
            sid = student_id
        else:
            c.execute(
                "INSERT INTO students (name, join_date) VALUES (?, ?)",
                (name.strip(), join_date),
            )
            sid = c.lastrowid

        conn.commit()
        return sid
    except sqlite3.IntegrityError as e:
        conn.rollback()
        # Could be duplicate name if you later add such a constraint
        raise DBError(str(e)) from e
    finally:
        conn.close()


def update_student(
    student_id: int,
    name: Optional[str] = None,
    join_date: Optional[str] = None,
) -> None:
    """
    Update student's basic info (name and/or join_date).

    Raises NotFoundError if the student does not exist.
    """
    if name is None and join_date is None:
        return  # nothing to do

    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM students WHERE id = ?", (student_id,))
        if not c.fetchone():
            raise NotFoundError(f"Student {student_id} not found.")

        fields = []
        params = []

        if name is not None:
            fields.append("name = ?")
            params.append(name.strip())

        if join_date is not None:
            fields.append("join_date = ?")
            params.append(join_date)

        params.append(student_id)

        c.execute(
            f"UPDATE students SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def get_student(student_id: int) -> Student:
    """
    Return a Student object for the given ID.

    Raises NotFoundError if not found.
    """
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        c.execute(
            "SELECT id, name, join_date FROM students WHERE id = ?",
            (student_id,),
        )
        row = c.fetchone()
        if row is None:
            raise NotFoundError(f"Student {student_id} not found.")
        return Student(id=row["id"], name=row["name"], join_date=row["join_date"])
    finally:
        conn.close()


def get_all_students(order_by: str = "name") -> list[Student]:
    """
    Return all students.

    order_by can be 'name', 'id', or 'join_date'.
    """
    allowed = {"name", "id", "join_date"}
    if order_by not in allowed:
        raise ValueError(f"order_by must be one of {allowed}")

    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        c.execute(
            f"SELECT id, name, join_date FROM students ORDER BY {order_by} COLLATE NOCASE"
        )
        return [
            Student(id=row["id"], name=row["name"], join_date=row["join_date"])
            for row in c.fetchall()
        ]
    finally:
        conn.close()


def delete_student(student_id: int, snapshot_for_undo: bool = False) -> Optional[dict]:
    """
    Delete a student and their links.

    If snapshot_for_undo is True, this returns a dict with:
        {
            "student": {"id", "name", "join_date"},
            "groups": ["G1", "G2", ...],
            "payments": [
                {"year": ..., "month": ..., "paid": ..., "payment_date": ...},
                ...
            ],
        }

    The caller can store this and pass it to restore_student_snapshot() to undo.

    Raises NotFoundError if the student does not exist.
    """
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        # basic student row
        c.execute(
            "SELECT id, name, join_date FROM students WHERE id = ?",
            (student_id,),
        )
        row = c.fetchone()
        if row is None:
            raise NotFoundError(f"Student {student_id} not found.")

        snapshot: Optional[dict] = None
        if snapshot_for_undo:
            # groups
            c.execute(
                """
                SELECT g.name
                FROM groups g
                JOIN student_group sg ON g.id = sg.group_id
                WHERE sg.student_id = ?
                ORDER BY g.name
                """,
                (student_id,),
            )
            groups = [r[0] for r in c.fetchall()]

            # payments
            c.execute(
                """
                SELECT year, month, paid, payment_date
                FROM payments
                WHERE student_id = ?
                ORDER BY year, month
                """,
                (student_id,),
            )
            payments = [
                {
                    "year": r["year"],
                    "month": r["month"],
                    "paid": r["paid"],
                    "payment_date": r["payment_date"],
                }
                for r in c.fetchall()
            ]

            snapshot = {
                "student": {
                    "id": row["id"],
                    "name": row["name"],
                    "join_date": row["join_date"],
                },
                "groups": groups,
                "payments": payments,
            }

        # delete links & student (payments & student_group have FK cascade, but we
        # delete student_group explicitly as well for older SQLite compatibility)
        c.execute("DELETE FROM student_group WHERE student_id = ?", (student_id,))
        c.execute("DELETE FROM payments WHERE student_id = ?", (student_id,))
        c.execute("DELETE FROM students WHERE id = ?", (student_id,))

        conn.commit()
        return snapshot
    finally:
        conn.close()


def restore_student_snapshot(snapshot: dict) -> None:
    """
    Restore a student previously returned by delete_student(..., snapshot_for_undo=True).

    If the student's ID is already in use, raises AlreadyExistsError.
    """
    student = snapshot.get("student", {})
    sid = student.get("id")
    name = student.get("name")
    join_date = student.get("join_date", _today_str())
    groups = snapshot.get("groups", [])
    payments = snapshot.get("payments", [])

    if sid is None or name is None:
        raise DBError("Invalid snapshot: missing student id or name.")

    conn = _get_conn()
    c = conn.cursor()
    try:
        # check ID availability
        c.execute("SELECT 1 FROM students WHERE id = ?", (sid,))
        if c.fetchone():
            raise AlreadyExistsError(f"Student ID {sid} already exists; cannot restore.")

        # insert student
        c.execute(
            "INSERT INTO students (id, name, join_date) VALUES (?, ?, ?)",
            (sid, name, join_date),
        )

        # ensure groups exist and link
        for gname in groups:
            c.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (gname,))
            c.execute("SELECT id FROM groups WHERE name = ?", (gname,))
            row = c.fetchone()
            if row:
                gid = row[0]
                c.execute(
                    "INSERT OR IGNORE INTO student_group (student_id, group_id) VALUES (?, ?)",
                    (sid, gid),
                )

        # restore payments
        for p in payments:
            c.execute(
                """
                INSERT INTO payments (student_id, year, month, paid, payment_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sid, p["year"], p["month"], p["paid"], p["payment_date"]),
            )

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Group operations
# ---------------------------------------------------------------------------

def create_group(name: str) -> int:
    """
    Create a new group.

    Returns the group ID.

    Raises AlreadyExistsError if a group with that name already exists.
    """
    name = name.strip()
    if not name:
        raise DBError("Group name cannot be empty.")

    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO groups (name) VALUES (?)", (name,))
        gid = c.lastrowid
        conn.commit()
        return gid
    except sqlite3.IntegrityError as e:
        conn.rollback()
        # UNIQUE(name) violated
        raise AlreadyExistsError(f"Group '{name}' already exists.") from e
    finally:
        conn.close()


def delete_group_by_name(name: str) -> bool:
    """
    Delete a group by its name, and all student_group links.

    Returns True if a group was deleted, False if not found.
    """
    name = name.strip()
    if not name:
        raise DBError("Group name cannot be empty.")

    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM groups WHERE name = ?", (name,))
        row = c.fetchone()
        if not row:
            return False

        gid = row[0]
        c.execute("DELETE FROM student_group WHERE group_id = ?", (gid,))
        c.execute("DELETE FROM groups WHERE id = ?", (gid,))
        conn.commit()
        return True
    finally:
        conn.close()


def get_all_groups() -> list[str]:
    """Return a list of all group names sorted alphabetically."""
    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute("SELECT name FROM groups ORDER BY name")
        return [r[0] for r in c.fetchall()]
    finally:
        conn.close()


def set_student_groups(student_id: int, group_names: Sequence[str]) -> None:
    """
    Replace a student's group list with the provided names.

    Any groups that don't exist are created automatically.
    """
    conn = _get_conn()
    c = conn.cursor()
    try:
        # ensure student exists
        c.execute("SELECT 1 FROM students WHERE id = ?", (student_id,))
        if not c.fetchone():
            raise NotFoundError(f"Student {student_id} not found.")

        # clear existing links
        c.execute("DELETE FROM student_group WHERE student_id = ?", (student_id,))

        # add new ones
        for gname in group_names:
            gname = gname.strip()
            if not gname:
                continue
            c.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (gname,))
            c.execute("SELECT id FROM groups WHERE name = ?", (gname,))
            row = c.fetchone()
            if row:
                gid = row[0]
                c.execute(
                    "INSERT OR IGNORE INTO student_group (student_id, group_id) VALUES (?, ?)",
                    (student_id, gid),
                )

        conn.commit()
    finally:
        conn.close()


def get_student_groups(student_id: int) -> list[str]:
    """Return list of group names for a student."""
    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT g.name
            FROM groups g
            JOIN student_group sg ON g.id = sg.group_id
            WHERE sg.student_id = ?
            ORDER BY g.name
            """,
            (student_id,),
        )
        return [r[0] for r in c.fetchall()]
    finally:
        conn.close()


def get_group_students(group_name: str) -> list[Student]:
    """
    Return all students in the given group (by name), ordered by name.
    """
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM groups WHERE name = ?", (group_name,))
        row = c.fetchone()
        if not row:
            return []

        gid = row["id"]
        c.execute(
            """
            SELECT s.id, s.name, s.join_date
            FROM students s
            JOIN student_group sg ON s.id = sg.student_id
            WHERE sg.group_id = ?
            ORDER BY s.name
            """,
            (gid,),
        )
        return [
            Student(id=r["id"], name=r["name"], join_date=r["join_date"])
            for r in c.fetchall()
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Payment operations
# ---------------------------------------------------------------------------

def upsert_payment(
    student_id: int,
    year: int,
    month: int,
    paid: str,
    payment_date: Optional[str] = None,
) -> None:
    """
    Insert or update a single payment record.

    paid must be 'paid' or 'unpaid'.
    payment_date defaults to today if not provided.
    """
    if paid not in ("paid", "unpaid"):
        raise DBError("paid must be 'paid' or 'unpaid'.")

    payment_date = payment_date or _today_str()

    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO payments (student_id, year, month, paid, payment_date)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, year, month)
            DO UPDATE SET paid = excluded.paid,
                          payment_date = excluded.payment_date
            """,
            (student_id, year, month, paid, payment_date),
        )
        conn.commit()
    except sqlite3.OperationalError:
        # Fallback for older SQLite versions (no ON CONFLICT DO UPDATE)
        c.execute(
            """
            REPLACE INTO payments (student_id, year, month, paid, payment_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (student_id, year, month, paid, payment_date),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_payments_bulk(student_id: int, items: Iterable[dict]) -> None:
    """
    Bulk version used by the edit-payments UI.

    items: iterable of dicts with keys:
        year, month, paid ('paid'|'unpaid'), payment_date ('' or 'YYYY-MM-DD')
    """
    conn = _get_conn()
    c = conn.cursor()
    rows = []
    for it in items:
        paid = it["paid"]
        if paid not in ("paid", "unpaid"):
            raise DBError("paid must be 'paid' or 'unpaid'.")
        payment_date = it.get("payment_date") or _today_str()
        rows.append(
            (student_id, it["year"], it["month"], paid, payment_date)
        )

    try:
        c.executemany(
            """
            INSERT INTO payments (student_id, year, month, paid, payment_date)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, year, month)
            DO UPDATE SET paid = excluded.paid,
                          payment_date = excluded.payment_date
            """,
            rows,
        )
    except sqlite3.OperationalError:
        c.executemany(
            """
            REPLACE INTO payments (student_id, year, month, paid, payment_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
    conn.commit()
    conn.close()


def get_payment(student_id: int, year: int, month: int) -> Optional[Payment]:
    """Return a single Payment or None."""
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT id, student_id, year, month, paid, payment_date
            FROM payments
            WHERE student_id = ? AND year = ? AND month = ?
            """,
            (student_id, year, month),
        )
        row = c.fetchone()
        if not row:
            return None
        return Payment(
            id=row["id"],
            student_id=row["student_id"],
            year=row["year"],
            month=row["month"],
            paid=row["paid"],
            payment_date=row["payment_date"],
        )
    finally:
        conn.close()


def get_payments_for_student(student_id: int) -> list[Payment]:
    """Return all payments for a student sorted by year, month."""
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT id, student_id, year, month, paid, payment_date
            FROM payments
            WHERE student_id = ?
            ORDER BY year, month
            """,
            (student_id,),
        )
        return [
            Payment(
                id=row["id"],
                student_id=row["student_id"],
                year=row["year"],
                month=row["month"],
                paid=row["paid"],
                payment_date=row["payment_date"],
            )
            for row in c.fetchall()
        ]
    finally:
        conn.close()


def get_payments_for_student_academic_year(
    student_id: int, academic_start_year: int
) -> list[Payment]:
    """
    Return payments for a student in a given academic year.

    academic_start_year is the year of August.
    So academic year 2024–2025 => academic_start_year = 2024.
    """
    # months Aug..Dec of start year, Jan..Jul of next year
    start_year = academic_start_year
    end_year = academic_start_year + 1

    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT id, student_id, year, month, paid, payment_date
            FROM payments
            WHERE student_id = ?
              AND (
                    (year = ? AND month BETWEEN 8 AND 12)
                 OR (year = ? AND month BETWEEN 1 AND 7)
              )
            ORDER BY year, month
            """,
            (student_id, start_year, end_year),
        )
        return [
            Payment(
                id=row["id"],
                student_id=row["student_id"],
                year=row["year"],
                month=row["month"],
                paid=row["paid"],
                payment_date=row["payment_date"],
            )
            for row in c.fetchall()
        ]
    finally:
        conn.close()


def get_students_with_payment_for_month(
    year: int,
    month: int,
    search_text: str = "",
    search_type: str = "name",
) -> list[dict]:
    """
    Return a list of rows used by the main tree view for a given month.

    Each dict has:
        {
            "id": int,
            "name": str,
            "groups": "G1, G2, ...",
            "join_date": "YYYY-MM-DD",
            "monthly_payment": "Paid (YYYY-MM-DD)" | "Unpaid" | "No record",
        }

    search_type: "id" or "name"
    """
    search_type = search_type.lower()
    if search_type not in ("id", "name"):
        raise ValueError("search_type must be 'id' or 'name'.")

    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        base_sql = """
            SELECT
                s.id,
                s.name,
                s.join_date,
                COALESCE(GROUP_CONCAT(g.name, ', '), '') AS groups,
                CASE
                    WHEN p.payment_date IS NOT NULL
                         AND strftime('%Y-%m', p.payment_date) = strftime('%Y-%m', ?) THEN
                         CASE
                             WHEN p.paid = 'paid' THEN 'Paid (' || p.payment_date || ')'
                             WHEN p.paid = 'unpaid' THEN 'Unpaid'
                             ELSE 'Unpaid'
                         END
                    WHEN p.payment_date IS NULL THEN 'No record'
                    ELSE 'No record'
                END AS monthly_payment
            FROM students s
            LEFT JOIN student_group sg ON s.id = sg.student_id
            LEFT JOIN groups g ON sg.group_id = g.id
            LEFT JOIN payments p
                ON s.id = p.student_id
               AND p.year = ?
               AND p.month = ?
        """

        params: list = [f"{year}-{month:02d}-01", year, month]

        if search_type == "id" and search_text:
            base_sql += " WHERE s.id = ? GROUP BY s.id"
            params.append(int(search_text))
        elif search_text:
            base_sql += " WHERE s.name LIKE ? GROUP BY s.id"
            params.append(f"%{search_text}%")
        else:
            base_sql += " GROUP BY s.id"

        c.execute(base_sql, tuple(params))
        rows = []
        for r in c.fetchall():
            rows.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "join_date": r["join_date"],
                    "groups": r["groups"],
                    "monthly_payment": r["monthly_payment"],
                }
            )
        return rows
    finally:
        conn.close()


def get_unpaid_students_for_month(
    year: int,
    month: int,
    group_name: Optional[str] = None,
) -> list[dict]:
    """
    Return list of unpaid students for the given year / month.

    If group_name is provided, filters to that group.
    """
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        sql = """
            SELECT
                s.id,
                s.name,
                COALESCE(GROUP_CONCAT(g.name, ', '), '') AS groups
            FROM students s
            LEFT JOIN student_group sg ON s.id = sg.student_id
            LEFT JOIN groups g ON sg.group_id = g.id
            LEFT JOIN payments p
                ON s.id = p.student_id
               AND p.year = ?
               AND p.month = ?
            WHERE (p.paid IS NULL OR p.paid = 'unpaid')
        """
        params: list = [year, month]

        if group_name:
            sql += " AND g.name = ?"
            params.append(group_name)

        sql += " GROUP BY s.id ORDER BY s.name"

        c.execute(sql, tuple(params))
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "groups": r["groups"],
            }
            for r in c.fetchall()
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Utility queries for tools / exports
# ---------------------------------------------------------------------------

def get_groupless_students() -> list[dict]:
    """
    Return students who are not in any group.

    Each dict: {"id": int, "name": str}
    """
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT id, name
            FROM students
            WHERE id NOT IN (SELECT student_id FROM student_group)
            ORDER BY name
            """
        )
        return [{"id": r["id"], "name": r["name"]} for r in c.fetchall()]
    finally:
        conn.close()


def delete_students_by_ids(student_ids: Sequence[int]) -> None:
    """
    Delete multiple students by ID.

    This will also cascade-delete their payments and group links.
    """
    if not student_ids:
        return

    conn = _get_conn()
    c = conn.cursor()
    try:
        placeholders = ",".join("?" for _ in student_ids)
        # delete payments & links explicitly for compatibility
        c.execute(
            f"DELETE FROM student_group WHERE student_id IN ({placeholders})",
            tuple(student_ids),
        )
        c.execute(
            f"DELETE FROM payments WHERE student_id IN ({placeholders})",
            tuple(student_ids),
        )
        c.execute(
            f"DELETE FROM students WHERE id IN ({placeholders})",
            tuple(student_ids),
        )
        conn.commit()
    finally:
        conn.close()


def get_student_counts_by_group() -> list[dict]:
    """
    Return total students per group plus a 'TOTAL' row.

    Each dict: {"group": str, "count": int}
    """
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT g.name AS group_name, COUNT(sg.student_id) AS count
            FROM groups g
            LEFT JOIN student_group sg ON g.id = sg.group_id
            GROUP BY g.id
            ORDER BY g.name
            """
        )
        rows = [
            {"group": r["group_name"], "count": r["count"]}
            for r in c.fetchall()
        ]

        # total
        total = sum(r["count"] for r in rows)
        rows.append({"group": "TOTAL", "count": total})
        return rows
    finally:
        conn.close()

def get_group_by_id(group_id: int) -> Group:
    """Fetch a group by ID. Raises NotFoundError if it doesn't exist."""
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        c.execute("SELECT id, name FROM groups WHERE id = ?", (group_id,))
        row = c.fetchone()
        if not row:
            raise NotFoundError(f"Group {group_id} not found.")
        return Group(id=int(row["id"]), name=str(row["name"]))
    finally:
        conn.close()


def update_group_name(group_id: int, new_name: str) -> None:
    """Rename a group (keeps same group_id).

    Raises:
        NotFoundError: if group_id doesn't exist
        AlreadyExistsError: if new_name is taken
    """
    new_name = (new_name or "").strip()
    if not new_name:
        raise DBError("Group name cannot be empty.")

    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE groups SET name = ? WHERE id = ?", (new_name, group_id))
        if c.rowcount == 0:
            raise NotFoundError(f"Group {group_id} not found.")
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise AlreadyExistsError(f"Group '{new_name}' already exists.") from e
    finally:
        conn.close()


def get_group_schedule_payload(group_id: int) -> Optional[dict]:
    """Return schedule payload for schedule.attach_group_schedule_extension().

    Shape:
        {
          "start_date": "YYYY-MM-DD",
          "end_date":   "YYYY-MM-DD",
          "days": { weekday_int: {"enabled": True, "start": "HH:MM", "end": "HH:MM"}, ... },
          "exclusions": ["YYYY-MM-DD", ...]
        }

    Returns None if the group has no schedule.
    """
    conn = _get_conn(row_factory=True)
    c = conn.cursor()
    try:
        try:
            c.execute(
                "SELECT start_date, end_date FROM group_schedules WHERE group_id = ?",
                (group_id,),
            )
        except sqlite3.OperationalError:
            # schedule tables not created yet
            return None

        sched = c.fetchone()
        if not sched:
            return None

        payload = {
            "start_date": sched["start_date"],
            "end_date": sched["end_date"],
            "days": {},
            "exclusions": [],
        }

        c.execute(
            "SELECT weekday, start_time, end_time FROM group_schedule_days WHERE group_id = ?",
            (group_id,),
        )
        for r in c.fetchall():
            w = int(r["weekday"])
            payload["days"][w] = {
                "enabled": True,
                "start": r["start_time"],
                "end": r["end_time"],
            }

        c.execute(
            "SELECT date FROM group_schedule_exclusions WHERE group_id = ? ORDER BY date",
            (group_id,),
        )
        payload["exclusions"] = [row["date"] for row in c.fetchall()]

        return payload
    finally:
        conn.close()
