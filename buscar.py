"""Buscar en la bitácora de MLflow desde la terminal: qué se preguntó, quién, con qué modelo, cómo salió.

    python buscar.py                          → las últimas 15 preguntas
    python buscar.py --texto anulados         → las que mencionan «anulados»
    python buscar.py --modelo llama3.2:3b     → solo las de ese modelo
    python buscar.py --usuario ana            → solo las de esa persona
    python buscar.py --motor sqlserver        → solo las que fueron a la base compartida
    python buscar.py --malas                  → las que alguien marcó 👎 o que un calificador reprobó
    python buscar.py --lentas 20              → las que tardaron más de 20 segundos
    python buscar.py tr-1a2b3c...             → el detalle de una traza: cada paso, el SQL, las filas, las opiniones

Es lo mismo que la pestaña Traces de MLflow, pero escrito: así se ve que la bitácora es una base
que se consulta, no solo una página bonita. Cada búsqueda imprime el filtro que usó.
"""
import os
os.environ.setdefault("MLFLOW_LOGGING_LEVEL", "WARNING")   # sin líneas INFO de MLflow en la terminal
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import argparse
import json
from datetime import datetime

import mlflow

from agente import preparar_mlflow


def raiz(t):
    return next((s for s in t.data.spans if s.parent_id is None), None)


def opiniones(t) -> list:
    return [a for a in t.info.assessments if a.value is not None and a.name not in ("id", "tipo")]


def es_mala(t) -> bool:
    return any(a.value is False for a in opiniones(t))


def corto(texto, n) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def listar(x) -> None:
    filtros = []
    if x.modelo:
        filtros.append(f"tags.modelo = '{x.modelo}'")
    if x.motor:
        filtros.append(f"tags.motor = '{x.motor}'")
    if x.usuario:
        filtros.append(f"metadata.`mlflow.trace.user` = '{x.usuario}'")
    filtro = " AND ".join(filtros) or None
    print(f"\n  Filtro en MLflow: {filtro or '(ninguno: todas las trazas)'}"
          + (f"   ·   y en la pregunta: «{x.texto}»" if x.texto else "")
          + ("   ·   solo malas" if x.malas else "") + (f"   ·   más de {x.lentas} s" if x.lentas else ""))
    trazas = mlflow.search_traces(filter_string=filtro, order_by=["timestamp_ms DESC"],
                                  max_results=1000, return_type="list")
    filas = []
    for t in trazas:
        r = raiz(t)
        if r is None or r.name != "agente":
            continue
        e, o = r.inputs or {}, r.outputs or {}
        pregunta = e.get("pregunta") or o.get("pregunta") or ""
        seg = (t.info.execution_duration or 0) / 1000
        if x.texto and x.texto.lower() not in pregunta.lower():
            continue
        if x.malas and not es_mala(t):
            continue
        if x.lentas and seg < x.lentas:
            continue
        tok = o.get("tokens") or {}
        op = opiniones(t)
        humana = next((a for a in op if a.source.source_type == "HUMAN"), None)
        filas.append((datetime.fromtimestamp(t.info.request_time / 1000).strftime("%m-%d %H:%M"),
                      corto(t.info.trace_metadata.get("mlflow.trace.user", "?"), 11),
                      corto(t.info.tags.get("modelo", "?"), 17),
                      "compartida" if t.info.tags.get("motor") == "sqlserver" else "local",
                      o.get("estado", t.info.state), f"{seg:5.1f}",
                      str(tok.get("entrada", 0) + tok.get("salida", 0)),
                      ("👎" if humana.value is False else "👍") if humana else ("✗" if es_mala(t) else ("✓" if op else "·")),
                      corto(pregunta, 52), t.info.trace_id))
    total = len(filas)
    filas = filas[: x.n]
    print(f"  {total} trazas encontradas" + (f" (se muestran {len(filas)}; use -n para ver más)" if total > len(filas) else "") + "\n")
    if not filas:
        return
    cab = ("cuándo", "quién", "modelo", "base", "estado", "seg", "tokens", "op", "pregunta", "traza")
    anchos = [max(len(cab[i]), *(len(f[i]) for f in filas)) for i in range(len(cab))]
    print("  " + "  ".join(c.ljust(anchos[i]) for i, c in enumerate(cab)))
    print("  " + "  ".join("─" * a for a in anchos))
    for f in filas:
        print("  " + "  ".join(c.ljust(anchos[i]) for i, c in enumerate(f)))
    print("\n  op: 👍/👎 opinión de una persona · ✓/✗ calificadores automáticos · · sin evaluar"
          f"\n  Detalle de una:  python buscar.py {filas[0][-1]}\n")


def detalle(trace_id: str) -> None:
    t = mlflow.get_trace(trace_id)
    if t is None:
        raise SystemExit(f"No hay una traza {trace_id} en esta bitácora.")
    r = raiz(t)
    e, o = r.inputs or {}, r.outputs or {}
    print(f"\n  TRAZA {trace_id}")
    print(f"  Pregunta : {e.get('pregunta')}")
    print(f"  Quién    : {t.info.trace_metadata.get('mlflow.trace.user')} · modelo {t.info.tags.get('modelo')} · "
          f"base {t.info.tags.get('motor')} · capa {t.info.tags.get('capa')} · ¿datos salen? {t.info.tags.get('datos_salen')}")
    print(f"  Resultado: {o.get('estado')} en {(t.info.execution_duration or 0) / 1000:.1f} s\n")
    print("  PASO A PASO (lo que pasó por dentro)")
    t0 = r.start_time_ns
    nivel = {r.span_id: 0}
    for s in sorted(t.data.spans, key=lambda s: s.start_time_ns):
        nivel[s.span_id] = 0 if s.parent_id is None else nivel.get(s.parent_id, 0) + 1
        sangria = "  " + "   " * nivel[s.span_id]
        cuando = f"+{(s.start_time_ns - t0) / 1e9:5.1f}s  {(s.end_time_ns - s.start_time_ns) / 1e9:5.1f}s"
        if s.span_type == "CHAT_MODEL":
            u = s.attributes.get("mlflow.chat.tokenUsage") or {}
            msg = (s.outputs or {}).get("choices", [{}])[0].get("message", {}) if isinstance(s.outputs, dict) else {}
            pide = [tc["function"]["arguments"] for tc in msg.get("tool_calls") or []]
            print(f"{sangria}🧠 modelo   {cuando}  ({u.get('input_tokens', 0)} + {u.get('output_tokens', 0)} tokens)"
                  + (f"  → pide SQL" if pide else "  → responde"))
        elif s.span_type == "TOOL":
            sal = s.outputs or {}
            print(f"{sangria}🛡  guardián {cuando}  {corto(s.inputs.get('sql'), 90)}")
            res = f"{len(sal.get('rows') or [])} filas: {corto(json.dumps(sal.get('rows'), ensure_ascii=False, default=str), 80)}" \
                if sal.get("ok") else f"NEGADO: {corto(sal.get('error'), 80)}"
            print(f"{sangria}             {res}")
        else:
            print(f"{sangria}🤖 {s.name}   {cuando}")
    print("\n  RESPUESTA\n  " + "\n  ".join(str(o.get("respuesta") or "").strip().splitlines()) + "\n")
    op = opiniones(t)
    if op:
        print("  EVALUACIONES")
        for a in op:
            quien = "persona" if a.source.source_type == "HUMAN" else "código"
            print(f"  {'✓' if a.value else '✗'} {a.name:24} ({quien}: {a.source.source_id}) {corto(a.rationale, 70)}")
    else:
        print(f"  Sin evaluaciones. Opine:  python opinar.py {trace_id} bien \"comentario\"")
    print()


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("trace_id", nargs="?", help="Ver el detalle de una traza")
    a.add_argument("--texto", help="Palabra que aparece en la pregunta")
    a.add_argument("--modelo")
    a.add_argument("--usuario")
    a.add_argument("--motor", choices=("sqlite", "sqlserver"))
    a.add_argument("--malas", action="store_true", help="Solo las reprobadas (persona o calificador)")
    a.add_argument("--lentas", type=float, help="Solo las que tardaron más de estos segundos")
    a.add_argument("-n", type=int, default=15, help="Cuántas mostrar (15)")
    x = a.parse_args()
    preparar_mlflow()
    detalle(x.trace_id) if x.trace_id else listar(x)


if __name__ == "__main__":
    main()
