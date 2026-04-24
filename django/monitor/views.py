import json
import requests
from datetime import datetime

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import SystemMetric, AiAnalysis, AlertHistory, ChatMessage, AlertThreshold, TelegramBotLog

try:
    from pymongo import MongoClient
    _mongo_client = MongoClient(
        host=settings.MONGODB_HOST,
        port=settings.MONGODB_PORT,
        username=settings.MONGODB_USER,
        password=settings.MONGODB_PASSWORD,
        serverSelectionTimeoutMS=3000,
    )
    _mongo_db = _mongo_client[settings.MONGODB_DB]
    _mongo_ok = True
except Exception:
    _mongo_ok = False
    _mongo_db = None


def _get_mongo_collection(name='metrics_raw'):
    if not _mongo_ok or _mongo_db is None:
        return None
    try:
        _mongo_client.admin.command('ping')
        return _mongo_db[name]
    except Exception:
        return None


def dashboard(request):
    latest         = SystemMetric.objects.first()
    recent_metrics = SystemMetric.objects.all()[:20]
    recent_analysis = AiAnalysis.objects.all()[:5]
    recent_alerts  = AlertHistory.objects.all()[:10]
    chat_history   = ChatMessage.objects.using('local').all()[:50]

    col = _get_mongo_collection()
    mongo_count = 0
    if col is not None:
        try:
            mongo_count = col.count_documents({})
        except Exception:
            pass

    context = {
        'latest':          latest,
        'recent_metrics':  recent_metrics,
        'recent_analysis': recent_analysis,
        'recent_alerts':   recent_alerts,
        'chat_history':    chat_history,
        'mongo_count':     mongo_count,
        'mongo_ok':        _mongo_ok,
        'ollama_host':     settings.OLLAMA_HOST,
        'ollama_model':    settings.OLLAMA_MODEL,
    }
    return render(request, 'monitor/dashboard.html', context)


def api_metrics(request):
    metrics = list(
        SystemMetric.objects.values(
            'id', 'hostname', 'cpu_usage', 'mem_percent', 'disk_percent',
            'net_bytes_sent', 'net_bytes_recv', 'recorded_at'
        )[:100]
    )
    for m in metrics:
        m['recorded_at'] = m['recorded_at'].strftime('%Y-%m-%d %H:%M:%S')
    return JsonResponse({'metrics': metrics})


def api_analysis(request):
    items = list(
        AiAnalysis.objects.values(
            'id', 'severity', 'title', 'analysis', 'suggestion', 'created_at'
        )[:20]
    )
    for item in items:
        item['created_at'] = item['created_at'].strftime('%Y-%m-%d %H:%M:%S')
    return JsonResponse({'analysis': items})


def api_alerts(request):
    # 알림 통계용: n8n_check 제외, 최신 200건
    exclude = {'n8n_check'}
    alerts = list(
        AlertHistory.objects.exclude(alert_type__in=exclude)
        .values('id', 'alert_type', 'threshold', 'actual_value', 'message', 'triggered_at')
        .order_by('-triggered_at')[:200]
    )
    for a in alerts:
        a['triggered_at'] = a['triggered_at'].strftime('%Y-%m-%d %H:%M:%S')
    return JsonResponse({'alerts': alerts})


def api_alerts_stats(request):
    """alert_type별 집계 카운트 반환."""
    from django.db.models import Count
    # 구형 타입 → 신형 타입 매핑
    TYPE_MAP = {'cpu_high': 'vm_cpu', 'disk_high': 'vm_disk', 'mem_high': 'vm_ram'}
    exclude = {'n8n_check'}
    rows = (
        AlertHistory.objects
        .exclude(alert_type__in=exclude)
        .values('alert_type')
        .annotate(cnt=Count('id'))
    )
    counts = {}
    for r in rows:
        t = TYPE_MAP.get(r['alert_type'], r['alert_type'])
        counts[t] = counts.get(t, 0) + r['cnt']
    return JsonResponse({'counts': counts})


@csrf_exempt
@require_http_methods(['POST'])
def api_log(request):
    """Node-RED가 호출 → MongoDB에 원시 메트릭 로그 저장."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'invalid json'}, status=400)

    data['timestamp'] = datetime.now().isoformat()
    data['source']    = 'node-red'

    col = _get_mongo_collection()
    if col is not None:
        try:
            col.insert_one(data)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    else:
        return JsonResponse({'error': 'MongoDB unavailable'}, status=503)

    return JsonResponse({'ok': True})


def api_logs(request):
    """MongoDB에서 최근 로그 조회."""
    col = _get_mongo_collection()
    if col is None:
        return JsonResponse({'logs': [], 'error': 'MongoDB unavailable'})

    try:
        limit = int(request.GET.get('limit', 50))
        docs = list(col.find({}, {'_id': 0}).sort('timestamp', -1).limit(limit))
        return JsonResponse({'logs': docs, 'total': col.count_documents({})})
    except Exception as e:
        return JsonResponse({'logs': [], 'error': str(e)})


@csrf_exempt
@require_http_methods(['POST'])
def api_analyze(request):
    """최신 메트릭으로 Ollama AI 분석 실행."""
    try:
        latest = SystemMetric.objects.first()
        if not latest:
            return JsonResponse({'error': '수집된 메트릭 데이터가 없습니다.'}, status=404)

        prompt = f"""당신은 리눅스 서버 모니터링 전문가입니다. 다음 시스템 메트릭을 분석해주세요.

서버: {latest.hostname}
CPU 사용률: {latest.cpu_usage:.1f}%
메모리 사용률: {latest.mem_percent:.1f}% ({latest.mem_used_gb()}GB / {latest.mem_total_gb()}GB)
디스크 사용률: {latest.disk_percent:.1f}% ({latest.disk_used_gb()}GB / {latest.disk_total_gb()}GB)
측정 시각: {latest.recorded_at}

위 수치를 기반으로:
1. 현재 서버 상태 평가 (정상/주의/위험)
2. 문제가 있다면 원인 분석
3. 개선 방안 제시

한국어로 간결하게 답변해주세요."""

        response = requests.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120
        )

        if response.status_code != 200:
            return JsonResponse({'error': 'Ollama 응답 오류'}, status=500)

        ai_text = response.json().get('response', '')
        cpu, mem, disk = latest.cpu_usage, latest.mem_percent, latest.disk_percent

        if cpu > 80 or mem > 85 or disk > 90:
            severity = 'critical'
        elif cpu > 60 or mem > 70 or disk > 75:
            severity = 'warning'
        else:
            severity = 'info'

        analysis = AiAnalysis.objects.create(
            metric=latest,
            severity=severity,
            title=f"AI 분석 — CPU:{cpu:.0f}% MEM:{mem:.0f}% DISK:{disk:.0f}%",
            analysis=ai_text,
        )

        return JsonResponse({
            'severity':   severity,
            'title':      analysis.title,
            'analysis':   ai_text,
            'created_at': analysis.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    except requests.exceptions.ConnectionError:
        return JsonResponse({'error': 'Ollama 서버에 연결할 수 없습니다. Windows 호스트에서 Ollama가 실행 중인지 확인하세요.'}, status=503)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(['POST'])
def api_analyze_windows(request):
    """최신 Windows 메트릭으로 Ollama AI 분석 실행."""
    col = _get_mongo_collection('windows_metrics')
    if col is None:
        return JsonResponse({'error': 'MongoDB unavailable'}, status=503)
    try:
        doc = col.find_one(sort=[('_id', -1)])
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    if not doc:
        return JsonResponse({'error': 'Windows 메트릭 데이터가 없습니다.'}, status=404)

    cpu = doc.get('cpu', {})
    gpu = doc.get('gpu', {})
    mem = doc.get('memory', {})

    prompt = f"""당신은 Windows 시스템 및 하드웨어 모니터링 전문가입니다. 다음 메트릭을 분석해주세요.

호스트: {doc.get('hostname', 'unknown')} / OS: {doc.get('os', 'Windows')}

CPU 모델: {cpu.get('model', 'N/A')}
CPU 사용률: {cpu.get('usage_pct', 0):.1f}%  |  온도: {cpu.get('temp_package_c', 'N/A')}°C  |  전력: {cpu.get('power_package_w', 'N/A')}W  |  클럭: {cpu.get('freq_effective_mhz', 'N/A')}MHz

GPU 사용률: {gpu.get('usage_pct', 0):.1f}%  |  온도: {gpu.get('temp_c', 'N/A')}°C  |  전력: {gpu.get('power_w', 'N/A')}W  |  VRAM: {gpu.get('mem_pct', 0):.1f}%

메모리 사용률: {mem.get('percent', 0):.1f}%

위 수치를 기반으로:
1. 현재 시스템 상태 평가 (정상/주의/위험)
2. 문제가 있다면 원인 분석
3. 개선 방안 제시

한국어로 간결하게 답변해주세요."""

    try:
        response = requests.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120
        )
        if response.status_code != 200:
            return JsonResponse({'error': 'Ollama 응답 오류'}, status=500)

        ai_text = response.json().get('response', '')
        cpu_pct = float(cpu.get('usage_pct') or 0)
        gpu_pct = float(gpu.get('usage_pct') or 0)
        mem_pct = float(mem.get('percent') or 0)

        if cpu_pct > 80 or gpu_pct > 85 or mem_pct > 85:
            severity = 'critical'
        elif cpu_pct > 60 or gpu_pct > 70 or mem_pct > 70:
            severity = 'warning'
        else:
            severity = 'info'

        return JsonResponse({
            'severity':   severity,
            'title':      f"Windows AI 분석 — CPU:{cpu_pct:.0f}% GPU:{gpu_pct:.0f}% MEM:{mem_pct:.0f}%",
            'analysis':   ai_text,
            'created_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        })
    except requests.exceptions.ConnectionError:
        return JsonResponse({'error': 'Ollama 서버에 연결할 수 없습니다.'}, status=503)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(['POST'])
def api_chat(request):
    """Ollama와 대화 — SQLite에 히스토리 저장. system 파라미터로 vmware/windows 선택."""
    try:
        data    = json.loads(request.body)
        message = data.get('message', '').strip()
        if not message:
            return JsonResponse({'error': '메시지를 입력하세요.'}, status=400)

        system_type = data.get('system', 'vmware')
        system_ctx  = ''

        if system_type == 'windows':
            col = _get_mongo_collection('windows_metrics')
            if col is not None:
                try:
                    doc = col.find_one(sort=[('_id', -1)])
                    if doc:
                        c = doc.get('cpu', {})
                        g = doc.get('gpu', {})
                        m = doc.get('memory', {})
                        system_ctx = (
                            f"\n\n현재 Windows 컴퓨터 상태: "
                            f"CPU {float(c.get('usage_pct') or 0):.1f}% (온도:{c.get('temp_package_c','N/A')}°C, "
                            f"전력:{c.get('power_package_w','N/A')}W), "
                            f"GPU {float(g.get('usage_pct') or 0):.1f}% (온도:{g.get('temp_c','N/A')}°C, "
                            f"VRAM:{float(g.get('mem_pct') or 0):.1f}%), "
                            f"RAM {float(m.get('percent') or 0):.1f}%"
                        )
                except Exception:
                    pass
            role_desc = "당신은 Windows 시스템 및 하드웨어 전문가이자 친절한 AI 어시스턴트입니다."
        else:
            latest = SystemMetric.objects.first()
            if latest:
                system_ctx = (
                    f"\n\n현재 VMware Zorin OS 상태: CPU {latest.cpu_usage:.1f}%, "
                    f"메모리 {latest.mem_percent:.1f}%, 디스크 {latest.disk_percent:.1f}%"
                )
            role_desc = "당신은 임베디드 리눅스 및 VMware 가상화 전문가이자 친절한 AI 어시스턴트입니다."

        full_prompt = (
            role_desc
            + system_ctx
            + f"\n\n사용자 질문: {message}\n\n한국어로 답변해주세요."
        )

        ChatMessage.objects.using('local').create(role='user', content=message)

        response = requests.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={"model": settings.OLLAMA_MODEL, "prompt": full_prompt, "stream": False},
            timeout=120
        )

        if response.status_code != 200:
            return JsonResponse({'error': 'Ollama 응답 오류'}, status=500)

        ai_text = response.json().get('response', '').strip()
        ChatMessage.objects.using('local').create(role='assistant', content=ai_text)

        return JsonResponse({'response': ai_text, 'role': 'assistant'})

    except requests.exceptions.ConnectionError:
        return JsonResponse({'error': 'Ollama 서버에 연결할 수 없습니다.'}, status=503)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def api_chat_history(request):
    """SQLite 채팅 히스토리 조회."""
    msgs = list(
        ChatMessage.objects.using('local').values('role', 'content', 'created_at').order_by('created_at')[:100]
    )
    for m in msgs:
        m['created_at'] = m['created_at'].strftime('%Y-%m-%d %H:%M:%S')
    return JsonResponse({'messages': msgs})


@csrf_exempt
@require_http_methods(['DELETE'])
def api_chat_clear(request):
    """채팅 히스토리 초기화."""
    ChatMessage.objects.using('local').all().delete()
    return JsonResponse({'ok': True})


def _ensure_windows_sql_table():
    """MySQL에 windows_metrics_sql 테이블 없으면 생성."""
    try:
        with connection.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS windows_metrics_sql (
                    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
                    hostname      VARCHAR(100),
                    cpu_usage     FLOAT,
                    cpu_temp_c    FLOAT,
                    cpu_power_w   FLOAT,
                    cpu_clock_mhz INT,
                    gpu_usage     FLOAT,
                    gpu_temp_c    FLOAT,
                    gpu_power_w   FLOAT,
                    vram_pct      FLOAT,
                    ram_pct       FLOAT,
                    recorded_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_win_ts (recorded_at)
                )
            """)
    except Exception:
        pass

_ensure_windows_sql_table()


@csrf_exempt
@require_http_methods(['POST'])
def api_windows_receive(request):
    """Windows 에이전트에서 하드웨어 데이터 수신 → MongoDB + MySQL 저장."""
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid JSON'}, status=400)

    payload['_received_at'] = datetime.utcnow().isoformat() + 'Z'

    col = _get_mongo_collection('windows_metrics')
    if col is not None:
        col.insert_one(payload)
        payload.pop('_id', None)

    try:
        cpu = payload.get('cpu', {})
        gpu = payload.get('gpu', {})
        mem = payload.get('memory', {})
        with connection.cursor() as cur:
            cur.execute(
                """INSERT INTO windows_metrics_sql
                   (hostname, cpu_usage, cpu_temp_c, cpu_power_w, cpu_clock_mhz,
                    gpu_usage, gpu_temp_c, gpu_power_w, vram_pct, ram_pct)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [
                    payload.get('hostname', 'unknown'),
                    cpu.get('usage_pct'),
                    cpu.get('temp_package_c'),
                    cpu.get('power_package_w'),
                    cpu.get('freq_effective_mhz'),
                    gpu.get('usage_pct'),
                    gpu.get('temp_c'),
                    gpu.get('power_w'),
                    gpu.get('mem_pct'),
                    mem.get('percent'),
                ]
            )
    except Exception:
        pass

    return JsonResponse({'ok': True})


def api_windows_latest(request):
    """MongoDB에서 최신 Windows 메트릭 반환."""
    col = _get_mongo_collection('windows_metrics')
    if col is None:
        return JsonResponse({'error': 'MongoDB unavailable'}, status=503)
    try:
        doc = col.find_one(sort=[('_id', -1)])
        if doc is None:
            return JsonResponse({'error': 'no data'}, status=404)
        doc.pop('_id', None)
        return JsonResponse(doc)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def api_windows_history(request):
    """MongoDB에서 최근 N개 Windows 메트릭 반환 (차트용)."""
    limit = min(int(request.GET.get('limit', 60)), 200)
    col = _get_mongo_collection('windows_metrics')
    if col is None:
        return JsonResponse({'error': 'MongoDB unavailable'}, status=503)
    try:
        docs = list(col.find({}, {'_id': 0}).sort('_id', -1).limit(limit))
        docs.reverse()
        return JsonResponse({'data': docs, 'count': len(docs)})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def api_windows_logs(request):
    """MongoDB windows_metrics 컬렉션의 최근 로그 반환."""
    limit = min(int(request.GET.get('limit', 50)), 200)
    col = _get_mongo_collection('windows_metrics')
    if col is None:
        return JsonResponse({'logs': [], 'error': 'MongoDB unavailable'})
    try:
        docs = list(col.find({}, {'_id': 0}).sort('_id', -1).limit(limit))
        return JsonResponse({'logs': docs, 'total': col.count_documents({})})
    except Exception as e:
        return JsonResponse({'logs': [], 'error': str(e)})


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_thresholds(request):
    """임계값 조회(GET) / 저장(POST)."""
    th = AlertThreshold.get()
    if request.method == 'GET':
        return JsonResponse({
            'vm_cpu_pct':    th.vm_cpu_pct,
            'vm_ram_pct':    th.vm_ram_pct,
            'vm_disk_pct':   th.vm_disk_pct,
            'win_cpu_pct':   th.win_cpu_pct,
            'win_cpu_temp_c':th.win_cpu_temp_c,
            'win_gpu_pct':   th.win_gpu_pct,
            'win_gpu_temp_c':th.win_gpu_temp_c,
            'win_vram_pct':  th.win_vram_pct,
            'win_ram_pct':   th.win_ram_pct,
            'cooldown_min':  th.cooldown_min,
        })
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'invalid json'}, status=400)

    fields = ['vm_cpu_pct','vm_ram_pct','vm_disk_pct',
              'win_cpu_pct','win_cpu_temp_c','win_gpu_pct',
              'win_gpu_temp_c','win_vram_pct','win_ram_pct','cooldown_min']
    for f in fields:
        if f in data:
            setattr(th, f, data[f])
    th.save()
    return JsonResponse({'ok': True})


def api_bot_logs(request):
    """텔레그램 알림 발송 로그 조회."""
    limit = min(int(request.GET.get('limit', 50)), 200)
    logs = list(
        TelegramBotLog.objects.values('id', 'alert_type', 'message', 'created_at')[:limit]
    )
    for l in logs:
        l['created_at'] = l['created_at'].strftime('%Y-%m-%d %H:%M:%S')
    return JsonResponse({'logs': logs, 'total': TelegramBotLog.objects.count()})


def api_db_overview(request):
    """MySQL + MongoDB + SQLite 통합 DB 현황 반환."""
    result = {}

    # MySQL
    try:
        with connection.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = [row[0] for row in cur.fetchall()]
            table_counts = []
            for t in tables:
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                cnt = cur.fetchone()[0]
                table_counts.append({'name': t, 'count': cnt})
        result['mysql'] = {'tables': table_counts, 'ok': True}
    except Exception as e:
        result['mysql'] = {'ok': False, 'error': str(e)}

    # MongoDB
    if _mongo_ok and _mongo_db is not None:
        try:
            colls = _mongo_db.list_collection_names()
            coll_counts = []
            for c in colls:
                cnt = _mongo_db[c].count_documents({})
                coll_counts.append({'name': c, 'count': cnt})
            result['mongodb'] = {'collections': coll_counts, 'ok': True}
        except Exception as e:
            result['mongodb'] = {'ok': False, 'error': str(e)}
    else:
        result['mongodb'] = {'ok': False, 'error': 'MongoDB unavailable'}

    # SQLite
    try:
        from django.db import connections as _conns
        with _conns['local'].cursor() as cur:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [row[0] for row in cur.fetchall()]
            table_counts = []
            for t in tables:
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                    cnt = cur.fetchone()[0]
                    table_counts.append({'name': t, 'count': cnt})
                except Exception:
                    pass
        result['sqlite'] = {'tables': table_counts, 'ok': True}
    except Exception as e:
        result['sqlite'] = {'ok': False, 'error': str(e)}

    return JsonResponse(result)
