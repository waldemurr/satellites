"""
routing.py — маршрутизация и анализ устойчивости LEO-группировки.

Закрывает разрыв между geometry.py (снапшот графа контактов) и
требованиями ТЗ «Проектирование устойчивой спутниковой группировки»:

  п.3 «Маршрутизация и реакция на отказы»:
    - построить маршрут client -> gateway через спутниковую сеть;
    - маршрут пересчитывается при изменении положения/доступности КА;
    - для периода без маршрута показать ПРИЧИНУ (одна из четырёх,
      дословно по ТЗ): нет видимого спутника у клиента, разрыв ISL-сети,
      нет видимого спутника у шлюза, шлюз недоступен.

  п.2 «диаграмма доступности показывает интервалы связи и перерывы»:
    - не только доля доступного времени (это уже даёт availability.py),
      а список интервалов перерывов с длительностью и причиной.

  Доп. сценарии из ТЗ («могут быть реализованы дополнительно»):
    - поиск наиболее уязвимых аппаратов (satellite_criticality);
    - анализ резервных путей (find_backup_path, edge-disjoint);
    - сравнение стратегий маршрутизации (hops / latency / capacity).

Основной алгоритм — Dijkstra на графе снапшота (не max-flow): для UI
нужен КОНКРЕТНЫЙ путь для отрисовки, а не только факт связности.
Наземные узлы, кроме источника (клиент) и цели (шлюз), в граф пути не
включаются — по условию geometry.py «ground nodes cannot relay traffic».
"""
from __future__ import annotations
import heapq
import json
import sys
from collections import Counter, deque
from dataclasses import dataclass, field

from geometry import load, snapshot
from availability import link_capacity, ground_link_max_range, CAP_UNITS

C_KM_S = 299792.458  # скорость света, км/с

REASON_NO_CLIENT_VIEW = "no_visible_satellite_client"
REASON_ISL_BROKEN = "isl_mesh_disconnected"
REASON_NO_GATEWAY_VIEW = "no_visible_satellite_gateway"
REASON_GATEWAY_OFFLINE = "gateway_offline"

REASON_TEXT_RU = {
    REASON_NO_CLIENT_VIEW: "нет видимого спутника у наземного пункта",
    REASON_ISL_BROKEN: "разрыв межспутниковой сети (ISL)",
    REASON_NO_GATEWAY_VIEW: "нет видимого спутника у шлюза",
    REASON_GATEWAY_OFFLINE: "шлюз недоступен (в отказе)",
}


# --------------------------------------------------------------------------
# Построение подграфа для одной пары client -> gateway и поиск пути
# --------------------------------------------------------------------------

def _build_adjacency(snap: dict, client_id: str, gateway_id: str,
                      exclude_sats: frozenset = frozenset()):
    """Adjacency: node -> list[(neighbor, dist_km)].
    Включены только ISL-рёбра между активными спутниками и рёбра
    client<->sat, sat<->gateway. Прочие наземные узлы не участвуют."""
    adj: dict[str, list[tuple[str, float]]] = {}

    def add(u, v, w):
        adj.setdefault(u, []).append((v, w))
        adj.setdefault(v, []).append((u, w))

    sat_ids = {sat['id'] for sat in snap['satellites'] if sat['active']} - exclude_sats
    for a, b, dist in snap['edges']:
        a_is_sat, b_is_sat = a in sat_ids, b in sat_ids
        if a_is_sat and b_is_sat:
            add(a, b, dist)
        else:
            ground_id = a if not a_is_sat else b
            sat_id = b if not a_is_sat else a
            if ground_id not in (client_id, gateway_id):
                continue
            if sat_id not in sat_ids:
                continue
            add(ground_id, sat_id, dist)
    return adj


def _dijkstra(adj: dict, source: str, target: str, weight_fn):
    """Обычный Dijkstra по сумме weight_fn(dist_km) вдоль пути.
    Возвращает (path:list[str]|None, total_weight, total_dist_km)."""
    dist_to = {source: 0.0}
    km_to = {source: 0.0}
    prev = {}
    pq = [(0.0, source)]
    visited = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == target:
            break
        for v, dist_km in adj.get(u, []):
            w = weight_fn(dist_km)
            nd = d + w
            if v not in dist_to or nd < dist_to[v]:
                dist_to[v] = nd
                km_to[v] = km_to[u] + dist_km
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if target not in dist_to:
        return None, None, None
    path = [target]
    while path[-1] != source:
        path.append(prev[path[-1]])
    path.reverse()
    return path, dist_to[target], km_to[target]


def _widest_path(adj_cap: dict, source: str, target: str):
    """Maximin (widest path) Dijkstra по ёмкости ребра (capacity units)."""
    best = {source: float('inf')}
    prev = {}
    pq = [(-float('inf'), source)]
    visited = set()
    while pq:
        neg_c, u = heapq.heappop(pq)
        c = -neg_c
        if u in visited:
            continue
        visited.add(u)
        if u == target:
            break
        for v, cap in adj_cap.get(u, []):
            nc = min(c, cap)
            if v not in best or nc > best[v]:
                best[v] = nc
                prev[v] = u
                heapq.heappush(pq, (-nc, v))
    if target not in best or best[target] <= 0:
        return None, None
    path = [target]
    while path[-1] != source:
        path.append(prev[path[-1]])
    path.reverse()
    return path, best[target]


def find_path(s: dict, snap: dict, client_id: str, gateway_id: str,
              strategy: str = 'hops', exclude_sats: frozenset = frozenset()):
    """strategy: 'hops' | 'latency' | 'capacity'.
    Возвращает dict с path, metric, latency_ms, hops — либо None, если пути нет."""
    adj = _build_adjacency(snap, client_id, gateway_id, exclude_sats)
    if strategy == 'capacity':
        e = s['environment']
        adj_cap = {}
        for u, edges in adj.items():
            for v, dist_km in edges:
                if u in (client_id, gateway_id) or v in (client_id, gateway_id):
                    ground = u if u in (client_id, gateway_id) else v
                    sat = v if ground == u else u
                    el = snap['elevation_deg'].get(ground, {}).get(sat)
                    frac = ground_link_max_range(el, e['min_elevation_deg']) if el is not None else 0.0
                    cap = int(round(frac * CAP_UNITS))
                else:
                    cap = link_capacity(dist_km, e['isl_range_km'])
                adj_cap.setdefault(u, []).append((v, cap))
        path, cap = _widest_path(adj_cap, client_id, gateway_id)
        if path is None:
            return None
        latency_ms = _path_latency_ms(snap, path)
        return {'path': path, 'strategy': 'capacity', 'bottleneck_capacity': cap,
                'hops': len(path) - 2, 'latency_ms': latency_ms}
    if strategy == 'latency':
        weight_fn = lambda d: d / C_KM_S
    else:  # 'hops'
        weight_fn = lambda d: 1.0
    path, metric, total_km = _dijkstra(adj, client_id, gateway_id, weight_fn)
    if path is None:
        return None
    latency_ms = (total_km / C_KM_S) * 1000.0
    return {'path': path, 'strategy': strategy, 'hops': len(path) - 2,
            'latency_ms': round(latency_ms, 3), 'total_dist_km': round(total_km, 1)}


def _path_latency_ms(snap: dict, path: list[str]) -> float:
    dist_map = {}
    for a, b, dist in snap['edges']:
        dist_map[(a, b)] = dist
        dist_map[(b, a)] = dist
    total = sum(dist_map.get((path[i], path[i + 1]), 0.0) for i in range(len(path) - 1))
    return round((total / C_KM_S) * 1000.0, 3)


# --------------------------------------------------------------------------
# Классификация причины отсутствия маршрута (п.3 ТЗ)
# --------------------------------------------------------------------------

def classify_no_path(s: dict, snap: dict, t_s: float, client_id: str, gateway_id: str) -> str:
    e = s['environment']
    sat_ids = {sat['id'] for sat in snap['satellites'] if sat['active']}

    gw_offline = any(o['gateway_id'] == gateway_id and o['start_s'] <= t_s < o['end_s']
                      for o in s['gateway_outages'])
    if gw_offline:
        return REASON_GATEWAY_OFFLINE

    client_view = {sid for sid, el in snap['elevation_deg'].get(client_id, {}).items()
                    if sid in sat_ids and el >= e['min_elevation_deg']}
    if not client_view:
        return REASON_NO_CLIENT_VIEW

    gw_view = {sid for sid, el in snap['elevation_deg'].get(gateway_id, {}).items()
               if sid in sat_ids and el >= e['min_elevation_deg']}
    if not gw_view:
        return REASON_NO_GATEWAY_VIEW

    # BFS по чисто ISL-подграфу от видимых клиенту спутников
    isl_adj: dict[str, set[str]] = {}
    for a, b, dist in snap['edges']:
        if a in sat_ids and b in sat_ids:
            isl_adj.setdefault(a, set()).add(b)
            isl_adj.setdefault(b, set()).add(a)
    seen = set(client_view)
    q = deque(client_view)
    while q:
        u = q.popleft()
        for v in isl_adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                q.append(v)
    if seen & gw_view:
        return "unknown"  # путь на самом деле есть — защитная ветка от рассинхронизации
    return REASON_ISL_BROKEN


# --------------------------------------------------------------------------
# Таймлайн маршрута для одной пары client/gateway с агрегацией перерывов
# --------------------------------------------------------------------------

@dataclass
class RouteTimeline:
    client_id: str
    gateway_id: str
    strategy: str
    steps: list = field(default_factory=list)   # [{t, connected, path?, reason?, latency_ms?}]
    outages: list = field(default_factory=list)  # [{start_s, end_s, duration_s, reason}]
    availability: float = 0.0
    max_outage_s: int = 0
    outage_count: int = 0


def compute_route_timeline(s: dict, client_id: str, gateway_id: str,
                            strategy: str = 'hops') -> RouteTimeline:
    e = s['environment']
    tl = RouteTimeline(client_id=client_id, gateway_id=gateway_id, strategy=strategy)
    cur_outage_start = None
    cur_outage_reason = None
    up_steps = 0

    times = list(range(0, e['horizon_s'], e['step_s']))
    for t in times:
        snap = snapshot(s, t)
        res = find_path(s, snap, client_id, gateway_id, strategy)
        if res is not None:
            up_steps += 1
            tl.steps.append({'t_s': t, 'connected': True, **res})
            if cur_outage_start is not None:
                tl.outages.append({'start_s': cur_outage_start, 'end_s': t,
                                    'duration_s': t - cur_outage_start, 'reason': cur_outage_reason})
                cur_outage_start = None
        else:
            reason = classify_no_path(s, snap, t, client_id, gateway_id)
            tl.steps.append({'t_s': t, 'connected': False, 'reason': reason})
            if cur_outage_start is None:
                cur_outage_start = t
                cur_outage_reason = reason
            elif reason != cur_outage_reason:
                tl.outages.append({'start_s': cur_outage_start, 'end_s': t,
                                    'duration_s': t - cur_outage_start, 'reason': cur_outage_reason})
                cur_outage_start = t
                cur_outage_reason = reason

    if cur_outage_start is not None:
        end = e['horizon_s']
        tl.outages.append({'start_s': cur_outage_start, 'end_s': end,
                            'duration_s': end - cur_outage_start, 'reason': cur_outage_reason})

    tl.availability = round(up_steps / len(times), 4)
    tl.outage_count = len(tl.outages)
    tl.max_outage_s = max((o['duration_s'] for o in tl.outages), default=0)
    return tl


# --------------------------------------------------------------------------
# Уязвимость: критичность спутников (какие КА чаще всего являются
# единственной точкой отказа на текущем маршруте)
# --------------------------------------------------------------------------

def satellite_criticality(s: dict, client_ids: list[str], gateway_ids: list[str],
                           step_sample: int = 1, strategy: str = 'hops') -> list[tuple[str, int]]:
    """Для каждого момента t (с прореживанием step_sample) и каждой пары
    client/gateway с существующим маршрутом пробует исключить по очереди
    каждый спутник ЭТОГО маршрута и проверяет, остаётся ли альтернативный
    путь. Считает частоту, с которой отказ спутника рвёт связь конкретного
    клиента — количественная оценка «уязвимости» узла.
    Ограничение перебора спутниками текущего пути (а не всеми active)
    делает расчёт практичным по времени."""
    e = s['environment']
    times = list(range(0, e['horizon_s'], e['step_s'] * step_sample))
    hits = Counter()
    checked = 0
    for t in times:
        snap = snapshot(s, t)
        for cid in client_ids:
            for gid in gateway_ids:
                res = find_path(s, snap, cid, gid, strategy)
                if res is None:
                    continue
                sat_nodes = [n for n in res['path'] if n not in (cid, gid)]
                for sat in sat_nodes:
                    checked += 1
                    alt = find_path(s, snap, cid, gid, strategy, exclude_sats=frozenset({sat}))
                    if alt is None:
                        hits[sat] += 1
    return sorted(hits.items(), key=lambda kv: -kv[1])


# --------------------------------------------------------------------------
# Резервный путь (edge-disjoint по ISL-рёбрам)
# --------------------------------------------------------------------------

def find_backup_path(s: dict, snap: dict, client_id: str, gateway_id: str, strategy: str = 'hops'):
    primary = find_path(s, snap, client_id, gateway_id, strategy)
    if primary is None:
        return primary, None
    used_sats = frozenset(n for n in primary['path'] if n not in (client_id, gateway_id))
    # Убираем из графа спутники основного пути целиком (простая, консервативная
    # оценка резерва: полностью независимый маршрут, не разделяющий ни одного узла)
    backup = find_path(s, snap, client_id, gateway_id, strategy, exclude_sats=used_sats)
    return primary, backup


# --------------------------------------------------------------------------
# Сравнение стратегий маршрутизации на одном снапшоте
# --------------------------------------------------------------------------

def compare_strategies(s: dict, snap: dict, client_id: str, gateway_id: str) -> dict:
    out = {}
    for strat in ('hops', 'latency', 'capacity'):
        out[strat] = find_path(s, snap, client_id, gateway_id, strat)
    return out


# --------------------------------------------------------------------------
# Отчёт по сценарию: маршруты + уязвимость для всех client/gateway пар
# --------------------------------------------------------------------------

def scenario_routing_report(s: dict, strategy: str = 'hops', criticality_sample: int = 6) -> dict:
    clients = [g['id'] for g in s['ground_sites'] if g['role'] == 'client']
    gateways = [g['id'] for g in s['ground_sites'] if g['role'] == 'gateway']
    report = {'meta': s['meta'], 'strategy': strategy, 'routes': {}, 'criticality': []}
    for cid in clients:
        best = None
        for gid in gateways:
            tl = compute_route_timeline(s, cid, gid, strategy)
            if best is None or tl.availability > best[1].availability:
                best = (gid, tl)
        gid, tl = best
        report['routes'][cid] = {
            'gateway': gid,
            'availability': tl.availability,
            'meets_target': tl.availability >= s['environment']['target_availability'],
            'outage_count': tl.outage_count,
            'max_outage_s': tl.max_outage_s,
            'outages': tl.outages,
        }
    report['criticality'] = satellite_criticality(s, clients, gateways, step_sample=criticality_sample, strategy=strategy)[:10]
    return report


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python routing.py scenario.json [strategy]')
    scenario = load(sys.argv[1])
    strat = sys.argv[2] if len(sys.argv) > 2 else 'hops'
    rep = scenario_routing_report(scenario, strat)
    print(json.dumps(rep, ensure_ascii=False, indent=2))