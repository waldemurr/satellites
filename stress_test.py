#!/usr/bin/env python3
"""Стресс-тесты API: масштаб группировки, плотность сетки, конкурентность.

Запуск: .venv/bin/python stress_test.py  (сервер должен слушать :5002)
Сценарии-нагрузчики создаются в uploads/ и удаляются после прогона.
"""

import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import statistics

BASE = "http://localhost:5002"
R_EARTH = 6371.0


def api(path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
        return time.perf_counter() - t0, payload, None
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, None, f"HTTP {e.code}: {e.read()[:200]}"
    except Exception as e:
        return time.perf_counter() - t0, None, str(e)


def make_scenario(n_sats, step_s=120, horizon_s=86400, planes=None):
    planes = planes or max(3, n_sats // 16)
    per = n_sats // planes
    sats, pls = [], []
    for p in range(planes):
        pid = f"P{p+1}"
        pls.append(
            {
                "id": pid,
                "raan_deg": round(p * 360.0 / planes, 2),
                "phase_deg": round(p * 7.5, 2),
            }
        )
        for k in range(per):
            sats.append(
                {
                    "id": f"S{p+1:02d}{k+1:02d}",
                    "plane_id": pid,
                    "slot_deg": round(k * 360.0 / per, 3),
                    "launch_batch": min(3, p // (planes // 3) + 1),
                }
            )
    return {
        "schema_version": "cosmo-A-1.0",
        "meta": {
            "id": f"stress_{n_sats}",
            "title": f"Стресс {n_sats} КА, шаг {step_s}",
        },
        "environment": {
            "altitude_km": 550.0,
            "inclination_deg": 87.0,
            "earth_angle0_deg": 12.0,
            "horizon_s": horizon_s,
            "step_s": step_s,
            "min_elevation_deg": 10.0,
            "isl_range_km": 3000.0,
            "target_availability": 0.9,
        },
        "design": {"launch_stage": 3, "planes": pls, "satellites": sats},
        "ground_sites": [
            {
                "id": "G_MUR",
                "name": "Мурманск",
                "role": "gateway",
                "lat_deg": 68.97,
                "lon_deg": 33.07,
            },
            {
                "id": "C65",
                "name": "Пункт 65",
                "role": "client",
                "lat_deg": 65.0,
                "lon_deg": 60.0,
            },
            {
                "id": "C70",
                "name": "Пункт 70",
                "role": "client",
                "lat_deg": 70.0,
                "lon_deg": 90.0,
            },
            {
                "id": "C72",
                "name": "Пункт 72",
                "role": "client",
                "lat_deg": 72.0,
                "lon_deg": 130.0,
            },
        ],
        "failures": [],
        "gateway_outages": [],
    }


def upload(sc):
    fn = f"stress_{len(sc['design']['satellites'])}_{sc['environment']['step_s']}.json"
    _, res, err = api("/api/data/upload", {"filename": fn, "scenario": sc})
    if err or not res.get("valid"):
        raise RuntimeError(f"upload {fn}: {err or res}")
    return fn


def bench(label, path, repeats=3):
    times, errs = [], 0
    out = None
    for _ in range(repeats):
        dt, res, err = api(path)
        if err:
            errs += 1
        else:
            times.append(dt)
            out = res
    if times:
        print(
            f"{label:55s} min {min(times)*1000:8.0f} ms  med {statistics.median(times)*1000:8.0f} ms"
            + (f"  (ошибок {errs})" if errs else "")
        )
    else:
        print(f"{label:55s} ВСЕ ЗАПРОСЫ УПАЛИ: {errs}")
    return out, times


def main():
    created = []
    try:
        print("=== 1. Масштаб группировки (snapshot на t=43200) ===")
        scale = {}
        for n in (48, 96, 192, 384):
            fn = upload(make_scenario(n))
            created.append(fn)
            scale[n] = fn
            _, res, err = api("/api/calculate", {"file": fn, "timestamp": 43200})
            assert not err, err
            snap = res["result"]
            print(f"  N={n:4d}: {len(snap['edges'])} рёбер в снапшоте")

        print("\n=== 2. Латентность эндпоинтов по масштабу ===")
        results = {}
        for n, fn in scale.items():
            ts = []
            for _ in range(3):
                dt, res, err = api("/api/calculate", {"file": fn, "timestamp": 43200})
                assert not err, err
                ts.append(dt)
            print(
                f"calculate          N={n:4d}  min {min(ts)*1000:8.0f} ms  med {statistics.median(ts)*1000:8.0f} ms"
            )
            results[("calc", n)] = statistics.median(ts)
        for n, fn in scale.items():
            ss = 6 if n >= 192 else 1
            dt, res, err = api(
                f"/api/route-timeline/{fn}/C65/G_MUR?strategy=hops&step_sample={ss}"
            )
            assert not err, err
            print(
                f"route-timeline     N={n:4d} (sample={ss})  {dt*1000:8.0f} ms  avail={res['availability']:.3f}"
            )
            results[("tl", n)] = dt

        print("\n=== 3. Тяжёлые расчёты на базовом сценарии (48 КА) ===")
        fn = scale[48]
        dt, res, err = api(f"/api/availability/{fn}")
        assert not err, err
        print(f"availability  720 шагов      {dt*1000:8.0f} ms")
        results[("avail", 48)] = dt
        dt, res, err = api(f"/api/monte-carlo/{fn}?trials=100&mode=poisson")
        assert not err, err
        print(f"monte-carlo   100 испытаний  {dt*1000:8.0f} ms")
        results[("mc", 48)] = dt
        dt, res, err = api(f"/api/criticality/{fn}?step_sample=12")
        assert not err, err
        print(f"criticality   sample=12      {dt*1000:8.0f} ms")
        results[("crit", 48)] = dt

        print("\n=== 4. Плотность временной сетки (шаг 60 с → 1440 отсчётов) ===")
        fn60 = upload(make_scenario(48, step_s=60))
        created.append(fn60)
        dt, res, err = api(f"/api/availability/{fn60}")
        assert not err, err
        print(
            f"availability  1440 шагов     {dt*1000:8.0f} ms  (C65 {res['clients']['C65']['availability']:.3f})"
        )

        print("\n=== 5. Отказоустойчивость: exclude + невалидный файл ===")
        all_ids = [s["id"] for s in make_scenario(48)["design"]["satellites"]][:24]
        dt, res, err = api(
            "/api/calculate",
            {"file": scale[48], "timestamp": 43200, "exclude": all_ids},
        )
        assert not err, err
        active = sum(s["active"] for s in res["result"]["satellites"])
        assert active == 24, f"ожидалось 24 активных, получено {active}"
        print(f"calculate + exclude 24 КА  {dt*1000:8.0f} ms  активно {active} из 48")
        dt, res, err = api(
            "/api/data/upload",
            {"filename": "stress_bad.json", "scenario": {"schema_version": "wrong"}},
        )
        assert err and "422" in err, f"ожидался 422, получено res={res} err={err}"
        print(
            f"невалидный сценарий → 422 за {dt*1000:6.0f} ms ({err.split(':')[1].strip()[:80]}...)"
        )

        print("\n=== 6. Конкурентная нагрузка: 16 потоков × 20 смешанных запросов ===")
        reqs = []
        for i in range(320):
            t = (i * 977) % 86400
            reqs.append(
                ("/api/calculate", {"file": scale[48], "timestamp": t})
                if i % 3
                else (f"/api/route/{scale[48]}/C65/G_MUR?t_s={t}&strategy=hops", None)
            )
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=16) as ex:
            out = list(ex.map(lambda r: api(r[0], r[1], timeout=120), reqs))
        wall = time.perf_counter() - t0
        lats = sorted(d for d, _, err in out if not err)
        fails = sum(1 for _, _, err in out if err)
        p = lambda q: lats[int(q * (len(lats) - 1))] * 1000
        print(
            f"  320 запросов за {wall:.1f} с, пропускная способность {len(out)/wall:.0f} зап/с"
        )
        print(
            f"  ошибок: {fails}, латентность: p50 {p(.5):.0f} ms, p95 {p(.95):.0f} ms, p99 {p(.99):.0f} ms, max {lats[-1]*1000:.0f} ms"
        )
        assert fails == 0

        print("\n=== 7. Тяжёлый расчёт под конкурентной нагрузкой ===")
        with ThreadPoolExecutor(max_workers=8) as ex:
            bg = ex.submit(
                lambda: api(f"/api/monte-carlo/{scale[48]}?trials=200&mode=poisson")
            )
            lat = list(
                ex.map(
                    lambda r: api(r[0], r[1], timeout=120),
                    [
                        (
                            "/api/calculate",
                            {"file": scale[48], "timestamp": 5000 + i * 777},
                        )
                        for i in range(16)
                    ],
                )
            )
        dt_mc, res_mc, err_mc = bg.result()
        lats2 = sorted(d for d, _, e in lat if not e)
        print(
            f"  фон: monte-carlo 200 испытаний {dt_mc*1000:.0f} ms; "
            f"параллельно 16 × calculate: p50 {lats2[len(lats2)//2]*1000:.0f} ms, "
            f"p95 {lats2[int(len(lats2)*.95)]*1000:.0f} ms, ошибок {sum(1 for _,_,e in lat if e)}"
        )
        print("\nOK — все проверки пройдены")
    finally:
        import os

        for fn in created:
            for d in ("uploads",):
                p = os.path.join(d, fn)
                if os.path.isfile(p):
                    os.remove(p)
        print("временные сценарии удалены из uploads/")


if __name__ == "__main__":
    main()
