"""Un agente de consultas SQL sin framework, observable de punta a punta con MLflow.

    python agente.py "¿Cuántos proyectos vigentes tiene el centro?"
    python agente.py "¿Qué porcentaje de ejecución lleva la vigencia 2026?" --backend groq
    python agente.py "..." --modelo granite4:tiny-h --usuario ana

El ciclo cabe en una pantalla: el modelo propone, el código decide. Cada vuelta queda en una traza
de MLflow (agente → llamadas al modelo → herramienta), con tokens, tiempos, el SQL y las filas.
"""
import argparse
import json
import os
import re
import time

import mlflow
import openai
from mlflow.entities import SpanType

import config
import guardian

EXPERIMENTO = "agente-observable"

HERRAMIENTAS = [{
    "type": "function",
    "function": {
        "name": "ejecutar_sql",
        "description": "Ejecuta UNA consulta SELECT sobre las tablas del mapa. Devuelve JSON con ok, rows y truncated, o ok=false y error.",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
    },
}]


def preparar_mlflow() -> None:
    """Sin servidor: todo queda en mlflow.db junto al código. Con servidor: MLFLOW_TRACKING_URI en .env."""
    config.cargar_env()
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", f"sqlite:///{config.RAIZ / 'mlflow.db'}"))
    mlflow.set_experiment(os.environ.get("MLFLOW_EXPERIMENTO", EXPERIMENTO))
    mlflow.openai.autolog()          # cada llamada al modelo = un span con mensajes, tokens y tiempo


def mapa() -> str:
    capa = guardian.capa()
    partes = [f"MAPA DE LA BASE (versión {capa['version']}, corte {capa['corte']}). Lo que no está aquí no se puede leer."]
    for t, info in capa["tablas"].items():
        cols = "; ".join(f"{c}: {d}" for c, d in info["columnas"].items())
        partes.append(f"- {t}: {info['descripcion']} Columnas: {cols}")
        partes += [f"  Regla: {r}" for r in info.get("reglas", [])]
        partes += [f"  Ejemplo: {e['pregunta']} → {e['sql']}" for e in info.get("ejemplos", [])]
    partes.append("Relaciones: " + "; ".join(capa["relaciones"]))
    return "\n".join(partes)


DIALECTOS = {"sqlite": "SQLite", "sqlserver": "SQL Server (T-SQL: TOP n en lugar de LIMIT; fechas como '2026-01-01')"}


def instrucciones() -> str:
    return (config.INSTRUCCIONES.read_text(encoding="utf-8")
            .replace("{{motor}}", DIALECTOS[config.motor()]).replace("{{mapa}}", mapa()))


@mlflow.trace(span_type=SpanType.TOOL)
def ejecutar_sql(sql: str) -> dict:
    """El guardián decide: solo lectura, solo lo que está en la capa, topes de filas y tiempo."""
    return guardian.ejecutar(sql)


def _sql_de(tc) -> str:
    try:
        return json.loads(tc.function.arguments or "{}").get("sql", "")
    except (json.JSONDecodeError, AttributeError):
        return ""


def _limpiar(texto: str | None) -> str:
    return re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S).strip()


@mlflow.trace(name="agente", span_type=SpanType.AGENT)
def preguntar(pregunta: str, b: config.Backend, cli=None, usuario: str = "anonimo", al_paso=None) -> dict:
    """al_paso(evento) es opcional: la página web lo usa para mostrar cada paso mientras ocurre."""
    cli = cli or config.cliente(b)
    avisar = al_paso or (lambda e: None)
    span = mlflow.get_current_active_span()
    if span:
        # Entradas explícitas: sin esto el decorador guarda el objeto Backend entero, API key incluida.
        span.set_inputs({"pregunta": pregunta, "usuario": usuario, "modelo": b.modelo, "backend": b.nombre})
    mlflow.update_current_trace(
        tags={"backend": b.nombre, "modelo": b.modelo, "datos_salen": str(b.externo).lower(), "motor": config.motor(),
              "capa": guardian.capa()["version"]},
        metadata={"mlflow.trace.user": usuario},
    )
    mensajes = [{"role": "system", "content": instrucciones()}, {"role": "user", "content": pregunta}]
    r = {"pregunta": pregunta, "respuesta": "", "consultas": [], "llamadas": 0, "herramientas": 0,
         "tokens": {"entrada": 0, "salida": 0}, "estado": "completo", "modelo": b.modelo,
         "trace_id": span.trace_id if span else None}
    t0 = time.perf_counter()
    try:
        while True:
            if r["llamadas"] >= config.MAX_LLAMADAS_MODELO:
                r["estado"], r["respuesta"] = "tope", "Detuve la consulta: llegó al tope de llamadas al modelo."
                break
            avisar({"tipo": "modelo_inicio", "n": r["llamadas"] + 1, "t": round(time.perf_counter() - t0, 2)})
            t1 = time.perf_counter()
            resp = cli.chat.completions.create(model=b.modelo, messages=mensajes, tools=HERRAMIENTAS,
                                               temperature=0, max_tokens=config.MAX_TOKENS_SALIDA)
            r["llamadas"] += 1
            u = resp.usage
            avisar({"tipo": "modelo", "n": r["llamadas"], "seg": round(time.perf_counter() - t1, 2),
                    "t": round(t1 - t0, 2), "entrada": getattr(u, "prompt_tokens", 0) or 0,
                    "salida": getattr(u, "completion_tokens", 0) or 0,
                    "pide": [_sql_de(tc) for tc in resp.choices[0].message.tool_calls or []],
                    "texto": _limpiar(resp.choices[0].message.content)[:600]})
            if resp.usage:
                r["tokens"]["entrada"] += resp.usage.prompt_tokens or 0
                r["tokens"]["salida"] += resp.usage.completion_tokens or 0
            msg = resp.choices[0].message
            if resp.choices[0].finish_reason == "length":
                r["estado"], r["respuesta"] = "tope_tokens", "El modelo agotó los tokens de salida antes de responder."
                break
            if not msg.tool_calls:
                r["respuesta"] = _limpiar(msg.content) or "(el modelo no devolvió texto)"
                break
            mensajes.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                if r["herramientas"] >= config.MAX_HERRAMIENTAS:
                    salida = {"ok": False, "error": "TOPE: no se ejecutan más consultas."}
                else:
                    r["herramientas"] += 1
                    sql = _sql_de(tc)
                    t1 = time.perf_counter()
                    salida = ejecutar_sql(sql)
                    r["consultas"].append({"sql": sql, **salida})
                    avisar({"tipo": "sql", "sql": sql, "seg": round(time.perf_counter() - t1, 2), "t": round(t1 - t0, 2),
                            **{k: salida.get(k) for k in ("ok", "rows", "error", "truncated")}})
                mensajes.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(salida, ensure_ascii=False, default=str)})
    except openai.RateLimitError:
        r["estado"], r["respuesta"] = "429", "Cuota por minuto agotada en el proveedor. Espere un minuto y repita."
    except openai.APIConnectionError:
        r["estado"], r["respuesta"] = "sin_conexion", f"No hay servidor de modelo en {b.base_url}."
    except openai.APIError as e:
        r["estado"], r["respuesta"] = "error", f"{type(e).__name__}: {str(e)[:160]}"
    r["segundos"] = round(time.perf_counter() - t0, 1)
    return r


def imprimir(r: dict) -> None:
    print(f"\nRESPUESTA\n{r['respuesta']}\n")
    for c in r["consultas"]:
        print(f"SQL  {c['sql']}")
        print(f"     {json.dumps(c.get('rows') or c.get('error'), ensure_ascii=False, default=str)[:300]}")
    print(f"\n· {r['estado']} · {r['segundos']} s · {r['llamadas']} llamadas al modelo · "
          f"{r['herramientas']} consultas · tokens {r['tokens']['entrada']}+{r['tokens']['salida']} · {r['modelo']}")
    if r["trace_id"]:
        print(f"· traza {r['trace_id']}")
        print(f"  opinar:  python opinar.py {r['trace_id']} bien \"comentario\"")


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("pregunta")
    a.add_argument("--backend", choices=("local", "groq"))
    a.add_argument("--modelo")
    a.add_argument("--usuario", default=os.environ.get("USER", "anonimo"))
    x = a.parse_args()
    preparar_mlflow()
    b = config.backend(x.backend, x.modelo)
    if b.externo:
        print(f"⚠ {b.nombre}: las filas que devuelva la base viajan a un servidor externo. Solo datos sintéticos.")
    imprimir(preguntar(x.pregunta, b, usuario=x.usuario))


if __name__ == "__main__":
    main()
