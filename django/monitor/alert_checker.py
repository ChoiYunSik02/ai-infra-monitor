"""
주기적으로 최신 메트릭을 읽어 임계값 초과 시 Telegram 알림 발송.
Ollama 미사용 — 순수 알림 전용.
"""
import logging
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30  # 초마다 체크


def _get_threshold():
    from monitor.models import AlertThreshold
    try:
        obj, _ = AlertThreshold.objects.get_or_create(id=1)
        return obj
    except Exception:
        return None


def _cooldown_ok(alert_type: str, cooldown_min: int) -> bool:
    """쿨다운 체크 — True면 알림 발송 가능."""
    from monitor.models import AlertCooldown
    try:
        cd = AlertCooldown.objects.get(alert_type=alert_type)
        return datetime.now() > cd.last_sent_at + timedelta(minutes=cooldown_min)
    except AlertCooldown.DoesNotExist:
        return True


def _mark_sent(alert_type: str):
    from monitor.models import AlertCooldown
    AlertCooldown.objects.update_or_create(
        alert_type=alert_type,
        defaults={'last_sent_at': datetime.now()},
    )


def _send_alert(alert_type: str, message: str):
    """Telegram 발송 + TelegramBotLog + AlertHistory 저장."""
    import os, requests
    from monitor.models import AlertHistory, TelegramBotLog

    token   = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID',   '')

    try:
        TelegramBotLog.objects.create(alert_type=alert_type, message=message)
    except Exception as e:
        logger.warning("TelegramBotLog save failed: %s", e)

    if token and chat_id:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": message},
                timeout=10,
            )
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)


def _alert_if_exceeded(key: str, value, threshold, unit: str, label: str, cooldown_min: int):
    if value is None:
        return
    value = float(value)
    if value > threshold and _cooldown_ok(key, cooldown_min):
        icon = "🔴" if value > threshold * 1.1 else "🟡"
        msg = f"{icon} [알림] {label} 초과\n현재값: {value:.1f}{unit} / 임계값: {threshold:.1f}{unit}"
        _send_alert(key, msg)
        _mark_sent(key)

        from monitor.models import AlertHistory
        try:
            AlertHistory.objects.create(
                alert_type=key,
                threshold=threshold,
                actual_value=value,
                message=msg,
            )
        except Exception as e:
            logger.warning("AlertHistory save failed: %s", e)


def check_vmware(th):
    from monitor.models import SystemMetric
    try:
        m = SystemMetric.objects.order_by('-recorded_at').first()
        if not m:
            return
        _alert_if_exceeded('vm_cpu',  m.cpu_usage,    th.vm_cpu_pct,  '%', 'VMware CPU 사용률',  th.cooldown_min)
        _alert_if_exceeded('vm_ram',  m.mem_percent,  th.vm_ram_pct,  '%', 'VMware RAM 사용률',  th.cooldown_min)
        _alert_if_exceeded('vm_disk', m.disk_percent, th.vm_disk_pct, '%', 'VMware 디스크 사용률', th.cooldown_min)
    except Exception as e:
        logger.warning("VMware check error: %s", e)


def check_windows(th):
    from monitor.views import _get_mongo_collection
    try:
        col = _get_mongo_collection('windows_metrics')
        if col is None:
            return
        doc = col.find_one(sort=[('_id', -1)])
        if not doc:
            return
        cpu = doc.get('cpu', {})
        gpu = doc.get('gpu', {})
        mem = doc.get('memory', {})
        _alert_if_exceeded('win_cpu_pct',   cpu.get('usage_pct'),    th.win_cpu_pct,   '%',  'Windows CPU 사용률',  th.cooldown_min)
        _alert_if_exceeded('win_cpu_temp',  cpu.get('temp_package_c'), th.win_cpu_temp_c, '°C', 'Windows CPU 온도',   th.cooldown_min)
        _alert_if_exceeded('win_gpu_pct',   gpu.get('usage_pct'),    th.win_gpu_pct,   '%',  'Windows GPU 사용률',  th.cooldown_min)
        _alert_if_exceeded('win_gpu_temp',  gpu.get('temp_c'),       th.win_gpu_temp_c, '°C', 'Windows GPU 온도',   th.cooldown_min)
        _alert_if_exceeded('win_vram',      gpu.get('mem_pct'),      th.win_vram_pct,  '%',  'Windows VRAM 사용률', th.cooldown_min)
        _alert_if_exceeded('win_ram',       mem.get('percent'),      th.win_ram_pct,   '%',  'Windows RAM 사용률',  th.cooldown_min)
    except Exception as e:
        logger.warning("Windows check error: %s", e)


def _run():
    time.sleep(15)  # 서버 초기 기동 대기
    while True:
        try:
            th = _get_threshold()
            if th:
                check_vmware(th)
                check_windows(th)
        except Exception as e:
            logger.warning("Alert checker error: %s", e)
        time.sleep(CHECK_INTERVAL)


def start():
    t = threading.Thread(target=_run, daemon=True, name="alert-checker")
    t.start()
    logger.info("Alert checker thread started (every %ds)", CHECK_INTERVAL)
