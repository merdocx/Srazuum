"""Клиент для работы с MAX API."""
import asyncio
import httpx
from typing import Optional, Dict, Any, List
from config.settings import settings
from app.utils.logger import get_logger
from app.utils.retry import retry_with_backoff
from app.utils.exceptions import APIError
from app.utils.rate_limiter import max_api_limiter

logger = get_logger(__name__)


class MaxAPIClient:
    """Клиент для работы с MAX API."""
    
    def __init__(self):
        self.base_url = settings.max_api_base_url
        self.token = settings.max_bot_token
        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30.0,
        )
    
    async def close(self):
        """Закрыть HTTP клиент."""
        await self.client.aclose()
    
    async def get_bot_info(self) -> Dict[str, Any]:
        """
        Получить информацию о боте.
        
        Returns:
            Информация о боте
        
        Raises:
            APIError: При ошибке API
        """
        try:
            await max_api_limiter.wait_if_needed("max_api_bot_info")
            response = await retry_with_backoff(
                self.client.get,
                "/me"
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("failed_to_get_bot_info", status_code=e.response.status_code, error=str(e))
            raise APIError(
                f"HTTP ошибка при получении информации о боте: {e.response.status_code}",
                status_code=e.response.status_code,
                response=e.response.json() if e.response else None
            )
        except httpx.RequestError as e:
            logger.error("failed_to_get_bot_info", error=str(e))
            raise APIError(f"Ошибка сети при получении информации о боте: {e}")
        except Exception as e:
            logger.error("failed_to_get_bot_info", error=str(e))
            raise APIError(f"Неожиданная ошибка при получении информации о боте: {e}")
    
    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отправить текстовое сообщение в канал.
        
        Args:
            chat_id: ID канала в MAX (может быть строкой или числом)
            text: Текст сообщения
            parse_mode: Режим парсинга (HTML, Markdown)
        
        Returns:
            Информация об отправленном сообщении
        """
        # Преобразуем chat_id в правильный формат для query parameter
        # Если это строка с числом, пробуем преобразовать в int
        try:
            # Пробуем преобразовать в int, если это числовая строка
            if isinstance(chat_id, str) and (chat_id.lstrip('-').isdigit() or chat_id.lstrip('-').replace('.', '').isdigit()):
                chat_id_value = int(float(chat_id))
            elif isinstance(chat_id, (int, float)):
                chat_id_value = int(chat_id)
            else:
                chat_id_value = chat_id
        except (ValueError, TypeError):
            chat_id_value = chat_id
        
        # В MAX API chat_id передается как query parameter, а не в теле запроса!
        # Формат: POST /messages?chat_id={chat_id}
        data = {
            "text": text,
        }
        if parse_mode:
            # MAX API использует "format" вместо "parse_mode"
            data["format"] = parse_mode
        
        try:
            await max_api_limiter.wait_if_needed(f"max_api_{chat_id}")
            # Используем правильный формат: chat_id в query parameter
            response = await retry_with_backoff(
                self.client.post,
                f"/messages?chat_id={chat_id_value}",
                json=data
            )
            response.raise_for_status()
            result = response.json()
            logger.info("message_sent", chat_id=chat_id, message_id=result.get("message_id"))
            return result
        except httpx.HTTPStatusError as e:
            logger.error("failed_to_send_message", chat_id=chat_id, status_code=e.response.status_code, error=str(e))
            raise APIError(
                f"HTTP ошибка при отправке сообщения: {e.response.status_code}",
                status_code=e.response.status_code,
                response=e.response.json() if e.response else None
            )
        except httpx.RequestError as e:
            logger.error("failed_to_send_message", chat_id=chat_id, error=str(e))
            raise APIError(f"Ошибка сети при отправке сообщения: {e}")
        except Exception as e:
            logger.error("failed_to_send_message", chat_id=chat_id, error=str(e))
            raise APIError(f"Неожиданная ошибка при отправке сообщения: {e}")
    
    async def upload_file(self, file_path: str, file_type: str = "image") -> str:
        """
        Загрузить файл в MAX API и получить token.
        
        Args:
            file_path: Путь к файлу на диске
            file_type: Тип файла (image, video, document, audio)
        
        Returns:
            Token для использования в content
        """
        try:
            # Шаг 1: Получаем URL для загрузки
            await max_api_limiter.wait_if_needed("max_api_upload")
            upload_response = await retry_with_backoff(
                self.client.post,
                f"/uploads?type={file_type}"
            )
            upload_response.raise_for_status()
            upload_data = upload_response.json()
            upload_url = upload_data.get("url")
            
            if not upload_url:
                raise APIError("Не получен URL для загрузки файла", response=upload_data)
            
            logger.info("upload_url_received", upload_url=upload_url[:100])
            
            # Шаг 2: Загружаем файл
            from pathlib import Path
            from urllib.parse import urlparse, parse_qs
            file = Path(file_path)
            if not file.exists():
                raise APIError(f"Файл не найден: {file_path}")
            
            # Извлекаем photoIds из URL
            parsed_url = urlparse(upload_url)
            query_params = parse_qs(parsed_url.query)
            photo_ids = query_params.get("photoIds", [])
            
            with open(file_path, "rb") as f:
                files = {"data": (file.name, f, "image/jpeg" if file_type == "image" else "application/octet-stream")}
                upload_client = httpx.AsyncClient(timeout=60.0)
                try:
                    upload_file_response = await upload_client.post(
                        upload_url,
                        files=files,
                        headers={"Authorization": self.token}
                    )
                    upload_file_response.raise_for_status()
                    upload_result = upload_file_response.json()
                    
                    # Извлекаем token из структуры {"photos": {"photoId": {"token": "..."}}}
                    photos = upload_result.get("photos", {})
                    if not photos:
                        raise APIError("Не получен photos в ответе", response=upload_result)
                    
                    # Используем первый photoId из URL или первый ключ в photos
                    photo_id = photo_ids[0] if photo_ids else list(photos.keys())[0]
                    photo_data = photos.get(photo_id)
                    
                    if not photo_data:
                        raise APIError(f"Не найден photoId {photo_id} в ответе", response=upload_result)
                    
                    token = photo_data.get("token")
                    
                    if not token:
                        raise APIError("Не получен token после загрузки файла", response=upload_result)
                    
                    logger.info("file_uploaded", file_path=file_path, token=token[:20])
                    return token
                finally:
                    await upload_client.aclose()
                    
        except httpx.HTTPStatusError as e:
            error_response = e.response.json() if e.response else None
            logger.error(
                "failed_to_upload_file",
                file_path=file_path,
                status_code=e.response.status_code if e.response else None,
                error_response=error_response
            )
            raise APIError(
                f"HTTP ошибка при загрузке файла: {e.response.status_code if e.response else 'unknown'}",
                status_code=e.response.status_code if e.response else None,
                response=error_response
            )
        except httpx.RequestError as e:
            logger.error("failed_to_upload_file", file_path=file_path, error=str(e))
            raise APIError(f"Ошибка сети при загрузке файла: {e}")
        except Exception as e:
            logger.error("failed_to_upload_file", file_path=file_path, error=str(e))
            raise APIError(f"Неожиданная ошибка при загрузке файла: {e}")

    async def send_photo(
        self,
        chat_id: str,
        photo_url: str,
        caption: Optional[str] = None,
        local_file_path: Optional[str] = None,
        parse_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отправить фото в канал.
        
        Args:
            chat_id: ID канала в MAX
            photo_url: URL фото
            caption: Подпись к фото
        
        Returns:
            Информация об отправленном сообщении
        """
        # Преобразуем chat_id в правильный формат для query parameter
        try:
            if isinstance(chat_id, str) and (chat_id.lstrip('-').isdigit() or chat_id.lstrip('-').replace('.', '').isdigit()):
                chat_id_value = int(float(chat_id))
            elif isinstance(chat_id, (int, float)):
                chat_id_value = int(chat_id)
            else:
                chat_id_value = chat_id
        except (ValueError, TypeError):
            chat_id_value = chat_id
        
        # ВАЖНО: MAX API требует загрузку файла через /uploads endpoint
        # Сначала загружаем файл, получаем token, затем используем его в content
        # После загрузки может потребоваться задержка для обработки файла
        if local_file_path:
            try:
                token = await self.upload_file(local_file_path, "image")
                
                # Добавляем задержку после загрузки (рекомендуется в документации)
                # для обработки файла на сервере MAX
                await asyncio.sleep(2)
                
                # Формируем запрос с attachments и payload.token
                # ПРАВИЛЬНЫЙ ФОРМАТ: {"attachments": [{"type": "image", "payload": {"token": "..."}}]}
                # Этот формат возвращает attachments в ответе с photo_id, token и url!
                # Используем пустую строку вместо эмодзи, чтобы не было иконки
                text = caption or ""  # Пустая строка, если нет caption
                data = {
                    "text": text,
                    "attachments": [{
                        "type": "image",
                        "payload": {
                            "token": token
                        }
                    }]
                }
                if parse_mode:
                    # MAX API использует "format" вместо "parse_mode"
                    data["format"] = parse_mode
                
                await max_api_limiter.wait_if_needed(f"max_api_{chat_id}")
                
                # Пробуем отправить с повторными попытками при ошибке attachment.not.ready
                max_retries = 3
                retry_delay = 2
                
                for attempt in range(max_retries):
                    try:
                        response = await retry_with_backoff(
                            self.client.post,
                            f"/messages?chat_id={chat_id_value}",
                            json=data
                        )
                        response.raise_for_status()
                        result = response.json()
                        
                        # Проверяем на ошибку attachment.not.ready
                        if 'error' in result or 'errors' in result:
                            error_msg = str(result.get('error', result.get('errors', '')))
                            if 'attachment.not.ready' in error_msg.lower() or 'not.ready' in error_msg.lower():
                                if attempt < max_retries - 1:
                                    logger.warning(f"attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2  # Увеличиваем задержку
                                    continue
                        
                        logger.info("photo_sent", chat_id=chat_id, message_id=result.get("message_id"), result=result)
                        return result
                    except httpx.HTTPStatusError as e:
                        if e.response:
                            try:
                                error_data = e.response.json()
                                error_msg = str(error_data)
                                if 'attachment.not.ready' in error_msg.lower() or 'not.ready' in error_msg.lower():
                                    if attempt < max_retries - 1:
                                        logger.warning(f"attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                        await asyncio.sleep(retry_delay)
                                        retry_delay *= 2
                                        continue
                            except:
                                pass
                        if attempt == max_retries - 1:
                            raise
                    except Exception as e:
                        if attempt == max_retries - 1:
                            raise
                        logger.warning(f"retry_after_error", attempt=attempt+1, error=str(e))
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                
            except Exception as e:
                logger.error("failed_to_send_photo_via_upload", chat_id=chat_id, error=str(e))
                raise
        
        # Fallback: старая логика с URL (может не работать)
        text = caption or ""  # Пустая строка, если нет caption
        data = {
            "text": text,
            "content": {
                "type": "image",
                "src": photo_url
            }
        }
        
        try:
            await max_api_limiter.wait_if_needed(f"max_api_{chat_id}")
            # Используем правильный формат: chat_id в query parameter
            response = await retry_with_backoff(
                self.client.post,
                f"/messages?chat_id={chat_id_value}",
                json=data
            )
            response.raise_for_status()
            result = response.json()
            logger.info("photo_sent", chat_id=chat_id, message_id=result.get("message_id"), result=result)
            return result
        except httpx.HTTPStatusError as e:
            # Логируем детальную информацию об ошибке
            error_response = None
            try:
                if e.response:
                    error_response = e.response.json()
                    logger.error(
                        "failed_to_send_photo",
                        chat_id=chat_id,
                        status_code=e.response.status_code,
                        error_response=error_response,
                        request_data=data
                    )
            except:
                error_response = e.response.text if e.response else None
                logger.error(
                    "failed_to_send_photo",
                    chat_id=chat_id,
                    status_code=e.response.status_code if e.response else None,
                    error_response=error_response,
                    request_data=data
                )
            raise APIError(
                f"HTTP ошибка при отправке фото: {e.response.status_code}",
                status_code=e.response.status_code,
                response=error_response
            )
        except httpx.RequestError as e:
            logger.error("failed_to_send_photo", chat_id=chat_id, error=str(e))
            raise APIError(f"Ошибка сети при отправке фото: {e}")
        except Exception as e:
            logger.error("failed_to_send_photo", chat_id=chat_id, error=str(e))
            raise APIError(f"Неожиданная ошибка при отправке фото: {e}")
    
    async def send_photos(
        self,
        chat_id: str,
        local_file_paths: List[str],
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отправить несколько фото в одном сообщении (альбом).
        
        Args:
            chat_id: ID канала в MAX
            local_file_paths: Список путей к локальным файлам фото
            caption: Подпись к альбому (будет только у первого фото в Telegram)
        
        Returns:
            Информация об отправленном сообщении
        """
        if not local_file_paths:
            raise APIError("Список файлов пуст")
        
        # Преобразуем chat_id в правильный формат для query parameter
        try:
            if isinstance(chat_id, str) and (chat_id.lstrip('-').isdigit() or chat_id.lstrip('-').replace('.', '').isdigit()):
                chat_id_value = int(float(chat_id))
            elif isinstance(chat_id, (int, float)):
                chat_id_value = int(chat_id)
            else:
                chat_id_value = chat_id
        except (ValueError, TypeError):
            chat_id_value = chat_id
        
        try:
            # Загружаем все фото и получаем токены
            tokens = []
            for file_path in local_file_paths:
                token = await self.upload_file(file_path, "image")
                tokens.append(token)
                # Небольшая задержка между загрузками
                await asyncio.sleep(0.5)
            
            # Ждем обработки всех файлов
            await asyncio.sleep(2)
            
            # Формируем запрос с массивом attachments
            text = caption or ""  # Пустая строка, если нет caption
            data = {
                "text": text,
                "attachments": [
                    {
                        "type": "image",
                        "payload": {
                            "token": token
                        }
                    }
                    for token in tokens
                ]
            }
            if parse_mode:
                # MAX API использует "format" вместо "parse_mode"
                data["format"] = parse_mode
            
            await max_api_limiter.wait_if_needed(f"max_api_{chat_id}")
            
            # Пробуем отправить с повторными попытками при ошибке attachment.not.ready
            max_retries = 3
            retry_delay = 2
            
            for attempt in range(max_retries):
                try:
                    response = await retry_with_backoff(
                        self.client.post,
                        f"/messages?chat_id={chat_id_value}",
                        json=data
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    # Проверяем на ошибку attachment.not.ready
                    if 'error' in result or 'errors' in result:
                        error_msg = str(result.get('error', result.get('errors', '')))
                        if 'attachment.not.ready' in error_msg.lower() or 'not.ready' in error_msg.lower():
                            if attempt < max_retries - 1:
                                logger.warning(f"attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2  # Увеличиваем задержку
                                continue
                    
                    logger.info(
                        "photos_sent",
                        chat_id=chat_id,
                        photos_count=len(tokens),
                        message_id=result.get("message_id"),
                        result=result
                    )
                    return result
                except httpx.HTTPStatusError as e:
                    if e.response:
                        try:
                            error_data = e.response.json()
                            error_msg = str(error_data)
                            if 'attachment.not.ready' in error_msg.lower() or 'not.ready' in error_msg.lower():
                                if attempt < max_retries - 1:
                                    logger.warning(f"attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2
                                    continue
                        except:
                            pass
                    if attempt == max_retries - 1:
                        raise
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"retry_after_error", attempt=attempt+1, error=str(e))
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
        
        except Exception as e:
            logger.error("failed_to_send_photos", chat_id=chat_id, error=str(e))
            raise APIError(f"Неожиданная ошибка при отправке фото: {e}")
    
    async def get_chat(self, chat_id: str) -> Dict[str, Any]:
        """
        Получить информацию о чате/канале.
        
        Args:
            chat_id: ID чата/канала (может быть строковый идентификатор или числовой ID)
        
        Returns:
            Информация о чате
        """
        try:
            await max_api_limiter.wait_if_needed(f"max_api_{chat_id}")
            # Пробуем сначала числовой ID, если передан строковый
            try:
                numeric_id = int(chat_id)
                response = await retry_with_backoff(
                    self.client.get,
                    f"/chats/{numeric_id}"
                )
            except (ValueError, TypeError):
                # Если не числовой, используем как есть
                response = await retry_with_backoff(
                    self.client.get,
                    f"/chats/{chat_id}"
                )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("failed_to_get_chat", chat_id=chat_id, status_code=e.response.status_code, error=str(e))
            raise APIError(
                f"HTTP ошибка при получении информации о чате: {e.response.status_code}",
                status_code=e.response.status_code,
                response=e.response.json() if e.response else None
            )
        except httpx.RequestError as e:
            logger.error("failed_to_get_chat", chat_id=chat_id, error=str(e))
            raise APIError(f"Ошибка сети при получении информации о чате: {e}")
        except Exception as e:
            logger.error("failed_to_get_chat", chat_id=chat_id, error=str(e))
            raise APIError(f"Неожиданная ошибка при получении информации о чате: {e}")
    
    async def get_available_chats(self) -> List[Dict[str, Any]]:
        """
        Получить список доступных чатов/каналов для бота.
        
        Returns:
            Список чатов/каналов
        """
        try:
            await max_api_limiter.wait_if_needed("max_api_chats_list")
            response = await retry_with_backoff(
                self.client.get,
                "/chats"
            )
            response.raise_for_status()
            result = response.json()
            return result.get('chats', [])
        except httpx.HTTPStatusError as e:
            logger.error("failed_to_get_chats", status_code=e.response.status_code, error=str(e))
            raise APIError(
                f"HTTP ошибка при получении списка чатов: {e.response.status_code}",
                status_code=e.response.status_code,
                response=e.response.json() if e.response else None
            )
        except httpx.RequestError as e:
            logger.error("failed_to_get_chats", error=str(e))
            raise APIError(f"Ошибка сети при получении списка чатов: {e}")
        except Exception as e:
            logger.error("failed_to_get_chats", error=str(e))
            raise APIError(f"Неожиданная ошибка при получении списка чатов: {e}")

