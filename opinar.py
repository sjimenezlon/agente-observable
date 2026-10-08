"""Deja la opinión de una persona sobre una respuesta, pegada a su traza.

    python opinar.py tr-1a2b3c... bien "la cifra cuadra con el informe"
    python opinar.py tr-1a2b3c... mal  "contó los suspendidos como cerrados" --quien ana

En MLflow queda como evaluación humana (HUMAN) junto a las del código (CODE): cuando no coinciden,
ahí está la conversación que vale la pena.
"""
import os
os.environ.setdefault("MLFLOW_LOGGING_LEVEL", "WARNING")   # sin líneas INFO de MLflow en la terminal
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import argparse

import mlflow
from mlflow.entities import AssessmentSource, AssessmentSourceType

from agente import preparar_mlflow


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("trace_id")
    a.add_argument("veredicto", choices=("bien", "mal"))
    a.add_argument("comentario", nargs="?", default="")
    a.add_argument("--quien", default="persona")
    x = a.parse_args()
    preparar_mlflow()
    mlflow.log_feedback(
        trace_id=x.trace_id, name="opinion_humana", value=x.veredicto == "bien", rationale=x.comentario or None,
        source=AssessmentSource(source_type=AssessmentSourceType.HUMAN, source_id=x.quien),
    )
    print(f"Opinión de {x.quien} guardada en {x.trace_id}: {x.veredicto}")


if __name__ == "__main__":
    main()
