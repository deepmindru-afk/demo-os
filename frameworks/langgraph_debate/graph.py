"""
LangGraph debate graph: Pro and Con branches run in parallel, then a Judge merges.

Flow:
    START
      ├── pro_advocate ──┐
      │                  ├── judge ── END
      └── con_advocate ──┘

The Pro and Con nodes run concurrently against the same input. The Judge
sees both arguments and produces a verdict, returned as the assistant's
final message.
"""

from functools import lru_cache
from operator import add
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph


class DebateState(TypedDict):
    messages: Annotated[list[BaseMessage], add]
    arguments: Annotated[list[str], add]


@lru_cache(maxsize=1)
def _llm():
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model="gpt-5.4")


def _topic(state: DebateState) -> str:
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
    return ""


def pro_advocate(state: DebateState) -> dict:
    prompt = f"Argue PRO on this topic. Give your strongest 3 points, each in 1-2 sentences. Topic: {_topic(state)}"
    response = _llm().invoke(prompt)
    return {"arguments": [f"**PRO**\n{response.content}"]}


def con_advocate(state: DebateState) -> dict:
    prompt = f"Argue CON on this topic. Give your strongest 3 points, each in 1-2 sentences. Topic: {_topic(state)}"
    response = _llm().invoke(prompt)
    return {"arguments": [f"**CON**\n{response.content}"]}


def judge(state: DebateState) -> dict:
    args = "\n\n".join(state["arguments"])
    prompt = (
        f"You are an impartial judge. Read both sides and declare a winner with one "
        f"paragraph of reasoning, then summarize the strongest point from each side.\n\n"
        f"Topic: {_topic(state)}\n\n{args}"
    )
    response = _llm().invoke(prompt)
    verdict = f"{args}\n\n---\n\n**VERDICT**\n{response.content}"
    return {"messages": [AIMessage(content=verdict)]}


def build_graph():
    graph = StateGraph(DebateState)
    graph.add_node("pro", pro_advocate)
    graph.add_node("con", con_advocate)
    graph.add_node("judge", judge)

    graph.add_edge(START, "pro")
    graph.add_edge(START, "con")
    graph.add_edge("pro", "judge")
    graph.add_edge("con", "judge")
    graph.add_edge("judge", END)

    return graph.compile()
