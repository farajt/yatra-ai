"""Graph wiring.

    START -> load_profile -> parse_intent --(missing info)--> clarify --(interrupt/resume)--> parse_intent
                                  |        --(3 failed rounds)--> give_up -> END
                                  |
                                  +--> flights_agent  --+
                                       hotels_agent   --+
                                       research_agent --+--> budget -> itinerary -> critic
                                       weather_agent  --+       ^                      |
                                     (parallel fan-out)         |                      |
                                                                +------ replan <-------+ (blocking issues,
                                                                                          max 2 revisions)
                                                    critic --(approved)--> save_profile -> END
"""
from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Checkpointer

from yatra.graph.agents import flights_agent, hotels_agent, research_agent, weather_agent
from yatra.graph.critic import critic_node, replan_node, route_after_critic
from yatra.graph.intent import MAX_CLARIFICATION_ROUNDS, clarify, give_up, parse_intent
from yatra.graph.memory import load_profile, save_profile
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


def build_graph(checkpointer: Checkpointer = None, store: BaseStore | None = None):
    g = StateGraph(TripState)
    g.add_node("load_profile", load_profile)
    g.add_node("parse_intent", parse_intent)
    g.add_node("clarify", clarify)
    g.add_node("give_up", give_up)
    g.add_node("flights_agent", flights_agent)
    g.add_node("hotels_agent", hotels_agent)
    g.add_node("research_agent", research_agent)
    g.add_node("weather_agent", weather_agent)
    g.add_node("budget", budget_node)
    g.add_node("itinerary", itinerary_node)
    g.add_node("critic", critic_node)
    g.add_node("replan", replan_node)
    g.add_node("save_profile", save_profile)

    g.add_edge(START, "load_profile")
    g.add_edge("load_profile", "parse_intent")
    g.add_conditional_edges("parse_intent", route_after_intent, ["clarify", "give_up", *AGENTS, END])
    g.add_edge("clarify", "parse_intent")
    g.add_edge("give_up", END)
    g.add_edge(AGENTS, "budget")        # join: waits until every agent has finished
    g.add_edge("budget", "itinerary")
    g.add_edge("itinerary", "critic")
    g.add_conditional_edges("critic", route_after_critic, ["replan", "save_profile"])
    g.add_edge("replan", "budget")      # the self-correction loop
    g.add_edge("save_profile", END)
    return g.compile(checkpointer=checkpointer, store=store)


@lru_cache
def get_app():
    """The production graph: sessions checkpointed and user profiles stored in PostgreSQL."""
    from yatra.db import get_checkpointer, get_store
    return build_graph(get_checkpointer(), get_store())
