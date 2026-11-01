"""Facts Counted checks for itself: where the death happened, whether a disaster was declared there,
and what the National Weather Service was warning about that day.

Every lookup has a backup source, and every result records where it came from.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from functools import lru_cache

import boto3
import httpx

from ..config import AFTERMATH_WINDOW_DAYS, HTTP_USER_AGENT, REGION
from ..schemas import DisasterContext

log = logging.getLogger(__name__)
_http = httpx.Client(timeout=20, headers={"User-Agent": HTTP_USER_AGENT})

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11",
    "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30",
    "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56", "PR": "72", "VI": "78", "GU": "66",
}


# ---------------------------------------------------------------- geocoding

def _census_geocode(address: str) -> dict | None:
    """US Census geocoder: free, no key, returns county FIPS directly."""
    r = _http.get(
        "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress",
        params={"address": address, "benchmark": "Public_AR_Current", "vintage": "Current_Current", "format": "json"},
    )
    matches = r.json().get("result", {}).get("addressMatches", [])
    if not matches:
        return None
    m = matches[0]
    county = m["geographies"]["Counties"][0]
    return {
        "label": m["matchedAddress"],
        "lat": m["coordinates"]["y"],
        "lon": m["coordinates"]["x"],
        "county": county["BASENAME"],
        "state": m["addressComponents"]["state"],
        "county_fips": county["STATE"] + county["COUNTY"],
        "source": "US Census Geocoder",
    }


def _census_county_for_point(lat: float, lon: float) -> tuple[str, str] | None:
    r = _http.get(
        "https://geocoding.geo.census.gov/geocoder/geographies/coordinates",
        params={"x": lon, "y": lat, "benchmark": "Public_AR_Current", "vintage": "Current_Current", "format": "json"},
    )
    counties = r.json().get("result", {}).get("geographies", {}).get("Counties", [])
    if not counties:
        return None
    return counties[0]["BASENAME"], counties[0]["STATE"] + counties[0]["COUNTY"]


@lru_cache(maxsize=512)
def geocode(address: str) -> dict | None:
    """Address -> point + county. Amazon Location Service first, US Census geocoder as backup."""
    try:
        places = boto3.client("geo-places", region_name=REGION)
        res = places.geocode(QueryText=address, MaxResults=1, Filter={"IncludeCountries": ["USA"]})
        item = res["ResultItems"][0]
        lon, lat = item["Position"]
        addr = item["Address"]
        out = {
            "label": addr.get("Label"),
            "lat": lat,
            "lon": lon,
            "county": addr.get("SubRegion", {}).get("Name"),
            "state": addr.get("Region", {}).get("Code"),
            "source": "Amazon Location Service",
        }
        # Amazon Location names the county; the Census point lookup adds the FIPS code FEMA indexes by.
        try:
            hit = _census_county_for_point(lat, lon)
            out["county_fips"] = hit[1] if hit else None
        except Exception:  # FIPS is a nice-to-have; FEMA lookups fall back to county name.
            out["county_fips"] = None
        return out
    except Exception as exc:
        log.warning("Amazon Location geocode failed (%s); falling back to Census", exc)
    try:
        return _census_geocode(address)
    except Exception as exc:
        log.warning("Census geocode failed: %s", exc)
        return None


# ---------------------------------------------------------------- FEMA declarations

def _d(value: str | None) -> date | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if value else None


@lru_cache(maxsize=512)
def fema_declarations(state: str, county: str | None, on: date) -> list[dict]:
    """OpenFEMA DisasterDeclarationsSummaries for a state (and county) whose incident window covers `on`,
    including the aftermath window for indirect deaths. https://www.fema.gov/openfema-data-page/disaster-declarations-summaries-v2"""
    lo = (on - timedelta(days=60)).isoformat()
    flt = f"state eq '{state.upper()}' and incidentBeginDate le '{on.isoformat()}' and incidentBeginDate ge '{lo}'"
    r = _http.get(
        "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
        params={"$filter": flt, "$top": 1000, "$orderby": "incidentBeginDate desc"},
    )
    rows = r.json().get("DisasterDeclarationsSummaries", [])
    if county:
        name = county.lower().replace(" county", "").replace(" parish", "").strip()
        rows = [x for x in rows if (x.get("designatedArea") or "").lower().startswith(name) or x.get("designatedArea") == "Statewide"]
    return rows


def disaster_context(state: str | None, county: str | None, death_date: date | None,
                     lat: float | None = None, lon: float | None = None) -> DisasterContext:
    """Assemble everything checkable about the disaster at this place and time."""
    ctx = DisasterContext()
    if not (state and death_date):
        return ctx
    try:
        rows = fema_declarations(state, county, death_date)
    except Exception as exc:
        log.warning("OpenFEMA lookup failed: %s", exc)
        rows = []
    ctx.sources.append("OpenFEMA DisasterDeclarationsSummaries v2")
    major = [r for r in rows if r.get("declarationType") in ("DR", "EM")]
    if major:
        # Prefer a declaration with Individual Assistance: that is the program that pays funeral assistance.
        best = sorted(major, key=lambda r: (not r.get("ihProgramDeclared"), r.get("declarationType") != "DR"))[0]
        begin, end = _d(best.get("incidentBeginDate")), _d(best.get("incidentEndDate"))
        ctx.declared = True
        ctx.declaration = best.get("femaDeclarationString")
        ctx.declaration_title = (best.get("declarationTitle") or "").title()
        ctx.incident_type = best.get("incidentType")
        ctx.incident_begin, ctx.incident_end = begin, end
        ctx.individual_assistance = bool(best.get("ihProgramDeclared") or best.get("iaProgramDeclared"))
        if begin and death_date >= begin:
            if end is None or death_date <= end:
                ctx.within_incident_window, ctx.days_after_incident_end = True, 0
            else:
                late = (death_date - end).days
                ctx.days_after_incident_end = late
                ctx.within_incident_window = late <= AFTERMATH_WINDOW_DAYS
        else:
            ctx.within_incident_window = False
    if lat is not None and lon is not None:
        try:
            ctx.nws_warnings = nws_warnings(lat, lon, death_date)
            ctx.sources.append("NWS warnings archive (Iowa Environmental Mesonet VTEC)")
        except Exception as exc:
            log.warning("NWS archive lookup failed: %s", exc)
    return ctx


# ---------------------------------------------------------------- weather warnings

@lru_cache(maxsize=512)
def nws_warnings(lat: float, lon: float, on: date, days_before: int = 7) -> list[str]:
    """National Weather Service watches/warnings/advisories in force at a point in the week before a death.
    Historical archive via Iowa Environmental Mesonet; api.weather.gov only keeps recent alerts."""
    r = _http.get(
        "https://mesonet.agron.iastate.edu/json/vtec_events_bypoint.py",
        params={"lat": lat, "lon": lon, "sdate": (on - timedelta(days=days_before)).isoformat(), "edate": (on + timedelta(days=1)).isoformat()},
    )
    seen: list[str] = []
    for e in r.json().get("events", []):
        label = f"{e['name']} ({e['issue'][:10]})"
        if e.get("significance") in ("W", "A", "Y") and label not in seen:
            seen.append(label)
    return seen[:12]
