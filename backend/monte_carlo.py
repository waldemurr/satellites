"""
monte_carlo.py — вероятностная оценка риска через Monte Carlo перебор
случайных отказов спутников.

Проблема, которую закрывает модуль:
  Сценарии 01–04 дают ТОЧЕЧНУЮ оценку (один заданный набор отказов).
  Для инженерного решения "хватит ли группировке запаса устойчивости"
  нужна оценка РИСКА: с какой вероятностью доступность окажется ниже
  target_availability при случайном (не выбранном заранее) наборе
  отказов, какой разброс исходов, какой worst-case в пределах разумной
  вероятности.

Ключевая оптимизация производительности:
  Положения спутников и геометрические условия видимости (ISL line-of-
  sight, elevation к наземным станциям) НЕ зависят от того, какие
  спутники сейчас в отказе — они зависят только от времени и design.
  Поэтому вся дорогая геометрия (O(N^2) по спутникам на каждый момент
  времени) считается ОДИН РАЗ и кэшируется (build_geometry_cache), а
  каждое MC-испытание лишь фильтрует предвычисленный граф по своему
  случайному набору отказов и делает лёгкий BFS. Без этой оптимизации
  N_trials испытаний означали бы N_trials полных пересчётов геометрии
  (как в routing.py/availability.py) — на порядки дороже.

Использование:
    python monte_carlo.py scenario.json [--trials 300] [--mode poisson|fixed_k]
"""

from __future__ import annotations
import argparse
import json
import math
import sys
from collections import defaultdict, deque

import numpy as np

from geometry import load, positions, ground_position, R

# --------------------------------------------------------------------------
# Кэш геометрии, не зависящий от отказов (считается один раз на сценарий)
# --------------------------------------------------------------------------


def build_geometry_cache(s: dict, times: list[int]) -> dict:
    e, d = s["environment"], s["design"]
    eligible_mask_static = np.array(
        [sat["launch_batch"] <= d["launch_stage"] for sat in d["satellites"]]
    )
    ids_static = [sat["id"] for sat in d["satellites"]]
    eligible_ids = [sid for sid, ok in zip(ids_static, eligible_mask_static) if ok]

    cache = {"eligible_ids": eligible_ids, "by_t": {}}
    for t in times:
        ids, _, xyz = positions(s, t)
        i, j = np.triu_indices(len(ids), 1)
        delta = xyz[j] - xyz[i]
        dist = np.linalg.norm(delta, axis=1)
        denom = np.sum(delta * delta, axis=1)
        lam = np.clip(-np.sum(xyz[i] * delta, axis=1) / np.maximum(denom, 1e-12), 0, 1)
        closest = np.linalg.norm(xyz[i] + lam[:, None] * delta, axis=1)
        ok = (
            (dist < e["isl_range_km"])
            & (closest > R)
            & eligible_mask_static[i]
            & eligible_mask_static[j]
        )

        isl_adj: dict[str, list[str]] = defaultdict(list)
        for a, b in zip(i[ok], j[ok]):
            isl_adj[ids[a]].append(ids[b])
            isl_adj[ids[b]].append(ids[a])

        ground_visible: dict[str, set[str]] = {}
        for g in s["ground_sites"]:
            gp = ground_position(g)
            dif = xyz - gp
            dl = np.linalg.norm(dif, axis=1)
            el = np.degrees(np.arcsin(np.clip(dif @ (gp / R) / dl, -1, 1)))
            vis = (el >= e["min_elevation_deg"]) & eligible_mask_static
            ground_visible[g["id"]] = {ids[k] for k in np.where(vis)[0]}

        cache["by_t"][t] = {"isl_adj": isl_adj, "ground_visible": ground_visible}
    return cache


# --------------------------------------------------------------------------
# Генераторы случайных отказов
# --------------------------------------------------------------------------


def generate_failures_poisson(
    sat_ids: list[str],
    horizon_s: int,
    rate_per_day: float,
    mean_repair_h: float,
    rng: np.random.Generator,
):
    """Каждый спутник — независимый пуассоновский процесс отказов:
    rate_per_day — среднее число отказов в сутки на один аппарат,
    mean_repair_h — среднее время восстановления (экспоненциальное распределение)."""
    events = []
    mean_n = rate_per_day * horizon_s / 86400.0
    for sid in sat_ids:
        n = rng.poisson(mean_n)
        for _ in range(n):
            start = rng.uniform(0, horizon_s)
            dur = rng.exponential(mean_repair_h * 3600.0)
            end = min(horizon_s, start + dur)
            if end > start:
                events.append((sid, start, end))
    return events


def generate_failures_fixed_k(
    sat_ids: list[str],
    horizon_s: int,
    k: int,
    rng: np.random.Generator,
    start_frac_max: float = 0.5,
):
    """K случайно выбранных аппаратов одновременно уходят в отказ в случайный
    момент (до половины горизонта) и не восстанавливаются до конца горизонта —
    обобщение сценария 03_satellite_outages на случайный выбор аппаратов."""
    k = min(k, len(sat_ids))
    chosen = rng.choice(sat_ids, size=k, replace=False)
    start = rng.uniform(0, start_frac_max * horizon_s)
    return [(sid, start, horizon_s) for sid in chosen]


# --------------------------------------------------------------------------
# Быстрая проверка связности одного клиента с использованием кэша
# --------------------------------------------------------------------------


def _connected(
    cache_t: dict, client_id: str, gateway_id: str, failed_now: set[str]
) -> bool:
    client_view = cache_t["ground_visible"].get(client_id, set()) - failed_now
    if not client_view:
        return False
    gw_view = cache_t["ground_visible"].get(gateway_id, set()) - failed_now
    if not gw_view:
        return False
    isl_adj = cache_t["isl_adj"]
    seen = set(client_view)
    q = deque(client_view)
    while q:
        u = q.popleft()
        if u in gw_view:
            return True
        for v in isl_adj.get(u, ()):
            if v not in seen and v not in failed_now:
                seen.add(v)
                q.append(v)
    return bool(seen & gw_view)


# --------------------------------------------------------------------------
# Основной Monte Carlo прогон
# --------------------------------------------------------------------------


def monte_carlo_risk(
    s: dict,
    n_trials: int = 300,
    step_sample: int = 1,
    mode: str = "poisson",
    rate_per_day: float = 0.03,
    mean_repair_h: float = 6.0,
    k_fixed: int = 10,
    seed: int = 42,
) -> dict:
    e = s["environment"]
    times = list(range(0, e["horizon_s"], e["step_s"] * step_sample))
    cache = build_geometry_cache(s, times)
    sat_ids = cache["eligible_ids"]
    clients = [g["id"] for g in s["ground_sites"] if g["role"] == "client"]
    gateways = [g["id"] for g in s["ground_sites"] if g["role"] == "gateway"]
    rng = np.random.default_rng(seed)

    raw_availability = {cid: [] for cid in clients}
    raw_max_outage = {cid: [] for cid in clients}
    raw_outage_count = {cid: [] for cid in clients}

    for _trial in range(n_trials):
        if mode == "poisson":
            failures = generate_failures_poisson(
                sat_ids, e["horizon_s"], rate_per_day, mean_repair_h, rng
            )
        elif mode == "fixed_k":
            failures = generate_failures_fixed_k(sat_ids, e["horizon_s"], k_fixed, rng)
        else:
            raise ValueError('mode must be "poisson" or "fixed_k"')

        intervals_by_sat = defaultdict(list)
        for sid, st, en in failures:
            intervals_by_sat[sid].append((st, en))

        failed_by_t = []
        for t in times:
            failed_by_t.append(
                {
                    sid
                    for sid, ivs in intervals_by_sat.items()
                    if any(st <= t < en for st, en in ivs)
                }
            )

        for cid in clients:
            up = 0
            outages = []
            cur_start = None
            for idx, t in enumerate(times):
                failed_now = failed_by_t[idx]
                connected = any(
                    _connected(cache["by_t"][t], cid, gid, failed_now)
                    for gid in gateways
                )
                if connected:
                    up += 1
                    if cur_start is not None:
                        outages.append(t - cur_start)
                        cur_start = None
                else:
                    if cur_start is None:
                        cur_start = t
            if cur_start is not None:
                outages.append(e["horizon_s"] - cur_start)

            raw_availability[cid].append(up / len(times))
            raw_max_outage[cid].append(max(outages) if outages else 0)
            raw_outage_count[cid].append(len(outages))

    report = {
        "meta": s["meta"],
        "mode": mode,
        "n_trials": n_trials,
        "target_availability": e["target_availability"],
        "clients": {},
    }
    for cid in clients:
        arr = np.array(raw_availability[cid])
        report["clients"][cid] = {
            "mean_availability": round(float(arr.mean()), 4),
            "std_availability": round(float(arr.std()), 4),
            "p05": round(float(np.percentile(arr, 5)), 4),
            "p50_median": round(float(np.percentile(arr, 50)), 4),
            "p95": round(float(np.percentile(arr, 95)), 4),
            "worst_case": round(float(arr.min()), 4),
            "prob_meets_target": round(
                float((arr >= e["target_availability"]).mean()), 4
            ),
            "mean_max_outage_s": round(float(np.mean(raw_max_outage[cid])), 1),
            "mean_outage_count": round(float(np.mean(raw_outage_count[cid])), 2),
        }
    report["_raw_availability"] = raw_availability  # для построения гистограммы
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--mode", choices=["poisson", "fixed_k"], default="poisson")
    ap.add_argument("--step-sample", type=int, default=1)
    ap.add_argument("--rate-per-day", type=float, default=0.03)
    ap.add_argument("--mean-repair-h", type=float, default=6.0)
    ap.add_argument("--k-fixed", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    scenario = load(args.scenario)
    rep = monte_carlo_risk(
        scenario,
        n_trials=args.trials,
        step_sample=args.step_sample,
        mode=args.mode,
        rate_per_day=args.rate_per_day,
        mean_repair_h=args.mean_repair_h,
        k_fixed=args.k_fixed,
        seed=args.seed,
    )
    rep.pop("_raw_availability", None)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
