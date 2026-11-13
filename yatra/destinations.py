"""Base areas for well-known region destinations (island / state / coast).

A region is too big to search hotels or weather for as one point ("hotels in Bali" spans
a 140 km island). The intent model is asked for a base area, but this table guarantees one
for common destinations even when the model forgets. Keys are lowercase destination names.
"""

REGION_BASES: dict[str, str] = {
    # India
    "goa": "Calangute",
    "north goa": "Calangute",
    "south goa": "Colva",
    "kerala": "Kochi",
    "ladakh": "Leh",
    "kashmir": "Srinagar",
    "himachal": "Manali",
    "himachal pradesh": "Manali",
    "sikkim": "Gangtok",
    "meghalaya": "Shillong",
    "rajasthan": "Jaipur",
    "andaman": "Port Blair",
    "andaman and nicobar islands": "Port Blair",
    "coorg": "Madikeri",
    "kodagu": "Madikeri",
    "spiti": "Kaza",
    "uttarakhand": "Rishikesh",
    # Abroad
    "bali": "Seminyak",
    "lombok": "Senggigi",
    "phuket": "Patong",
    "krabi": "Ao Nang",
    "langkawi": "Pantai Cenang",
    "maldives": "Malé",
    "mauritius": "Grand Baie",
    "sri lanka": "Colombo",
    "santorini": "Fira",
    "mykonos": "Mykonos Town",
    "crete": "Chania",
    "sicily": "Palermo",
    "tuscany": "Florence",
    "swiss alps": "Interlaken",
    "switzerland": "Interlaken",
    "hokkaido": "Sapporo",
    "jeju": "Jeju City",
    "bora bora": "Vaitape",
}


def base_area_for(destination: str | None) -> str | None:
    if not destination:
        return None
    return REGION_BASES.get(destination.strip().lower())
