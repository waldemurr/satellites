#!/usr/bin/env python3
"""Минимаксная оптимизация конфигурации группировки.

Задача: max_cfg min_{F: |F|=k} min_client availability(cfg, F) — выбрать
конфигурацию, устойчивую к потере k аппаратов (worst-case, не среднее).

Семейство конфигураций — схемы Уокера (число плоскостей P, фазировка F),
базовая схема 01_full_constellation, эллиптический вариант. Сценарии
отказов: случайные k-подмножества + адверсариальный набор (топ-k по
критичности из routing.satellite_criticality).

Стадия 1 (скрининг): сетка 240 с, 10 случайных наборов на каждое k.
Стадия 2 (финал): полная сетка 120 с, 30 случайных наборов + адверсариальный.

Запуск: .venv/bin/python optimize_config.py
"""

import copy
import itertools
import json
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "module"))

from geometry import load  # noqa: E402
import availability  # noqa: E402
import routing  # noqa: E402

random.seed(42)

HORIZON = 86400
CLIENTS = ["C65", "C70", "C72"]
K_VALUES = (2, 4, 6)
BASE = load(os.path.join(ROOT, "data", "01_full_constellation.json"))


def walker(P, F, n=48, **env_over):
    """Схема Уокера: P плоскостей, сдвиг фазы между соседними Δu = 360·F/n."""
    m = n // P
    planes, sats = [], []
    for p in range(P):
        pid = f"P{p+1}"
        planes.append(
            {
                "id": pid,
                "raan_deg": round(p * 360.0 / P, 3),
                "phase_deg": round(p * 360.0 * F / n, 3),
            }
        )
        for k in range(m):
            sats.append(
                {
                    "id": f"S{p+1:02d}{k+1:02d}",
                    "plane_id": pid,
                    "slot_deg": round(k * 360.0 / m, 3),
                    "launch_batch": 1 + (k % 3),
                }
            )
    s = copy.deepcopy(BASE)
    s["meta"] = {"id": f"walker_{P}_{F}", "title": f"Уокер {P} плоскостей, F={F}"}
    s["design"]["planes"], s["design"]["satellites"] = planes, sats
    s["environment"].update(env_over)
    return s


def elliptical_of(scenario, e=0.15, argp=90.0, alt=2000.0):
    s = copy.deepcopy(scenario)
    s["environment"].update(
        {
            "orbit_type": "elliptical",
            "eccentricity": e,
            "arg_perigee_deg": argp,
            "altitude_km": alt,
        }
    )
    return s


def with_failures(scenario, sat_ids):
    s = copy.deepcopy(scenario)
    for sid in sat_ids:
        s["failures"].append({"satellite_id": sid, "start_s": 0, "end_s": HORIZON})
    return s


def worst_client_avail(scenario):
    rep = availability.scenario_availability(scenario)
    avails = [rep["clients"][c]["availability"] for c in CLIENTS]
    return min(avails), rep


def adversarial_set(scenario, k, step_sample=12):
    """Жадная оценка худшего набора: топ-k по критичности."""
    hits = routing.satellite_criticality(
        scenario, CLIENTS, ["G_MUR"], step_sample=step_sample, strategy="hops"
    )
    return [sat for sat, _ in hits[:k]]


def evaluate(name, scenario, k_values, n_random, step_s, adversarial=True):
    sids = [s["id"] for s in scenario["design"]["satellites"]]
    scr = copy.deepcopy(scenario)
    scr["environment"]["step_s"] = step_s
    base_worst, _ = worst_client_avail(scr)
    rows = {0: [(base_worst, ())]}
    for k in k_values:
        sets = [tuple(random.sample(sids, k)) for _ in range(n_random)]
        if adversarial:
            sets.append(tuple(adversarial_set(scr, k)))
        rows[k] = []
        for fs in sets:
            w, _ = worst_client_avail(with_failures(scr, fs))
            rows[k].append((w, fs))
    return rows


def summarize(name, rows):
    out = {"name": name}
    for k, res in rows.items():
        worst = min(r[0] for r in res)
        mean = sum(r[0] for r in res) / len(res)
        argmin = min(res, key=lambda r: r[0])
        out[k] = {
            "minimax": worst,
            "mean": mean,
            "worst_set": list(argmin[1]),
            "n_scenarios": len(res),
        }
    return out


def fmt(res):
    cells = []
    for k in sorted(kk for kk in res if isinstance(kk, int)):
        r = res[k]
        cells.append(
            f"k={k}: {r['minimax']*100:5.1f}% (средн {r['mean']*100:5.1f}%, n={r['n_scenarios']})"
        )
    return f"{res['name']:28s} " + " | ".join(cells)


CANDIDATES = [
    ("base (3 пл., ΔΩ=60°, как 01)", lambda: copy.deepcopy(BASE)),
    ("Уокер 3, F=1 (ΔΩ=120°)", lambda: walker(3, 1)),
    ("Уокер 3, F=5", lambda: walker(3, 5)),
    ("Уокер 4, F=1", lambda: walker(4, 1)),
    ("Уокер 4, F=3", lambda: walker(4, 3)),
    ("Уокер 6, F=1", lambda: walker(6, 1)),
    ("Уокер 6, F=2", lambda: walker(6, 2)),
]


def main():
    print("=== Стадия 1: скрининг (сетка 240 с, 10 случайных наборов на k) ===")
    stage1 = []
    for name, make in CANDIDATES:
        t0 = time.perf_counter()
        rows = evaluate(name, make(), K_VALUES, n_random=10, step_s=240)
        res = summarize(name, rows)
        stage1.append((name, make, res))
        print(f"{fmt(res)}   [{time.perf_counter()-t0:.0f} с]")

    # финалисты: лучшие по суммарному минимаксу
    def total(r):
        return sum(r[k]["minimax"] for k in K_VALUES)

    stage1.sort(key=lambda x: -total(x[2]))
    finalists = stage1[:3]
    print("\nФиналисты:", ", ".join(n for n, _, _ in finalists))

    print("\n=== Стадия 2: финал (сетка 120 с, 30 случайных + адверсариальный) ===")
    random.seed(7)  # другая выборка — финал не подгоняется под скрининг
    final = []
    for name, make, _ in finalists:
        t0 = time.perf_counter()
        rows = evaluate(name, make(), K_VALUES, n_random=30, step_s=120)
        res = summarize(name, rows)
        final.append((name, make, res))
        print(f"{fmt(res)}   [{time.perf_counter()-t0:.0f} с]")

    # эллиптический вариант лучшего кругового финалиста
    best_circ = max(final, key=lambda x: total(x[2]))
    print(f"\n=== Эллиптический вариант лучшей круговой схемы: {best_circ[0]} ===")
    for argp in (90.0, 45.0):
        name = f"{best_circ[0]} + эллипс e=0.15, ω={argp:.0f}°"
        t0 = time.perf_counter()
        rows = evaluate(
            name, elliptical_of(best_circ[1]()), K_VALUES, n_random=30, step_s=120
        )
        res = summarize(name, rows)
        final.append((name, lambda a=argp: elliptical_of(best_circ[1](), argp=a), res))
        print(f"{fmt(res)}   [{time.perf_counter()-t0:.0f} с]")

    final.sort(key=lambda x: -total(x[2]))
    print("\n=== Итог (ранжирование по суммарному минимаксу k=2,4,6) ===")
    for name, _, res in final:
        print(fmt(res))

    winner_name, winner_make, winner_res = final[0]
    out = os.path.join(ROOT, "data", "06_optimal.json")
    w = winner_make()
    w["meta"] = {"id": "06_optimal", "title": f"Оптимальная (минимакс): {winner_name}"}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(w, f, ensure_ascii=False, indent=2)
    print(f"\nПобедитель: {winner_name}\nСценарий сохранён: {out}")
    print("Худшие наборы отказов по k:")
    for k in K_VALUES:
        print(f"  k={k}: {winner_res[k]['worst_set']}")


if __name__ == "__main__":
    main()
