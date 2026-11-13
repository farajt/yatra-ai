"""Known airports for common Indian and international destinations.

The intent model guesses IATA codes; for well-known places this table is authoritative
(eval 13 Nov: "Pune" came back with a wrong code and the flight search found nothing).
Keys are lowercase place names as people write them.
"""

AIRPORTS: dict[str, str] = {
    # India: metros and big cities
    "mumbai": "BOM", "bombay": "BOM", "delhi": "DEL", "new delhi": "DEL", "bengaluru": "BLR",
    "bangalore": "BLR", "chennai": "MAA", "madras": "MAA", "kolkata": "CCU", "calcutta": "CCU",
    "hyderabad": "HYD", "pune": "PNQ", "ahmedabad": "AMD", "jaipur": "JAI", "lucknow": "LKO",
    "kochi": "COK", "cochin": "COK", "thiruvananthapuram": "TRV", "trivandrum": "TRV",
    "goa": "GOI", "north goa": "GOX", "south goa": "GOI", "panaji": "GOI", "calangute": "GOX",
    "nagpur": "NAG", "indore": "IDR", "bhopal": "BHO", "chandigarh": "IXC", "amritsar": "ATQ",
    "guwahati": "GAU", "bhubaneswar": "BBI", "patna": "PAT", "ranchi": "IXR", "raipur": "RPR",
    "coimbatore": "CJB", "madurai": "IXM", "mangaluru": "IXE", "mangalore": "IXE", "mysuru": "MYQ",
    "visakhapatnam": "VTZ", "vizag": "VTZ", "vadodara": "BDQ", "surat": "STV", "rajkot": "HSR",
    # India: tourist places
    "udaipur": "UDR", "jodhpur": "JDH", "jaisalmer": "JSA", "varanasi": "VNS", "agra": "AGR",
    "srinagar": "SXR", "kashmir": "SXR", "leh": "IXL", "ladakh": "IXL", "rishikesh": "DED",
    "dehradun": "DED", "haridwar": "DED", "uttarakhand": "DED", "manali": "KUU", "kullu": "KUU",
    "himachal": "KUU", "himachal pradesh": "KUU", "shimla": "SLV", "dharamshala": "DHM",
    "gangtok": "PYG", "sikkim": "PYG", "darjeeling": "IXB", "shillong": "SHL", "meghalaya": "SHL",
    "port blair": "IXZ", "andaman": "IXZ", "andaman and nicobar islands": "IXZ", "kerala": "COK",
    "munnar": "COK", "alleppey": "COK", "alappuzha": "COK", "hampi": "VDY", "pondicherry": "PNY",
    "puducherry": "PNY", "tirupati": "TIR", "aurangabad": "IXU", "khajuraho": "HJR",
    # International
    "dubai": "DXB", "abu dhabi": "AUH", "singapore": "SIN", "bangkok": "BKK", "phuket": "HKT",
    "krabi": "KBV", "pattaya": "BKK", "kuala lumpur": "KUL", "langkawi": "LGK", "bali": "DPS",
    "denpasar": "DPS", "jakarta": "CGK", "hanoi": "HAN", "ho chi minh city": "SGN",
    "kathmandu": "KTM", "colombo": "CMB", "sri lanka": "CMB", "maldives": "MLE",
    "malé": "MLE", "mauritius": "MRU", "tokyo": "HND", "japan": "HND", "osaka": "KIX",
    "kyoto": "KIX", "seoul": "ICN", "hong kong": "HKG", "london": "LHR", "paris": "CDG",
    "rome": "FCO", "amsterdam": "AMS", "zurich": "ZRH", "switzerland": "ZRH", "interlaken": "ZRH",
    "swiss alps": "ZRH", "istanbul": "IST", "barcelona": "BCN", "madrid": "MAD", "prague": "PRG",
    "vienna": "VIE", "santorini": "JTR", "athens": "ATH", "new york": "JFK", "san francisco": "SFO",
    "sydney": "SYD", "melbourne": "MEL", "doha": "DOH", "muscat": "MCT", "baku": "GYD",
    "almaty": "ALA", "tbilisi": "TBS", "cairo": "CAI", "nairobi": "NBO",
}


def airport_for(place: str | None) -> str | None:
    if not place:
        return None
    return AIRPORTS.get(place.strip().lower())


# ── Finding known places in free text (safety net when the model misses one) ──
import re as _re  # noqa: E402
import string as _string  # noqa: E402


def _known_names() -> list[str]:
    from yatra.destinations import REGION_BASES
    return sorted(set(AIRPORTS) | set(REGION_BASES), key=len, reverse=True)


def find_places(text: str) -> list[tuple[int, str, bool]]:
    """Known places in the text as (position, Name, came_right_after_from), longest names first
    so "north goa" wins over "goa". Hinglish "X se" (from X) also counts as an origin."""
    found, taken = [], []
    for name in _known_names():
        for m in _re.finditer(rf"\b{_re.escape(name)}\b", text, _re.IGNORECASE):
            if any(a <= m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            before = text[max(0, m.start() - 6):m.start()].lower()
            after = text[m.end():m.end() + 4].lower()
            is_origin = before.rstrip().endswith("from") or after.startswith(" se")
            found.append((m.start(), _string.capwords(m.group(0)), is_origin))
    return sorted(found)


def guess_origin_destination(text: str) -> tuple[str | None, str | None]:
    places = find_places(text)
    origin = next((name for _, name, is_from in places if is_from), None)
    destination = next((name for _, name, is_from in places
                        if not is_from and name.lower() != (origin or "").lower()), None)
    return origin, destination
