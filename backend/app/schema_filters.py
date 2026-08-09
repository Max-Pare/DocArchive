"""Shared Alembic autogenerate/compare filters.

Lives here rather than in alembic/env.py because env.py runs migrations as a side
effect of being imported, so it cannot be imported by tests. Both the migration
environment and the schema-parity test use these, which keeps them from drifting.
"""

# Indexes that exist in the database but cannot be expressed in Base.metadata, so
# autogenerate and `alembic check` would otherwise always propose dropping them.
#
# ix_documents_fts is a functional GIN index over
#   to_tsvector('italian', coalesce(ocr_text,'') || ' ' || original_filename)
# created with raw SQL in revision 0001.
IGNORED_INDEXES = frozenset({"ix_documents_fts"})


def include_object(object_, name, type_, reflected, compare_to):
    return not (type_ == "index" and name in IGNORED_INDEXES)
