import os, sqlite3, sys
tdb = os.path.join(os.environ.get("TEMP", "/tmp"), "tt_mig_test.db")
url = "sqlite:///" + tdb.replace("\\", "/")
os.environ["DATABASE_URL"] = url
# run migration
from alembic.config import Config
from alembic import command
cfg = Config(os.path.join(os.path.dirname(__file__), "..", "tournament_platform", "alembic.ini"))
command.upgrade(cfg, "head")
c = sqlite3.connect(tdb)
print("alembic_version:", c.execute("select version_num from alembic_version").fetchall())
print("table_count:", len(c.execute("select name from sqlite_master where type='table'").fetchall()))
c.close()
os.remove(tdb)
print("MIGRATION SMOKE TEST OK")
