from src.graph import build_schema_context


def test_empty_returns_empty_string():
    assert build_schema_context([], 10) == ""


def test_includes_all_when_under_cap():
    ctx = build_schema_context([("a.sql", "SELECT 1"), ("b.sql", "SELECT 2")], 10)
    assert "--- a.sql ---" in ctx
    assert "--- b.sql ---" in ctx
    assert "SELECT 1" in ctx


def test_caps_to_most_recent():
    scripts = [(f"{i}.sql", f"SELECT {i}") for i in range(5)]
    ctx = build_schema_context(scripts, 2)
    assert "3.sql" in ctx and "4.sql" in ctx
    assert "0.sql" not in ctx and "2.sql" not in ctx


def test_zero_means_unlimited():
    scripts = [(f"{i}.sql", f"SELECT {i}") for i in range(5)]
    ctx = build_schema_context(scripts, 0)
    assert all(f"{i}.sql" in ctx for i in range(5))
