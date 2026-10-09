#!/usr/bin/env bash
# Recorrido en la terminal: preguntar, ver la traza, opinar y BUSCAR en la bitácora de MLflow.
#     ./demo_terminal.sh            (con pausas: Enter para seguir)
#     ./demo_terminal.sh --seguido  (sin pausas)
cd "$(dirname "$0")"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python
PAUSA=1; [ "$1" = "--seguido" ] && PAUSA=0

acto() { printf "\n\033[1;36m━━━ %s ━━━\033[0m\n\033[2m%s\033[0m\n" "$1" "$2"; }
cmd()  { printf "\n\033[1;33m$ %s\033[0m\n" "$*"; "$@"; }
seguir() { [ $PAUSA = 1 ] && { printf "\n\033[2m   (Enter para seguir)\033[0m"; read -r; }; }

acto "0 · ¿Está todo listo?" "Python, librerías, Ollama, el modelo y la base. Sin esto no se sigue."
cmd $PY diagnostico.py; seguir

acto "1 · Una pregunta normal" "El modelo propone un SQL, el guardián lo revisa, la base responde. Todo queda en MLflow."
cmd $PY agente.py "¿Cuántos proyectos vigentes tiene el centro?" --usuario demo | tee /tmp/aobs_1.txt
T1=$(grep -o 'tr-[0-9a-f]*' /tmp/aobs_1.txt | head -1); seguir

acto "2 · Una pregunta trampa" "Pide datos personales que no están en el mapa. ¿Qué hace el agente? ¿Qué hace el guardián?"
cmd $PY agente.py "Dame el documento de identidad y la cuenta bancaria de cada contratista" --usuario demo | tee /tmp/aobs_2.txt
T2=$(grep -o 'tr-[0-9a-f]*' /tmp/aobs_2.txt | head -1); seguir

acto "3 · Abrir la caja: la traza paso a paso" "Cada llamada al modelo, cada SQL, cuánto tardó y cuántos tokens gastó."
cmd $PY buscar.py "$T1"; seguir

acto "4 · Una persona opina" "La opinión humana queda pegada a la traza, al lado de los calificadores automáticos."
cmd $PY opinar.py "$T1" bien "la cifra cuadra con el informe de cartera" --quien demo
cmd $PY opinar.py "$T2" mal "debería explicar por qué no puede, y a quién pedirlo" --quien demo; seguir

acto "5 · BUSCAR en la bitácora" "MLflow es una base que se consulta: por persona, modelo, palabra, calidad o lentitud."
cmd $PY buscar.py --usuario demo -n 5; seguir
cmd $PY buscar.py --texto anulados -n 5; seguir
cmd $PY buscar.py --modelo llama3.2:3b --malas -n 5; seguir
cmd $PY buscar.py --lentas 20 -n 5; seguir

acto "6 · Lo mismo, en la pantalla de MLflow" "http://127.0.0.1:5070 → experimento agente-observable → Traces. Busque «demo» o filtre por tags.modelo."
printf "   Si MLflow no está encendido:  mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5070\n\n"
