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
| Base compartida | `cargar_sqlserver.py` | Lleva la base a SQL Server (Azure, Docker o el del aula) y crea un usuario que solo lee la capa |
| App web | `web.py` + `web/index.html` | Preguntar con la traza en vivo, opinar y probar el guardián desde el navegador (puerto 8070) |
| Diagnóstico | `diagnostico.py` | Revisa uno por uno los requisitos y dice qué hacer si algo falla |
| Opinión humana | `opinar.py` | Una persona califica una respuesta; queda pegada a su traza |
| Pruebas | `pruebas/prueba_sin_red.py` | 28 pruebas sin red ni modelo |
| Exportar | `exportar.py` | Corridas y trazas a un JSON liviano para un tablero |

## Instalar (una vez)

Requisitos: Python 3.11 o más reciente (recomendado 3.13; probado con 3.11, 3.13 y 3.14), Git y [Ollama](https://ollama.com/download).

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
python pruebas/prueba_sin_red.py        # debe decir: 28 ok · 0 fallas
python diagnostico.py                   # revisa Python, librerías, Ollama, modelo y base: dice qué arreglar
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

# 1b. O en el navegador, con la traza en vivo → http://127.0.0.1:8070 (enciende MLflow solo)
python web.py

# 2. El set completo, medido
python evaluar.py
python evaluar.py --modelo llama3.2:3b      # otro modelo, misma vara

# 3. Ver todo en MLflow (otra terminal) → http://127.0.0.1:5070
mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5070

# 4. Dar su opinión sobre una respuesta (el id lo imprime agente.py)
python opinar.py tr-xxxxxxxx mal "contó los suspendidos como cerrados"
```

Se usa el puerto 5070 para no chocar con otro MLflow abierto (el del curso usa 5050; en macOS el 5000 lo ocupa AirPlay). Cada proyecto tiene su propio `mlflow.db`, así que los registros tampoco se mezclan.

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

## La base compartida del curso (SQL Server en Azure)

Para replicar el ejercicio como en el aula —un servidor de base de datos real, varias personas conectadas, permisos puestos por el servidor— la misma base sintética está en Azure SQL:

| | |
|---|---|
| Servidor | `aurora-obs-francecentral.database.windows.net` (puerto 1433) |
| Base | `aurora` |
| Usuario | `estudiante` (solo lectura) |
| Clave | la comparte el docente; no está en este repositorio |

Ese usuario solo puede leer las columnas de la capa semántica: `contratistas` y `contratos.id_contratista` están **denegadas por el servidor**, y no puede escribir nada. Pruébelo: el servidor responde *«The SELECT permission was denied…»*.

**Con el agente.** En `.env`:

```
DB_MOTOR=sqlserver
SQLSERVER_HOST=aurora-obs-francecentral.database.windows.net
SQLSERVER_DB=aurora
SQLSERVER_USER=estudiante
SQLSERVER_PASSWORD=<la clave del docente>
```

y corra igual: `python agente.py "..."` y `python evaluar.py`. Las trazas llevan la etiqueta `motor = sqlserver`.

**Para mirarla sin código.** VS Code con la extensión *SQL Server (mssql)*, DBeaver o Azure Data Studio: servidor `aurora-obs-francecentral.database.windows.net`, autenticación *SQL Login*, base `aurora`. O en la terminal:

```bash
sqlcmd -S aurora-obs-francecentral.database.windows.net -d aurora -U estudiante
```

**A tener en cuenta.** Es la oferta gratuita de Azure SQL (sin servidor): si nadie la usa durante una hora se pausa, y la primera conexión después tarda hasta un minuto en despertarla. Si se agota el cupo gratuito del mes, se pausa hasta el mes siguiente; el plan B es la base local (`DB_MOTOR=sqlite`), que tiene exactamente los mismos datos.

**Su propio servidor.** `cargar_sqlserver.py` carga la base en cualquier SQL Server; con Docker:

```bash
docker run -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD='Clave-Larga-2026' -p 1433:1433 -d mcr.microsoft.com/mssql/server:2022-latest
python cargar_sqlserver.py --servidor localhost --admin sa --base aurora --crear-base --clave-estudiante 'Otra-Clave-2026'
```

## En el navegador

`python web.py` abre **http://127.0.0.1:8070** y, si no está encendido, enciende MLflow en el 5070 en silencio. Un solo comando; Ctrl+C apaga los dos:

- **Preguntar**: cada llamada al modelo y cada consulta aparecen mientras ocurren, con su tiempo, sus tokens, el SQL y las filas. Al final, la respuesta, el enlace a su traza en MLflow y los botones 👍 / 👎 para dejar su opinión (queda como HUMAN en la traza).
- **Guardián**: SQL directo, sin modelo, contra la base local o la compartida, para ver qué niega el guardián y qué niega el servidor.

Arriba se elige el modelo (solo los locales; los `-cloud` de Ollama no se ofrecen porque corren fuera del equipo) y la base (local o compartida). Use los puertos 8070 (web) y 5070 (MLflow) para no chocar con otras herramientas del curso.

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
| `qwen3:4b-instruct` contra **SQL Server en Azure** | 100 % | 100 % | 2.370 | 4,4 |

Detalle y lectura en [RESULTADOS.md](RESULTADOS.md).

## Ejercicios

1. **Rompa la capa.** Corra `AURORA_CAPA=datos/capa_sin_reglas.json python evaluar.py` (misma capa sin reglas ni ejemplos; en PowerShell: `$env:AURORA_CAPA="datos/capa_sin_reglas.json"`) y compare las dos corridas en MLflow. Luego devuelva una sola regla y mida cuánto recupera.
2. **Cambie las instrucciones.** Edite `instrucciones.txt`; MLflow registra una versión nueva del prompt. ¿Cambió algo medible?
3. **Agregue una pregunta** a `datos/preguntas.json` con su `sql_referencia`. La cifra esperada nunca se escribe a mano.
4. **Escriba un calificador** en `evaluar.py`: por ejemplo, que la respuesta mencione la fecha de corte.
5. **Opine en desacuerdo con el código**: busque una respuesta con `cifra_correcta = sí` que usted no le creería a nadie, y regístrelo con `opinar.py`.

## Licencia

MIT. Datos sintéticos, sin ninguna persona ni institución real.
