from src.skill_middleware import (
    build_skills_header,
    load_skills_from_disk,
    make_load_skill_tool,
)


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

    skills = load_skills_from_disk(tmp_path)

    assert [s["name"] for s in skills] == ["sql-code-review", "sql-optimization"]
    assert skills[0]["description"] == "Guia de revision"
    assert "Contenido de la skill." in skills[0]["content"]


def test_missing_directory_returns_empty(tmp_path):
    assert load_skills_from_disk(tmp_path / "no-existe") == []


def test_frontmatter_tolerates_comments_and_blanks(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\n# comentario\n\nname: s\ndescription: 'con comillas'\n---\nbody\n",
        encoding="utf-8",
    )
    skills = load_skills_from_disk(tmp_path)
    assert skills[0]["name"] == "s"
    assert skills[0]["description"] == "con comillas"


def test_non_directory_entries_ignored(tmp_path):
    (tmp_path / "README.md").write_text("no soy una skill", encoding="utf-8")
    _make_skill(tmp_path, "real", "ok")
    skills = load_skills_from_disk(tmp_path)
    assert [s["name"] for s in skills] == ["real"]


def test_load_skill_tool_hit_and_miss(tmp_path):
    _make_skill(tmp_path, "sql-code-review", "d", body="GUIA COMPLETA")
    skills = load_skills_from_disk(tmp_path)
    tool = make_load_skill_tool(skills)

    hit = tool.invoke({"skill_name": "sql-code-review"})
    assert "GUIA COMPLETA" in hit

    miss = tool.invoke({"skill_name": "inexistente"})
    assert "no encontrada" in miss
    assert "sql-code-review" in miss


def test_skills_header_lists_names(tmp_path):
    _make_skill(tmp_path, "a", "desc a")
    header = build_skills_header(load_skills_from_disk(tmp_path))
    assert "- a: desc a" in header
    assert "load_skill()" in header
