from __future__ import annotations

import logging

_WIDTH = 60


def banner(logger: logging.Logger, title: str, char: str = "=", level: int = logging.INFO) -> None:
    """Loguea un título enmarcado por una línea de ``char`` repetido.

    Reemplaza el patrón repetido de tres ``logger.info(f"{'=' * 60}")`` que
    aparecía por todo el pipeline.
    """
    rule = char * _WIDTH
    logger.log(level, rule)
    logger.log(level, title)
    logger.log(level, rule)
