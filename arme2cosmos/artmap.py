"""Hull crosswalk: Artemis 2.8 vesselData.xml <-> Cosmos shipDataBB.json.

There is no shared identifier between the two registries, so the map is built by
fuzzy-matching: a 2.8 vessel (race + classname) maps to the Cosmos hull on the same
side whose name/key best matches the classname. The result (``hullmap``) lets the
converter resolve real ship art instead of placeholders. It is a *draft* -- review
the ``unmatched`` list and the lower-confidence entries.

``shipDataBB.json`` is HJSON (JSON + ``//`` comments), so rather than a full parse we
extract each ship's key/name/side by position (robust to the comment syntax).
"""

from __future__ import annotations

import bisect
import re
import xml.etree.ElementTree as ET

# 2.8 hullRace name -> Cosmos `side` token.
_RACE_SIDE = {
    "tsn": "TSN", "terran": "TSN", "kralien": "Kralien", "torgoth": "Torgoth",
    "arvonian": "Arvonian", "skaraan": "Skaraan", "pirate": "Pirate",
    "biomech": "Biomech", "ximni": "Ximni",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def parse_vesseldata(path: str):
    """Return (races, vessels) from a 2.8 vesselData.xml."""
    root = ET.parse(path).getroot()
    races = {hr.get("ID"): {"name": hr.get("name", ""), "keys": hr.get("keys", "")}
             for hr in root.iter("hullRace")}
    vessels = [{"id": v.get("uniqueID"), "race_id": v.get("side"),
                "classname": v.get("classname", ""), "broadType": v.get("broadType", "")}
               for v in root.iter("vessel")]
    return races, vessels


def parse_shipdata(path: str):
    """Return a list of {key,name,side} from a Cosmos shipDataBB.json (HJSON)."""
    t = open(path, encoding="utf-8").read()
    keys = [(m.start(), m.group(1)) for m in re.finditer(r'"key"\s*:\s*"([^"]+)"', t)]
    names = {m.start(): m.group(1) for m in re.finditer(r'"name"\s*:\s*"([^"]*)"', t)}
    sides = {m.start(): m.group(1) for m in re.finditer(r'"side"\s*:\s*"([^"]*)"', t)}
    npos, spos = sorted(names), sorted(sides)

    def after(pos, arr, d):
        i = bisect.bisect_right(arr, pos)
        return d[arr[i]] if i < len(arr) else ""

    return [{"key": k, "name": after(p, npos, names), "side": after(p, spos, sides)}
            for p, k in keys]


def _best_hull(race_name: str, classname: str, hulls):
    """Best Cosmos hull key for a 2.8 (race, classname), or None. Side-constrained."""
    side = _RACE_SIDE.get((race_name or "").lower())
    cands = [h for h in hulls if side and h["side"] == side]
    if not cands:
        return None, 0.0
    cls = _norm(classname)
    cls_tokens = set(cls.split())
    best, best_score = None, 0.0
    for h in cands:
        hn, hk = _norm(h["name"]), _norm(h["key"])
        if cls and (cls == hn):
            score = 3.0
        elif cls and (cls in hn or cls in hk):
            score = 2.0
        else:
            score = float(len(cls_tokens & (set(hn.split()) | set(hk.split()))))
        if score > best_score:
            best, best_score = h, score
    return (best["key"], best_score) if best and best_score >= 1.0 else (None, 0.0)


def build_hullmap(races, vessels, hulls):
    by_hull_id, by_race_class, unmatched = {}, {}, []
    for v in vessels:
        rname = races.get(v["race_id"], {}).get("name", "")
        key, score = _best_hull(rname, v["classname"], hulls)
        if key:
            by_hull_id[v["id"]] = key
            by_race_class[f"{rname.lower()}|{_norm(v['classname'])}"] = key
        else:
            unmatched.append({"id": v["id"], "race": rname, "class": v["classname"]})
    return {"by_hull_id": by_hull_id, "by_race_class": by_race_class,
            "unmatched": unmatched}


def generate(vesseldata_path: str, shipdata_path: str):
    races, vessels = parse_vesseldata(vesseldata_path)
    hulls = parse_shipdata(shipdata_path)
    hm = build_hullmap(races, vessels, hulls)
    stats = {"vessels": len(vessels), "hulls": len(hulls),
             "matched": len(hm["by_hull_id"]), "unmatched": len(hm["unmatched"])}
    return hm, stats


def resolve_art(hullmap: dict, hull_id=None, race_keys=None, hull_keys=None):
    """Resolve a Cosmos art key from a hullmap given 2.8 create attributes."""
    if not hullmap:
        return None
    if hull_id and hull_id in hullmap.get("by_hull_id", {}):
        return hullmap["by_hull_id"][hull_id]
    race = (race_keys or "").split()
    race0 = race[0].lower() if race else ""
    hull = _norm(hull_keys) if hull_keys else ""
    return hullmap.get("by_race_class", {}).get(f"{race0}|{hull}")
