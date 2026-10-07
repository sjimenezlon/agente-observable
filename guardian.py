"""El guardián del SQL: la base dice qué se puede leer, no el prompt.

La lista blanca sale de la capa semántica (datos/capa_semantica.json):
conexión de solo lectura, una sola sentencia SELECT/WITH, solo tablas y columnas descritas,
funciones seguras, límite de filas y de tiempo.
"""
import json
import re
import sqlite3
import time
from contextlib import closing

from config import BASE, CAPA

FUNCIONES = frozenset("count sum total avg min max coalesce ifnull nullif round abs date datetime julianday "
                      "strftime substr lower upper trim length like instr replace cast".split())
TIMEOUT = 2.0
MAX_SQL = 4000


def capa() -> dict:
    return json.loads(CAPA.read_text(encoding="utf-8"))


def lista_blanca() -> dict[str, set]:
    return {t: set(info["columnas"]) for t, info in capa()["tablas"].items()}


def ejecutar(sql: str, base=BASE) -> dict:
    permitido, limite = lista_blanca(), capa().get("limite_filas", 50)
    if not isinstance(sql, str) or not sql.strip() or len(sql) > MAX_SQL:
        return {"ok": False, "error": "SQL_INVALIDO: vacía o demasiado larga."}
    cuerpo = re.sub(r"\A(?:\s+|--[^\n]*(?:\n|$)|/\*.*?\*/)*", "", sql, flags=re.S)
    if not re.match(r"(SELECT|WITH)\b", cuerpo, re.I):
        return {"ok": False, "error": "SQL_DENEGADO: solo SELECT o WITH de lectura."}
    negado, t0, vencido = [], time.perf_counter(), False

    def autorizar(accion, a, b, base_datos, disparador):
        if accion == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if accion == sqlite3.SQLITE_READ:
            if a in permitido and (not b or b in permitido[a]):
                return sqlite3.SQLITE_OK
            if base_datos is None and not b:      # columnas de subconsultas y CTE
                return sqlite3.SQLITE_OK
        if accion == sqlite3.SQLITE_FUNCTION and (b or "").lower() in FUNCIONES:
            return sqlite3.SQLITE_OK
        negado.append(f"{a}.{b}" if a and b else (a or b or str(accion)))
        return sqlite3.SQLITE_DENY

    def cancelar():
        nonlocal vencido
        vencido = time.perf_counter() - t0 > TIMEOUT
        return int(vencido)

    try:
        with closing(sqlite3.connect(base.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)) as db:
            db.execute("PRAGMA query_only = ON")
            db.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
            db.set_authorizer(autorizar)
            db.set_progress_handler(cancelar, 200)
            cur = db.execute(sql)
            cols = [c[0] for c in cur.description]
            filas = cur.fetchmany(limite + 1)
            return {"ok": True, "rows": [dict(zip(cols, f)) for f in filas[:limite]], "truncated": len(filas) > limite}
    except sqlite3.Error as e:
        if vencido:
            return {"ok": False, "error": "SQL_TIMEOUT: consulta cancelada."}
        if negado:
            return {"ok": False, "error": f"SQL_DENEGADO: recurso no permitido {negado[0]}."}
        return {"ok": False, "error": f"SQL_INVALIDO: {e}"}
