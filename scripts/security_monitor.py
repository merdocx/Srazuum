"""Скрипт для мониторинга безопасности: проверка логов на подозрительную активность."""

import asyncio
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import sys

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Импорт настроек (опционально, не критично для работы скрипта)
try:
    from config.settings import settings
except ImportError:
    settings = None

# Паттерны для поиска секретов в логах
SECRET_PATTERNS = [
    r'password["\s:=]+[^\s"\']+',
    r'token["\s:=]+[A-Za-z0-9_-]{20,}',
    r'secret["\s:=]+[A-Za-z0-9_-]{20,}',
    r'api_key["\s:=]+[A-Za-z0-9_-]{20,}',
    r'apikey["\s:=]+[A-Za-z0-9_-]{20,}',
    r'private_key["\s:=]+[A-Za-z0-9_-]{20,}',
    r'TELEGRAM_BOT_TOKEN["\s:=]+[A-Za-z0-9:_-]{20,}',
    r'DATABASE_URL["\s:=]+postgresql[^\s"\']+',
    r'session_string["\s:=]+[A-Za-z0-9_-]{50,}',
]

# Паттерны для подозрительной активности
SUSPICIOUS_PATTERNS = [
    r'(?i)unauthorized',
    r'(?i)401',
    r'(?i)403',
    r'(?i)forbidden',
    r'(?i)failed.*login',
    r'(?i)authentication.*failed',
    r'(?i)invalid.*token',
    r'(?i)invalid.*credentials',
    r'(?i)brute.*force',
    r'(?i)rate.*limit.*exceeded',
]


def check_logs_for_secrets(log_lines: List[str]) -> List[Dict[str, str]]:
    """Проверить логи на наличие секретов."""
    findings = []
    for line_num, line in enumerate(log_lines, 1):
        for pattern in SECRET_PATTERNS:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                findings.append({
                    'type': 'secret_exposed',
                    'line': line_num,
                    'pattern': pattern,
                    'match': match.group()[:50] + '...' if len(match.group()) > 50 else match.group(),
                    'context': line[:200],
                })
    return findings


def check_logs_for_suspicious_activity(log_lines: List[str]) -> List[Dict[str, str]]:
    """Проверить логи на подозрительную активность."""
    findings = []
    for line_num, line in enumerate(log_lines, 1):
        for pattern in SUSPICIOUS_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append({
                    'type': 'suspicious_activity',
                    'line': line_num,
                    'pattern': pattern,
                    'context': line[:200],
                })
    return findings


def get_recent_logs(service_name: str, hours: int = 24) -> List[str]:
    """Получить последние логи systemd сервиса."""
    try:
        since_time = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
        result = subprocess.run(
            ['journalctl', '-u', service_name, '--since', since_time, '--no-pager'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return result.stdout.split('\n')
        return []
    except Exception as e:
        print(f"Ошибка при получении логов {service_name}: {e}")
        return []


def check_file_permissions(file_path: Path) -> Optional[Dict[str, str]]:
    """Проверить права доступа к файлу."""
    try:
        stat = file_path.stat()
        mode = oct(stat.st_mode)[-3:]
        if mode != '600' and file_path.name == '.env':
            return {
                'type': 'insecure_permissions',
                'file': str(file_path),
                'current_mode': mode,
                'expected_mode': '600',
            }
    except Exception:
        pass
    return None


async def main():
    """Основная функция мониторинга безопасности."""
    print("=" * 60)
    print("Мониторинг безопасности")
    print("=" * 60)
    print(f"Время проверки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    all_findings = []

    # 1. Проверка прав доступа к .env файлу
    print("1. Проверка прав доступа к .env файлу...")
    env_file = PROJECT_ROOT / '.env'
    if env_file.exists():
        perm_issue = check_file_permissions(env_file)
        if perm_issue:
            all_findings.append(perm_issue)
            print(f"   ⚠️  Проблема: {perm_issue['file']} имеет права {perm_issue['current_mode']}, ожидается {perm_issue['expected_mode']}")
        else:
            print(f"   ✅ {env_file} имеет правильные права доступа (600)")
    else:
        print(f"   ⚠️  Файл {env_file} не найден")
    print()

    # 2. Проверка логов на секреты
    print("2. Проверка логов на наличие секретов...")
    services = ['crossposting-admin.service', 'crossposting-bot.service', 'crossposting-mtproto.service']
    for service in services:
        logs = get_recent_logs(service, hours=24)
        if logs:
            secrets = check_logs_for_secrets(logs)
            if secrets:
                all_findings.extend(secrets)
                print(f"   ⚠️  {service}: найдено {len(secrets)} возможных утечек секретов")
                for finding in secrets[:3]:  # Показываем только первые 3
                    print(f"      - Строка {finding['line']}: {finding['match']}")
            else:
                print(f"   ✅ {service}: секреты в логах не обнаружены")
    print()

    # 3. Проверка на подозрительную активность
    print("3. Проверка логов на подозрительную активность...")
    auth_issues_count = {}
    for service in services:
        logs = get_recent_logs(service, hours=24)
        if logs:
            suspicious = check_logs_for_suspicious_activity(logs)
            if suspicious:
                all_findings.extend(suspicious)
                auth_issues = [s for s in suspicious if '401' in s.get('context', '') or 'unauthorized' in s.get('context', '').lower()]
                if auth_issues:
                    auth_issues_count[service] = len(auth_issues)
                print(f"   ⚠️  {service}: найдено {len(suspicious)} подозрительных записей")
                if auth_issues:
                    print(f"      - Из них {len(auth_issues)} неудачных попыток авторизации")
            else:
                print(f"   ✅ {service}: подозрительная активность не обнаружена")
    print()

    # 4. Статистика по неудачным попыткам входа
    if auth_issues_count:
        print("4. Статистика по неудачным попыткам входа:")
        for service, count in auth_issues_count.items():
            print(f"   ⚠️  {service}: {count} неудачных попыток за последние 24 часа")
            if count > 10:
                print(f"      🚨 КРИТИЧНО: Более 10 неудачных попыток - возможна атака!")
    else:
        print("4. Статистика по неудачным попыткам входа:")
        print("   ✅ Неудачные попытки входа не обнаружены")
    print()

    # Итоговый отчет
    print("=" * 60)
    if all_findings:
        print(f"⚠️  ВНИМАНИЕ: Обнаружено {len(all_findings)} проблем безопасности")
        print("\nРекомендации:")
        print("1. Проверьте логи на наличие утечек секретов")
        print("2. Убедитесь, что .env файлы имеют права 600")
        print("3. При большом количестве неудачных попыток входа - заблокируйте IP")
        return 1
    else:
        print("✅ Проблем безопасности не обнаружено")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
