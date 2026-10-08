"""Exporta las corridas de evaluación y sus trazas a un JSON liviano (para un tablero o una lección).

    python exportar.py --salida resultados.json
    python exportar.py --salida resultados.json --traza-de P05

Lee la base de MLflow: parámetros y métricas de cada corrida, la respuesta y los veredictos de cada
pregunta, y el árbol de tramos de una pregunta por corrida (para dibujar la traza).
"""
import os
os.environ.setdefault("MLFLOW_LOGGING_LEVEL", "WARNING")   # sin líneas INFO de MLflow en la terminal
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import argparse
import json
import platform
from datetime import date

import mlflow

from agente import EXPERIMENTO, preparar_mlflow

CALIFICADORES = ("cifra_correcta", "admite_el_limite", "base_intacta", "sin_datos_personales",
                 "no_revela_instrucciones", "termino")


def raiz(t):
    return next(s for s in t.data.spans if s.parent_id is None)


def resumen_llamada(s) -> tuple[str, str, str]:
    msgs = s.inputs.get("messages", [])
    sistema = next((m for m in msgs if m.get("role") == "system"), None)
    ultimo = msgs[-1] if msgs else {}
    entrada = f"{len(msgs)} mensajes · instrucciones + mapa: {len(sistema['content']) if sistema else 0} caracteres\n"
    entrada += f"último ({ultimo.get('role')}): {str(ultimo.get('content'))[:500]}"
    msg = (s.outputs or {}).get("choices", [{}])[0].get("message", {}) if isinstance(s.outputs, dict) else {}
    partes = []
    if msg.get("reasoning"):
        partes.append(f"[piensa {len(msg['reasoning'])} caracteres] {msg['reasoning'][:420]}…")
    for tc in msg.get("tool_calls") or []:
        partes.append(f"pide {tc['function']['name']}: {tc['function']['arguments'][:500]}")
    if msg.get("content"):
        partes.append(msg["content"][:600])
    u = s.attributes.get("mlflow.chat.tokenUsage") or {}
    return entrada, "\n".join(partes) or "(vacío)", f"{u.get('input_tokens', 0)} + {u.get('output_tokens', 0)} tokens"


def arbol(t) -> dict:
    spans = sorted(t.data.spans, key=lambda s: s.start_time_ns)
    r = raiz(t)
    t0 = r.start_time_ns
    nivel = {r.span_id: 0}
    out = []
    for s in spans:
        nivel[s.span_id] = 0 if s.parent_id is None else nivel.get(s.parent_id, 0) + 1
        item = {"nombre": s.name, "tipo": str(s.span_type), "inicio": round((s.start_time_ns - t0) / 1e9, 2),
                "dur": round((s.end_time_ns - s.start_time_ns) / 1e9, 2), "nivel": nivel[s.span_id]}
        if s.span_type == "CHAT_MODEL":
            item["entrada"], item["salida"], item["tokens"] = resumen_llamada(s)
        elif s.span_type == "TOOL":
            item["entrada"] = s.inputs.get("sql", "")
            item["salida"] = json.dumps(s.outputs, ensure_ascii=False, default=str)[:700]
        else:
            item["entrada"] = s.inputs.get("pregunta", "")
            item["salida"] = (s.outputs or {}).get("respuesta", "")
        out.append(item)
    salida = r.outputs or {}
    tok = salida.get("tokens", {})
    return {"trace_id": t.info.trace_id, "modelo": salida.get("modelo"), "pregunta": salida.get("pregunta"),
            "total": round((r.end_time_ns - r.start_time_ns) / 1e9, 1), "tokens_entrada": tok.get("entrada", 0),
            "tokens_salida": tok.get("salida", 0), "spans": out}


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--salida", default="resultados.json")
    a.add_argument("--traza-de", default="P05", help="Id de la pregunta cuya traza se exporta completa")
    x = a.parse_args()
    preparar_mlflow()
    exp = mlflow.get_experiment_by_name(EXPERIMENTO)
    runs = mlflow.search_runs([exp.experiment_id], order_by=["start_time ASC"], output_format="list")
    corridas, trazas = [], []
    for run in runs:
        p, m = run.data.params, run.data.metrics
        if "modelo" not in p:
            continue
        filas = []
        for t in mlflow.search_traces(run_id=run.info.run_id, return_type="list"):
            r = raiz(t)
            o = r.outputs or {}
            esp = {a.name: a.value for a in t.info.assessments if a.name in ("id", "tipo")}
            ver = {a.name: {"v": bool(a.value), "r": a.rationale or ""} for a in t.info.assessments
                   if a.name in CALIFICADORES and a.value is not None}
            fila = {"id": esp.get("id"), "tipo": esp.get("tipo"), "pregunta": o.get("pregunta"),
                    "respuesta": o.get("respuesta"), "estado": o.get("estado"), "segundos": o.get("segundos"),
                    "tokens": o.get("tokens", {}).get("entrada", 0) + o.get("tokens", {}).get("salida", 0),
                    "llamadas": o.get("llamadas"),
                    "consultas": [{"sql": c.get("sql"), "ok": c.get("ok"), "rows": (c.get("rows") or [])[:6],
                                   "error": c.get("error")} for c in o.get("consultas", [])],
                    "veredictos": ver}
            if fila["id"]:
                filas.append(fila)
            if fila["id"] == x.traza_de and "sin-reglas" not in p.get("capa", ""):
                trazas.append(arbol(t))
        filas.sort(key=lambda f: ({"P": 0, "R": 1, "A": 2}.get(f["id"][0], 3), f["id"]))
        corridas.append({"run_id": run.info.run_id, "modelo": p["modelo"], "capa": p.get("capa"),
                         "instrucciones": p.get("instrucciones"),
                         "tasas": {k[:-5]: round(v, 3) for k, v in m.items() if k.endswith("/mean")},
                         "tokens_por_pregunta": int(m.get("tokens_por_pregunta", 0)),
                         "segundos_por_pregunta": m.get("segundos_por_pregunta", 0), "filas": filas})
    datos = {"fecha": date.today().isoformat(),
             "entorno": f"{platform.machine()} · {platform.system()} · MLflow {mlflow.__version__} · modelos locales en Ollama",
             "corridas": corridas, "trazas": trazas}
    with open(x.salida, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1, default=str)
    print(f"{len(corridas)} corridas · {sum(len(c['filas']) for c in corridas)} preguntas · {len(trazas)} trazas → {x.salida}")


if __name__ == "__main__":
    main()
