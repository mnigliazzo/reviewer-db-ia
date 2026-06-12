from __future__ import annotations

from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .agents import ReviewerAgent
from .models import SqlScript


class ReviewState(TypedDict):
    script: SqlScript
    sql_content: str
    schema_context: str
    messages: list
    skills_used: list[str]


def build_review_graph(reviewer: ReviewerAgent):

    def reviewer_node(state: ReviewState) -> dict:
        messages = state.get("messages") or reviewer.build_messages(
            state["script"],
            sql_content=state["sql_content"],
            schema_context=state.get("schema_context", ""),
        )
        response = reviewer.model_with_tools.invoke(messages)
        return {"messages": messages + [response]}

    def tool_node(state: ReviewState) -> dict:
        last_message = state["messages"][-1]
        tool_messages = []
        new_skills = []

        for tc in last_message.tool_calls:
            result = reviewer.load_skill_tool.invoke(tc["args"])
            skill_name = tc["args"].get("skill_name", "")
            if skill_name and skill_name not in state["skills_used"]:
                new_skills.append(skill_name)
            tool_messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

        return {
            "messages": state["messages"] + tool_messages,
            "skills_used": state["skills_used"] + new_skills,
        }

    def route_after_reviewer(state: ReviewState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    graph = StateGraph(ReviewState)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "reviewer")
    graph.add_conditional_edges("reviewer", route_after_reviewer, {"tools": "tools", END: END})
    graph.add_edge("tools", "reviewer")

    return graph.compile()
