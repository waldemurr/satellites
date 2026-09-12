#!/usr/bin/env python3
"""Тестирование расчётных модулей напрямую — проверка импорта и базовых функций."""

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

    print("Все модули успешно импортированы!")

except Exception as e:
    print(f"✗ Ошибка импорта: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)
