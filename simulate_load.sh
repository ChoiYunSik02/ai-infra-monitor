#!/bin/bash
# 시스템 부하 시뮬레이터 - 그래프를 역동적으로 만들기 위한 스크립트
# Ctrl+C 로 종료

TMPDIR=/tmp/aim_sim
mkdir -p $TMPDIR

cleanup() {
    echo "시뮬레이터 종료 중..."
    kill $(pgrep -f "simulate_load") 2>/dev/null
    kill $(jobs -p) 2>/dev/null
    rm -rf $TMPDIR
    exit 0
}
trap cleanup SIGINT SIGTERM

cpu_spike() {
    local cores=$1
    local duration=$2
    echo "[CPU] ${cores}코어 ${duration}초 부하"
    for i in $(seq 1 $cores); do
        timeout $duration yes > /dev/null 2>&1 &
    done
}

mem_spike() {
    local mb=$1
    local duration=$2
    echo "[MEM] ${mb}MB ${duration}초 점유"
    python3 -c "
import time
data = bytearray($mb * 1024 * 1024)
time.sleep($duration)
" &
}

disk_io() {
    echo "[DISK] 디스크 I/O 발생"
    dd if=/dev/zero of=$TMPDIR/test bs=1M count=50 2>/dev/null
    rm -f $TMPDIR/test
}

TOTAL_CORES=$(nproc)
echo "======================================"
echo "  AI Infra Monitor 부하 시뮬레이터"
echo "  코어 수: $TOTAL_CORES | Ctrl+C 로 종료"
echo "======================================"

CYCLE=0
while true; do
    CYCLE=$((CYCLE + 1))
    RAND=$((RANDOM % 100))

    echo "--- 사이클 $CYCLE (난수: $RAND) ---"

    if [ $RAND -lt 20 ]; then
        # 20% 확률: 강한 CPU 스파이크
        CORES=$((TOTAL_CORES > 1 ? TOTAL_CORES - 1 : 1))
        cpu_spike $CORES $((RANDOM % 6 + 5))
        sleep $((RANDOM % 5 + 8))

    elif [ $RAND -lt 45 ]; then
        # 25% 확률: 중간 CPU 부하
        CORES=$((TOTAL_CORES / 2 + 1))
        cpu_spike $CORES $((RANDOM % 5 + 3))
        sleep $((RANDOM % 4 + 5))

    elif [ $RAND -lt 60 ]; then
        # 15% 확률: 메모리 스파이크
        MB=$((RANDOM % 400 + 200))
        DURATION=$((RANDOM % 8 + 5))
        mem_spike $MB $DURATION
        sleep $((RANDOM % 5 + 6))

    elif [ $RAND -lt 70 ]; then
        # 10% 확률: CPU + 메모리 동시
        cpu_spike $((TOTAL_CORES / 2)) $((RANDOM % 4 + 3))
        mem_spike $((RANDOM % 200 + 100)) $((RANDOM % 5 + 4))
        sleep $((RANDOM % 6 + 7))

    elif [ $RAND -lt 78 ]; then
        # 8% 확률: 디스크 I/O
        disk_io
        sleep $((RANDOM % 3 + 3))

    else
        # 나머지: 조용한 구간 (그래프가 내려가게)
        echo "[IDLE] 안정 구간"
        sleep $((RANDOM % 6 + 4))
    fi

    # 잔여 백그라운드 작업 정리
    wait 2>/dev/null
done
