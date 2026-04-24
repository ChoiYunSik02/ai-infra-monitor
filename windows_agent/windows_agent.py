"""
Windows Laptop Hardware Monitoring Agent - Full Edition
LHM DLL (exe 없이) + pynvml + win32pdh + psutil

AssemblyResolve 핸들러로 lib/ 폴더의 의존성 DLL을 직접 로드.
LibreHardwareMonitor.exe 실행 불필요.
관리자 권한 필요 (CPU 온도/전력 수집).
"""

import json
import os
import platform
import socket
import sys
import threading
import time
from datetime import datetime

import psutil
import requests

# ── 설정 ──────────────────────────────────────────────────────────────────────
DJANGO_URL = "http://192.168.0.37:8000/api/windows/"
INTERVAL   = 5
HOSTNAME   = socket.gethostname()
LIB_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
# ─────────────────────────────────────────────────────────────────────────────

# ── LHM DLL 초기화 (exe 없이) ─────────────────────────────────────────────────
_lhm_computer = None
_lhm_ok       = False

def _init_lhm():
    global _lhm_computer, _lhm_ok

    dll_path = os.path.join(LIB_DIR, "LibreHardwareMonitorLib.dll")
    if not os.path.exists(dll_path):
        print("[LHM] LibreHardwareMonitorLib.dll 없음")
        return

    try:
        import clr
        from System import AppDomain
        from System.Reflection import Assembly

        # AssemblyResolve: CLR이 못 찾는 DLL을 lib/ 에서 직접 로드
        # UnsafeLoadFrom: 인터넷에서 다운받은 DLL의 Zone 보안 차단(0x80131515) 우회
        def _resolve(sender, args):
            name = str(args.Name).split(',')[0].strip()
            path = os.path.join(LIB_DIR, name + '.dll')
            if os.path.exists(path):
                return Assembly.UnsafeLoadFrom(path)
            return None

        AppDomain.CurrentDomain.AssemblyResolve += _resolve

        Assembly.UnsafeLoadFrom(dll_path)
        from LibreHardwareMonitor.Hardware import Computer

        comp = Computer()
        comp.IsCpuEnabled = True
        comp.IsGpuEnabled = True
        comp.Open()
        _lhm_computer = comp
        _lhm_ok = True
        print("[LHM] DLL 초기화 완료 ✓")

    except Exception as e:
        import traceback
        print(f"[LHM] DLL 초기화 실패 — 정확한 오류:")
        traceback.print_exc()

_init_lhm()


# ── LHM 센서 수집 백그라운드 스레드 ──────────────────────────────────────────
_lhm_cache      = {}
_lhm_cache_lock = threading.Lock()

def _lhm_collect_thread():
    """LHM Computer 객체에서 직접 센서 데이터를 5초마다 수집."""
    while True:
        if not _lhm_ok or _lhm_computer is None:
            time.sleep(5)
            continue
        try:
            cpu_temps  = []
            cpu_clocks = []
            cpu        = {}
            gpu        = {}

            for hw in _lhm_computer.Hardware:
                hw.Update()
                for sub in hw.SubHardware:
                    sub.Update()

                hw_type = str(hw.HardwareType)

                # hw 자신 + 서브 하드웨어 센서 모두 수집
                sensors = list(hw.Sensors)
                for sub in hw.SubHardware:
                    sensors.extend(list(sub.Sensors))

                for s in sensors:
                    if s.Value is None:
                        continue
                    val   = float(s.Value)
                    stype = str(s.SensorType)
                    name  = str(s.Name)

                    if "Cpu" in hw_type:
                        if stype == "Temperature":
                            if "Package" in name:
                                # Package 센서 최우선 — 한 번 설정되면 다른 값으로 덮어쓰지 않음
                                cpu["temp_package_c"] = round(val, 1)
                            elif any(k in name for k in ("Tctl", "Die")) \
                                    and "temp_package_c" not in cpu:
                                cpu["temp_package_c"] = round(val, 1)
                            elif "Core" in name or "CCD" in name:
                                cpu_temps.append(round(val, 1))
                        elif stype == "Power":
                            if "Package" in name:
                                cpu["power_package_w"] = round(val, 1)
                            elif "Core" in name and "power_cores_w" not in cpu:
                                cpu["power_cores_w"] = round(val, 1)
                        elif stype == "Clock" and "Core" in name:
                            cpu_clocks.append(round(val, 0))

                    elif "Gpu" in hw_type:
                        if stype == "Temperature":
                            if "Core" in name or "GPU" in name:
                                gpu["temp_c"] = round(val, 1)
                        elif stype == "Power":
                            if any(k in name for k in
                                   ("Package", "Board", "TGP", "GPU Power")):
                                gpu["power_w"] = round(val, 1)
                            elif "power_w" not in gpu:
                                gpu["power_w"] = round(val, 1)
                        elif stype == "Clock":
                            if "Core" in name or "GPU Core" in name:
                                gpu["clock_core_mhz"] = round(val, 0)
                            elif "Memory" in name or "Mem" in name:
                                gpu["clock_mem_mhz"] = round(val, 0)
                            elif ("Shader" in name or "Boost" in name) \
                                    and "clock_core_mhz" not in gpu:
                                gpu["clock_core_mhz"] = round(val, 0)
                        elif stype == "Load":
                            if "Core" in name or "GPU Core" in name:
                                gpu["usage_pct"] = round(val, 1)
                        elif stype == "Fan":
                            gpu["fan_pct"] = round(val, 1)

            if cpu_temps:
                cpu["temp_cores_c"] = cpu_temps
                if "temp_package_c" not in cpu:
                    cpu["temp_package_c"] = round(max(cpu_temps), 1)
            if cpu_clocks:
                cpu["clock_max_mhz"]   = max(cpu_clocks)
                cpu["clock_cores_mhz"] = cpu_clocks

            with _lhm_cache_lock:
                _lhm_cache["cpu"] = cpu
                _lhm_cache["gpu"] = gpu

        except Exception as e:
            print(f"[LHM] 센서 수집 오류: {e}")
        time.sleep(5)

if _lhm_ok:
    threading.Thread(target=_lhm_collect_thread, daemon=True).start()


# ── pynvml (NVIDIA GPU) ───────────────────────────────────────────────────────
_nvml_ok = False
try:
    import pynvml
    pynvml.nvmlInit()
    _nvml_ok = True
    print("[NVML] pynvml 초기화 완료 ✓")
except Exception:
    pass


# ── win32pdh (CPU 유효 클럭) ──────────────────────────────────────────────────
_pdh_query = _pdh_counter = None
_pdh_ok    = False

def _init_pdh():
    global _pdh_query, _pdh_counter, _pdh_ok
    try:
        import win32pdh
        q = win32pdh.OpenQuery()
        c = win32pdh.AddCounter(
            q, r"\Processor Information(_Total)\% Processor Performance")
        win32pdh.CollectQueryData(q)
        _pdh_query, _pdh_counter, _pdh_ok = q, c, True
        print("[PDH] win32pdh 초기화 완료 ✓")
    except Exception as e:
        print(f"[PDH] 초기화 실패: {e}")

_init_pdh()


# ── WMI 백그라운드 스레드 (RAM 클럭/용량 + CPU ACPI 온도) ────────────────────
_wmi_ram_mhz         = None
_wmi_ram_physical_gb = None
_wmi_cpu_temp_c      = None   # LHM 없을 때 fallback

def _wmi_worker():
    global _wmi_ram_mhz, _wmi_ram_physical_gb, _wmi_cpu_temp_c
    try:
        import pythoncom, wmi
        pythoncom.CoInitialize()
        c = wmi.WMI()

        # RAM 물리 용량 + 클럭
        sticks = list(c.Win32_PhysicalMemory())
        speeds = [int(m.Speed) for m in sticks if m.Speed]
        if speeds:
            _wmi_ram_mhz = max(speeds)
        total = sum(int(m.Capacity) for m in sticks if m.Capacity)
        if total:
            _wmi_ram_physical_gb = round(total / 1024**3, 2)
            print(f"[WMI-RAM] 물리 RAM: {_wmi_ram_physical_gb} GB  클럭: {_wmi_ram_mhz} MHz")

        # CPU ACPI 온도 (LHM fallback) — 주기적 갱신
        acpi = wmi.WMI(namespace="root/wmi")
        print("[WMI-TEMP] ACPI 온도 센서 시작")
        while True:
            try:
                temps = []
                for t in acpi.MSAcpi_ThermalZoneTemperature():
                    val = (float(t.CurrentTemperature) / 10.0) - 273.15
                    if 0 < val < 120:
                        temps.append(val)
                if temps:
                    _wmi_cpu_temp_c = round(max(temps), 1)
            except Exception:
                pass
            time.sleep(5)

    except Exception as e:
        print(f"[WMI] 오류: {e}")

threading.Thread(target=_wmi_worker, daemon=True).start()


# =============================================================================
# 수집 함수들
# =============================================================================

def _cpu_clock():
    if not _pdh_ok:
        f = psutil.cpu_freq()
        return round(f.current, 0) if f else None
    try:
        import win32pdh
        win32pdh.CollectQueryData(_pdh_query)
        _, pct = win32pdh.GetFormattedCounterValue(
            _pdh_counter, win32pdh.PDH_FMT_DOUBLE)
        f = psutil.cpu_freq()
        return round((f.max if f else 0) * pct / 100, 0)
    except Exception:
        f = psutil.cpu_freq()
        return round(f.current, 0) if f else None


def _collect_cpu():
    freq = psutil.cpu_freq()
    return {
        "model":              platform.processor(),
        "physical":           psutil.cpu_count(logical=False),
        "logical":            psutil.cpu_count(logical=True),
        "usage_pct":          psutil.cpu_percent(interval=1),
        "usage_per_core":     psutil.cpu_percent(interval=None, percpu=True),
        "freq_effective_mhz": _cpu_clock(),
        "freq_base_mhz":      round(freq.max,     0) if freq else None,
        "freq_current_mhz":   round(freq.current, 0) if freq else None,
    }


def _collect_gpu_nvidia():
    if not _nvml_ok:
        return {}
    try:
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        def _s(fn, *a, default=None):
            try: return fn(*a)
            except: return default

        util  = _s(pynvml.nvmlDeviceGetUtilizationRates, h)
        mem   = _s(pynvml.nvmlDeviceGetMemoryInfo, h)
        temp  = _s(pynvml.nvmlDeviceGetTemperature, h, pynvml.NVML_TEMPERATURE_GPU)
        clks  = _s(pynvml.nvmlDeviceGetClockInfo, h, pynvml.NVML_CLOCK_GRAPHICS)
        clkm  = _s(pynvml.nvmlDeviceGetClockInfo, h, pynvml.NVML_CLOCK_MEM)
        power = _s(pynvml.nvmlDeviceGetPowerUsage, h)
        plim  = _s(pynvml.nvmlDeviceGetPowerManagementLimit, h)
        fan   = _s(pynvml.nvmlDeviceGetFanSpeed, h)
        name  = _s(pynvml.nvmlDeviceGetName, h, default=b"")
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")

        return {
            "name":           name,
            "usage_pct":      util.gpu    if util else None,
            "mem_usage_pct":  util.memory if util else None,
            "temp_c":         float(temp) if temp is not None else None,
            "clock_core_mhz": clks,
            "clock_mem_mhz":  clkm,
            "power_w":        round(power / 1000, 1) if power is not None else None,
            "power_limit_w":  round(plim  / 1000, 1) if plim  is not None else None,
            "mem_used_mb":    round(mem.used  / 1024**2, 1) if mem else None,
            "mem_total_mb":   round(mem.total / 1024**2, 1) if mem else None,
            "mem_pct":        round(mem.used / mem.total * 100, 1)
                              if mem and mem.total else None,
            "fan_pct":        fan,
        }
    except Exception as e:
        print(f"[NVML] 오류: {e}")
        return {}


def _collect_memory():
    mem  = psutil.virtual_memory()
    swap = psutil.swap_memory()
    physical_total = _wmi_ram_physical_gb or round(mem.total / 1024**3, 2)
    used_gb        = round(mem.total / 1024**3, 2) - round(mem.available / 1024**3, 2)
    used_pct       = round(used_gb / physical_total * 100, 1) if physical_total else mem.percent
    return {
        "total_gb":      physical_total,
        "used_gb":       round(used_gb, 2),
        "available_gb":  round(mem.available / 1024**3, 2),
        "percent":       used_pct,
        "clock_mhz":     _wmi_ram_mhz,
        "swap_total_gb": round(swap.total / 1024**3, 2),
        "swap_used_gb":  round(swap.used  / 1024**3, 2),
        "swap_percent":  swap.percent,
    }


def _collect_disks():
    result = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
            result.append({
                "device":     part.device,
                "mountpoint": part.mountpoint,
                "fstype":     part.fstype,
                "total_gb":   round(u.total / 1024**3, 2),
                "used_gb":    round(u.used  / 1024**3, 2),
                "free_gb":    round(u.free  / 1024**3, 2),
                "percent":    u.percent,
            })
        except PermissionError:
            pass
    return result


def _collect_network():
    result = {}
    for nic, s in psutil.net_io_counters(pernic=True).items():
        if s.bytes_sent == 0 and s.bytes_recv == 0:
            continue
        result[nic] = {
            "bytes_sent":   s.bytes_sent,
            "bytes_recv":   s.bytes_recv,
            "packets_sent": s.packets_sent,
            "packets_recv": s.packets_recv,
            "errin":        s.errin,
            "errout":       s.errout,
        }
    return result


def collect():
    cpu_data = _collect_cpu()
    gpu_data = _collect_gpu_nvidia()

    with _lhm_cache_lock:
        lhm_cpu = dict(_lhm_cache.get("cpu", {}))
        lhm_gpu = dict(_lhm_cache.get("gpu", {}))

    cpu_data.update(lhm_cpu)

    # LHM으로 온도를 못 읽었으면 WMI ACPI fallback
    if cpu_data.get("temp_package_c") is None and _wmi_cpu_temp_c is not None:
        cpu_data["temp_package_c"] = _wmi_cpu_temp_c

    for k, v in lhm_gpu.items():
        if gpu_data.get(k) is None:
            gpu_data[k] = v

    return {
        "hostname":    HOSTNAME,
        "os":          f"{platform.system()} {platform.release()}",
        "timestamp":   datetime.utcnow().isoformat() + "Z",
        "boot_time":   datetime.fromtimestamp(psutil.boot_time()).isoformat(),
        "lhm_active":  _lhm_ok,
        "nvml_active": _nvml_ok,
        "cpu":         cpu_data,
        "gpu":         gpu_data,
        "memory":      _collect_memory(),
        "disks":       _collect_disks(),
        "network":     _collect_network(),
    }


def main():
    print("=" * 55)
    print(" Windows Hardware Monitor Agent (Full Edition)")
    print(f" Target : {DJANGO_URL}")
    print(f" Host   : {HOSTNAME}")
    print(f" LHM    : {'✓ (DLL, exe 없이)' if _lhm_ok else '✗ (lib/LibreHardwareMonitorLib.dll 필요)'}")
    print(f" NVML   : {'✓ (NVIDIA GPU)' if _nvml_ok else '✗'}")
    print(f" PDH    : {'✓ (유효클럭)' if _pdh_ok else '✗'}")
    print("=" * 55)

    while True:
        try:
            data = collect()
            cpu  = data["cpu"]
            mem  = data["memory"]
            gpu  = data.get("gpu", {})
            resp = requests.post(DJANGO_URL, json=data, timeout=10)

            ts       = datetime.now().strftime("%H:%M:%S")
            cpu_pct  = cpu.get("usage_pct",       0)
            cpu_tmp  = cpu.get("temp_package_c")
            cpu_clk  = cpu.get("freq_effective_mhz")
            cpu_pwr  = cpu.get("power_package_w")
            mem_used = mem.get("used_gb",          0)
            mem_tot  = mem.get("total_gb",         0)
            mem_pct  = mem.get("percent",          0)
            gpu_pct  = gpu.get("usage_pct")
            gpu_tmp  = gpu.get("temp_c")
            gpu_clk  = gpu.get("clock_core_mhz")
            gpu_pwr  = gpu.get("power_w")

            parts = [
                f"CPU {cpu_pct:4.1f}%",
                f"{cpu_tmp:.1f}C"    if cpu_tmp is not None else "--.-C",
                f"{int(cpu_clk)}MHz" if cpu_clk is not None else "----MHz",
                f"{cpu_pwr:.1f}W"    if cpu_pwr is not None else "--.-W",
                f"MEM {mem_used:.1f}/{mem_tot:.1f}GB({mem_pct:.0f}%)",
            ]
            if gpu_pct is not None: parts.append(f"GPU {gpu_pct:.0f}%")
            if gpu_tmp is not None: parts.append(f"{gpu_tmp:.1f}C")
            if gpu_clk is not None: parts.append(f"{int(gpu_clk)}MHz")
            if gpu_pwr is not None: parts.append(f"{gpu_pwr:.1f}W")

            print(f"[{ts}] {' | '.join(parts)}  -> HTTP {resp.status_code}")

        except requests.exceptions.ConnectionError:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Connection error - retrying...")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
