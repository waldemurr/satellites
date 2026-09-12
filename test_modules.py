#!/usr/bin/env python3
"""Тестирование расчётных модулей напрямую — проверка импорта и базовых функций."""

import math
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.join(ROOT, "backend", "module")
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, MODULE_DIR)

try:
    from geometry import load, validate, snapshot

    print("✓ geometry.py успешно импортирован")

    # Реальный расчёт по первому доступному сценарию
    data_dir = os.path.join(ROOT, "data")
    scenarios = sorted(f for f in os.listdir(data_dir) if f.endswith(".json"))
    if scenarios:
        path = os.path.join(data_dir, scenarios[0])
        scenario = load(path)
        print(f"✓ Сценарий загружен и валиден: {scenarios[0]}")
        snap = snapshot(scenario, 0)
        print(
            f"✓ Снапшот t=0: {len(snap['satellites'])} спутников, "
            f"{len(snap['edges'])} связей"
        )
    else:
        print("! В data/ нет сценариев — проверка только импорта")

    import routing

    print("✓ routing.py успешно импортирован")

    import availability

    print("✓ availability.py успешно импортирован")

    import monte_carlo

    print("✓ monte_carlo.py успешно импортирован")

    # --- Эллиптические орбиты ---
    import copy

    import numpy as np

    from geometry import R, positions

    ell_path = os.path.join(data_dir, "05_elliptical.json")
    if os.path.isfile(ell_path):
        ell = load(ell_path)
        env = ell["environment"]
        a = R + env["altitude_km"]
        ecc = env["eccentricity"]
        rp, ra = a * (1 - ecc), a * (1 + ecc)
        # мини-/максир радиус по орбите за часть периода
        radii = []
        for t in range(0, 12000, 100):
            _, xyz, _ = positions(ell, t)
            radii.append(float(np.linalg.norm(xyz[0])))
        assert abs(min(radii) - rp) < 1, f"перигей {min(radii):.1f} != {rp:.1f}"
        assert abs(max(radii) - ra) < 1, f"апогей {max(radii):.1f} != {ra:.1f}"
        assert rp >= R + 500, "перигей ниже 500 км"
        print(
            f"✓ Эллиптическая орбита: перигей {rp - R:.0f} км, апогей {ra - R:.0f} км "
            f"— сходится с теорией"
        )

        # per-satellite override (P3 в 05_elliptical.json)
        p3 = [s for s in ell["design"]["satellites"] if s["plane_id"] == "P3"][0]
        assert p3.get("eccentricity"), "ожидался override eccentricity у P3"
        print("✓ Per-satellite override eccentricity валиден")

    # регрессия: при J2=0 и e=0 позиции точно совпадают с двухтельной задачей
    import geometry

    def two_body_xyz(scenario, t_s):
        env, des = scenario["environment"], scenario["design"]
        pmap = {p["id"]: p for p in des["planes"]}
        inc = math.radians(env["inclination_deg"])
        a = geometry.R + env["altitude_km"]
        nn = math.sqrt(geometry.MU / a**3)
        out = []
        for sat in des["satellites"]:
            u = math.radians(sat["slot_deg"] + pmap[sat["plane_id"]]["phase_deg"]) + nn * t_s
            om = math.radians(pmap[sat["plane_id"]]["raan_deg"])
            out.append(
                a
                * np.array(
                    [
                        math.cos(om) * math.cos(u) - math.sin(om) * math.sin(u) * math.cos(inc),
                        math.sin(om) * math.cos(u) + math.cos(om) * math.sin(u) * math.cos(inc),
                        math.sin(u) * math.sin(inc),
                    ]
                )
            )
        return np.array(out)

    circ = load(os.path.join(data_dir, "01_full_constellation.json"))
    saved_j2 = geometry.J2
    try:
        geometry.J2 = 0.0
        _, xyz_0, _ = positions(circ, 3600)
    finally:
        geometry.J2 = saved_j2
    manual = two_body_xyz(circ, 3600)
    assert np.allclose(xyz_0, manual, atol=1e-6), "двухтельная задача (J2=0) не сходится"
    print("✓ Регрессия: J2=0, e=0 — точное совпадение с двухтельной задачей")

    # влияние J2: отклонение от двухтельной задачи растёт и правдоподобно по величине
    _, xyz_j2, _ = positions(circ, 86400)
    dev = float(np.max(np.linalg.norm(xyz_j2 - two_body_xyz(circ, 86400), axis=1)))
    assert 50.0 < dev < 20000.0, f"отклонение от J2 вне ожидаемого диапазона: {dev:.0f} км"
    print(f"✓ J2 учитывается: отклонение от двухтельной задачи за сутки ≈ {dev:.0f} км")
    # регрессия узлов: при i=87° (прямое движение) узлы дрейфуют к западу
    _, xyz_t0, _ = positions(circ, 0)
    assert float(np.max(np.linalg.norm(xyz_t0 - two_body_xyz(circ, 0), axis=1))) < 1e-6
    print("✓ При t=0 возмущения J2 нулевые (секулярная модель)")

    # отказ при перигее < 500 км
    bad = copy.deepcopy(circ)
    bad["environment"]["orbit_type"] = "elliptical"
    bad["environment"]["altitude_km"] = 550.0
    bad["environment"]["eccentricity"] = 0.3  # перигей ~394 км
    bad["environment"]["arg_perigee_deg"] = 0.0
    try:
        validate(bad)
        print("✗ Ограничение перигея 500 км не сработало")
        sys.exit(1)
    except ValueError:
        print("✓ Ограничение перигея ≥ 500 км срабатывает")

    print("Все модули успешно импортированы!")

except Exception as e:
    print(f"✗ Ошибка импорта: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)
