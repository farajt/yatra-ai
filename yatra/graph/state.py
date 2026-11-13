"""Graph state. One thread_id = one planning session (a fresh trip gets a fresh thread)."""
import operator
from typing import Annotated, Literal, TypedDict

from yatra.schemas import (BudgetReport, Critique, DailyWeather, DestinationBrief, FlightOption,
                           GeoPoint, HotelOption, TripRequest, UserProfile)

Status = Literal["planned", "failed"]


class TripState(TypedDict, total=False):
    # input
    user_query: str
    user_id: str                   # long-term memory key (one user, many trips)

    # long-term memory
    profile: UserProfile           # loaded at start, updated at the end
    stated: dict                   # preferences the user stated in this session (saved at the end)

    # intent + clarification
    request: TripRequest
    issues: list[str]              # problems found while validating the request (e.g. past date)
    assumptions: list[str]         # interpretations made (e.g. "Japan" -> Tokyo, saved home city)
    clarification_rounds: int

    # specialist agents (run in parallel)
    flights: list[FlightOption]
    hotels: list[HotelOption]
    brief: DestinationBrief | None
    destination_geo: GeoPoint | None
    weather: list[DailyWeather]

    # synthesis + self-correction loop
    budget: BudgetReport
    itinerary: str
    itinerary_failed: bool         # the writer could not run (e.g. provider quota); don't loop on it
    critiques: Annotated[list[Critique], operator.add]   # one per review round
    revision: int                  # number of re-plans done
    strict_budget: bool            # set by the critic when the plan is over budget
    feedback: list[str]            # critic's instructions for the next itinerary draft
    status: Status

    # accumulated across nodes — parallel agents append without overwriting each other
    errors: Annotated[list[str], operator.add]
    llm_calls: Annotated[int, operator.add]
