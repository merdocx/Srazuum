"""Клиент для работы с MAX API."""
import asyncio
import httpx
from typing import Optional, Dict, Any, List
from config.settings import settings
from app.utils.logger import get_logger
from app.utils.retry import retry_with_backoff
from app.utils.exceptions import APIError
from app.utils.rate_limiter import max_api_limiter
from app.utils.chat_id_converter import convert_chat_id

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
            timeout=settings.max_api_timeout,
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
        
        Raises:
            APIError: Если текст пустой или при ошибке API
        """
        # Проверяем, что текст не пустой
        if not text or not text.strip():
            raise APIError("Нельзя отправить пустое сообщение в MAX", status_code=400)
        
        # Преобразуем chat_id в правильный формат для query parameter
        chat_id_value = convert_chat_id(chat_id)
        
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
            token_from_response = upload_data.get("token")  # Token может быть уже в ответе
            
            if not upload_url:
                raise APIError("Не получен URL для загрузки файла", response=upload_data)
            
            logger.info("upload_url_received", upload_url=upload_url[:100], has_token=bool(token_from_response))
            
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
                # Определяем Content-Type в зависимости от типа файла
                content_type_map = {
                    "image": "image/jpeg",
                    "video": "video/mp4",
                    "document": "application/octet-stream",
                    "audio": "audio/mpeg"
                }
                content_type = content_type_map.get(file_type, "application/octet-stream")
                
                files = {"data": (file.name, f, content_type)}
                upload_client = httpx.AsyncClient(timeout=settings.max_api_upload_timeout)
                try:
                    upload_file_response = await upload_client.post(
                        upload_url,
                        files=files,
                        headers={"Authorization": self.token}
                    )
                    upload_file_response.raise_for_status()
                    
                    # Если token уже был в ответе от /uploads, используем его
                    if token_from_response:
                        token = token_from_response
                        logger.info("using_token_from_upload_response", file_path=file_path)
                    else:
                        # Иначе пытаемся извлечь token из ответа CDN
                        # Проверяем Content-Type ответа
                        content_type_header = upload_file_response.headers.get("content-type", "")
                        if "application/json" not in content_type_header.lower():
                            # Если ответ не JSON, пробуем прочитать как текст
                            response_text = upload_file_response.text
                            logger.warning(
                                "upload_response_not_json",
                                content_type=content_type_header,
                                response_preview=response_text[:200]
                            )
                            # Пробуем распарсить как JSON, даже если Content-Type не указан
                            try:
                                upload_result = upload_file_response.json()
                            except Exception:
                                # Если не JSON, возможно это HTML или другой формат
                                # Проверяем, может быть ответ содержит JSON внутри
                                import json
                                import re
                                # Пробуем найти JSON в ответе
                                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                                if json_match:
                                    upload_result = json.loads(json_match.group())
                                else:
                                    # Если ответ не JSON и token не был в первом ответе,
                                    # это может быть просто подтверждение загрузки (например, <retval>1</retval>)
                                    # В этом случае используем token из первого ответа, если он был
                                    if token_from_response:
                                        token = token_from_response
                                        logger.info("using_token_from_upload_response_after_cdn_confirm", file_path=file_path)
                                    else:
                                        raise APIError(f"Ответ от CDN не является JSON и token не найден: {response_text[:200]}")
                        else:
                            upload_result = upload_file_response.json()
                        
                        # Извлекаем token из структуры ответа
                        # Для фото: {"photos": {"photoId": {"token": "..."}}}
                        # Для видео: может быть {"videos": {...}} или {"photos": {...}}
                        token = None
                        
                        # Пробуем найти token в разных структурах
                        if "photos" in upload_result:
                            photos = upload_result.get("photos", {})
                            if photos:
                                # Используем первый photoId из URL или первый ключ в photos
                                photo_id = photo_ids[0] if photo_ids else list(photos.keys())[0]
                                photo_data = photos.get(photo_id)
                                if photo_data:
                                    token = photo_data.get("token")
                        
                        # Для видео может быть другая структура
                        if not token and "videos" in upload_result:
                            videos = upload_result.get("videos", {})
                            if videos:
                                # Аналогично для видео
                                video_id = list(videos.keys())[0]
                                video_data = videos.get(video_id)
                                if video_data:
                                    token = video_data.get("token")
                        
                        # Если token не найден, пробуем найти его напрямую в ответе
                        if not token:
                            token = upload_result.get("token")
                        
                        if not token:
                            logger.error("upload_result_structure", upload_result=upload_result)
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
        chat_id_value = convert_chat_id(chat_id)
        
        # ВАЖНО: MAX API требует загрузку файла через /uploads endpoint
        # Сначала загружаем файл, получаем token, затем используем его в content
        # После загрузки может потребоваться задержка для обработки файла
        if local_file_path:
            try:
                token = await self.upload_file(local_file_path, "image")
                
                # Адаптивная задержка после загрузки
                await asyncio.sleep(settings.media_processing_delay_photo)
                
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
    
    async def send_video(
        self,
        chat_id: str,
        video_url: str,
        caption: Optional[str] = None,
        local_file_path: Optional[str] = None,
        parse_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отправить видео в канал.
        
        Args:
            chat_id: ID канала в MAX
            video_url: URL видео (для fallback)
            caption: Подпись к видео
            local_file_path: Путь к локальному файлу видео
            parse_mode: Режим парсинга (HTML, Markdown)
        
        Returns:
            Информация об отправленном сообщении
        """
        # Преобразуем chat_id в правильный формат для query parameter
        chat_id_value = convert_chat_id(chat_id)
        
        # ВАЖНО: MAX API требует загрузку файла через /uploads endpoint
        # Сначала загружаем файл, получаем token, затем используем его в attachments
        # Видео может обрабатываться дольше, поэтому увеличиваем задержку
        if local_file_path:
            try:
                token = await self.upload_file(local_file_path, "video")
                
                # Адаптивная задержка для видео
                await asyncio.sleep(settings.media_processing_delay_video)
                
                # Формируем запрос с attachments и payload.token
                text = caption or ""  # Пустая строка, если нет caption
                data = {
                    "text": text,
                    "attachments": [{
                        "type": "video",
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
                max_retries = 5  # Для видео больше попыток
                retry_delay = 3  # Больше задержка для видео
                
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
                                    logger.warning(f"video_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2  # Увеличиваем задержку
                                    continue
                        
                        logger.info("video_sent", chat_id=chat_id, message_id=result.get("message_id"), result=result)
                        return result
                    except httpx.HTTPStatusError as e:
                        if e.response:
                            try:
                                error_data = e.response.json()
                                error_msg = str(error_data)
                                if 'attachment.not.ready' in error_msg.lower() or 'not.ready' in error_msg.lower():
                                    if attempt < max_retries - 1:
                                        logger.warning(f"video_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
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
                        logger.warning(f"video_retry_after_error", attempt=attempt+1, error=str(e))
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                
            except Exception as e:
                logger.error("failed_to_send_video_via_upload", chat_id=chat_id, error=str(e))
                raise
        
        # Fallback: отправка текста с упоминанием видео
        text = caption or "[Видео]"
        if caption:
            text = f"[Видео]\n{caption}"
        else:
            text = "[Видео]"
        
        data = {
            "text": text
        }
        if parse_mode:
            # MAX API использует "format" вместо "parse_mode"
            data["format"] = parse_mode
        
        try:
            await max_api_limiter.wait_if_needed(f"max_api_{chat_id}")
            response = await retry_with_backoff(
                self.client.post,
                f"/messages?chat_id={chat_id_value}",
                json=data
            )
            response.raise_for_status()
            result = response.json()
            logger.info("video_fallback_sent", chat_id=chat_id, message_id=result.get("message_id"))
            return result
        except httpx.HTTPStatusError as e:
            error_response = None
            try:
                if e.response:
                    error_response = e.response.json()
                    logger.error(
                        "failed_to_send_video",
                        chat_id=chat_id,
                        status_code=e.response.status_code,
                        error_response=error_response
                    )
            except:
                error_response = e.response.text if e.response else None
                logger.error(
                    "failed_to_send_video",
                    chat_id=chat_id,
                    status_code=e.response.status_code if e.response else None,
                    error_response=error_response
                )
            raise APIError(
                f"HTTP ошибка при отправке видео: {e.response.status_code}",
                status_code=e.response.status_code,
                response=error_response
            )
        except httpx.RequestError as e:
            logger.error("failed_to_send_video", chat_id=chat_id, error=str(e))
            raise APIError(f"Ошибка сети при отправке видео: {e}")
        except Exception as e:
            logger.error("failed_to_send_video", chat_id=chat_id, error=str(e))
            raise APIError(f"Неожиданная ошибка при отправке видео: {e}")
    
    async def send_document(
        self,
        chat_id: str,
        document_url: str,
        caption: Optional[str] = None,
        local_file_path: Optional[str] = None,
        parse_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отправить документ в канал.
        
        Args:
            chat_id: ID канала в MAX
            document_url: URL документа (для fallback)
            caption: Подпись к документу
            local_file_path: Путь к локальному файлу документа
            parse_mode: Режим парсинга (HTML, Markdown)
        
        Returns:
            Информация об отправленном сообщении
        """
        # Преобразуем chat_id в правильный формат для query parameter
        chat_id_value = convert_chat_id(chat_id)
        
        # ВАЖНО: MAX API требует загрузку файла через /uploads endpoint
        # Сначала загружаем файл, получаем token, затем используем его в attachments
        # ПРИМЕЧАНИЕ: MAX API не поддерживает type=document, используем type=file
        if local_file_path:
            try:
                token = await self.upload_file(local_file_path, "file")
                
                # Адаптивная задержка для документов
                await asyncio.sleep(settings.media_processing_delay_video)  # Используем ту же задержку, что и для видео
                
                # Формируем запрос с attachments и payload.token
                # ПРИМЕЧАНИЕ: MAX API использует "file" как attachment type для документов, а не "document"
                text = caption or ""  # Пустая строка, если нет caption
                data = {
                    "text": text,
                    "attachments": [{
                        "type": "file",
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
                max_retries = 5  # Для документов больше попыток
                retry_delay = 3  # Больше задержка для документов
                
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
                                    logger.warning(f"document_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2  # Увеличиваем задержку
                                    continue
                        
                        logger.info("document_sent", chat_id=chat_id, message_id=result.get("message_id"), result=result)
                        return result
                    except httpx.HTTPStatusError as e:
                        if e.response:
                            try:
                                error_data = e.response.json()
                                error_msg = str(error_data)
                                if 'attachment.not.ready' in error_msg.lower() or 'not.ready' in error_msg.lower():
                                    if attempt < max_retries - 1:
                                        logger.warning(f"document_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
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
                        logger.warning(f"document_retry_after_error", attempt=attempt+1, error=str(e))
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                
            except Exception as e:
                logger.error("failed_to_send_document_via_upload", chat_id=chat_id, error=str(e))
                raise
        
        # Fallback: отправка текста с упоминанием документа
        text = caption or "[Документ]"
        if caption:
            text = f"[Документ]\n{caption}"
        else:
            text = "[Документ]"
        
        data = {
            "text": text
        }
        if parse_mode:
            # MAX API использует "format" вместо "parse_mode"
            data["format"] = parse_mode
        
        try:
            await max_api_limiter.wait_if_needed(f"max_api_{chat_id}")
            response = await retry_with_backoff(
                self.client.post,
                f"/messages?chat_id={chat_id_value}",
                json=data
            )
            response.raise_for_status()
            result = response.json()
            logger.info("document_fallback_sent", chat_id=chat_id, message_id=result.get("message_id"))
            return result
        except httpx.HTTPStatusError as e:
            error_response = None
            try:
                if e.response:
                    error_response = e.response.json()
                    logger.error(
                        "failed_to_send_document",
                        chat_id=chat_id,
                        status_code=e.response.status_code,
                        error_response=error_response
                    )
            except:
                error_response = e.response.text if e.response else None
                logger.error(
                    "failed_to_send_document",
                    chat_id=chat_id,
                    status_code=e.response.status_code if e.response else None,
                    error_response=error_response
                )
            raise APIError(
                f"HTTP ошибка при отправке документа: {e.response.status_code}",
                status_code=e.response.status_code,
                response=error_response
            )
        except httpx.RequestError as e:
            logger.error("failed_to_send_document", chat_id=chat_id, error=str(e))
            raise APIError(f"Ошибка сети при отправке документа: {e}")
        except Exception as e:
            logger.error("failed_to_send_document", chat_id=chat_id, error=str(e))
            raise APIError(f"Неожиданная ошибка при отправке документа: {e}")
    
    async def send_sticker(
        self,
        chat_id: str,
        sticker_url: str,
        local_file_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отправить стикер в канал.
        
        Args:
            chat_id: ID канала в MAX
            sticker_url: URL стикера (для fallback)
            local_file_path: Путь к локальному файлу стикера
        
        Returns:
            Информация об отправленном сообщении
        """
        chat_id_value = convert_chat_id(chat_id)
        
        # ВАЖНО: MAX API требует загрузку файла через /uploads endpoint
        # Сначала загружаем файл, получаем token, затем используем его в attachments
        # Стикеры могут быть в формате WebP (статичные) или TGS (анимированные)
        # TGS файлы MAX API не поддерживает как изображения, поэтому отправляем fallback
        if local_file_path:
            # Проверяем расширение файла
            import os
            file_ext = os.path.splitext(local_file_path)[1].lower()
            
            # Если это TGS файл (анимированный стикер), MAX API не поддерживает его
            # Выбрасываем исключение, чтобы пост был пропущен
            if file_ext == '.tgs':
                logger.warning("tgs_sticker_not_supported_skipping", file_path=local_file_path, chat_id=chat_id)
                raise APIError("TGS стикеры (анимированные) не поддерживаются MAX API")
            
            # Для WebP стикеров пытаемся загрузить как изображение
            try:
                token = await self.upload_file(local_file_path, "image")
                
                # Задержка для обработки стикера
                await asyncio.sleep(settings.media_processing_delay)
                
                # Формируем запрос с attachments и payload.token
                # MAX API использует "image" как attachment type для стикеров
                data = {
                    "text": "",  # Пустая строка для стикеров
                    "attachments": [{
                        "type": "image",
                        "payload": {
                            "token": token
                        }
                    }]
                }
                
                await max_api_limiter.wait_if_needed(f"max_api_{chat_id}")
                
                # Пробуем отправить с повторными попытками при ошибке attachment.not.ready
                max_retries = 5
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
                                    logger.warning(f"sticker_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2
                                    continue
                        
                        logger.info("sticker_sent", chat_id=chat_id, message_id=result.get("message_id"), result=result)
                        return result
                    except httpx.HTTPStatusError as e:
                        if e.response:
                            try:
                                error_data = e.response.json()
                                error_msg = str(error_data)
                                if 'attachment.not.ready' in error_msg.lower() or 'not.ready' in error_msg.lower():
                                    if attempt < max_retries - 1:
                                        logger.warning(f"sticker_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
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
                        logger.warning(f"sticker_retry_after_error", attempt=attempt+1, error=str(e))
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                
            except Exception as e:
                logger.error("failed_to_send_sticker_via_upload", chat_id=chat_id, error=str(e))
                raise
        
        # Fallback: отправка текста с упоминанием стикера
        text = "[Стикер]"
        data = {
            "text": text
        }
        
        try:
            await max_api_limiter.wait_if_needed(f"max_api_{chat_id}")
            response = await retry_with_backoff(
                self.client.post,
                f"/messages?chat_id={chat_id_value}",
                json=data
            )
            response.raise_for_status()
            result = response.json()
            logger.info("sticker_fallback_sent", chat_id=chat_id, message_id=result.get("message_id"))
            return result
        except httpx.HTTPStatusError as e:
            error_response = None
            try:
                if e.response:
                    error_response = e.response.json()
                    logger.error(
                        "failed_to_send_sticker",
                        chat_id=chat_id,
                        status_code=e.response.status_code,
                        error_response=error_response
                    )
            except:
                error_response = e.response.text if e.response else None
                logger.error(
                    "failed_to_send_sticker",
                    chat_id=chat_id,
                    status_code=e.response.status_code if e.response else None,
                    error_response=error_response
                )
            raise APIError(
                f"HTTP ошибка при отправке стикера: {e.response.status_code}",
                status_code=e.response.status_code,
                response=error_response
            )
        except httpx.RequestError as e:
            logger.error("failed_to_send_sticker", chat_id=chat_id, error=str(e))
            raise APIError(f"Ошибка сети при отправке стикера: {e}")
        except Exception as e:
            logger.error("failed_to_send_sticker", chat_id=chat_id, error=str(e))
            raise APIError(f"Неожиданная ошибка при отправке стикера: {e}")
    
    async def send_photos(
        self,
        chat_id: str,
        local_file_paths: List[str],
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отправить несколько фото в одном сообщении (альбом).
        
        ВАЖНО: Нет ограничений на количество фото - отправляются ВСЕ файлы из списка.
        Батчинг используется только для оптимизации загрузки, не для ограничения количества.
        
        Args:
            chat_id: ID канала в MAX
            local_file_paths: Список путей к локальным файлам фото (без ограничений по количеству)
            caption: Подпись к альбому (будет только у первого фото в Telegram)
        
        Returns:
            Информация об отправленном сообщении
        """
        if not local_file_paths:
            raise APIError("Список файлов пуст")
        
        # Преобразуем chat_id в правильный формат для query parameter
        chat_id_value = convert_chat_id(chat_id)
        
        try:
            # Батчинг загрузок медиа
            tokens = []
            batch_size = settings.batch_size_media_uploads
            for i in range(0, len(local_file_paths), batch_size):
                batch = local_file_paths[i:i + batch_size]
                # Параллельная загрузка батча
                batch_tokens = await asyncio.gather(*[
                    self.upload_file(file_path, "image")
                    for file_path in batch
                ])
                tokens.extend(batch_tokens)
                # Адаптивная задержка между батчами
                if i + batch_size < len(local_file_paths):
                    await asyncio.sleep(settings.media_upload_delay_photo)
            
            # Адаптивная задержка обработки (зависит от количества файлов)
            processing_delay = min(
                settings.media_processing_delay_photo * (1 + len(tokens) * 0.1),
                10.0  # Максимум 10 секунд
            )
            await asyncio.sleep(processing_delay)
            
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
    
    async def send_videos(
        self,
        chat_id: str,
        local_file_paths: List[str],
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отправить несколько видео в одном сообщении (альбом).
        
        ВАЖНО: Нет ограничений на количество видео - отправляются ВСЕ файлы из списка.
        Батчинг используется только для оптимизации загрузки, не для ограничения количества.
        
        Args:
            chat_id: ID канала в MAX
            local_file_paths: Список путей к локальным файлам видео (без ограничений по количеству)
            caption: Подпись к альбому
            parse_mode: Режим парсинга (HTML, Markdown)
        
        Returns:
            Информация об отправленном сообщении
        """
        if not local_file_paths:
            raise APIError("Список файлов пуст")
        
        # Преобразуем chat_id в правильный формат для query parameter
        chat_id_value = convert_chat_id(chat_id)
        
        try:
            # Батчинг загрузок медиа
            tokens = []
            batch_size = settings.batch_size_media_uploads
            for i in range(0, len(local_file_paths), batch_size):
                batch = local_file_paths[i:i + batch_size]
                # Параллельная загрузка батча
                batch_tokens = await asyncio.gather(*[
                    self.upload_file(file_path, "video")
                    for file_path in batch
                ])
                tokens.extend(batch_tokens)
                # Адаптивная задержка между батчами (для видео больше)
                if i + batch_size < len(local_file_paths):
                    await asyncio.sleep(settings.media_upload_delay_video)
            
            # Адаптивная задержка обработки (зависит от количества файлов)
            processing_delay = min(
                settings.media_processing_delay_video * (1 + len(tokens) * 0.15),
                15.0  # Максимум 15 секунд для видео
            )
            await asyncio.sleep(processing_delay)
            
            # Формируем запрос с массивом attachments
            text = caption or ""  # Пустая строка, если нет caption
            data = {
                "text": text,
                "attachments": [
                    {
                        "type": "video",
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
            max_retries = 5  # Для видео больше попыток
            retry_delay = 3  # Больше задержка для видео
            
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
                                logger.warning(f"videos_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2  # Увеличиваем задержку
                                continue
                    
                    logger.info(
                        "videos_sent",
                        chat_id=chat_id,
                        videos_count=len(tokens),
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
                                    logger.warning(f"videos_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
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
                    logger.warning(f"videos_retry_after_error", attempt=attempt+1, error=str(e))
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
            
        except httpx.HTTPStatusError as e:
            error_response = None
            try:
                if e.response:
                    error_response = e.response.json()
                    logger.error(
                        "failed_to_send_videos",
                        chat_id=chat_id,
                        status_code=e.response.status_code,
                        error_response=error_response
                    )
            except:
                error_response = e.response.text if e.response else None
                logger.error(
                    "failed_to_send_videos",
                    chat_id=chat_id,
                    status_code=e.response.status_code if e.response else None,
                    error_response=error_response
                )
            raise APIError(
                f"HTTP ошибка при отправке видео: {e.response.status_code}",
                status_code=e.response.status_code,
                response=error_response
            )
        except httpx.RequestError as e:
            logger.error("failed_to_send_videos", chat_id=chat_id, error=str(e))
            raise APIError(f"Ошибка сети при отправке видео: {e}")
        except Exception as e:
            logger.error("failed_to_send_videos", chat_id=chat_id, error=str(e))
            raise APIError(f"Неожиданная ошибка при отправке видео: {e}")
    
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

