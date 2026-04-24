"""
Telegram 폴링 봇 — 알림 전용 (Ollama 미사용).
/vmware → VMware 상태만
/windows → Windows 상태만
/status  → 전체 요약
알림은 alert_checker.py 에서 발송.
"""
import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)

TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID',   '')

HELP_TEXT = (
    "🤖 <b>AI Infra Monitor 알림 봇</b>\n\n"
    "이 봇은 임계값 초과 시 자동 알림을 발송합니다.\n\n"
    "<b>명령어</b>\n"
    "/vmware  — VMware Zorin OS 현재 상태\n"
    "/windows — Windows 노트북 현재 상태\n"
    "/status  — 전체 시스템 요약\n"
    "/thresh  — 현재 임계값 확인\n"
    "/help    — 이 도움말\n\n"
    "⚙️ 임계값 설정은 대시보드 → 알림 이력 탭에서 가능합니다."
)


# ── Telegram API 헬퍼 ─────────────────────────────────
def _api(method: str, timeout: int = 12, **kwargs) -> dict:
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    try:
        r = requests.post(url, timeout=timeout, **kwargs)
        return r.json()
    except Exception as e:
        logger.debug("Telegram API [%s]: %s", method, e)
        return {}


def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> dict:
    return _api("sendMessage",
                data={"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


def send_typing(chat_id: str):
    _api("sendChatAction", data={"chat_id": chat_id, "action": "typing"})


# ── VMware 상태 ───────────────────────────────────────
def _vmware_status() -> str:
    try:
        from monitor.models import SystemMetric, AlertThreshold
        m  = SystemMetric.objects.order_by('-recorded_at').first()
        th = AlertThreshold.objects.get_or_create(id=1)[0]
        if not m:
            return "🐧 <b>VMware Zorin OS</b>\n데이터 없음 — Node-RED 확인 필요"

        def icon(val, warn, crit):
            return "🔴" if val > crit else "🟡" if val > warn else "🟢"

        cpu_i  = icon(m.cpu_usage,   th.vm_cpu_pct  * 0.75, th.vm_cpu_pct)
        ram_i  = icon(m.mem_percent, th.vm_ram_pct  * 0.85, th.vm_ram_pct)
        disk_i = icon(m.disk_percent,th.vm_disk_pct * 0.85, th.vm_disk_pct)

        return (
            f"🐧 <b>VMware Zorin OS</b>\n"
            f"{cpu_i} CPU:   {m.cpu_usage:.1f}%  (임계: {th.vm_cpu_pct:.0f}%)\n"
            f"{ram_i} RAM:   {m.mem_percent:.1f}%  (임계: {th.vm_ram_pct:.0f}%)\n"
            f"{disk_i} DISK: {m.disk_percent:.1f}%  (임계: {th.vm_disk_pct:.0f}%)\n"
            f"⏱ 수집: {m.recorded_at.strftime('%H:%M:%S')}"
        )
    except Exception as e:
        return f"🐧 VMware 오류: {e}"


# ── Windows 상태 ──────────────────────────────────────
def _windows_status() -> str:
    try:
        from monitor.views import _get_mongo_collection
        from monitor.models import AlertThreshold
        col = _get_mongo_collection('windows_metrics')
        if col is None:
            return "🖥️ <b>Windows 노트북</b>\nMongoDB 연결 불가"
        doc = col.find_one(sort=[('_id', -1)])
        if not doc:
            return "🖥️ <b>Windows 노트북</b>\n에이전트 오프라인"

        th  = AlertThreshold.objects.get_or_create(id=1)[0]
        cpu = doc.get('cpu', {})
        gpu = doc.get('gpu', {})
        mem = doc.get('memory', {})
        ts  = (doc.get('timestamp', '')[:19]).replace('T', ' ')

        def icon(val, warn, crit):
            if val is None: return "⚪"
            return "🔴" if float(val) > crit else "🟡" if float(val) > warn else "🟢"

        def fmt(v, u='%', d=1):
            return f"{float(v):.{d}f}{u}" if v is not None else "N/A"

        return (
            f"🖥️ <b>Windows 노트북</b>  ({doc.get('hostname','?')})\n"
            f"{icon(cpu.get('usage_pct'),     th.win_cpu_pct  *0.75, th.win_cpu_pct)}  CPU:      {fmt(cpu.get('usage_pct'))}  (임계: {th.win_cpu_pct:.0f}%)\n"
            f"{icon(cpu.get('temp_package_c'),th.win_cpu_temp_c*0.9, th.win_cpu_temp_c)}  CPU 온도: {fmt(cpu.get('temp_package_c'),'°C')}  (임계: {th.win_cpu_temp_c:.0f}°C)\n"
            f"{icon(gpu.get('usage_pct'),     th.win_gpu_pct  *0.75, th.win_gpu_pct)}  GPU:      {fmt(gpu.get('usage_pct'))}  (임계: {th.win_gpu_pct:.0f}%)\n"
            f"{icon(gpu.get('temp_c'),        th.win_gpu_temp_c*0.9, th.win_gpu_temp_c)}  GPU 온도: {fmt(gpu.get('temp_c'),'°C')}  (임계: {th.win_gpu_temp_c:.0f}°C)\n"
            f"{icon(gpu.get('mem_pct'),       th.win_vram_pct *0.85, th.win_vram_pct)}  VRAM:     {fmt(gpu.get('mem_pct'))}  (임계: {th.win_vram_pct:.0f}%)\n"
            f"{icon(mem.get('percent'),       th.win_ram_pct  *0.85, th.win_ram_pct)}  RAM:      {fmt(mem.get('percent'))}  (임계: {th.win_ram_pct:.0f}%)\n"
            f"⏱ 수집: {ts}"
        )
    except Exception as e:
        return f"🖥️ Windows 오류: {e}"


# ── 임계값 현황 ───────────────────────────────────────
def _thresh_status() -> str:
    try:
        from monitor.models import AlertThreshold
        th = AlertThreshold.objects.get_or_create(id=1)[0]
        return (
            f"⚙️ <b>현재 임계값 설정</b>\n\n"
            f"🐧 VMware\n"
            f"  CPU: {th.vm_cpu_pct:.0f}%  RAM: {th.vm_ram_pct:.0f}%  DISK: {th.vm_disk_pct:.0f}%\n\n"
            f"🖥️ Windows\n"
            f"  CPU: {th.win_cpu_pct:.0f}%  CPU온도: {th.win_cpu_temp_c:.0f}°C\n"
            f"  GPU: {th.win_gpu_pct:.0f}%  GPU온도: {th.win_gpu_temp_c:.0f}°C\n"
            f"  VRAM: {th.win_vram_pct:.0f}%  RAM: {th.win_ram_pct:.0f}%\n\n"
            f"⏱ 쿨다운: {th.cooldown_min}분"
        )
    except Exception as e:
        return f"임계값 조회 오류: {e}"


# ── 메시지 처리 ───────────────────────────────────────
def _handle(update: dict):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id = str(msg["chat"]["id"])
    text    = msg.get("text", "").strip()
    if not text:
        return

    send_typing(chat_id)

    if text in ("/start", "/help"):
        send_message(chat_id, HELP_TEXT)

    elif text == "/vmware":
        send_message(chat_id, _vmware_status())

    elif text == "/windows":
        send_message(chat_id, _windows_status())

    elif text == "/status":
        send_message(chat_id, _vmware_status() + "\n\n" + _windows_status())

    elif text == "/thresh":
        send_message(chat_id, _thresh_status())

    else:
        send_message(
            chat_id,
            "❓ 알 수 없는 명령어입니다.\n/help 를 입력해 명령어를 확인하세요.\n\n"
            "💬 AI 채팅은 대시보드 웹페이지에서 이용 가능합니다.",
            parse_mode="",
        )


# ── 폴링 루프 ─────────────────────────────────────────
def _poll_loop():
    if not TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot disabled")
        return

    logger.info("Telegram bot polling started")
    offset = 0
    while True:
        try:
            data = _api("getUpdates", timeout=15,
                        data={"offset": offset, "timeout": 10,
                              "allowed_updates": ["message"]})
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                _handle(update)
        except Exception as e:
            logger.warning("Poll error: %s", e)
            time.sleep(5)


def start():
    t = threading.Thread(target=_poll_loop, daemon=True, name="telegram-bot")
    t.start()
    logger.info("Telegram bot thread started")
