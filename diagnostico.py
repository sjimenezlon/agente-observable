"""Revisa, uno por uno, que todo lo necesario esté instalado y conectado. Dice qué hacer si algo falla.

    python diagnostico.py

Nada de lo que revisa sale del equipo, salvo la conexión a la base compartida (si la configuró).
"""
import os
os.environ.setdefault("MLFLOW_LOGGING_LEVEL", "WARNING")   # sin líneas INFO de MLflow en la terminal
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import importlib
import importlib.util
import json
import os
import platform
import sys
import urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
resultados = []


def paso(nombre, ok, detalle, arreglo=""):
    resultados.append(ok)
    print(f"  {'✓' if ok else '✕'}  {nombre:<30} {detalle}")
    if not ok and arreglo:
        print(f"       → {arreglo}")


def main():
    win = platform.system() == "Windows"
    print(f"\nDiagnóstico · {platform.system()} · Python {platform.python_version()}\n")

    v = sys.version_info
    paso("Python 3.11 o superior", v >= (3, 11), f"{v.major}.{v.minor}.{v.micro}",
         "Instale Python 3.11 y cree el entorno con él (py -3.11 -m venv .venv en Windows).")
    if v < (3, 11):
        print("\n  Con este Python no se puede seguir. Active el entorno .venv creado con Python 3.11 y repita.")
        return
    en_venv = sys.prefix != sys.base_prefix
    paso("Entorno virtual activo", en_venv, sys.prefix if en_venv else "está usando el Python del sistema",
         (".venv\\Scripts\\Activate.ps1" if win else "source .venv/bin/activate") + "  (debe ver (.venv) al inicio de la línea)")

    for lib, para in (("openai", "hablar con el modelo"), ("mlflow", "registrar trazas"), ("pymssql", "conectarse a SQL Server")):
        try:
            m = importlib.import_module(lib)
            paso(f"Librería {lib}", True, f"{getattr(m, '__version__', '')} · para {para}")
        except ImportError:
            paso(f"Librería {lib}", False, "no instalada", "pip install -r requirements.txt  (con el entorno activo)")

    if not all(importlib.util.find_spec(m) for m in ("openai", "mlflow")):
        print("\n  Faltan librerías: instálelas y repita.")
        return
    import config
    config.cargar_env()
    paso("Archivo .env", os.path.exists(os.path.join(RAIZ, ".env")), "configuración local",
         "Copie .env.example como .env (Windows: copy .env.example .env · macOS: cp .env.example .env)")

    b = config.backend()
    if b.nombre == "local":
        try:
            with urllib.request.urlopen(b.base_url.rstrip("/") + "/models", timeout=5) as r:
                modelos = [m["id"] for m in json.load(r).get("data", [])]
            paso("Servidor de modelos local", True, f"{b.base_url} responde")
            paso(f"Modelo {b.modelo}", b.modelo in modelos or f"{b.modelo}:latest" in modelos,
                 "descargado" if b.modelo in modelos else f"no está; hay: {', '.join(modelos[:4]) or 'ninguno'}",
                 f"ollama pull {b.modelo}")
        except OSError:
            paso("Servidor de modelos local", False, f"nada responde en {b.base_url}",
                 "Abra la aplicación Ollama (o en una terminal: ollama serve) y repita.")
    else:
        paso("Modelo en la nube", True, f"{b.nombre} · {b.modelo} · los datos salen del equipo")

    motor = config.motor()
    if motor == "sqlite":
        paso("Base local (SQLite)", config.BASE.exists(), str(config.BASE.name),
             "python crear_base.py")
    else:
        import guardian
        try:
            r = guardian.ejecutar("SELECT COUNT(*) AS vigentes FROM proyectos WHERE estado IN ('A','S')")
            paso("Conexión a la base compartida", r["ok"],
                 f"{config.sqlserver()['server']} · {r['rows'][0]['vigentes']} proyectos vigentes" if r["ok"] else r["error"][:90],
                 "Revise SQLSERVER_HOST, SQLSERVER_USER y SQLSERVER_PASSWORD en .env. Si tarda, la base estaba dormida: repita en un minuto.")
            if r["ok"]:
                import pymssql
                with pymssql.connect(**config.sqlserver(), login_timeout=60) as db:
                    cur = db.cursor()
                    try:
                        cur.execute("SELECT TOP 1 documento FROM contratistas")
                        paso("Datos personales protegidos", False, "¡el usuario puede leer contratistas!",
                             "Avise al docente: el usuario no debería tener ese permiso.")
                    except pymssql.Error:
                        paso("Datos personales protegidos", True, "el servidor niega la tabla contratistas (así debe ser)")
        except SystemExit as e:
            paso("Conexión a la base compartida", False, str(e))
        except Exception as e:      # red, firewall, DNS
            paso("Conexión a la base compartida", False, f"{type(e).__name__}: {str(e)[:80]}",
                 "¿Hay internet? Algunas redes bloquean el puerto 1433; pruebe con otra red o use DB_MOTOR=sqlite.")

    bien = sum(resultados)
    print(f"\n{bien} de {len(resultados)} en orden." + ("  Todo listo: python agente.py \"¿Cuántos proyectos vigentes tiene el centro?\""
                                                   if bien == len(resultados) else "  Arregle lo marcado con ✕ y vuelva a correr este diagnóstico."))


if __name__ == "__main__":
    main()
