"""
Расчёт фактической доступности связи client -> gateway через ISL-mesh.

Проблема, которую закрывает модуль:
  geometry.py умеет строить снапшот графа контактов (snapshot()), но нигде
  не отвечает на прикладной вопрос сценария: держит ли группировка
  target_availability для каждого клиентского терминала на горизонте
  моделирования, при заданных отказах спутников/шлюзов.

Модель связности:
  - Наземные узлы НЕ ретранслируют трафик (см. geometry.py docstring).
    Поэтому путь client -> gateway всегда имеет вид:
        client -> sat_a -> sat_b -> ... -> sat_k -> gateway
    Прочие наземные точки в граф пути не включаются.
  - Пропускная способность ребра — не бинарная (0/1), а оценка ёмкости
    канала по дальности (упрощённый link budget: чем ближе к пределу
    дальности/углу места, тем ниже ёмкость). Это отличает модель от
    примитивного "путь существует / не существует" и даёт более
    реалистичную метрику деградации сети, а не только факта связности.
  - Доступность на момент t = 1, если max-flow(client, gateway) > 0.
  - Итоговая availability = доля временных отсчётов на горизонте,
    когда доступность = 1 (классическое определение SLA-аптайма).
  - Дополнительно считается средняя ёмкость канала в доступные моменты
    (bandwidth-aware метрика) — задел на capacity planning, а не только
    on/off доступность.

Как использовать:
    python availability.py scenario.json
"""

from __future__ import annotations
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import maximum_flow

from geometry import load, snapshot

# ---- Простая модель ёмкости канала по дальности -----------------------
# Иллюстративная (не измеренная) деградация ёмкости с расстоянием:
# на нулевой дальности - полная ёмкость (CAP_UNITS), на пределе дальности
# (isl_range_km для ISL, диапазон видимости для ground-link) - емкость
# падает к минимуму по квадратичному закону (грубое приближение
# свободного пространства, Friis: P ~ 1/d^2). Дискретизуется в целые
# "капacity units", т.к. maximum_flow scipy требует integer capacities.
CAP_UNITS = 1000
MIN_CAP_FRACTION = 0.05  # канал не обнуляется резко на самой границе


def link_capacity(dist_km: float, max_range_km: float) -> int:
    frac = max(0.0, 1.0 - (dist_km / max_range_km) ** 2)
    frac = max(frac, MIN_CAP_FRACTION) if dist_km < max_range_km else 0.0
    return max(1, int(round(frac * CAP_UNITS))) if frac > 0 else 0


def ground_link_max_range(elevation_deg: float, min_elevation_deg: float) -> float:
    """Синтетическая 'дальность' для земных линий не физическая (нет
    жёсткого предела в километрах, только по углу места), поэтому вес
    земной линии строим по запасу над минимальным углом места, а не по
    дистанции. Возвращает capacity fraction напрямую (0..1)."""
    if elevation_deg < min_elevation_deg:
        return 0.0
    # запас угла места 0..80 градусов сверх минимума -> насыщение ёмкости
    margin = min(elevation_deg - min_elevation_deg, 80.0) / 80.0
    return max(MIN_CAP_FRACTION, margin)


def build_flow_graph(s: dict, snap: dict, client_id: str, gateway_ids: list[str]):
    """Строит граф для max-flow: client -> sat* -> ... -> gateway(ы).
    Прочие наземные узлы исключены (не ретранслируют).
    Несколько шлюзов объединяются через виртуальный сток с
    бесконечной ёмкостью рёбер gateway->sink (стандартный приём
    multi-sink max-flow)."""
    e = s["environment"]
    active_sat_ids = [sat["id"] for sat in snap["satellites"] if sat["active"]]
    sat_index = {sid: i for i, sid in enumerate(active_sat_ids)}
    n_sat = len(active_sat_ids)

    # Индексация узлов: 0 = source(client), 1..n_sat = satellites,
    # n_sat+1..n_sat+len(gateways) = gateways, последний = virtual sink
    SRC = 0
    SAT0 = 1
    GW0 = SAT0 + n_sat
    SINK = GW0 + len(gateway_ids)
    n_nodes = SINK + 1

    rows, cols, data = [], [], []

    def add_edge(u, v, cap):
        if cap <= 0:
            return
        rows.append(u)
        cols.append(v)
        data.append(cap)

    for a, b, dist in snap["edges"]:
        a_is_sat = a in sat_index
        b_is_sat = b in sat_index
        if a_is_sat and b_is_sat:
            cap = link_capacity(dist, e["isl_range_km"])
            ia, ib = SAT0 + sat_index[a], SAT0 + sat_index[b]
            add_edge(ia, ib, cap)
            add_edge(ib, ia, cap)
        else:
            # один конец земной, другой спутниковый (иначе не бывает в snapshot)
            ground_id = a if not a_is_sat else b
            sat_id = b if not a_is_sat else a
            if ground_id not in (client_id, *gateway_ids):
                continue  # прочие наземные точки в путь не включаем
            el = snap["elevation_deg"].get(ground_id, {}).get(sat_id)
            if el is None:
                continue
            frac = ground_link_max_range(el, e["min_elevation_deg"])
            cap = max(1, int(round(frac * CAP_UNITS))) if frac > 0 else 0
            isat = SAT0 + sat_index[sat_id]
            if ground_id == client_id:
                add_edge(SRC, isat, cap)
                add_edge(isat, SRC, cap)
            else:
                gi = GW0 + gateway_ids.index(ground_id)
                add_edge(isat, gi, cap)
                add_edge(gi, isat, cap)

    for gi in range(len(gateway_ids)):
        add_edge(GW0 + gi, SINK, CAP_UNITS * 10)  # виртуальный сток, не узкое место

    graph = csr_matrix((data, (rows, cols)), shape=(n_nodes, n_nodes))
    return graph, SRC, SINK


def scenario_availability(s: dict) -> dict:
    e = s["environment"]
    gateways = [g["id"] for g in s["ground_sites"] if g["role"] == "gateway"]
    clients = [g["id"] for g in s["ground_sites"] if g["role"] == "client"]
    times = list(range(0, e["horizon_s"], e["step_s"]))

    result = {
        cid: {"up_steps": 0, "flow_sum": 0.0, "total_steps": len(times)}
        for cid in clients
    }

    for t in times:
        snap = snapshot(s, t)
        for cid in clients:
            graph, src, sink = build_flow_graph(s, snap, cid, gateways)
            flow = maximum_flow(graph, src, sink)
            f = flow.flow_value
            if f > 0:
                result[cid]["up_steps"] += 1
                result[cid]["flow_sum"] += f

    report = {
        "meta": s["meta"],
        "target_availability": e["target_availability"],
        "clients": {},
    }
    for cid, r in result.items():
        avail = r["up_steps"] / r["total_steps"]
        avg_flow = (r["flow_sum"] / r["up_steps"]) if r["up_steps"] else 0.0
        report["clients"][cid] = {
            "availability": round(avail, 4),
            "meets_target": avail >= e["target_availability"],
            "avg_relative_capacity": round(
                avg_flow / (CAP_UNITS * 10), 4
            ),  # доля от насыщения стока
            "up_steps": r["up_steps"],
            "total_steps": r["total_steps"],
        }
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python availability.py scenario.json")
    scenario = load(sys.argv[1])
    rep = scenario_availability(scenario)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
