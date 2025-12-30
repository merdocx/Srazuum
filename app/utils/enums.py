"""Перечисления для статусов и типов."""
from enum import Enum


class MessageStatus(str, Enum):
    """Статусы сообщений."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class MessageType(str, Enum):
    """Типы сообщений."""
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    STICKER = "sticker"
    VIDEO_NOTE = "video_note"
    LOCATION = "location"
    CONTACT = "contact"
    POLL = "poll"


class AuditAction(str, Enum):
    """Действия в аудите."""
    CREATE_LINK = "create_link"
    DELETE_LINK = "delete_link"
    ENABLE_LINK = "enable_link"
    DISABLE_LINK = "disable_link"
    UPDATE_LINK = "update_link"



