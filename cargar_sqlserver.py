"""Lleva la base sintética a un SQL Server (Azure SQL, uno local en Docker o el del aula) y crea
un usuario de SOLO LECTURA que no puede ver los datos personales.

    python cargar_sqlserver.py --servidor mi-servidor.database.windows.net --base aurora \
        --admin aurora_admin --clave-estudiante "..."

La clave del administrador se pide por teclado (o SQL_ADMIN_PASSWORD). El permiso lo pone el
servidor, no el código: el usuario `estudiante` solo puede leer las columnas de la capa semántica.
La tabla `contratistas` existe, pero para ese usuario es como si no existiera.

SQL Server en Docker, para practicar sin nube:
    docker run -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD='Clave-Larga-2026' -p 1433:1433 \
        -d mcr.microsoft.com/mssql/server:2022-latest
    python cargar_sqlserver.py --servidor localhost --admin sa --base aurora --crear-base
"""
import argparse
import getpass
import json
import os
import sqlite3

import pymssql

import config
import crear_base

ESQUEMA = """
CREATE TABLE dependencias(id_dependencia INT PRIMARY KEY, nombre NVARCHAR(120));
CREATE TABLE lineas(id_linea INT PRIMARY KEY, nombre NVARCHAR(120), id_dependencia INT REFERENCES dependencias);
CREATE TABLE proyectos(id_proyecto VARCHAR(12) PRIMARY KEY, nombre NVARCHAR(200), id_linea INT REFERENCES lineas,
    fecha_inicio DATE, fecha_fin_prevista DATE, estado CHAR(1));
CREATE TABLE contratistas(id_contratista INT PRIMARY KEY, nombre NVARCHAR(120), documento VARCHAR(20), cuenta_bancaria VARCHAR(20));
CREATE TABLE contratos(id_contrato VARCHAR(16) PRIMARY KEY, id_proyecto VARCHAR(12) REFERENCES proyectos,
    id_contratista INT REFERENCES contratistas, objeto NVARCHAR(200), vigencia INT, fecha_firma DATE, valor_total BIGINT);
CREATE TABLE desembolsos(id_desembolso INT PRIMARY KEY, id_contrato VARCHAR(16) REFERENCES contratos,
    fecha DATE, valor BIGINT, anulado BIT);
"""
ORDEN = ["dependencias", "lineas", "proyectos", "contratistas", "contratos", "desembolsos"]


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--servidor", required=True)
    a.add_argument("--puerto", type=int, default=1433)
    a.add_argument("--base", default="aurora")
    a.add_argument("--admin", required=True)
    a.add_argument("--estudiante", default="estudiante")
    a.add_argument("--clave-estudiante", default=os.environ.get("SQL_ESTUDIANTE_PASSWORD"))
    a.add_argument("--crear-base", action="store_true", help="CREATE DATABASE primero (SQL Server local, no Azure)")
    x = a.parse_args()
    clave = os.environ.get("SQL_ADMIN_PASSWORD") or getpass.getpass(f"Clave de {x.admin}: ")
    if not x.clave_estudiante:
        raise SystemExit("Falta --clave-estudiante (la que compartirá con el grupo)")
    if not config.BASE.exists():
        crear_base.crear()

    if x.crear_base:
        with pymssql.connect(x.servidor, x.admin, clave, "master", port=x.puerto, autocommit=True) as c:
            c.cursor().execute(f"IF DB_ID('{x.base}') IS NULL CREATE DATABASE [{x.base}]")

    capa = json.loads(config.CAPA.read_text(encoding="utf-8"))
    origen = sqlite3.connect(config.BASE)
    with pymssql.connect(x.servidor, x.admin, clave, x.base, port=x.puerto, login_timeout=60) as c:
        cur = c.cursor()
        for t in reversed(ORDEN):
            cur.execute(f"IF OBJECT_ID('dbo.{t}') IS NOT NULL DROP TABLE dbo.{t}")
        for sentencia in filter(str.strip, ESQUEMA.split(";")):
            cur.execute(sentencia)
        for t in ORDEN:
            filas = origen.execute(f"SELECT * FROM {t}").fetchall()
            marcas = ",".join(["%s"] * len(filas[0]))
            cur.executemany(f"INSERT INTO dbo.{t} VALUES ({marcas})", filas)
            print(f"  {t:<14} {len(filas):>4} filas")
        c.commit()

        # Usuario contenido en la base (Azure SQL lo permite sin login de servidor).
        u, k = x.estudiante, x.clave_estudiante.replace("'", "''")
        cur.execute(f"IF USER_ID('{u}') IS NULL CREATE USER [{u}] WITH PASSWORD = '{k}' "
                    f"ELSE ALTER USER [{u}] WITH PASSWORD = '{k}'")
        for t, info in capa["tablas"].items():                       # solo lo que está en la capa
            cols = ", ".join(info["columnas"])
            cur.execute(f"GRANT SELECT ON dbo.{t} ({cols}) TO [{u}]")
        cur.execute(f"DENY SELECT ON dbo.contratistas TO [{u}]")
        c.commit()

        resumen = {t: cur.execute(f"SELECT COUNT(*) FROM dbo.{t}") or cur.fetchone()[0] for t in ORDEN}
    print(f"\nListo: {x.servidor}/{x.base} · {resumen}")
    print(f"Usuario de solo lectura: {u} (puede leer {len(capa['tablas'])} tablas de la capa; contratistas denegada)")


if __name__ == "__main__":
    main()
