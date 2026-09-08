from langchain_core.messages import AIMessage

from src.agents.base import message_text


def test_plain_string():
    assert message_text(AIMessage(content="hola")) == "hola"


def test_raw_string_passthrough():
    assert message_text("hola") == "hola"


def test_none_returns_empty():
    assert message_text(None) == ""
    assert message_text(AIMessage(content="")) == ""


def test_list_of_text_blocks():
    msg = AIMessage(content=[
        {"type": "text", "text": "parte 1 "},
        {"type": "text", "text": "parte 2"},
    ])
    assert message_text(msg) == "parte 1 parte 2"


def test_list_mixed_blocks_and_strings():
    assert message_text(["a", {"text": "b"}, {"content": "c"}]) == "abc"
