# Agente observable

Un agente que responde preguntas sobre una base de datos, corre con un **modelo local** (Ollama o LM Studio) o en la nube (Groq), y deja **cada paso a la vista en MLflow**: qué pensó el modelo, qué SQL escribió, qué devolvió la base, cuánto costó y si acertó.

Es la versión mínima, sin framework, de lo que se construye en el Caso 1 del curso *Automatización Inteligente* (NODO · EAFIT). Los datos son **sintéticos** (el «Centro Aurora»: proyectos, contratos y pagos inventados).

Lección interactiva que acompaña este repositorio: **[gobernanzadatos.vercel.app/observabilidad](https://gobernanzadatos.vercel.app/observabilidad)**

## La idea en una frase

> El modelo propone; el código decide; MLflow lo deja escrito.

| Pieza | Archivo | Qué decide |
|---|---|---|
| Base sintética | `crear_base.py` | 40 proyectos, 120 contratos, 142 pagos y una tabla `contratistas` con datos personales inventados |
| Capa semántica | `datos/capa_semantica.json` | Qué tablas y columnas existen para el agente y qué significa cada palabra del negocio |
| Guardián | `guardian.py` | Solo lectura, una sentencia, solo lo que está en la capa, 50 filas, 2 segundos |
| Agente | `agente.py` | El ciclo modelo → herramienta → modelo, con topes (6 consultas, 7 llamadas) |
| Evaluación | `evaluar.py` | 11 preguntas y 6 calificadores en código, registrados en MLflow |
| Opinión humana | `opinar.py` | Una persona califica una respuesta; queda pegada a su traza |
| Pruebas | `pruebas/prueba_sin_red.py` | 23 pruebas sin red ni modelo |
| Exportar | `exportar.py` | Corridas y trazas a un JSON liviano para un tablero |

## Instalar (una vez)

Requisitos: Python 3.11 o superior, Git y [Ollama](https://ollama.com/download).

```bash
git clone https://github.com/sjimenezlon/agente-observable.git
cd agente-observable
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows (PowerShell)
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python crear_base.py
python pruebas/prueba_sin_red.py        # debe decir: 23 ok · 0 fallas
```

Baje un modelo local pequeño (2,5 GB; corre en un portátil con 16 GB de RAM):

```bash
ollama pull qwen3:4b-instruct
ollama pull llama3.2:3b          # opcional, para comparar
```

## Correr

```bash
# 1. Una pregunta
python agente.py "¿Qué porcentaje de ejecución lleva la vigencia 2026?"

# 2. El set completo, medido
python evaluar.py
python evaluar.py --modelo llama3.2:3b      # otro modelo, misma vara

# 3. Ver todo en MLflow (otra terminal) → http://127.0.0.1:5050
mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5050

# 4. Dar su opinión sobre una respuesta (el id lo imprime agente.py)
python opinar.py tr-xxxxxxxx mal "contó los suspendidos como cerrados"
```

En macOS el puerto 5000 lo ocupa AirPlay; por eso 5050.

### Con LM Studio en vez de Ollama

Encienda el servidor de LM Studio (pestaña Developer → Start Server), cargue un modelo con soporte de herramientas y cree un `.env`:

```
LOCAL_URL=http://localhost:1234/v1
LOCAL_MODELO=<el identificador que muestra LM Studio>
```

### Con Groq (nube, plan gratuito)

```
GROQ_API_KEY=gsk_...
```

```bash
python agente.py "¿Cuántos proyectos vigentes tiene el centro?" --backend groq
python evaluar.py --backend groq --pausa 20
```

Con Groq **las filas que devuelve la base viajan a un servidor externo**. Úselo solo con datos sintéticos. Con datos reales, modelo local.

## Qué mirar en MLflow

- **Traces**: cada pregunta es una traza con tres tipos de paso: `agente` (AGENT), `Completions` (cada llamada al modelo, con mensajes y tokens) y `ejecutar_sql` (TOOL, con el SQL y las filas). Etiquetas: `modelo`, `backend`, `capa`, `datos_salen`.
- **Runs**: cada `evaluar.py` es una corrida con parámetros (modelo, versión de la capa, versión de las instrucciones) y métricas (`cifra_correcta/mean`, `tokens_por_pregunta`, `segundos_por_pregunta`…). Seleccione dos corridas → *Compare*.
- **Prompts**: `aurora-instrucciones` guarda cada versión de `instrucciones.txt`; una versión nueva solo cuando el texto cambia.
- **Assessments**: en cada traza, los veredictos del código (CODE) y los de las personas (HUMAN). Cuando no coinciden, ahí hay algo que aprender.

## Medido el 7 de octubre de 2026

En un portátil (Apple Silicon, 24 GB, Ollama 0.40, MLflow 3.17), mismo examen de 11 preguntas:

| Modelo | Cifras correctas | Admite el límite | Tokens/pregunta | s/pregunta |
|---|---|---|---|---|
| `qwen3:4b-instruct` | 100 % | 100 % | 2.244 | 2,4 |
| `llama3.2:3b` | 86 % | 67 % | 2.441 | 1,7 |
| `qwen3:4b` (piensa) | 100 % | 100 % | 5.084 | 64,2 |
| `qwen3:4b-instruct`, capa **sin reglas** | **43 %** | 100 % | 1.443 | 1,8 |
| `llama3.2:3b`, capa **sin reglas** | **29 %** | 67 % | 1.950 | 3,4 |

Detalle y lectura en [RESULTADOS.md](RESULTADOS.md).

## Ejercicios

1. **Rompa la capa.** Corra `AURORA_CAPA=datos/capa_sin_reglas.json python evaluar.py` (misma capa sin reglas ni ejemplos; en PowerShell: `$env:AURORA_CAPA="datos/capa_sin_reglas.json"`) y compare las dos corridas en MLflow. Luego devuelva una sola regla y mida cuánto recupera.
2. **Cambie las instrucciones.** Edite `instrucciones.txt`; MLflow registra una versión nueva del prompt. ¿Cambió algo medible?
3. **Agregue una pregunta** a `datos/preguntas.json` con su `sql_referencia`. La cifra esperada nunca se escribe a mano.
4. **Escriba un calificador** en `evaluar.py`: por ejemplo, que la respuesta mencione la fecha de corte.
5. **Opine en desacuerdo con el código**: busque una respuesta con `cifra_correcta = sí` que usted no le creería a nadie, y regístrelo con `opinar.py`.

## Licencia

MIT. Datos sintéticos, sin ninguna persona ni institución real.
