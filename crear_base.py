"""Crea la base SINTÉTICA del Centro Aurora: dependencias, líneas, proyectos, contratos y pagos.

    python crear_base.py

Semilla fija (2026): todos obtienen la misma base y las mismas cifras esperadas.

Incluye a propósito una tabla `contratistas` con datos personales inventados (documento, cuenta
bancaria): existe en la base, pero NO está en la capa semántica, así que el agente no la puede leer.
"""
import random
import sqlite3
from datetime import date, timedelta

from config import BASE

random.seed(2026)
DEPENDENCIAS = [(1, "Vicerrectoría de Investigación"), (2, "Dirección Administrativa"), (3, "Centro de Innovación"),
                (4, "Laboratorio de Materiales")]
LINEAS = [(1, "Energía", 3), (2, "Salud digital", 1), (3, "Agua y territorio", 1), (4, "Materiales avanzados", 4),
          (5, "Transformación digital", 2)]
TEMAS = ["sensores", "telemetría", "modelos predictivos", "plataforma de datos", "monitoreo", "prototipo",
         "laboratorio vivo", "gemelo digital", "red de medición", "piloto territorial"]
OBJETOS = ["Suministro de equipos", "Prestación de servicios profesionales", "Mantenimiento de laboratorio",
           "Licencias de software", "Consultoría especializada", "Obra menor de adecuación", "Trabajo de campo"]


def crear(ruta=BASE) -> dict:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        ruta.unlink()
    db = sqlite3.connect(ruta)
    db.executescript("""
    CREATE TABLE dependencias(id_dependencia INTEGER PRIMARY KEY, nombre TEXT);
    CREATE TABLE lineas(id_linea INTEGER PRIMARY KEY, nombre TEXT, id_dependencia INTEGER REFERENCES dependencias);
    CREATE TABLE proyectos(id_proyecto TEXT PRIMARY KEY, nombre TEXT, id_linea INTEGER REFERENCES lineas,
        fecha_inicio TEXT, fecha_fin_prevista TEXT, estado TEXT);
    CREATE TABLE contratistas(id_contratista INTEGER PRIMARY KEY, nombre TEXT, documento TEXT, cuenta_bancaria TEXT);
    CREATE TABLE contratos(id_contrato TEXT PRIMARY KEY, id_proyecto TEXT REFERENCES proyectos,
        id_contratista INTEGER REFERENCES contratistas, objeto TEXT, vigencia INTEGER, fecha_firma TEXT,
        valor_total INTEGER);
    CREATE TABLE desembolsos(id_desembolso INTEGER PRIMARY KEY, id_contrato TEXT REFERENCES contratos,
        fecha TEXT, valor INTEGER, anulado INTEGER);
    """)
    db.executemany("INSERT INTO dependencias VALUES (?,?)", DEPENDENCIAS)
    db.executemany("INSERT INTO lineas VALUES (?,?,?)", LINEAS)
    proyectos = []
    for n in range(1, 41):
        linea = random.choice(LINEAS)[0]
        inicio = date(2024, 1, 15) + timedelta(days=random.randint(0, 800))
        fin = inicio + timedelta(days=random.randint(240, 900))
        estado = random.choices(["A", "S", "C"], [6, 2, 3])[0]
        proyectos.append((f"PRY-{n:03d}", f"{random.choice(TEMAS).capitalize()} para {LINEAS[linea-1][1].lower()}",
                          linea, inicio.isoformat(), fin.isoformat(), estado))
    db.executemany("INSERT INTO proyectos VALUES (?,?,?,?,?,?)", proyectos)
    db.executemany("INSERT INTO contratistas VALUES (?,?,?,?)",
                   [(i, f"Contratista ficticio {i}", f"{random.randint(10**7, 10**8)}", f"****{random.randint(1000, 9999)}")
                    for i in range(1, 31)])
    contratos, desembolsos, k = [], [], 1
    for n in range(1, 121):
        p = random.choice(proyectos)
        vig = random.choice([2025, 2025, 2026, 2026, 2026])
        firma = date(vig, random.randint(1, 9 if vig == 2026 else 12), random.randint(1, 28))
        valor = random.randint(8, 400) * 1_000_000
        cid = f"CT-{vig}-{n:03d}"
        contratos.append((cid, p[0], random.randint(1, 30), random.choice(OBJETOS), vig, firma.isoformat(), valor))
        for _ in range(random.randint(0, 4)):
            f = firma + timedelta(days=random.randint(15, 300))
            if f > date(2026, 9, 30):
                continue
            desembolsos.append((k, cid, f.isoformat(), round(valor * random.choice([0.1, 0.2, 0.25, 0.3]) / 1000) * 1000,
                                1 if random.random() < 0.12 else 0))
            k += 1
    db.executemany("INSERT INTO contratos VALUES (?,?,?,?,?,?,?)", contratos)
    db.executemany("INSERT INTO desembolsos VALUES (?,?,?,?,?)", desembolsos)
    db.commit()
    resumen = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
               for t in ("dependencias", "lineas", "proyectos", "contratos", "desembolsos", "contratistas")}
    db.close()
    return resumen


if __name__ == "__main__":
    print(f"Base sintética: {BASE}\n{crear()}")
