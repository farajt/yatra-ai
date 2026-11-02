"""Weather via Open-Meteo (free, no key).

Forecasts only reach ~16 days ahead. For trips further out, we fetch the *same dates
last year* from the historical archive and label it source="last_year", so the agent
can say "typically ~12°C and rainy" instead of inventing a forecast.
"""
from datetime import date, timedelta

from yatra.errors import ToolError
from yatra.schemas import DailyWeather
from yatra.tools.http import get_json

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TOOL = "weather"
FORECAST_HORIZON_DAYS = 15
ARCHIVE_LAG_DAYS = 6   # archive data lags real time by a few days

# WMO weather interpretation codes -> plain text
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Rain showers", 82: "Violent rain showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def _shift_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29 Feb in a non-leap year
        return d.replace(year=d.year - years, day=28)


def get_weather(
    latitude: float, longitude: float, start: date, end: date, today: date | None = None
) -> list[DailyWeather]:
    if end < start:
        raise ToolError(TOOL, "end date before start date")
    today = today or date.today()

    if start >= today and (end - today).days <= FORECAST_HORIZON_DAYS:
        data = get_json(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                         "precipitation_probability_max,weather_code",
                "timezone": "auto",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
            tool=TOOL,
        )
        return parse_daily(data, source="forecast", years_back=0)

    # Too far ahead (or in the past): use the same dates in the most recent complete year.
    years_back = 1
    while _shift_years(end, years_back) > today - timedelta(days=ARCHIVE_LAG_DAYS):
        years_back += 1
    data = get_json(
        ARCHIVE_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
            "timezone": "auto",
            "start_date": _shift_years(start, years_back).isoformat(),
            "end_date": _shift_years(end, years_back).isoformat(),
        },
        tool=TOOL,
    )
    return parse_daily(data, source="last_year", years_back=years_back)


def parse_daily(data: dict, source: str, years_back: int) -> list[DailyWeather]:
    """Pure function: Open-Meteo JSON -> typed days, re-labelled with the trip's real dates."""
    daily = data.get("daily") or {}
    days = daily.get("time") or []
    if not days:
        raise ToolError(TOOL, data.get("reason", "no daily data returned"))

    def col(name: str) -> list:
        return daily.get(name) or [None] * len(days)

    tmax, tmin = col("temperature_2m_max"), col("temperature_2m_min")
    rain, prob = col("precipitation_sum"), col("precipitation_probability_max")
    codes = col("weather_code")

    out = []
    for i, d in enumerate(days):
        actual = date.fromisoformat(d)
        trip_day = actual.replace(year=actual.year + years_back) if years_back else actual
        code = codes[i]
        out.append(
            DailyWeather(
                day=trip_day,
                temp_max_c=tmax[i],
                temp_min_c=tmin[i],
                precip_mm=rain[i],
                precip_prob_pct=int(prob[i]) if prob[i] is not None else None,
                condition=WMO_CODES.get(int(code), "Unknown") if code is not None else "Unknown",
                source=source,
            )
        )
    return out
