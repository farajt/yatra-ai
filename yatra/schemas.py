"""Typed domain models shared by tools, agents, API and UI.

Rule of the project: numbers (prices, dates, durations) live in these models and are
produced by tools or Python code — never invented by the LLM.
"""
from datetime import date
from enum import Enum
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from yatra.formatting import format_inr


# ── Trip request (what the user wants) ────────────────────────────────────────
class TripStyle(str, Enum):
    BUDGET = "budget"
    MID = "mid"
    LUXURY = "luxury"


class TripRequest(BaseModel):
    """Structured version of the user's free-text query (filled by the intent parser)."""

    origin_city: str | None = Field(None, description="City the traveller departs from, e.g. 'Pune'")
    origin_airport: str | None = Field(None, description="3-letter IATA code, e.g. 'PNQ'")
    destination_city: str | None = Field(None, description="Main destination city, e.g. 'Tokyo'")
    destination_airport: str | None = Field(None, description="3-letter IATA code, e.g. 'NRT'")
    destination_country: str | None = Field(None, description="ISO-2 country code, e.g. 'JP'")
    stay_area: str | None = Field(None, description="Base town for a region destination, e.g. 'Seminyak'")
    start_date: date | None = Field(None, description="Departure date (YYYY-MM-DD)")
    end_date: date | None = Field(None, description="Return date (YYYY-MM-DD)")
    adults: int = Field(1, ge=1, le=9)
    children: int = Field(0, ge=0, le=8)
    budget_inr: int | None = Field(None, gt=0, description="Total budget in INR for all travellers")
    style: TripStyle = TripStyle.MID
    interests: list[str] = Field(default_factory=list, description="e.g. ['food', 'temples', 'hiking']")
    dietary: list[str] = Field(default_factory=list, description="e.g. ['vegetarian', 'jain']")
    passport_country: str = Field("IN", description="ISO country code of the passport")

    REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = (
        "origin_city", "destination_city", "start_date", "end_date",
    )

    @model_validator(mode="after")
    def _check_dates(self) -> "TripRequest":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self

    @property
    def nights(self) -> int | None:
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days
        return None

    @property
    def is_domestic(self) -> bool:
        return (self.destination_country or "").upper() == self.passport_country.upper()

    @property
    def stay_location(self) -> str:
        """Where to search hotels / weather: the base area inside a region, else the city."""
        if self.stay_area and self.destination_city and \
                self.stay_area.lower() not in self.destination_city.lower():
            return f"{self.stay_area}, {self.destination_city}"
        return self.stay_area or self.destination_city or ""

    @property
    def travellers(self) -> int:
        return self.adults + self.children

    def missing_fields(self) -> list[str]:
        """Fields that must be asked from the user before planning (drives the HITL interrupt)."""
        return [f for f in self.REQUIRED_FIELDS if getattr(self, f) in (None, "")]


# ── Tool outputs ──────────────────────────────────────────────────────────────
class FlightSegment(BaseModel):
    airline: str
    flight_number: str = ""
    from_airport: str           # IATA
    to_airport: str             # IATA
    depart_at: str              # "2026-12-10 06:05" (local time, as returned by Google Flights)
    arrive_at: str
    duration_min: int = 0


class FlightOption(BaseModel):
    segments: list[FlightSegment]
    total_duration_min: int
    price_inr: int
    price_covers: Literal["one_way", "round_trip"]
    carbon_kg: int | None = None
    is_best: bool = False       # Google's "best flights" bucket
    departure_token: str | None = None  # used later to fetch return legs / booking options
    source: str = "google_flights"

    @property
    def stops(self) -> int:
        return max(len(self.segments) - 1, 0)

    @property
    def airlines(self) -> list[str]:
        return sorted({s.airline for s in self.segments})

    def summary(self) -> str:
        first, last = self.segments[0], self.segments[-1]
        h, m = divmod(self.total_duration_min, 60)
        stops = "non-stop" if self.stops == 0 else f"{self.stops} stop(s)"
        return (
            f"{', '.join(self.airlines)} | {first.from_airport} {first.depart_at} -> "
            f"{last.to_airport} {last.arrive_at} | {h}h{m:02d}m, {stops} | "
            f"{format_inr(self.price_inr)} ({self.price_covers.replace('_', ' ')})"
        )


class HotelOption(BaseModel):
    name: str
    hotel_class: float | None = None        # stars
    rating: float | None = None             # 0-5 guest rating
    reviews: int | None = None
    price_per_night_inr: int | None = None
    total_price_inr: int | None = None      # whole stay, as quoted
    latitude: float | None = None
    longitude: float | None = None
    amenities: list[str] = Field(default_factory=list)
    link: str | None = None
    property_token: str | None = None
    source: str = "google_hotels"

    def summary(self) -> str:
        stars = f"{self.hotel_class:g}*" if self.hotel_class else "unrated"
        rating = f"{self.rating}/5 ({self.reviews or 0} reviews)" if self.rating else "no rating"
        price = f"{format_inr(self.price_per_night_inr)}/night" if self.price_per_night_inr else "price n/a"
        return f"{self.name} | {stars} | {rating} | {price}"


class GeoPoint(BaseModel):
    name: str
    display_name: str
    latitude: float
    longitude: float
    country_code: str | None = None   # ISO-2, upper case
    extent_km: float | None = None    # diagonal of the place's bounding box (city ~10-40, island/state 100+)

    @property
    def is_region(self) -> bool:
        """True for places too big for their centre point to mean 'near' (islands, states)."""
        return self.extent_km is not None and self.extent_km > 60


class DailyWeather(BaseModel):
    day: date
    temp_max_c: float | None = None
    temp_min_c: float | None = None
    precip_mm: float | None = None
    precip_prob_pct: int | None = None
    condition: str = "Unknown"
    # "forecast" = real forecast; "last_year" = same dates last year (trip too far ahead to forecast)
    source: Literal["forecast", "last_year"]


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str
    score: float | None = None


class FxRate(BaseModel):
    base: str
    quote: str
    rate: float           # 1 base = rate quote
    as_of: str = ""
    source: str = ""


# ── Agent outputs ─────────────────────────────────────────────────────────────
class DestinationBrief(BaseModel):
    """Research agent output, distilled by the LLM from web search results."""

    summary: str = Field(description="2-3 sentence overview of the destination for this trip")
    # list fields accept null from the LLM (see _none_to_list) but are always lists afterwards
    top_attractions: list[str] | None = Field(
        default_factory=list, description="Up to 10 attractions/experiences matching the traveller's interests"
    )
    visa_info: str | None = Field(
        "", description="Visa requirement for the traveller's passport, as stated in the sources"
    )
    local_tips: list[str] | None = Field(
        default_factory=list, description="Practical tips: transport passes, etiquette, food for dietary needs"
    )
    daily_spend_per_person: float | None = Field(
        None, description="Typical daily spend per person (food, local transport, entry fees), excluding hotel"
    )
    daily_spend_currency: str | None = Field(None, description="ISO currency code of daily_spend_per_person")
    daily_spend_basis: str | None = Field("", description="Where the daily spend figure comes from")
    sources: list[str] | None = Field(default_factory=list)   # filled by code from search results

    @field_validator("top_attractions", "local_tips", "sources", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        return [] if v is None else v

    @field_validator("visa_info", "daily_spend_basis", mode="before")
    @classmethod
    def _none_to_str(cls, v):
        return "" if v is None else v


class BudgetLine(BaseModel):
    label: str
    amount_inr: int
    note: str = ""


class BudgetReport(BaseModel):
    """Produced by deterministic Python (yatra/budget.py) — no LLM arithmetic."""

    lines: list[BudgetLine]
    total_inr: int
    budget_inr: int | None = None
    within_budget: bool | None = None       # None when the user gave no budget
    difference_inr: int | None = None       # budget - total; negative means over budget
    selected_flight: FlightOption | None = None
    selected_hotel: HotelOption | None = None
    assumptions: list[str] = Field(default_factory=list)
    strict: bool = False                    # True when re-planned to cut cost


# ── Critic ────────────────────────────────────────────────────────────────────
IssueCategory = Literal["budget", "hotel", "flight", "itinerary", "preferences", "weather", "data"]


class CritiqueIssue(BaseModel):
    category: IssueCategory
    blocking: bool          # True = the plan must be fixed before it is shown as final
    message: str
    source: Literal["rules", "llm"] = "rules"


class Critique(BaseModel):
    round: int                              # 1 = first review, 2 = after first re-plan, ...
    approved: bool
    score: int | None = None                # LLM quality score 1-10
    issues: list[CritiqueIssue] = Field(default_factory=list)

    @property
    def blocking(self) -> list[CritiqueIssue]:
        return [i for i in self.issues if i.blocking]


# ── Long-term memory ──────────────────────────────────────────────────────────
class UserProfile(BaseModel):
    """Preferences remembered across trips (stored in the LangGraph Store, keyed by user id)."""

    home_city: str | None = None
    home_airport: str | None = None
    style: TripStyle | None = None
    dietary: list[str] = Field(default_factory=list)
    trips_planned: int = 0
    # Interests are deliberately NOT remembered: "temples" for Japan says little about a Goa trip.

    def is_empty(self) -> bool:
        return not (self.home_city or self.style or self.dietary)
