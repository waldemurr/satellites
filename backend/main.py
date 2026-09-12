"""
API веб-сервиса для проектирования спутниковой группировки.

Эндпоинты:
    GET  /api/health                              — состояние сервиса
    GET  /api/data/files                          — список файлов сценариев
    GET  /api/data/<filename>                     — содержимое сценария
    GET  /api/data/<filename>/meta                — состав группировки без расчёта
    POST /api/data/upload                         — загрузка пользовательского сценария
    POST /api/calculate                           — снапшот сети в момент t
    POST /api/validate                            — валидация сценария (текст ошибок)
    GET  /api/route/<file>/<client>/<gateway>     — маршрут в момент t (?t_s=, ?strategy=)
    GET  /api/route-timeline/<file>/<client>/<gateway> — маршрут на всём горизонте
    GET  /api/availability/<filename>             — доступность связи по сценарию
    GET  /api/monte-carlo/<filename>              — вероятностный анализ рисков
    GET  /api/download/<filename>                 — скачивание сценария
"""

import json
import os
import re
import sys

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")
MODULE_DIR = os.path.join(BASE_DIR, "module")
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
TEMPLATE_DIR = os.path.join(FRONTEND_DIR, "templates")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
sys.path.insert(0, MODULE_DIR)

SAFE_NAME = re.compile(r"^[\w][\w\-. ]*\.json$")

try:
    from geometry import load, validate, snapshot
    import routing
    import availability
    import monte_carlo

    MODULES_AVAILABLE = True
    MODULES_ERROR = None
except ImportError as e:
    MODULES_AVAILABLE = False
    MODULES_ERROR = str(e)
    print(f"Расчётные модули недоступны: {e}")


def scenario_path(filename):
    """Путь к сценарию: загруженные файлы приоритетнее файлов из data/."""
    if not SAFE_NAME.match(filename):
        raise ValueError("Недопустимое имя файла")
    for base in (UPLOAD_DIR, DATA_DIR):
        path = os.path.join(base, filename)
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(f"Файл не найден: {filename}")


def apply_exclude(scenario, exclude):
    """Клон сценария с принудительным отключением спутников на весь горизонт.

    exclude — iterable id спутников; неизвестные id игнорируются.
    Файл на диске не изменяется: отказ добавляется только в копию в памяти.
    """
    exclude = [sid for sid in (exclude or []) if isinstance(sid, str)]
    if not exclude:
        return scenario
    known = {sat["id"] for sat in scenario["design"]["satellites"]}
    horizon = scenario["environment"]["horizon_s"]
    s2 = json.loads(json.dumps(scenario))
    failures = s2.setdefault("failures", [])
    for sid in exclude:
        if sid in known:
            failures.append({"satellite_id": sid, "start_s": 0, "end_s": horizon})
    return s2


def parse_exclude_arg(raw):
    """exclude из query string: 'S01,S02' или повторяющийся ?exclude=S01&exclude=S02."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    return [x.strip() for x in raw if isinstance(x, str) and x.strip()]


def validation_errors(scenario):
    """validate() из geometry.py бросает ValueError с первой ошибкой —
    здесь приводим к списку человекочитаемых сообщений."""
    try:
        validate(scenario)
        return []
    except ValueError as e:
        return [str(e)]
    except KeyError as e:
        return [f"Отсутствует обязательное поле: {e}"]
    except Exception as e:
        return [f"Ошибка структуры сценария: {e}"]


def create_app():
    app = Flask(
        __name__,
        template_folder=TEMPLATE_DIR,
        static_folder=STATIC_DIR,
        static_url_path="/static",
    )
    CORS(app)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/health")
    def health():
        return jsonify(
            {
                "status": "healthy",
                "modules_available": MODULES_AVAILABLE,
                "modules_error": MODULES_ERROR,
            }
        )

    @app.route("/api/data/files")
    def get_data_files():
        files = []
        try:
            if os.path.isdir(DATA_DIR):
                files += [f for f in os.listdir(DATA_DIR) if f.endswith(".json")]
            if os.path.isdir(UPLOAD_DIR):
                files += [f for f in os.listdir(UPLOAD_DIR) if f.endswith(".json")]
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"files": sorted(set(files))})

    @app.route("/api/data/upload", methods=["POST"])
    def upload_data_file():
        """Загрузка сценария: multipart-файл или JSON в теле запроса."""
        try:
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            if request.files and "file" in request.files:
                f = request.files["file"]
                filename = os.path.basename(f.filename or "")
                if not SAFE_NAME.match(filename):
                    return (
                        jsonify({"error": "Имя файла должно заканчиваться на .json"}),
                        400,
                    )
                scenario = json.loads(f.read().decode("utf-8"))
            else:
                body = request.get_json(silent=True) or {}
                filename = os.path.basename(str(body.get("filename", "")))
                scenario = body.get("scenario")
                if not filename or not SAFE_NAME.match(filename):
                    return jsonify({"error": "Некорректное имя файла"}), 400
                if not isinstance(scenario, dict):
                    return (
                        jsonify(
                            {
                                "error": 'В теле запроса ожидается {"filename": ..., "scenario": {...}}'
                            }
                        ),
                        400,
                    )

            errors = validation_errors(scenario)
            if errors:
                return jsonify({"valid": False, "errors": errors}), 422

            with open(os.path.join(UPLOAD_DIR, filename), "w", encoding="utf-8") as out:
                json.dump(scenario, out, ensure_ascii=False, indent=2)
            return jsonify({"valid": True, "filename": filename})
        except json.JSONDecodeError as e:
            return jsonify({"error": f"Некорректный JSON: {e}"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/download/<path:filename>")
    def download_file(filename):
        try:
            path = scenario_path(filename)
            return send_from_directory(
                os.path.dirname(path), os.path.basename(path), as_attachment=True
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/data/<path:filename>")
    def get_data_file(filename):
        try:
            with open(scenario_path(filename), "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except json.JSONDecodeError:
            return (
                jsonify({"error": f"Файл {filename} содержит некорректный JSON"}),
                500,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/data/<path:filename>/meta")
    def get_scenario_meta(filename):
        """Состав группировки и параметры без дорогого расчёта."""
        try:
            scenario = load(scenario_path(filename))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404
        e = scenario["environment"]
        d = scenario["design"]
        return jsonify(
            {
                "meta": scenario.get("meta", {}),
                "environment": e,
                "launch_stage": d["launch_stage"],
                "planes": d["planes"],
                "satellites": d["satellites"],
                "ground_sites": scenario["ground_sites"],
                "failures": scenario.get("failures", []),
                "gateway_outages": scenario.get("gateway_outages", []),
            }
        )

    @app.route("/api/calculate", methods=["POST"])
    def calculate():
        if not MODULES_AVAILABLE:
            return jsonify({"error": "Расчётные модули недоступны"}), 500
        try:
            data = request.get_json(force=True)
            filename = data.get("file")
            t_s = data.get("timestamp", 0)
            exclude = data.get("exclude") or []
            if not filename:
                return jsonify({"error": 'Не указан файл сценария (поле "file")'}), 400
            scenario = apply_exclude(load(scenario_path(filename)), exclude)
            t_s = max(0.0, min(float(t_s), float(scenario["environment"]["horizon_s"])))
            return jsonify({"result": snapshot(scenario, t_s), "timestamp": t_s})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": f"Ошибка расчёта: {e}"}), 500

    @app.route("/api/validate", methods=["POST"])
    def validate_scenario():
        if not MODULES_AVAILABLE:
            return jsonify({"error": "Расчётные модули недоступны"}), 500
        body = request.get_json(force=True)
        scenario = body.get("scenario")
        if not isinstance(scenario, dict):
            return (
                jsonify({"error": 'В теле запроса ожидается {"scenario": {...}}'}),
                400,
            )
        errors = validation_errors(scenario)
        return jsonify({"valid": not errors, "errors": errors})

    @app.route("/api/route/<path:filename>/<client_id>/<gateway_id>")
    def calculate_route(filename, client_id, gateway_id):
        """Маршрут client->gateway в момент t (?t_s=сек, ?strategy=hops|latency|capacity).
        При отсутствии пути возвращает причину из classify_no_path."""
        if not MODULES_AVAILABLE:
            return jsonify({"error": "Расчётные модули недоступны"}), 500
        try:
            scenario = apply_exclude(
                load(scenario_path(filename)),
                parse_exclude_arg(request.args.get("exclude")),
            )
            t_s = float(request.args.get("t_s", 0))
            strategy = request.args.get("strategy", "hops")
            if strategy not in ("hops", "latency", "capacity"):
                return (
                    jsonify(
                        {"error": "strategy должен быть hops, latency или capacity"}
                    ),
                    400,
                )
            ground_ids = {g["id"] for g in scenario["ground_sites"]}
            if client_id not in ground_ids or gateway_id not in ground_ids:
                return jsonify({"error": "Неизвестный наземный пункт"}), 400

            snap = snapshot(scenario, t_s)
            res = routing.find_path(scenario, snap, client_id, gateway_id, strategy)
            out = {
                "t_s": t_s,
                "strategy": strategy,
                "client": client_id,
                "gateway": gateway_id,
                "connected": res is not None,
            }
            if res:
                out.update(res)
            else:
                reason = routing.classify_no_path(
                    scenario, snap, t_s, client_id, gateway_id
                )
                out["reason"] = reason
                out["reason_text"] = routing.REASON_TEXT_RU.get(reason, reason)
            return jsonify(out)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": f"Ошибка маршрутизации: {e}"}), 500

    @app.route("/api/route-timeline/<path:filename>/<client_id>/<gateway_id>")
    def route_timeline(filename, client_id, gateway_id):
        """Маршрут на всём горизонте: доступность, перерывы с причинами, шаги (?strategy=, ?step_sample=)."""
        if not MODULES_AVAILABLE:
            return jsonify({"error": "Расчётные модули недоступны"}), 500
        try:
            scenario = apply_exclude(
                load(scenario_path(filename)),
                parse_exclude_arg(request.args.get("exclude")),
            )
            strategy = request.args.get("strategy", "hops")
            step_sample = int(request.args.get("step_sample", 1))
            tl = routing.compute_route_timeline(
                scenario, client_id, gateway_id, strategy
            )
            return jsonify(
                {
                    "client": client_id,
                    "gateway": gateway_id,
                    "strategy": strategy,
                    "horizon_s": scenario["environment"]["horizon_s"],
                    "step_s": scenario["environment"]["step_s"],
                    "availability": tl.availability,
                    "outage_count": tl.outage_count,
                    "max_outage_s": tl.max_outage_s,
                    "outages": tl.outages,
                    "steps": tl.steps[:: max(1, step_sample)],
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": f"Ошибка построения таймлайна: {e}"}), 500

    @app.route("/api/criticality/<path:filename>")
    def satellite_criticality(filename):
        """Наиболее уязвимые аппараты (?step_sample=6&strategy=hops)."""
        if not MODULES_AVAILABLE:
            return jsonify({"error": "Расчётные модули недоступны"}), 500
        try:
            scenario = load(scenario_path(filename))
            strategy = request.args.get("strategy", "hops")
            step_sample = max(1, int(request.args.get("step_sample", 6)))
            clients = [
                g["id"] for g in scenario["ground_sites"] if g["role"] == "client"
            ]
            gateways = [
                g["id"] for g in scenario["ground_sites"] if g["role"] == "gateway"
            ]
            hits = routing.satellite_criticality(
                scenario, clients, gateways, step_sample=step_sample, strategy=strategy
            )
            return jsonify(
                {
                    "strategy": strategy,
                    "step_sample": step_sample,
                    "criticality": [
                        {"satellite": sat, "failures_caused": n} for sat, n in hits[:15]
                    ],
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": f"Ошибка анализа уязвимости: {e}"}), 500

    @app.route("/api/availability/<path:filename>")
    def calculate_availability(filename):
        if not MODULES_AVAILABLE:
            return jsonify({"error": "Расчётные модули недоступны"}), 500
        try:
            scenario = load(scenario_path(filename))
            return jsonify(availability.scenario_availability(scenario))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": f"Ошибка расчёта доступности: {e}"}), 500

    @app.route("/api/monte-carlo/<path:filename>")
    def monte_carlo_analysis(filename):
        """?trials=100&mode=poisson|fixed_k&k=10 — вероятностная оценка рисков.
        k — число одновременных отказов для режима fixed_k."""
        if not MODULES_AVAILABLE:
            return jsonify({"error": "Расчётные модули недоступны"}), 500
        try:
            scenario = load(scenario_path(filename))
            trials = max(1, min(int(request.args.get("trials", 100)), 1000))
            mode = request.args.get("mode", "poisson")
            k_fixed = max(0, min(int(request.args.get("k", 10)), 48))
            result = monte_carlo.monte_carlo_risk(
                scenario, n_trials=trials, mode=mode, k_fixed=k_fixed
            )
            result.pop("_raw_availability", None)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": f"Ошибка Монте-Карло анализа: {e}"}), 500

    return app


if __name__ == "__main__":
    create_app().run(debug=True, host="0.0.0.0", port=5002, threaded=True)
