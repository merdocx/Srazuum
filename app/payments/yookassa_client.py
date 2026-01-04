"""Клиент для работы с YooKassa API."""

from typing import Optional, Dict, Any
from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotificationFactory
from config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Настройка YooKassa
if settings.yookassa_shop_id and settings.yookassa_secret_key:
    Configuration.account_id = settings.yookassa_shop_id
    Configuration.secret_key = settings.yookassa_secret_key
else:
    logger.warning("YooKassa credentials not configured")


def get_return_url() -> str:
    """
    Получить URL для возврата после оплаты.

    Для Telegram ботов используется формат https://t.me/<bot_username>
    Если yookassa_return_url настроен в настройках, используется он.
    Иначе формируется URL на основе bot token (если можно извлечь username).
    """
    if settings.yookassa_return_url:
        return settings.yookassa_return_url

    # Для Telegram ботов можно использовать просто https://t.me/<bot_username>
    # Но лучше оставить пустым или использовать настраиваемый URL
    # В Telegram результат платежа приходит через webhook, return_url используется только для редиректа
    # Можно использовать простой формат или deep link
    return "https://t.me/"  # Базовый URL, пользователь вернется в Telegram


def create_payment(link_id: int, user_id: int, amount: Optional[float] = None) -> Dict[str, Any]:
    """
    Создать платеж в YooKassa.

    Args:
        link_id: ID связи кросспостинга
        user_id: ID пользователя
        amount: Сумма платежа (по умолчанию из настроек)

    Returns:
        Словарь с информацией о платеже (payment_id, confirmation_url)
    """
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        raise ValueError("YooKassa credentials not configured")

    amount = amount or settings.subscription_price

    return_url = get_return_url()

    payment_data = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "capture": True,
        "description": f"Оплата подписки кросспостинга (связь #{link_id})",
        "metadata": {"link_id": str(link_id), "user_id": str(user_id)},
    }

    try:
        payment = Payment.create(payment_data)

        logger.info(f"payment_created: payment_id={payment.id}, link_id={link_id}, user_id={user_id}, amount={amount}")

        return {
            "payment_id": payment.id,
            "confirmation_url": payment.confirmation.confirmation_url if payment.confirmation else None,
            "status": payment.status,
            "amount": amount,
        }
    except Exception as e:
        logger.error(f"payment_creation_failed: error={str(e)}, link_id={link_id}, user_id={user_id}")
        raise


def get_payment_status(payment_id: str) -> Optional[Dict[str, Any]]:
    """
    Получить статус платежа.

    Args:
        payment_id: ID платежа в YooKassa

    Returns:
        Информация о платеже или None
    """
    try:
        payment = Payment.find_one(payment_id)
        return {
            "id": payment.id,
            "status": payment.status,
            "paid": payment.paid,
            "amount": {"value": payment.amount.value, "currency": payment.amount.currency},
            "metadata": payment.metadata or {},
        }
    except Exception as e:
        logger.error(f"payment_status_check_failed: payment_id={payment_id}, error={str(e)}")
        return None


def parse_webhook(request_body: dict) -> Optional[Dict[str, Any]]:
    """
    Обработать webhook от YooKassa.

    Args:
        request_body: Тело запроса от YooKassa

    Returns:
        Информация о платеже из webhook или None
    """
    try:
        notification = WebhookNotificationFactory().create(request_body)
        payment_object = notification.object

        logger.info(
            f"webhook_received: event={notification.event}, payment_id={payment_object.id}, status={payment_object.status}"
        )

        return {
            "event": notification.event,
            "payment_id": payment_object.id,
            "status": payment_object.status,
            "paid": payment_object.paid,
            "amount": {"value": payment_object.amount.value, "currency": payment_object.amount.currency},
            "metadata": payment_object.metadata or {},
        }
    except Exception as e:
        logger.error(f"webhook_parsing_failed: {str(e)}, request_body={request_body}")
        return None
