"""APScheduler em background que roda a coleta CVM periodicamente."""
import logging
import os
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()
logger = logging.getLogger(__name__)

JOB_ID = "coleta_mercado"


def _executar_coleta(grafo) -> None:
    logger.info("[scheduler] Iniciando coleta agendada...")
    try:
        grafo.invoke(
            {
                "messages": [HumanMessage(
                    content="Execute coleta completa, priorizando FII, depois CRI e CRA."
                )],
                "next_agent": "coletor",
                "iteracoes": 0,
            },
            config={"recursion_limit": 25},
        )
        logger.info("[scheduler] Coleta concluída com sucesso.")
    except Exception as e:
        logger.exception(f"[scheduler] Coleta falhou: {e}")


def criar_scheduler(grafo) -> BackgroundScheduler:
    intervalo_min = int(os.getenv("COLETA_INTERVALO_MINUTOS", "30"))
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        func=_executar_coleta,
        trigger=IntervalTrigger(minutes=intervalo_min),
        args=[grafo],
        id=JOB_ID,
        name="Coleta CVM SRE",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),  # roda imediatamente ao iniciar
    )
    scheduler.start()
    logger.info(f"[scheduler] Iniciado. Intervalo: {intervalo_min} minutos.")
    return scheduler


def parar(scheduler: Optional[BackgroundScheduler]) -> None:
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[scheduler] Parado.")


def proximo_disparo(scheduler: Optional[BackgroundScheduler]) -> Optional[datetime]:
    if scheduler is None or not scheduler.running:
        return None
    job = scheduler.get_job(JOB_ID)
    return job.next_run_time if job else None
