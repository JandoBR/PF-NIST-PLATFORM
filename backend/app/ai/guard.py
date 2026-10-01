"""Bloqueo explicito antes de gastar dinero real en la API de DeepSeek.

Compartido por la CLI (`app/main.py`) y la API HTTP (`app/api/`): ambas pueden terminar llamando
al mismo `DeepSeekClient` real (extraccion U1, ajuste U2, o redaccion de planes), asi que ambas
deben pasar por el mismo guard antes de intentarlo.

Pedido tras un incidente real en esta sesion: una corrida de prueba disparo 3 llamadas pagadas
porque `backend/.env` ya tenia una API key real y nadie la noto hasta despues (docs/09 §5).
"""

from __future__ import annotations


def check_live_ai_guard(ai_requested: bool, api_key: str | None, confirmed: bool) -> str | None:
    """Retorna un mensaje de error si hay que abortar, o None si se puede seguir."""

    if not ai_requested or not api_key or confirmed:
        return None
    return (
        "Hay una DEEPSEEK_API_KEY real configurada (shell o backend/.env).\n"
        "Esta operacion hara llamadas reales y pagadas a la API de DeepSeek\n"
        "(los chunks ya cacheados en backend/.cache/ no se repiten).\n"
        "Confirma explicitamente (--confirm-live-ai en la CLI, confirm_live_ai=true en la API)"
        " si de verdad quieres continuar, o quita la key para una corrida sin costo."
    )
