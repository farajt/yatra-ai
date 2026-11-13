"""Graph wiring.

    START -> parse_intent --(missing info)--> clarify --(interrupt / resume)--> parse_intent
                  |        --(3 failed rounds)--> give_up -> END
                  |
                  +--(complete)--> flights_agent  --+
                                   hotels_agent   --+
                                   research_agent --+--> budget -> itinerary -> END
                                   weather_agent  --+
                     (parallel fan-out)        (fan-in: budget waits for all four)
"""
from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer

from yatra.graph.agents import flights_agent, hotels_agent, research_agent, weather_agent
from yatra.graph.intent import MAX_CLARIFICATION_ROUNDS, clarify, give_up, parse_intent
from yatra.graph.state import TripState
from yatra.graph.synthesis import budget_node, itinerary_node

AGENTS = ["flights_agent", "hotels_agent", "research_agent", "weather_agent"]


def route_after_intent(state: dict) -> str | list[str]:
    if state.get("status") == "failed":
        return END
    if state["request"].missing_fields():
        if state.get("clarification_rounds", 0) >= MAX_CLARIFICATION_ROUNDS:
            return "give_up"
        return "clarify"
    return AGENTS  # returning a list runs all four nodes in parallel


def build_graph(checkpointer: Checkpointer = None):
    g = StateGraph(TripState)
    g.add_node("parse_intent", parse_intent)
    g.add_node("clarify", clarify)
    g.add_node("give_up", give_up)
    g.add_node("flights_agent", flights_agent)
    g.add_node("hotels_agent", hotels_agent)
    g.add_node("research_agent", research_agent)
    g.add_node("weather_agent", weather_agent)
    g.add_node("budget", budget_node)
    g.add_node("itinerary", itinerary_node)

    g.add_edge(START, "parse_intent")
    g.add_conditional_edges("parse_intent", route_after_intent, ["clarify", "give_up", *AGENTS, END])
    g.add_edge("clarify", "parse_intent")
    g.add_edge("give_up", END)
    g.add_edge(AGENTS, "budget")        # join: waits until every agent has finished
    g.add_edge("budget", "itinerary")
    g.add_edge("itinerary", END)
    return g.compile(checkpointer=checkpointer)


@lru_cache
def get_app():
    """The production graph, checkpointed in PostgreSQL."""
    from yatra.db import get_checkpointer
    return build_graph(get_checkpointer())
