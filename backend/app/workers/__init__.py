"""Workers que consumen las colas de Redis de `app/core/queue.py` (docs/04 §5, §11).

`core.py` consume trabajos `assessment_run` (pipeline completo de evaluacion). `logs.py` consume
trabajos `event_ingest` (pipeline de eventos). Cada modulo separa `process_message` (logica
pura: sesion + metodologia + mensaje -> resultado, testeable sin Redis) de `main` (el loop real
que conecta a Redis y a la base de datos y nunca termina).
"""
