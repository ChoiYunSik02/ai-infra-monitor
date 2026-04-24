이 폴더에 LibreHardwareMonitorLib.dll 을 넣으면
CPU 온도 / 패키지 전력 / 코어 클럭을 수집할 수 있습니다.

다운로드 방법:
  1. https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases
  2. 최신 버전 zip 다운로드
  3. zip 안의 LibreHardwareMonitorLib.dll 을 이 폴더에 복사
  4. run_agent.bat 를 관리자 권한으로 실행

DLL 없이도 동작하지만:
  - CPU 온도 / 전력  → 수집 불가
  - CPU 클럭 → psutil 기반 (정밀도 낮음)
  - NVIDIA GPU 정보 → pynvml로 정상 수집 (DLL 불필요)
