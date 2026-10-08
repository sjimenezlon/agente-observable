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

import config
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
    if config.motor() == "sqlserver":
        return ejecutar_sqlserver(sql)
    return ejecutar_sqlite(sql, base)


def ejecutar_sqlite(sql: str, base=BASE) -> dict:
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


# ── SQL Server ──────────────────────────────────────────────────────────
# Aquí el control principal es el SERVIDOR: el usuario solo tiene permiso de leer las columnas de la
# capa (ver cargar_sqlserver.py). El código añade lo que el servidor no sabe: una sola sentencia de
# lectura, solo tablas de la capa, filas y tiempo limitados.
PROHIBIDAS = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|GRANT|REVOKE|DENY|"
                        r"INTO|OPENROWSET|OPENQUERY|OPENDATASOURCE|BULK|SHUTDOWN|DBCC|xp_\w+|sp_\w+)\b", re.I)


def ejecutar_sqlserver(sql: str) -> dict:
    import pymssql
    permitido, limite = lista_blanca(), capa().get("limite_filas", 50)
    if not isinstance(sql, str) or not sql.strip() or len(sql) > MAX_SQL:
        return {"ok": False, "error": "SQL_INVALIDO: vacía o demasiado larga."}
    cuerpo = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";").strip()
    if not re.match(r"(SELECT|WITH)\b", cuerpo, re.I):
        return {"ok": False, "error": "SQL_DENEGADO: solo SELECT o WITH de lectura."}
    if ";" in cuerpo:
        return {"ok": False, "error": "SQL_INVALIDO: una sola sentencia."}
    if m := PROHIBIDAS.search(cuerpo):
        return {"ok": False, "error": f"SQL_DENEGADO: {m.group(0).upper()} no está permitido."}
    ctes = {c.lower() for c in re.findall(r"(\w+)\s+AS\s*\(", cuerpo, re.I)}
    for t in re.findall(r"\b(?:FROM|JOIN)\s+((?:\[?\w+\]?\.)?\[?\w+\]?)", cuerpo, re.I):
        nombre = t.split(".")[-1].strip("[]").lower()
        if nombre not in permitido and nombre not in ctes:
            return {"ok": False, "error": f"SQL_DENEGADO: recurso no permitido {nombre}."}
    try:
        with pymssql.connect(**config.sqlserver(), login_timeout=60, timeout=int(TIMEOUT * 5)) as db:
            cur = db.cursor()
            cur.execute(cuerpo)
            cols = [c[0] or f"col{i + 1}" for i, c in enumerate(cur.description)]   # COUNT(*) sin alias
            filas = cur.fetchmany(limite + 1)
            limpias = [{k: (float(v) if type(v).__name__ == "Decimal" else v) for k, v in zip(cols, f)}
                       for f in filas[:limite]]
            return {"ok": True, "rows": limpias, "truncated": len(filas) > limite}
    except pymssql.Error as e:
        msg = str(e.args[1] if len(e.args) > 1 else e)
        msg = msg.split("DB-Lib error")[0].replace("b\"", "").replace("b'", "").strip(" .\"'")
        if "40613" in msg or "not currently available" in msg or "Adaptive Server connection failed" in msg:
            return {"ok": False, "error": "BASE_DORMIDA: la base compartida se está despertando (se duerme tras una hora "
                                          "sin uso) o no hay conexión. Repita en un minuto."}
        if "Login failed" in msg:
            return {"ok": False, "error": "SQL_LOGIN: el servidor rechazó el usuario o la clave. Revise SQLSERVER_USER y "
                                          "SQLSERVER_PASSWORD en .env (sin comillas ni espacios) y guarde el archivo."}
        if "permission was denied" in msg:
            return {"ok": False, "error": f"SQL_DENEGADO por el servidor: {msg[:160]}"}
        return {"ok": False, "error": f"SQL_INVALIDO: {msg[:200]}"}


def huella() -> list:
    """Conteo y suma de identificadores por tabla de la capa: si algo se escribió, cambia."""
    claves = {"dependencias": "id_dependencia", "lineas": "id_linea", "proyectos": "LEN(id_proyecto)",
              "contratos": "LEN(id_contrato)", "desembolsos": "id_desembolso"}
    out = []
    for t, k in claves.items():
        r = ejecutar(f"SELECT COUNT(*) AS n, SUM({k}) AS s FROM {t}")
        out.append(tuple(r.get("rows", [{}])[0].values()) if r["ok"] else r["error"])
    return out
