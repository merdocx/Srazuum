"""Задачи для синхронизации платежей с YooKassa."""

import sys
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.models.shared import CrosspostingLink
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Путь к основному приложению
_project_root = Path(__file__).parent.parent.parent.parent.parent


def _get_get_payment_status():
    """Ленивый импорт get_payment_status из основного приложения."""
    import importlib.util

    # Добавляем путь к основному приложению
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    # Используем importlib для динамического импорта
    yookassa_client_path = _project_root / "app" / "payments" / "yookassa_client.py"
    spec = importlib.util.spec_from_file_location("yookassa_client", yookassa_client_path)
    yookassa_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(yookassa_module)

    return yookassa_module.get_payment_status


async def sync_all_payments():
    """Синхронизировать статусы всех платежей с YooKassa."""
    try:
        logger.info("payment_sync_job_started")

        # Получаем функцию для получения статуса платежа
        get_payment_status = _get_get_payment_status()

        async with AsyncSessionLocal() as session:
            # Получаем все связи с платежами (yookassa_payment_id не NULL)
            result = await session.execute(
                select(CrosspostingLink).where(
                    CrosspostingLink.yookassa_payment_id.isnot(None),
                    CrosspostingLink.payment_status.in_(["pending", "waiting_for_capture"]),
                )
            )
            links = result.scalars().all()

            logger.info(f"payment_sync_job_found_links: count={len(links)}")

            synced_count = 0
            updated_count = 0
            error_count = 0

            for link in links:
                try:
                    if not link.yookassa_payment_id:
                        continue

                    # Получаем статус из YooKassa
                    payment_info = get_payment_status(link.yookassa_payment_id)

                    if not payment_info:
                        logger.warning(
                            f"payment_sync_job_payment_not_found: " f"payment_id={link.yookassa_payment_id}, link_id={link.id}"
                        )
                        error_count += 1
                        continue

                    # Проверяем, изменился ли статус
                    old_status = link.payment_status
                    new_status = payment_info["status"]

                    if old_status != new_status:
                        link.payment_status = new_status

                        # Если платеж успешен и дата еще не установлена, обновляем дату
                        if new_status == "succeeded" and not link.last_payment_date:
                            from datetime import datetime

                            link.last_payment_date = datetime.utcnow()

                        await session.commit()
                        await session.refresh(link)

                        logger.info(
                            f"payment_sync_job_status_updated: "
                            f"payment_id={link.yookassa_payment_id}, link_id={link.id}, "
                            f"old_status={old_status}, new_status={new_status}"
                        )
                        updated_count += 1
                    else:
                        synced_count += 1

                except Exception as e:
                    logger.error(
                        f"payment_sync_job_error: "
                        f"payment_id={link.yookassa_payment_id}, link_id={link.id}, error={str(e)}",
                        exc_info=True,
                    )
                    error_count += 1
                    await session.rollback()

            logger.info(
                f"payment_sync_job_completed: "
                f"total={len(links)}, synced={synced_count}, updated={updated_count}, errors={error_count}"
            )

    except Exception as e:
        logger.error(f"payment_sync_job_failed: error={str(e)}", exc_info=True)
