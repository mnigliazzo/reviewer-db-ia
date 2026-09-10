import pytest

from src.main import build_migrations_queue, discover_scripts


def _build_layout(root):
    mig = root / "2026" / "20260407112400"
    mig.mkdir(parents=True)
    (mig / "001.CreateTable.sql").write_text("CREATE TABLE Foo (Id INT);", encoding="utf-8")
    (mig / "002.SeedData.sql").write_text("INSERT INTO Foo VALUES (1);", encoding="utf-8")
    rb = mig / "rollback"
    rb.mkdir()
    (rb / "001.DropTable.sql").write_text("DROP TABLE Foo;", encoding="utf-8")
    return mig


def test_discovers_forward_and_rollback(tmp_path):
    _build_layout(tmp_path)
    scripts = discover_scripts(tmp_path)

    assert len(scripts) == 3
    forward = [s for s in scripts if not s.is_rollback]
    rollback = [s for s in scripts if s.is_rollback]
    assert [s.file.name for s in forward] == ["001.CreateTable.sql", "002.SeedData.sql"]
    assert [s.file.name for s in rollback] == ["001.DropTable.sql"]
    assert all(s.migration == "20260407112400" for s in scripts)


def test_empty_tree(tmp_path):
    (tmp_path / "2026").mkdir()
    assert discover_scripts(tmp_path) == []


def test_build_migrations_queue_reads_content_once(tmp_path):
    _build_layout(tmp_path)
    queue = build_migrations_queue(discover_scripts(tmp_path))

    assert len(queue) == 1
    migration_id, forward, rollback = queue[0]
    assert migration_id == "20260407112400"
    assert [name_content[0].file.name for name_content in forward] == [
        "001.CreateTable.sql",
        "002.SeedData.sql",
    ]
    assert forward[0][1] == "CREATE TABLE Foo (Id INT);"
    assert rollback == [("001.DropTable.sql", "DROP TABLE Foo;")]


def test_build_migrations_queue_raises_on_unreadable(tmp_path):
    mig = _build_layout(tmp_path)
    scripts = discover_scripts(tmp_path)
    (mig / "002.SeedData.sql").unlink()   # se vuelve ilegible después del discovery

    with pytest.raises(OSError):
        build_migrations_queue(scripts)
