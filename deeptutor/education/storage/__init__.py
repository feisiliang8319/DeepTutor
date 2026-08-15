"""SQLite storage layer for the Education Data Layer.

``sqlite`` owns connection setup, migration application, and the
append-only trigger self-check (fail-closed on startup — see
P0-DESIGN.md §2.5). ``repositories`` owns the actual read/write paths P0
needs; it is intentionally not a general ORM.
"""

from __future__ import annotations
