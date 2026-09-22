from fractions import Fraction

from app.viability.scoring import SubScore, WEIGHTS_BPS, distance_decay

# Village Directory facilities report availability directly, or a coarse
# distance-range code when unavailable in-village. These illustrative
# scores let "close but not present" beat "no evidence at all" without
# claiming a precise distance.
_DISTANCE_SCORES = {
    "a": Fraction(7, 10),
    "b": Fraction(4, 10),
    "c": Fraction(3, 20),
}

_ROAD_TIERS = (
    "all_weather",
    "black_topped",
    "national_highway",
    "state_highway",
    "major_district_road",
    "gravel",
)

_ROAD_TIER_SCORES = {
    "all_weather": Fraction(1),
    "black_topped": Fraction(17, 20),
    "national_highway": Fraction(3, 5),
    "state_highway": Fraction(3, 5),
    "major_district_road": Fraction(3, 5),
    "gravel": Fraction(7, 20),
}


def _facility_score(facility: dict | None) -> Fraction | None:
    if facility is None:
        return None

    if facility.get("available") is True:
        return Fraction(1)

    if facility.get("available") is False:
        return _DISTANCE_SCORES.get(facility.get("distance_code"))

    return None


def _power_component(power_commercial: dict | None) -> Fraction | None:
    if power_commercial is None:
        return None

    if power_commercial.get("available") is False:
        return Fraction(0)

    hours = [
        value
        for value in (
            power_commercial.get("hours_summer"),
            power_commercial.get("hours_winter"),
        )
        if value is not None
    ]

    if not hours:
        return None

    return min(Fraction(1), Fraction(sum(hours), len(hours) * 24))


def _road_component(roads: dict | None) -> Fraction | None:
    if not roads:
        return None

    if all(roads.get(tier, {}).get("available") is None for tier in _ROAD_TIERS):
        return None

    for tier in _ROAD_TIERS:
        if roads.get(tier, {}).get("available") is True:
            return _ROAD_TIER_SCORES[tier]

    return Fraction(0)


def _bank_component(finance: dict | None) -> Fraction | None:
    if not finance:
        return None

    scores = [
        _facility_score(finance.get(name))
        for name in ("commercial_bank", "cooperative_bank", "atm")
    ]
    known = [score for score in scores if score is not None]

    return max(known) if known else None


def _mandi_component(markets: dict | None) -> Fraction | None:
    if not markets:
        return None

    return _facility_score(markets.get("mandis_regular_market"))


def infrastructure_subscore(amenities: dict | None) -> SubScore:
    """Infrastructure evidence from Village Directory amenities.

    Requires all four components (power, road, bank, mandi) to be known;
    a single missing component makes the whole sub-score Unknown rather
    than silently averaging over fewer inputs.
    """
    if amenities is None:
        return SubScore(
            "infrastructure",
            WEIGHTS_BPS["infrastructure"],
            None,
            "No Village Directory amenities are loaded for this village.",
        )

    components = {
        "commercial power hours": _power_component(
            (amenities.get("power") or {}).get("commercial")
        ),
        "road quality": _road_component(amenities.get("roads")),
        "bank access": _bank_component(amenities.get("finance")),
        "mandi access": _mandi_component(amenities.get("markets")),
    }

    missing = [name for name, value in components.items() if value is None]

    if missing:
        return SubScore(
            "infrastructure",
            WEIGHTS_BPS["infrastructure"],
            None,
            "Missing Village Directory evidence for: "
            + ", ".join(missing)
            + ".",
        )

    value = sum(components.values(), start=Fraction(0)) / len(components)

    return SubScore(
        "infrastructure",
        WEIGHTS_BPS["infrastructure"],
        value,
        "Mean of commercial power hours, road quality, bank access and "
        "mandi access from the Village Directory (2011 reference year); "
        "illustrative, not a verified infrastructure audit.",
    )


def inputs_subscore(amenities: dict | None, inputs_required: list[str]) -> SubScore:
    """Crop-input match against the village's reported top-3 commodities."""
    if not inputs_required:
        return SubScore(
            "inputs",
            WEIGHTS_BPS["inputs"],
            Fraction(1),
            "Not crop-input constrained under this archetype; "
            "non-crop procurement still requires verification.",
        )

    if amenities is None:
        return SubScore(
            "inputs",
            WEIGHTS_BPS["inputs"],
            None,
            "No Village Directory amenities are loaded for this village; "
            "required crop inputs cannot be checked.",
        )

    commodities = {
        value.casefold()
        for value in (
            (amenities.get("crops") or {}).get("agricultural_commodities") or {}
        ).values()
        if value
    }

    required = {crop.casefold() for crop in inputs_required}
    matched = sorted(required & commodities)

    return SubScore(
        "inputs",
        WEIGHTS_BPS["inputs"],
        Fraction(len(matched), len(required)),
        f"{len(matched)} of {len(required)} required crop inputs "
        f"({', '.join(matched) if matched else 'none'}) appear among this "
        "village's top-3 reported agricultural commodities; absence from "
        "the top 3 does not confirm a crop is not grown locally.",
    )


# Village Directory market facilities most relevant to each archetype's
# output/input market access. The Directory has no direct cold-storage
# field, so onion_storage's storage-market linkage is proxied by the same
# regulated-market facilities used for the grain archetypes.
_MARKET_FACILITY_PATHS = {
    "onion_storage": (
        ("markets", "mandis_regular_market"),
        ("markets", "agricultural_marketing_society"),
    ),
    "dal_mill": (
        ("markets", "mandis_regular_market"),
        ("markets", "agricultural_marketing_society"),
    ),
    "flour_mill": (
        ("markets", "mandis_regular_market"),
        ("markets", "agricultural_marketing_society"),
    ),
    "kirana_store": (
        ("markets", "pds_shop"),
        ("markets", "weekly_haat"),
    ),
    "tailoring_unit": (
        ("markets", "pds_shop"),
        ("markets", "weekly_haat"),
    ),
    "dairy_collection": (
        ("finance", "cooperative_bank"),
        ("finance", "agricultural_credit_society"),
        ("finance", "shg"),
    ),
}

_FACILITY_LABELS = {
    ("markets", "mandis_regular_market"): "regular mandi/market",
    ("markets", "agricultural_marketing_society"): "agricultural marketing society",
    ("markets", "pds_shop"): "PDS shop",
    ("markets", "weekly_haat"): "weekly haat",
    ("finance", "cooperative_bank"): "cooperative bank",
    ("finance", "agricultural_credit_society"): "agricultural credit society",
    ("finance", "shg"): "SHG presence",
}

# Half-score radius for the nearest-town distance decay; coarser than the
# mandi/bank radii in infrastructure_subscore since "nearest town" is a
# single named-place distance, not a facility-specific one.
_TOWN_DISTANCE_HALF_SCORE_M = 15_000


def _best_facility_component(
    amenities: dict, paths: tuple[tuple[str, str], ...]
) -> tuple[Fraction | None, tuple[str, str] | None]:
    best_value = None
    best_path = None

    for group, name in paths:
        value = _facility_score((amenities.get(group) or {}).get(name))

        if value is not None and (best_value is None or value > best_value):
            best_value = value
            best_path = (group, name)

    return best_value, best_path


def _nearest_town_component(connectivity: dict | None) -> Fraction | None:
    if not connectivity:
        return None

    km = connectivity.get("nearest_town_distance_km")

    if km is None:
        return None

    return distance_decay(round(km * 1_000), _TOWN_DISTANCE_HALF_SCORE_M)


def market_context_component(
    amenities: dict | None, archetype_id: str
) -> tuple[Fraction | None, str]:
    """Census Village Directory market-access evidence for an archetype.

    This scores market access and saturation context from facility
    presence/distance and nearest-town distance. It is not a competitor
    headcount and must not be described as one. Returns (value, note);
    value is None when neither a relevant facility nor a nearest-town
    distance is reported, never a guessed default.
    """
    base_note = (
        "Market access scored from Census Village Directory facility "
        "presence and distance. Not a competitor census."
    )

    paths = _MARKET_FACILITY_PATHS.get(archetype_id, ())

    if amenities is None or not paths:
        return None, (
            base_note + " No Village Directory amenities are loaded, or this "
            "archetype has no mapped market facility."
        )

    facility_value, facility_path = _best_facility_component(amenities, paths)
    town_value = _nearest_town_component(amenities.get("connectivity"))

    if facility_value is not None and town_value is not None:
        value = (3 * facility_value + town_value) / 4
        detail = (
            f"Combines the {_FACILITY_LABELS[facility_path]} facility signal "
            "with nearest-town distance."
        )
    elif facility_value is not None:
        value = facility_value
        detail = f"Based on the {_FACILITY_LABELS[facility_path]} facility signal."
    elif town_value is not None:
        value = town_value
        detail = (
            "No relevant market facility is reported for this village; "
            "based on nearest-town distance only."
        )
    else:
        return None, (
            base_note + " No relevant facility or nearest-town distance is "
            "reported for this village."
        )

    return value, f"{base_note} {detail}"
