"""Explicit geography; country is never inferred from a name hash or building style."""
from dataclasses import dataclass, asdict
import json
import math
import re
from pathlib import Path

COUNTRIES = {
    "DE": ("Germany", "Europe", "western"), "FR": ("France", "Europe", "western"),
    "GB": ("United Kingdom", "Europe", "western"), "IT": ("Italy", "Europe", "western"),
    "ES": ("Spain", "Europe", "western"), "PL": ("Poland", "Europe", "western"),
    "NL": ("Netherlands", "Europe", "western"), "UA": ("Ukraine", "Europe", "western"),
    "US": ("United States", "NorthAmerica", "western"), "CA": ("Canada", "NorthAmerica", "western"),
    "MX": ("Mexico", "NorthAmerica", "western"), "BR": ("Brazil", "SouthAmerica", "western"),
    "AR": ("Argentina", "SouthAmerica", "western"), "CL": ("Chile", "SouthAmerica", "western"),
    "AE": ("United Arab Emirates", "MiddleEast", "arabic"), "SA": ("Saudi Arabia", "MiddleEast", "arabic"),
    "EG": ("Egypt", "MiddleEast", "arabic"), "IQ": ("Iraq", "MiddleEast", "arabic"),
    "JO": ("Jordan", "MiddleEast", "arabic"), "MA": ("Morocco", "Africa", "arabic"),
    "TN": ("Tunisia", "Africa", "arabic"), "TR": ("Turkey", "MiddleEast", "international"),
    "IN": ("India", "CentralAsia", "asian"), "PK": ("Pakistan", "CentralAsia", "arabic"),
    "JP": ("Japan", "SouthEastAsia", "asian"), "CN": ("China", "SouthEastAsia", "asian"),
    "KR": ("South Korea", "SouthEastAsia", "asian"), "VN": ("Vietnam", "SouthEastAsia", "asian"),
    "TH": ("Thailand", "SouthEastAsia", "asian"), "ID": ("Indonesia", "SouthEastAsia", "asian"),
    "SG": ("Singapore", "SouthEastAsia", "international"), "AU": ("Australia", "SouthEastAsia", "western"),
    "NZ": ("New Zealand", "SouthEastAsia", "western"), "ZA": ("South Africa", "Africa", "international"),
    "NG": ("Nigeria", "Africa", "international"), "KE": ("Kenya", "Africa", "international"),
}
LANDSCAPES = {
    "temperate": {"ground": [99,115,91], "grass": [75,108,69], "forest": [51,77,53], "day_color": [154,201,206], "rainy": True, "relief": 28},
    "arid": {"ground": [183,157,112], "grass": [138,137,82], "forest": [97,111,72], "day_color": [252,247,156], "rainy": False, "relief": 38},
    "tropical": {"ground": [94,120,78], "grass": [56,113,59], "forest": [36,73,42], "day_color": [231,214,171], "rainy": True, "relief": 32},
    "alpine": {"ground": [122,134,124], "grass": [85,116,95], "forest": [50,77,62], "day_color": [220,230,255], "rainy": True, "relief": 70},
    "mediterranean": {"ground": [158,151,111], "grass": [111,132,77], "forest": [72,101,59], "day_color": [255,232,188], "rainy": True, "relief": 40},
}
HOUSE_WEIGHTS = {
    "western": [("house_western0", 100)],
    "asian": [("house_asian0", 100)],
    "arabic": [("house_arab0", 100)],
    "international": [("house_asian0", 50), ("house_western0", 35), ("house_arab0", 15)],
}
OBJECTIVES = {
    "hospital": "objective_hospital", "university": "objective_university", "college": "objective_university",
    "prison": "objective_prison", "courthouse": "objective_courthouse", "marketplace": "objective_market",
    "fire_station": "objective_fire_rescue", "cemetery": "objective_cemetery", "recycling": "objective_recycling",
    "industrial": "objective_industrialcomplex", "plant": "objective_powerplant", "military": "objective_combatoutpost",
}

@dataclass(frozen=True)
class Config:
    city: str
    country_code: str
    landscape: str
    latitude: float
    country: str = ""
    region: str = ""
    culture: str = ""
    province: str = ""
    district: str = "City sector"
    seed: int = 1
    size: int = 8192
    max_buildings: int = 120
    objective_pairs: int = 3
    clearance: int = 32
    corridor_width: int = 192
    road_width: int = 96
    min_buildings: int = 12
    # Explicit asset group/style policy can be supplied by an art-aware profile.
    house_types: tuple = ()
    sin_city: bool = False

    def __post_init__(self):
        for key in ("size","seed","max_buildings","min_buildings","objective_pairs","clearance","corridor_width","road_width"):
            if type(getattr(self,key)) is not int:
                raise ValueError(f"{key} must be an integer")
        iso = self.country_code.upper()
        object.__setattr__(self, "country_code", iso)
        if not re.fullmatch(r"[A-Z]{2}", iso):
            raise ValueError("country_code must be a two-letter ISO code")
        defaults = COUNTRIES.get(iso, ("", "", ""))
        for key, default in zip(("country", "region", "culture"), defaults):
            if not getattr(self, key):
                object.__setattr__(self, key, default)
        if not all((self.country, self.region, self.culture)):
            raise ValueError("Unlisted country: supply country, region and culture explicitly")
        if self.culture not in HOUSE_WEIGHTS:
            raise ValueError("culture must be arabic, asian, western or international")
        if self.landscape not in LANDSCAPES:
            raise ValueError(f"landscape must be one of {', '.join(LANDSCAPES)}")
        if not math.isfinite(self.latitude) or not -85 <= self.latitude <= 85:
            raise ValueError("latitude must be -85..85")
        if self.size < 4096 or self.size > 16384 or self.size % 1024:
            raise ValueError("size must be 4096..16384 and divisible by 1024")
        if self.seed < 0 or self.seed >= 2**31:
            raise ValueError("seed must be 0..2^31-1")
        if not (0 <= self.min_buildings <= self.max_buildings <= 400) or self.max_buildings % 2:
            raise ValueError("max_buildings must be even and <=400; min_buildings must fit")
        if not 1 <= self.objective_pairs <= 6:
            raise ValueError("objective_pairs must be 1..6")
        if not (16 <= self.clearance <= 128 and 128 <= self.corridor_width <= 384 and 48 <= self.road_width <= 192):
            raise ValueError("Invalid clearance/corridor/road widths")
        for key in ("city", "country", "province", "district", "region"):
            value = getattr(self,key)
            if not isinstance(value,str) or (not value and key!="province") or "|" in value or any(ord(c)<32 for c in value):
                raise ValueError("Location labels must be printable strings without pipes")

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

    def metadata(self, source_digest):
        env = LANDSCAPES[self.landscape]
        return {"schema": 1, "generator_version": "0.1.0", "seed": self.seed, "source_digest": source_digest,
                "city": self.city, "cityname": self.city, "country": self.country, "country_code": self.country_code,
                "province": self.province, "citypart": self.district, "region": self.region, "culture": self.culture,
                "landscape": self.landscape, "rainy": env["rainy"], "day_color": env["day_color"],
                "sun_max_altitude": round(90-abs(self.latitude)*0.65, 3), "equatorial_sign": 1 if self.latitude>=0 else -1,
                "house_types": list(self.house_types), "sin_city": self.sin_city, "placement": "manual", "balance": "mirror-x", "size": self.size}

    def to_dict(self):
        return asdict(self)
