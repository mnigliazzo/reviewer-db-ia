import pytest
from langchain_core.messages import AIMessage

from src.skills import load_skills, make_load_skill_tool, skill_calls, skills_header


def _make_skill(root, name, description, body="Contenido de la skill."):
    d = root / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return d


def test_loads_skills_with_frontmatter(tmp_path):
    _make_skill(tmp_path, "sql-code-review", "Guia de revision")
    _make_skill(tmp_path, "sql-optimization", "Guia de performance")

    skills = load_skills(tmp_path)

    assert [s.name for s in skills] == ["sql-code-review", "sql-optimization"]
    assert skills[0].description == "Guia de revision"
    assert "Contenido de la skill." in skills[0].content


def test_missing_directory_returns_empty(tmp_path):
    assert load_skills(tmp_path / "no-existe") == []


def test_frontmatter_yaml_quotes_and_comments(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\n# comentario\nname: s\ndescription: 'con comillas'\n---\nbody\n",
        encoding="utf-8",
    )
    skills = load_skills(tmp_path)
    assert skills[0].name == "s"
    assert skills[0].description == "con comillas"


def test_non_skill_entries_ignored(tmp_path):
    (tmp_path / "README.md").write_text("no soy una skill", encoding="utf-8")
    (tmp_path / "vacia").mkdir()
    _make_skill(tmp_path, "real", "ok")
    assert [s.name for s in load_skills(tmp_path)] == ["real"]


def test_load_skill_tool_hit_and_miss(tmp_path):
    _make_skill(tmp_path, "sql-code-review", "d", body="GUIA COMPLETA")
    tool = make_load_skill_tool(load_skills(tmp_path))

    assert "GUIA COMPLETA" in tool.invoke({"skill_name": "sql-code-review"})

    with pytest.raises(ValueError, match="no existe"):
        tool.invoke({"skill_name": "inexistente"})


def test_skills_header_lists_names(tmp_path):
    _make_skill(tmp_path, "a", "desc a")
    header = skills_header(load_skills(tmp_path))
    assert "- a: desc a" in header
    assert "load_skill()" in header


def _skill_call(name, call_id="c1"):
    return {"name": "load_skill", "args": {"skill_name": name}, "id": call_id, "type": "tool_call"}


def test_skill_calls_unique_in_order():
    messages = [
        AIMessage(content="", tool_calls=[_skill_call("sql-code-review"), _skill_call("sql-optimization", "c2")]),
        AIMessage(content="", tool_calls=[
            _skill_call("sql-code-review", "c3"),                       # repetida
            {"name": "otra_tool", "args": {}, "id": "c4", "type": "tool_call"},
        ]),
        AIMessage(content="listo"),                                     # sin tool_calls
    ]
    assert skill_calls(messages) == ["sql-code-review", "sql-optimization"]
