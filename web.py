"""El agente en el navegador: pregunte, mire la traza en vivo, opine y pruebe el guardián.

    python web.py                 → http://127.0.0.1:8070
    python web.py --puerto 8071

Sin dependencias nuevas (servidor de la biblioteca estándar). Todo queda en el mismo MLflow del
ejercicio (mlflow.db): abra en otra terminal  mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5070
"""
import os
os.environ.setdefault("MLFLOW_LOGGING_LEVEL", "WARNING")   # sin líneas INFO de MLflow en la terminal
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import argparse
import json
import os
import threading
import time
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import mlflow
from mlflow.entities import AssessmentSource, AssessmentSourceType

import config
import guardian
from agente import EXPERIMENTO, preguntar, preparar_mlflow

PAGINA = Path(__file__).resolve().parent / "web" / "index.html"
MLFLOW_UI = os.environ.get("MLFLOW_UI", "http://127.0.0.1:5070")
TRABAJOS: dict[str, dict] = {}
UNO_A_LA_VEZ = threading.Lock()          # un modelo local atiende de a una pregunta


def modelos_locales(b) -> list[str]:
    try:
        with urllib.request.urlopen(b.base_url.rstrip("/") + "/models", timeout=3) as r:
            # los modelos «-cloud» de Ollama corren en servidores externos: no se ofrecen aquí
            return sorted(m["id"] for m in json.load(r).get("data", []) if "cloud" not in m["id"])
    except OSError:
        return []


def estado() -> dict:
    config.cargar_env()
    b = config.backend()
    exp = mlflow.get_experiment_by_name(EXPERIMENTO)
    try:
        urllib.request.urlopen(MLFLOW_UI, timeout=2)
        mlflow_vivo = True
    except OSError:
        mlflow_vivo = False
    preguntas = json.loads(config.PREGUNTAS.read_text(encoding="utf-8"))["preguntas"]
    return {
        "backend": b.nombre, "modelo": b.modelo, "modelos": modelos_locales(b) if b.nombre == "local" else [b.modelo],
        "motor": config.motor(), "hay_compartida": bool(os.environ.get("SQLSERVER_PASSWORD")),
        "servidor": os.environ.get("SQLSERVER_HOST", ""), "mlflow": MLFLOW_UI, "mlflow_vivo": mlflow_vivo,
        "experimento": exp.experiment_id if exp else None, "capa": guardian.capa()["version"],
        "preguntas": [{"id": p["id"], "tipo": p["tipo"], "pregunta": p["pregunta"]} for p in preguntas],
        "usuario": os.environ.get("USER") or os.environ.get("USERNAME") or "persona",
    }


def con_motor(motor: str):
    """Elige la base para esta pregunta (local o compartida)."""
    os.environ["DB_MOTOR"] = "sqlserver" if motor == "sqlserver" else "sqlite"


def trabajo_pregunta(tid: str, datos: dict):
    t = TRABAJOS[tid]
    with UNO_A_LA_VEZ:
        try:
            con_motor(datos.get("motor", "sqlite"))
            b = config.backend(None, datos.get("modelo") or None)
            t["eventos"].append({"tipo": "inicio", "modelo": b.modelo, "motor": config.motor(), "externo": b.externo})
            r = preguntar(datos["pregunta"], b, usuario=datos.get("usuario") or "web", al_paso=t["eventos"].append)
            mlflow.flush_trace_async_logging()
            t["resultado"] = r
        except SystemExit as e:
            t["error"] = str(e)
        except Exception as e:                    # se muestra en la página, no se esconde
            t["error"] = f"{type(e).__name__}: {e}"
        t["fin"] = True


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _json(self, datos, codigo=200):
        cuerpo = json.dumps(datos, ensure_ascii=False, default=str).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _leer(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            cuerpo = PAGINA.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
        elif self.path == "/api/estado":
            self._json(estado())
        elif self.path.startswith("/api/trabajo/"):
            t = TRABAJOS.get(self.path.rsplit("/", 1)[-1])
            self._json(t or {"error": "no existe"}, 200 if t else 404)
        else:
            self._json({"error": "no existe"}, 404)

    def do_POST(self):
        datos = self._leer()
        if self.path == "/api/preguntar":
            if not (datos.get("pregunta") or "").strip():
                return self._json({"error": "Escriba una pregunta"}, 400)
            tid = uuid.uuid4().hex[:10]
            TRABAJOS[tid] = {"eventos": [], "fin": False, "resultado": None, "error": None, "inicio": time.time()}
            threading.Thread(target=trabajo_pregunta, args=(tid, datos), daemon=True).start()
            self._json({"id": tid, "en_cola": UNO_A_LA_VEZ.locked()})
        elif self.path == "/api/opinar":
            try:
                mlflow.log_feedback(trace_id=datos["trace_id"], name="opinion_humana", value=bool(datos["bien"]),
                                    rationale=datos.get("comentario") or None,
                                    source=AssessmentSource(source_type=AssessmentSourceType.HUMAN,
                                                            source_id=datos.get("quien") or "web"))
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/guardian":
            con_motor(datos.get("motor", "sqlite"))
            self._json(guardian.ejecutar(datos.get("sql", "")))
        else:
            self._json({"error": "no existe"}, 404)


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--puerto", type=int, default=8070)
    a.add_argument("--sin-abrir", action="store_true", help="No abrir el navegador")
    x = a.parse_args()
    preparar_mlflow()
    if not config.BASE.exists():
        import crear_base
        crear_base.crear()
    url = f"http://127.0.0.1:{x.puerto}"
    print(f"\nAgente observable en el navegador → {url}\nMLflow del ejercicio → {MLFLOW_UI}\n(Ctrl+C para cerrar)\n")
    if not x.sin_abrir:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    ThreadingHTTPServer(("127.0.0.1", x.puerto), Manejador).serve_forever()


if __name__ == "__main__":
    main()
