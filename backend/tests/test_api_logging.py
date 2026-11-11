"""docs/09 §100: el proceso de la API configura logging como el de los workers.

Sin esto, los `ai_call` de U3 (la generacion de planes corre en la API) no tenian handler y se
perdian: un plan degradado parecia una ejecucion sin llamadas.
"""

import logging

from app.api import app as api_app


def test_the_api_installs_a_root_handler_with_the_workers_format(monkeypatch):
    raiz = logging.getLogger()
    monkeypatch.setattr(raiz, "handlers", [])
    monkeypatch.setattr(raiz, "level", logging.WARNING)

    api_app.configure_logging()

    assert raiz.level == logging.INFO
    (handler,) = raiz.handlers
    assert handler.formatter._fmt == "%(asctime)s %(name)s %(message)s"


def test_app_loggers_are_enabled_for_info_after_configuring(monkeypatch):
    raiz = logging.getLogger()
    monkeypatch.setattr(raiz, "handlers", [])
    monkeypatch.setattr(raiz, "level", logging.WARNING)

    api_app.configure_logging()

    assert logging.getLogger("app.ai.calls").isEnabledFor(logging.INFO)
    assert logging.getLogger("app.ai.client").isEnabledFor(logging.INFO)


def test_uvicorn_loggers_are_not_rewired(monkeypatch):
    """`basicConfig` solo toca el logger raiz: los de uvicorn conservan sus handlers."""

    raiz = logging.getLogger()
    monkeypatch.setattr(raiz, "handlers", [])
    monkeypatch.setattr(raiz, "level", logging.WARNING)
    uvicorn = logging.getLogger("uvicorn.error")
    antes = list(uvicorn.handlers)

    api_app.configure_logging()

    assert uvicorn.handlers == antes
