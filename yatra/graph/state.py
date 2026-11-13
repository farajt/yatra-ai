"""Graph state. One thread_id = one planning session (a fresh trip gets a fresh thread)."""
import operator
from typing import Annotated, Literal, TypedDict

from yatra.schemas import (BudgetReport, DailyWeather, DestinationBrief, FlightOption, GeoPoint,
                           HotelOption, TripRequest)

Status = Literal["planned", "failed"]


class TripState(TypedDict, total=False):
    # input
    user_query: str

    # intent + clarification
    request: TripRequest
    issues: list[str]              # problems found while validating the request (e.g. past date)
    assumptions: list[str]         # interpretations the parser made (e.g. "Japan" -> Tokyo)
    clarification_rounds: int

    # specialist agents (run in parallel)
    flights: list[FlightOption]
    hotels: list[HotelOption]
    brief: DestinationBrief | None
    destination_geo: GeoPoint | None
    weather: list[DailyWeather]

    # synthesis
    budget: BudgetReport
    itinerary: str
    status: Status

    # accumulated across nodes — parallel agents append without overwriting each other
    errors: Annotated[list[str], operator.add]
    llm_calls: Annotated[int, operator.add]
