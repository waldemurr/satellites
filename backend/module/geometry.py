"""Расчёт координат спутников и доступных контактов. Python 3.10+, NumPy.

Орбиты: круговые и эллиптические. environment.altitude_km — высота большой
полуоси (для круговых орбит — просто высота орбиты). Для эллиптических
орбит (orbit_type == 'elliptical') добавляются:
  eccentricity    — эксцентриситет e (0..0.6), общий для группировки;
  arg_perigee_deg — аргумент перигея ω (0..360), ориентация перигея
                    в плоскости орбиты.
Каждый спутник может переопределить оба параметра своими полями
eccentricity / arg_perigee_deg. Перигей не может быть ниже 500 км
(высота перигея h_p = (R + altitude_km)·(1 − e) − R ≥ 500), высота
большой полуоси для эллиптических орбит — до 5000 км.

Движение — по законам Кеплера с учётом секулярных возмущений от
приплюснутости Земли (первый порядок по J₂ = 1.08263·10⁻³):
  Ω̇ = −(3/2)·J₂·n·(R/p)²·cos i            — регрессия линии узлов,
  ω̇ =  (3/4)·J₂·n·(R/p)²·(5 cos²i − 1)     — прецессия линии апсид,
  n̄ = n·(1 + (3/4)·J₂·(R/p)²·√(1−e²)·(3 cos²i − 1)) — среднее движение,
где p = a·(1−e²). На высоте 550 км и i = 87° это ~0,4°/сут регрессии
узлов и ~3–4°/сут дрейфа перигея — заметно на горизонте моделирования.
Уравнение Кеплера решается методом Ньютона, истинная аномалия и радиус
дают аргумент широты u = arg_perigee + ν. При e = 0 и J₂ = 0 схема
точно вырождается в равномерное движение по круговой орбите.
Короткопериодические члены J₂ и резонансные эффекты не учитываются —
для расчётного горизонта до 2 сут это допущение не превышает
первого порядка малости.
"""

from __future__ import annotations
import json, math, sys
from pathlib import Path
import numpy as np

R = 6371.0
MU = 398600.435507
OMEGA = 2 * math.pi / 86164.09054
J2 = 1.08262668e-3  # коэффициент приплюснутости Земли (EGM96)


def load(path: str | Path) -> dict:
    scenario = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(scenario)
    return scenario


def finite(x):
    return (
        isinstance(x, (int, float)) and (not isinstance(x, bool)) and math.isfinite(x)
    )


def validate(s: dict) -> None:
    if s.get("schema_version") != "cosmo-A-1.0":
        raise ValueError("Unsupported scenario schema")
    e, d = (s["environment"], s["design"])
    for key in (
        "altitude_km",
        "inclination_deg",
        "earth_angle0_deg",
        "horizon_s",
        "step_s",
        "min_elevation_deg",
        "isl_range_km",
        "target_availability",
    ):
        if not finite(e[key]):
            raise ValueError("Non-finite environment value: " + key)
    if not (0 < e["inclination_deg"] <= 180):
        raise ValueError("Invalid orbit")
    if not isinstance(e["step_s"], int) or not isinstance(e["horizon_s"], int):
        raise ValueError("Time grid must use integer seconds")
    if not (
        0 < e["step_s"] <= e["horizon_s"] <= 172800
        and e["horizon_s"] % e["step_s"] == 0
    ):
        raise ValueError("Invalid time grid")
    if not (
        0 <= e["min_elevation_deg"] < 90
        and 0 < e["isl_range_km"] <= 10000
        and (0 <= e["target_availability"] <= 1)
    ):
        raise ValueError("Invalid link/target values")
    elliptical = e.get("orbit_type", "circular") == "elliptical"
    if "orbit_type" in e and e["orbit_type"] not in ("circular", "elliptical"):
        raise ValueError("orbit_type must be circular or elliptical")
    alt_max = 5000.0 if elliptical else 1200.0
    if not (200 <= e["altitude_km"] <= alt_max):
        raise ValueError("Invalid orbit altitude")
    env_e = 0.0
    if elliptical:
        if not finite(e.get("eccentricity")) or not (0 <= e["eccentricity"] <= 0.6):
            raise ValueError("Invalid eccentricity")
        if not finite(e.get("arg_perigee_deg")) or not (
            0 <= e["arg_perigee_deg"] < 360
        ):
            raise ValueError("Invalid arg_perigee_deg")
        env_e = e["eccentricity"]
        r_p = (R + e["altitude_km"]) * (1 - env_e)
        if r_p < R + 500:
            raise ValueError(f"Perigee below 500 km: {round(r_p - R)}")
    planes = {p["id"]: p for p in d["planes"]}
    if len(planes) != len(d["planes"]) or not planes:
        raise ValueError("Duplicate/empty planes")
    for p in planes.values():
        if not all(
            (finite(p[k]) and 0 <= p[k] < 360 for k in ("raan_deg", "phase_deg"))
        ):
            raise ValueError("Invalid plane angle")
    ids = [sat["id"] for sat in d["satellites"]]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Duplicate/empty satellite IDs")
    if not isinstance(d["launch_stage"], int) or d["launch_stage"] not in (1, 2, 3):
        raise ValueError("launch_stage must be 1, 2 or 3")
    for sat in d["satellites"]:
        if (
            sat["plane_id"] not in planes
            or sat["launch_batch"] not in (1, 2, 3)
            or (not finite(sat["slot_deg"]))
        ):
            raise ValueError("Invalid satellite")
        sat_e = sat.get("eccentricity", env_e)
        if not finite(sat_e) or not (0 <= sat_e <= 0.6):
            raise ValueError("Invalid satellite eccentricity")
        r_p = (R + e["altitude_km"]) * (1 - sat_e)
        if r_p < R + 500:
            raise ValueError(f"Perigee below 500 km: {round(r_p - R)}")
        sat_w = sat.get("arg_perigee_deg", e.get("arg_perigee_deg", 0.0))
        if not finite(sat_w) or not (0 <= sat_w < 360):
            raise ValueError("Invalid satellite arg_perigee_deg")
    ground = s["ground_sites"]
    gids = [g["id"] for g in ground]
    if len(gids) != len(set(gids)) or set(gids) & set(ids):
        raise ValueError("Non-unique node IDs")
    if not any((g["role"] == "client" for g in ground)) or not any(
        (g["role"] == "gateway" for g in ground)
    ):
        raise ValueError("Client and gateway required")
    for g in ground:
        if (
            g["role"] not in ("client", "gateway")
            or not finite(g["lat_deg"])
            or (not finite(g["lon_deg"]))
            or (not (-90 <= g["lat_deg"] <= 90 and -180 <= g["lon_deg"] <= 180))
        ):
            raise ValueError("Invalid ground site")
    for field, key, valid in [
        ("failures", "satellite_id", set(ids)),
        (
            "gateway_outages",
            "gateway_id",
            {g["id"] for g in ground if g["role"] == "gateway"},
        ),
    ]:
        for f in s[field]:
            if (
                f[key] not in valid
                or not all((finite(f[k]) for k in ("start_s", "end_s")))
                or (not 0 <= f["start_s"] < f["end_s"] <= e["horizon_s"])
            ):
                raise ValueError("Invalid outage")


def positions(s: dict, t_s: float) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Return satellite IDs, model inertial positions [km], Earth-fixed positions [km].

    Круговые орбиты (e=0): u(t) = slot + phase + n·t. Эллиптические:
    решение уравнения Кеплера M = E − e·sin E методом Ньютона,
    u = arg_perigee + ν(E), r = a·(1 − e·cos E).
    """
    e, d = (s["environment"], s["design"])
    pmap = {p["id"]: p for p in d["planes"]}
    inc = math.radians(e["inclination_deg"])
    env_e = e.get("eccentricity", 0.0) if e.get("orbit_type") == "elliptical" else 0.0
    ecc = np.array(
        [float(sat.get("eccentricity", env_e) or 0.0) for sat in d["satellites"]]
    )
    argp = np.radians(
        [
            float(sat.get("arg_perigee_deg", e.get("arg_perigee_deg", 0.0)) or 0.0)
            for sat in d["satellites"]
        ]
    )
    a = R + e["altitude_km"]
    n = math.sqrt(MU / a**3)
    p = a * (1.0 - ecc**2)
    ratio2 = (R / p) ** 2  # (R/p)² — для каждого аппарата
    cosi = math.cos(inc)
    # Секулярные скорости от J2 (на аппарат, т.к. e может отличаться)
    nbar = n * (
        1.0
        + 0.75
        * J2
        * ratio2
        * np.sqrt(np.maximum(1.0 - ecc**2, 1e-12))
        * (3.0 * cosi**2 - 1.0)
    )
    odot = -1.5 * J2 * n * ratio2 * cosi  # регрессия линии узлов
    wdot = 0.75 * J2 * n * ratio2 * (5.0 * cosi**2 - 1.0)  # прецессия апсид
    M0 = np.array(
        [
            math.radians(x["slot_deg"] + pmap[x["plane_id"]]["phase_deg"])
            for x in d["satellites"]
        ]
    )
    M = M0 + nbar * t_s
    E = M.copy()
    for _ in range(15):
        E = E - (E - ecc * np.sin(E) - M) / np.maximum(1 - ecc * np.cos(E), 1e-9)
    nu = 2 * np.arctan2(
        np.sqrt(1 + ecc) * np.sin(E / 2),
        np.sqrt(np.maximum(1 - ecc, 1e-12)) * np.cos(E / 2),
    )
    r = a * (1 - ecc * np.cos(E))
    u = argp + wdot * t_s + nu
    om = (
        np.array(
            [math.radians(pmap[x["plane_id"]]["raan_deg"]) for x in d["satellites"]]
        )
        + odot * t_s
    )
    cu, su, co, so = (np.cos(u), np.sin(u), np.cos(om), np.sin(om))
    xyz = np.stack(
        (
            co * cu - so * su * math.cos(inc),
            so * cu + co * su * math.cos(inc),
            su * math.sin(inc),
        ),
        axis=1,
    )
    xyz = r[:, None] * xyz
    th = math.radians(e["earth_angle0_deg"]) + OMEGA * t_s
    c, ss = (math.cos(th), math.sin(th))
    fixed = xyz @ np.array([[c, -ss, 0], [ss, c, 0], [0, 0, 1]])
    return ([x["id"] for x in d["satellites"]], xyz, fixed)


def ground_position(g: dict) -> np.ndarray:
    lat, lon = (math.radians(g["lat_deg"]), math.radians(g["lon_deg"]))
    return R * np.array(
        [math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)]
    )


def snapshot(s: dict, t_s: float) -> dict:
    """Edges are potential bidirectional contacts; ground nodes cannot relay traffic."""
    e, d = (s["environment"], s["design"])
    ids, inertial, xyz = positions(s, t_s)
    failed = {
        f["satellite_id"] for f in s["failures"] if f["start_s"] <= t_s < f["end_s"]
    }
    active = np.array(
        [
            sat["launch_batch"] <= d["launch_stage"] and sat["id"] not in failed
            for sat in d["satellites"]
        ]
    )
    i, j = np.triu_indices(len(ids), 1)
    delta = xyz[j] - xyz[i]
    dist = np.linalg.norm(delta, axis=1)
    denom = np.sum(delta * delta, axis=1)
    lam = np.clip(-np.sum(xyz[i] * delta, axis=1) / np.maximum(denom, 1e-12), 0, 1)
    closest = np.linalg.norm(xyz[i] + lam[:, None] * delta, axis=1)
    ok = (dist < e["isl_range_km"]) & (closest > R) & active[i] & active[j]
    edges = [[ids[a], ids[b], float(dd)] for a, b, dd in zip(i[ok], j[ok], dist[ok])]
    elevations = {}
    for g in s["ground_sites"]:
        gp = ground_position(g)
        dif = xyz - gp
        dl = np.linalg.norm(dif, axis=1)
        el = np.degrees(np.arcsin(np.clip(dif @ (gp / R) / dl, -1, 1)))
        elevations[g["id"]] = {
            sid: float(el[k]) for k, sid in enumerate(ids) if active[k]
        }
        offline = any(
            (
                f["gateway_id"] == g["id"] and f["start_s"] <= t_s < f["end_s"]
                for f in s["gateway_outages"]
            )
        )
        vis = (el >= e["min_elevation_deg"]) & active & (not offline)
        edges.extend([[g["id"], ids[k], float(dl[k])] for k in np.where(vis)[0]])
    return {
        "t_s": t_s,
        "satellites": [
            {
                "id": sid,
                "x_km": float(xyz[k, 0]),
                "y_km": float(xyz[k, 1]),
                "z_km": float(xyz[k, 2]),
                "active": bool(active[k]),
            }
            for k, sid in enumerate(ids)
        ],
        "edges": edges,
        "elevation_deg": elevations,
    }


def sunlight(s: dict, t_s: float, sun_eci: list[float]) -> dict[str, bool]:
    """Fixed Sun direction and cylindrical Earth shadow, intended for <=24-hour fixtures."""
    ids, xyz, _ = positions(s, t_s)
    sun = np.array(sun_eci, dtype=float)
    sun /= np.linalg.norm(sun)
    projection = xyz @ sun
    perp = np.linalg.norm(xyz - projection[:, None] * sun, axis=1)
    eclipse = (projection < 0) & (perp < R)
    return {sid: not bool(eclipse[k]) for k, sid in enumerate(ids)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python geometry.py scenario.json [t_s]")
    s = load(sys.argv[1])
    t = float(sys.argv[2]) if len(sys.argv) > 2 else 0
    print(json.dumps(snapshot(s, t), ensure_ascii=False, indent=2, allow_nan=False))
