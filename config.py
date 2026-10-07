"""Rutas, topes y el modelo. Todo lo que cambia entre equipos vive aquí o en .env.

El agente habla con cualquier servidor compatible con la API de OpenAI:
  local   Ollama (http://localhost:11434/v1) o LM Studio (http://localhost:1234/v1): los datos no salen del equipo.
  groq    Groq en la nube, plan gratuito: los datos SÍ salen del equipo. Solo con datos sintéticos.
"""
import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"
BASE = Path(os.environ.get("AURORA_DB", DATOS / "aurora.sqlite"))
CAPA = Path(os.environ.get("AURORA_CAPA", DATOS / "capa_semantica.json"))
PREGUNTAS = DATOS / "preguntas.json"
INSTRUCCIONES = RAIZ / "instrucciones.txt"

# Topes: los pone el código, no el prompt.
MAX_HERRAMIENTAS = 6
MAX_LLAMADAS_MODELO = 7
MAX_TOKENS_SALIDA = 4000      # los modelos que «piensan» gastan tokens antes de responder
TIMEOUT_MODELO = 120.0       # un modelo local en un portátil puede tardar


def cargar_env() -> None:
    ruta = RAIZ / ".env"
    if ruta.is_file():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                k, v = linea.split("=", 1)
                v = v.split(" #")[0].strip().strip('"')
                if v:
                    os.environ.setdefault(k.strip(), v)


@dataclass
class Backend:
    nombre: str
    base_url: str
    modelo: str
    api_key: str
    externo: bool            # True si los datos salen del equipo


def backend(nombre: str | None = None, modelo: str | None = None) -> Backend:
    cargar_env()
    nombre = nombre or os.environ.get("BACKEND", "local")
    if nombre == "local":
        return Backend("local", os.environ.get("LOCAL_URL", "http://localhost:11434/v1"),
                       modelo or os.environ.get("LOCAL_MODELO", "qwen3:4b-instruct"), "local", False)
    if nombre == "groq":
        key = os.environ.get("GROQ_API_KEY", "")
        if not key.startswith("gsk_"):
            raise SystemExit("Falta GROQ_API_KEY (empieza por gsk_) en .env")
        return Backend("groq", "https://api.groq.com/openai/v1",
                       modelo or os.environ.get("GROQ_MODELO", "openai/gpt-oss-20b"), key, True)
    raise SystemExit(f"Backend desconocido: {nombre} (use local o groq)")


def cliente(b: Backend):
    from openai import OpenAI
    # max_retries=0: un 429 se ve en la traza en vez de esconderse detrás de reintentos.
    return OpenAI(base_url=b.base_url, api_key=b.api_key, timeout=TIMEOUT_MODELO, max_retries=0)
