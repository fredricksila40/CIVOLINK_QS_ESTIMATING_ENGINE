"""Master SQLite rate library (Phase 20): enterprise resource rates.

Shared rates across projects: Direct Materials, Labour Trades,
Equipment & Plant, and Haulage Rates. Rates persist as exact strings
(validated non-negative Decimals on write; floats rejected) with a
source tag and update timestamp. All bulk imports run inside one
transaction — a single bad row aborts the whole import instead of
half-loading the library.
"""

import csv
import io
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from qs_engine.core.decimal_policy import to_decimal
from qs_engine.core.errors import ValidationError

CATEGORIES = ("materials", "labour", "plant", "haulage")

CATEGORY_LABELS = {
    "materials": "Direct Materials",
    "labour": "Labour Trades",
    "plant": "Equipment & Plant",
    "haulage": "Haulage Rates",
}

CSV_COLUMNS = ("category", "code", "description", "unit", "rate",
               "source")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rates (
    category TEXT NOT NULL,
    code TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    rate TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    updated_on TEXT NOT NULL,
    PRIMARY KEY (category, code)
)
"""


def default_library_path() -> Path:
    """Engine-root data/rate_library.db (created on first connect)."""
    return (Path(__file__).resolve().parent.parent.parent
            / "data" / "rate_library.db")


class RateLibrary:
    """SQLite-backed master rate store.

    One connection per operation (never a shared connection): FastAPI
    runs sync endpoints on a threadpool, so a single stored connection
    would be used concurrently from multiple threads. `:memory:`
    databases are the documented exception — each fresh connection
    would see an empty database, so one anchor connection is kept
    (in-memory libraries are for single-threaded tests only).
    """

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = str(default_library_path())
        self.db_path = str(db_path)
        self._anchor = None
        if self.db_path == ":memory:":
            self._anchor = sqlite3.connect(self.db_path)
            self._anchor.row_factory = sqlite3.Row
        else:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # Validate the path and create the schema at construction time.
        with self._connection():
            pass

    @contextmanager
    def _connection(self):
        """Fresh connection for one operation; commit/rollback + close.

        The anchor (in-memory) connection is reused but never closed
        here; file connections are opened, committed (or rolled back),
        and closed within this block.
        """
        if self._anchor is not None:
            conn = self._anchor
        else:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
        try:
            with conn:  # commit on success, rollback on failure
                conn.execute(_SCHEMA)
                yield conn
        finally:
            if conn is not self._anchor:
                conn.close()

    def close(self) -> None:
        """Release the anchor connection (file connections self-close)."""
        if self._anchor is None:
            return
        try:
            self._anchor.close()
        except Exception:
            pass
        self._anchor = None

    # -- validation ---------------------------------------------------------

    @staticmethod
    def _check_category(category: str) -> str:
        code = str(category or "").strip().lower()
        if code not in CATEGORIES:
            raise ValidationError(
                f"Unknown rate category {category!r}; expected one of "
                f"{list(CATEGORIES)}")
        return code

    @staticmethod
    def _check_rate(rate, code: str) -> str:
        try:
            amount = to_decimal(rate, f"rate for {code!r}")
        except TypeError as exc:
            raise ValidationError(str(exc)) from exc
        if amount < 0:
            raise ValidationError(
                f"Rate for {code!r} must be >= 0; got {rate!r}")
        return str(amount)

    # -- CRUD ------------------------------------------------------------------

    def upsert_rate(self, category: str, code: str, description: str = "",
                    unit: str = "", rate: str = "0",
                    source: str = "") -> dict:
        """Insert or replace one rate; returns the stored row as a dict."""
        category = self._check_category(category)
        code = str(code or "").strip()
        if not code:
            raise ValidationError("Rate code is required")
        amount = self._check_rate(rate, code)
        row = {"category": category, "code": code,
               "description": str(description or "").strip(),
               "unit": str(unit or "").strip(), "rate": amount,
               "source": str(source or "").strip(),
               "updated_on": date.today().isoformat()}
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO rates (category, code, description, unit,"
                " rate, source, updated_on) VALUES "
                "(:category, :code, :description, :unit, :rate,"
                " :source, :updated_on) "
                "ON CONFLICT (category, code) DO UPDATE SET "
                "description=excluded.description, unit=excluded.unit,"
                " rate=excluded.rate, source=excluded.source,"
                " updated_on=excluded.updated_on", row)
        return dict(row)

    def get_rate(self, category: str, code: str) -> dict:
        """Fetch one rate (ValidationError when absent)."""
        category = self._check_category(category)
        with self._connection() as conn:
            cursor = conn.execute(
                "SELECT category, code, description, unit, rate, source,"
                " updated_on FROM rates WHERE category = ? AND code = ?",
                (category, str(code or "").strip()))
            found = cursor.fetchone()
        if found is None:
            raise ValidationError(
                f"No {category!r} rate stored for {code!r}")
        return dict(found)

    def list_rates(self, category: str = "", search: str = "") -> list:
        """List rates, optionally filtered by category and/or free text."""
        query = ("SELECT category, code, description, unit, rate,"
                 " source, updated_on FROM rates")
        clauses, params = [], []
        if str(category or "").strip():
            clauses.append("category = ?")
            params.append(self._check_category(category))
        needle = str(search or "").strip().lower()
        if needle:
            clauses.append("(lower(code) LIKE ? OR lower(description)"
                           " LIKE ?)")
            params.extend([f"%{needle}%", f"%{needle}%"])
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY category, code"
        with self._connection() as conn:
            rows = [dict(row) for row in conn.execute(query, params)]
        return rows

    def delete_rate(self, category: str, code: str) -> None:
        """Remove one rate (ValidationError when absent)."""
        self.get_rate(category, code)  # validates presence first
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM rates WHERE category = ? AND code = ?",
                (self._check_category(category),
                 str(code or "").strip()))

    def count(self) -> int:
        """Total stored rates across all categories."""
        with self._connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM rates")
            total = int(cursor.fetchone()[0])
        return total

    # -- bulk CSV sync ------------------------------------------------------------

    @staticmethod
    def export_template_csv(path) -> str:
        """Write a header-only CSV template for rate capture."""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(str(output), "w", newline="",
                  encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS))
            writer.writeheader()
        return str(output)

    def export_to_csv(self, path, category: str = "") -> str:
        """Dump stored rates to CSV (all categories unless filtered)."""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(str(output), "w", newline="",
                  encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS))
            writer.writeheader()
            for row in self.list_rates(category=category):
                writer.writerow({key: row.get(key, "")
                                 for key in CSV_COLUMNS})
        return str(output)

    def import_from_csv(self, path) -> dict:
        """Bulk upsert from CSV inside one transaction (all-or-nothing).

        Returns {"inserted": n, "updated": n}. Any invalid row aborts
        the entire import with a ValidationError naming the row.
        """
        if hasattr(path, "read"):
            text = path.read()
            if isinstance(text, bytes):
                text = text.decode("utf-8-sig")
        else:
            file_path = Path(path)
            if not file_path.is_file():
                raise ValidationError(f"CSV file not found: {file_path}")
            text = file_path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValidationError("CSV file has no header row")
        missing = [key for key in CSV_COLUMNS
                   if key not in (reader.fieldnames or [])]
        if missing:
            raise ValidationError(
                f"CSV is missing columns: {', '.join(missing)}")
        staged = []
        for lineno, raw in enumerate(reader, start=2):
            if raw is None or all(
                    not str(value or "").strip()
                    for value in raw.values()):
                continue  # skip blank lines, never fail on them
            try:
                category = self._check_category(raw.get("category"))
                code = str(raw.get("code", "") or "").strip()
                if not code:
                    raise ValidationError("Rate code is required")
                amount = self._check_rate(raw.get("rate"), code)
            except ValidationError as exc:
                raise ValidationError(
                    f"CSV row {lineno}: {exc}") from exc
            staged.append({
                "category": category, "code": code,
                "description": str(raw.get("description", "") or ""
                                   ).strip(),
                "unit": str(raw.get("unit", "") or "").strip(),
                "rate": amount,
                "source": str(raw.get("source", "") or "").strip(),
                "updated_on": date.today().isoformat(),
            })
        if not staged:
            raise ValidationError("CSV file holds no rate rows")
        existing = {(row["category"], row["code"])
                    for row in self.list_rates()}
        try:
            with self._connection() as conn:
                for row in staged:
                    conn.execute(
                        "INSERT INTO rates (category, code, description,"
                        " unit, rate, source, updated_on) VALUES "
                        "(:category, :code, :description, :unit, :rate,"
                        " :source, :updated_on) "
                        "ON CONFLICT (category, code) DO UPDATE SET "
                        "description=excluded.description,"
                        " unit=excluded.unit, rate=excluded.rate,"
                        " source=excluded.source,"
                        " updated_on=excluded.updated_on", row)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(
                f"Rate import failed and was rolled back: {exc}") from exc
        inserted = sum(1 for row in staged
                       if (row["category"], row["code"]) not in existing)
        return {"inserted": inserted, "updated": len(staged) - inserted}
