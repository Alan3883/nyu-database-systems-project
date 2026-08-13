"""Part IV test suites.

The tests run against the live PostgreSQL database, not a fake and not
SQLite. A test that passes against a different engine says nothing about
whether the check constraints, the row locks, or the unique indexes that
this design depends on actually hold.
"""
