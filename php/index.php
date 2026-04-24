<?php
/* ── MySQL 연결 ─────────────────────────────────────── */
$host     = getenv('MYSQL_HOST')     ?: 'mysql';
$dbname   = getenv('MYSQL_DATABASE') ?: 'infra_monitor';
$user     = getenv('MYSQL_USER')     ?: 'monitor_user';
$password = getenv('MYSQL_PASSWORD') ?: 'monitor_pass123';

$error = null; $history = []; $wstats = null;

/* ── Windows 에이전트 API ─────────────────────────────── */
$win = null; $win_online = false;
$ch = curl_init('http://django:8000/api/windows/latest/');
curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER=>true, CURLOPT_TIMEOUT=>3, CURLOPT_CONNECTTIMEOUT=>2]);
$wjson = curl_exec($ch);
$wcode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);
if ($wcode === 200 && $wjson) {
    $win = json_decode($wjson, true);
    $win_online = isset($win['cpu']) && !isset($win['error']);
}
$wcpu  = $win_online ? ($win['cpu']     ?? []) : [];
$wgpu  = $win_online ? ($win['gpu']     ?? []) : [];
$wmem  = $win_online ? ($win['memory']  ?? []) : [];
$wdsk  = $win_online ? ($win['disks']   ?? []) : [];
$wnet  = $win_online ? ($win['network'] ?? []) : [];

/* ── MySQL (history + stats) ────────────────────────── */
try {
    $pdo = new PDO("mysql:host=$host;dbname=$dbname;charset=utf8mb4", $user, $password,
        [PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION, PDO::ATTR_TIMEOUT=>3]);

    /* 최근 30분 트랜드 (5초 간격 → max 360개, 최대 180개로 샘플링) */
    $rows = $pdo->query(
        "SELECT recorded_at, cpu_usage, cpu_temp_c, cpu_power_w, cpu_clock_mhz,
                gpu_usage, gpu_temp_c, gpu_power_w, vram_pct, ram_pct
         FROM windows_metrics_sql
         WHERE recorded_at >= NOW() - INTERVAL 30 MINUTE
         ORDER BY recorded_at ASC"
    )->fetchAll(PDO::FETCH_ASSOC);
    /* 180개 초과 시 균등 샘플링 */
    if (count($rows) > 180) {
        $step = count($rows) / 180;
        $sampled = [];
        for ($i = 0; $i < 180; $i++) $sampled[] = $rows[(int)round($i * $step)];
        $history = $sampled;
    } else {
        $history = $rows;
    }

    $wstats = $pdo->query(
        "SELECT COUNT(*) total,
                ROUND(AVG(cpu_usage),1) avg_cpu, ROUND(MAX(cpu_usage),1) max_cpu,
                ROUND(AVG(cpu_temp_c),1) avg_cpu_t, ROUND(MAX(cpu_temp_c),1) max_cpu_t,
                ROUND(AVG(gpu_usage),1) avg_gpu, ROUND(MAX(gpu_usage),1) max_gpu,
                ROUND(AVG(gpu_temp_c),1) avg_gpu_t, ROUND(MAX(gpu_temp_c),1) max_gpu_t,
                ROUND(AVG(ram_pct),1) avg_ram,
                ROUND(AVG(cpu_power_w),1) avg_cpu_w, ROUND(AVG(gpu_power_w),1) avg_gpu_w,
                MIN(recorded_at) first_rec
         FROM windows_metrics_sql"
    )->fetch(PDO::FETCH_ASSOC);
} catch (PDOException $e) { $error = $e->getMessage(); }

/* ── 헬퍼 ─────────────────────────────────────────── */
function bar($pct, $warn=65, $crit=85, $h=8) {
    $c = $pct>$crit ? '#ef4444' : ($pct>$warn ? '#f59e0b' : '#22c55e');
    return "<div style='background:#1a2540;border-radius:4px;height:{$h}px;overflow:hidden;margin-top:8px;'>
        <div style='width:".min(100,max(0,$pct))."%;height:100%;background:{$c};border-radius:4px;transition:width .6s'></div></div>";
}
function tempColor($t) { return $t>=90?'#ef4444':($t>=75?'#f59e0b':($t>=60?'#fb923c':'#22c55e')); }
function usageColor($p){ return $p>=85?'#ef4444':($p>=70?'#f59e0b':'#22c55e'); }
function fmtClk($mhz)  { return $mhz>=1000 ? round($mhz/1000,2).' GHz' : round($mhz).' MHz'; }
function fmtBytes($b)  { if($b>=1e12) return round($b/1e12,2).' TB'; if($b>=1e9) return round($b/1e9,2).' GB'; return round($b/1e6,1).' MB'; }
function na($v,$unit='',$dec=1){ return $v!==null&&$v!==''?number_format(floatval($v),$dec).$unit:'<span style="color:#334155">N/A</span>'; }

/* ── chart JSON 준비 ────────────────────────────────── */
$labels   = array_map(fn($r)=>substr($r['recorded_at'],11,5), $history); // HH:MM
$cpuD     = array_map(fn($r)=>round(floatval($r['cpu_usage']??0),1), $history);
$gpuD     = array_map(fn($r)=>round(floatval($r['gpu_usage']??0),1), $history);
$ramD     = array_map(fn($r)=>round(floatval($r['ram_pct']??0),1), $history);
$vramD    = array_map(fn($r)=>round(floatval($r['vram_pct']??0),1), $history);
$cpuTD    = array_map(fn($r)=>round(floatval($r['cpu_temp_c']??0),1), $history);
$gpuTD    = array_map(fn($r)=>round(floatval($r['gpu_temp_c']??0),1), $history);
$cpuWD    = array_map(fn($r)=>round(floatval($r['cpu_power_w']??0),1), $history);
$gpuWD    = array_map(fn($r)=>round(floatval($r['gpu_power_w']??0),1), $history);
$clkD     = array_map(fn($r)=>round(floatval($r['cpu_clock_mhz']??0)/1000,2), $history);
$jLabels  = json_encode($labels);
$jCpu=$cpuD?json_encode($cpuD):'[]';
$jGpu=$gpuD?json_encode($gpuD):'[]';
$jRam=$ramD?json_encode($ramD):'[]';
$jVram=$vramD?json_encode($vramD):'[]';
$jCpuT=$cpuTD?json_encode($cpuTD):'[]';
$jGpuT=$gpuTD?json_encode($gpuTD):'[]';
$jCpuW=$cpuWD?json_encode($cpuWD):'[]';
$jGpuW=$gpuWD?json_encode($gpuWD):'[]';
$jClk=$clkD?json_encode($clkD):'[]';

/* ── uptime 포맷 ────────────────────────────────────── */
$uptimeStr = '';
if ($win_online && !empty($win['boot_time'])) {
    try {
        $boot = new DateTime($win['boot_time']);
        $now  = new DateTime();
        $diff = $now->diff($boot);
        $uptimeStr = $diff->days.'일 '.$diff->h.'시간 '.$diff->i.'분';
    } catch(Exception $e) {}
}
?>
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="refresh" content="5">
<title>Windows 하드웨어 모니터 · AI Infra</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#080f1e;color:#e2e8f0;min-height:100vh}

/* ── Header ── */
header{background:linear-gradient(135deg,#0d1b35 0%,#06101f 100%);
  padding:16px 32px;border-bottom:2px solid #7c3aed;
  display:flex;align-items:center;justify-content:space-between}
.h-title{font-size:1.4rem;font-weight:800;background:linear-gradient(90deg,#a78bfa,#60a5fa);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-.02em}
.h-sub{font-size:.76rem;color:#64748b;margin-top:2px}
.h-right{display:flex;align-items:center;gap:14px}
.badge{padding:4px 12px;border-radius:6px;font-size:.74rem;font-weight:700}
.badge-win{background:#7c3aed;color:#fff}
.badge-php{background:#1e40af;color:#c7d2fe}
.status-row{display:flex;align-items:center;gap:6px;font-size:.74rem}

/* ── Layout ── */
.wrap{padding:24px 32px;max-width:1600px;margin:0 auto}

/* ── Sections ── */
.sec{border-radius:16px;border:1px solid;padding:22px 24px;margin-bottom:24px}
.sec-cpu {border-color:#1e3a6e;background:linear-gradient(180deg,#0a1830 0%,#060e20 100%)}
.sec-gpu {border-color:#2d1a5e;background:linear-gradient(180deg,#100a28 0%,#080518 100%)}
.sec-mem {border-color:#064e3b;background:linear-gradient(180deg,#071e1a 0%,#050f0e 100%)}
.sec-disk{border-color:#1c2a0e;background:linear-gradient(180deg,#0c1508 0%,#070c05 100%)}
.sec-net {border-color:#1a2a1a;background:linear-gradient(180deg,#0b1408 0%,#060b05 100%)}
.sec-chart{border-color:#1e2a3a;background:linear-gradient(180deg,#0a1020 0%,#060b18 100%)}
.sec-stat {border-color:#1e2030;background:linear-gradient(180deg,#0a0f22 0%,#070919 100%)}
.sec-hdr{display:flex;align-items:center;gap:10px;margin-bottom:18px;
  padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,.06)}
.sec-title{font-size:1rem;font-weight:700}

/* ── Cards ── */
.g1{display:grid;gap:12px;margin-bottom:12px}
.g2{grid-template-columns:repeat(2,1fr)}
.g3{grid-template-columns:repeat(3,1fr)}
.g4{grid-template-columns:repeat(4,1fr)}
.g5{grid-template-columns:repeat(5,1fr)}
.g6{grid-template-columns:repeat(6,1fr)}
.span2{grid-column:span 2}
.span3{grid-column:span 3}
.card{background:#0f1e35;border-radius:12px;padding:16px 18px;border:1px solid #1a2d4a}
.ct{font-size:.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin-bottom:7px}
.cv{font-size:1.85rem;font-weight:800;line-height:1;font-variant-numeric:tabular-nums}
.cv-md{font-size:1.3rem;font-weight:700}
.cv-sm{font-size:1rem;font-weight:600}
.cs{font-size:.73rem;color:#64748b;margin-top:5px;line-height:1.4}

/* accent tops */
.ac-blue  {border-top:2px solid #3b82f6}
.ac-sky   {border-top:2px solid #38bdf8}
.ac-violet{border-top:2px solid #8b5cf6}
.ac-purple{border-top:2px solid #a855f7}
.ac-green {border-top:2px solid #22c55e}
.ac-teal  {border-top:2px solid #14b8a6}
.ac-orange{border-top:2px solid #f97316}
.ac-yellow{border-top:2px solid #eab308}
.ac-red   {border-top:2px solid #ef4444}
.ac-pink  {border-top:2px solid #ec4899}
.ac-lime  {border-top:2px solid #84cc16}
.ac-cyan  {border-top:2px solid #22d3ee}

/* ── Online dot ── */
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.dot-on{background:#22c55e;box-shadow:0 0 8px #22c55e;animation:pulse 2s infinite}
.dot-off{background:#475569}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

/* ── Sub header ── */
.sh{font-size:.68rem;color:#475569;text-transform:uppercase;letter-spacing:.12em;
  margin:16px 0 10px;padding-bottom:6px;border-bottom:1px solid #111e33}

/* ── Core grid ── */
.cores{display:grid;grid-template-columns:repeat(8,1fr);gap:6px;margin-top:8px}
.core-cell{border-radius:6px;padding:6px 4px;text-align:center;font-size:.65rem;font-weight:700;
  color:#fff;transition:background .5s;line-height:1.3;border:1px solid rgba(255,255,255,.06)}
.core-lbl{font-size:.58rem;color:rgba(255,255,255,.5);margin-bottom:3px;font-weight:500}
.core-val{font-size:.78rem;font-weight:800;line-height:1}
.core-sub{font-size:.56rem;color:rgba(255,255,255,.45);margin-top:2px}

/* ── Table ── */
table{width:100%;border-collapse:collapse;font-size:.83rem}
th{padding:9px 14px;text-align:left;color:#475569;border-bottom:1px solid #111e33;font-weight:500;font-size:.72rem}
td{padding:9px 14px;border-bottom:1px solid #0d1929;color:#cbd5e1}
tr:last-child td{border-bottom:none}
tr:hover td{background:#0d1929}

/* ── Charts ── */
.chart-wrap{position:relative;height:160px}
.chart-wrap.tall{height:200px}
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.chart-grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:16px}

/* ── Stat row ── */
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.stat-card{background:#0f1e35;border-radius:12px;padding:14px 16px;border:1px solid #1a2d4a;text-align:center}
.stat-lbl{font-size:.65rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px}
.stat-v{font-size:1.4rem;font-weight:800;font-variant-numeric:tabular-nums}
.stat-sub{font-size:.7rem;color:#475569;margin-top:3px}

/* ── Alert offline ── */
.offline-box{text-align:center;padding:60px 20px;color:#334155}
.offline-box .oi{font-size:3rem;margin-bottom:12px}
.offline-box p{font-size:.92rem;color:#475569}
.offline-box code{background:#0d1929;color:#f97316;padding:3px 8px;border-radius:5px;font-size:.82rem}

/* ── Footer ── */
footer{text-align:center;padding:16px;color:#1e293b;font-size:.72rem;
  border-top:1px solid #0d1929;margin-top:4px}

@media(max-width:1200px){
  .g6{grid-template-columns:repeat(3,1fr)}
  .g5{grid-template-columns:repeat(3,1fr)}
  .cores{grid-template-columns:repeat(4,1fr)}
}
@media(max-width:768px){
  .wrap{padding:14px 16px}
  .g4,.g5,.g6{grid-template-columns:repeat(2,1fr)}
  .g3{grid-template-columns:1fr}
  .chart-grid,.chart-grid-3{grid-template-columns:1fr}
}
</style>
</head>
<body>

<header>
  <div>
    <div class="h-title">🖥️ Windows 하드웨어 모니터</div>
    <div class="h-sub">실시간 하드웨어 센서 · LHM + NVML · MySQL 이력</div>
  </div>
  <div class="h-right">
    <?php if ($win_online): ?>
    <div class="status-row">
      <span class="dot dot-on"></span>
      <span style="color:#22c55e;font-weight:700"><?= htmlspecialchars($win['hostname']??'') ?></span>
      <span style="color:#475569">·</span>
      <span style="color:#94a3b8"><?= htmlspecialchars($win['os']??'') ?></span>
    </div>
    <div style="font-size:.72rem;color:#475569">
      LHM <?= ($win['lhm_active']??false) ? '<span style="color:#22c55e">●</span>' : '<span style="color:#475569">●</span>' ?>
      &nbsp;NVML <?= ($win['nvml_active']??false) ? '<span style="color:#22c55e">●</span>' : '<span style="color:#475569">●</span>' ?>
    </div>
    <?php else: ?>
    <div class="status-row"><span class="dot dot-off"></span><span style="color:#ef4444">에이전트 오프라인</span></div>
    <?php endif; ?>
    <span class="badge badge-win">Windows</span>
    <span class="badge badge-php">PHP <?= PHP_VERSION ?></span>
    <span style="font-size:.74rem;color:#475569"><?= gmdate('H:i:s').' UTC' ?> · Auto 10s</span>
  </div>
</header>

<div class="wrap">

<?php if ($error): ?>
<div class="card" style="border-color:#ef4444;margin-bottom:20px">
  <span style="color:#ef4444;font-weight:700">MySQL 오류</span>
  <span style="color:#94a3b8;font-size:.84rem;margin-left:10px"><?= htmlspecialchars($error) ?></span>
</div>
<?php endif; ?>

<?php if (!$win_online): ?>
<!-- ── Offline ── -->
<div class="sec" style="border-color:#3b1a1a;background:#0f0808">
  <div class="offline-box">
    <div class="oi">💻</div>
    <p style="font-size:1rem;color:#ef4444;font-weight:700;margin-bottom:8px">Windows 에이전트가 실행 중이지 않습니다</p>
    <p>노트북에서 관리자 권한으로 에이전트를 실행하세요:</p>
    <p style="margin-top:12px"><code>windows_agent\run_agent.bat</code></p>
  </div>
</div>
<?php else: ?>

<!-- ══════════════════════════════════════
     CPU
══════════════════════════════════════ -->
<div class="sec sec-cpu">
  <div class="sec-hdr">
    <span style="font-size:1.1rem">🔵</span>
    <span class="sec-title" style="color:#60a5fa">CPU</span>
    <span style="font-size:.8rem;color:#475569"><?= htmlspecialchars($wcpu['model']??'') ?></span>
    <span style="margin-left:auto;font-size:.72rem;color:#334155"><?= ($wcpu['physical']??'?') ?>코어 <?= ($wcpu['logical']??'?') ?>스레드</span>
  </div>

  <div class="g1 g5">
    <!-- 사용률 -->
    <div class="card ac-blue">
      <div class="ct">CPU 사용률</div>
      <?php $cpuPct=floatval($wcpu['usage_pct']??0); ?>
      <div class="cv" style="color:<?= usageColor($cpuPct) ?>"><?= number_format($cpuPct,1) ?>%</div>
      <div class="cs"><?= ($wcpu['physical']??'?') ?>P / <?= ($wcpu['logical']??'?') ?>L 코어</div>
      <?= bar($cpuPct) ?>
    </div>
    <!-- 패키지 온도 -->
    <div class="card ac-orange">
      <div class="ct">패키지 온도</div>
      <?php $cpuT=$wcpu['temp_package_c']??null; ?>
      <div class="cv" style="color:<?= $cpuT!==null?tempColor($cpuT):'#334155' ?>">
        <?= $cpuT!==null?number_format($cpuT,1).'°C':'N/A' ?>
      </div>
      <?php if (!empty($wcpu['temp_cores_c'])): ?>
      <div class="cs">코어: <?= implode(' / ', array_map(fn($t)=>round($t).'°', array_slice($wcpu['temp_cores_c'],0,4))) ?>…</div>
      <?php endif; ?>
    </div>
    <!-- 패키지 전력 -->
    <div class="card ac-yellow">
      <div class="ct">패키지 전력</div>
      <?php $cpuW=$wcpu['power_package_w']??null; ?>
      <div class="cv" style="color:<?= $cpuW!==null?($cpuW>80?'#ef4444':($cpuW>50?'#f59e0b':'#e2e8f0')):'#334155' ?>">
        <?= $cpuW!==null?number_format($cpuW,1).' W':'N/A' ?>
      </div>
      <?php if (($wcpu['power_cores_w']??null)!==null): ?>
      <div class="cs">코어 <?= number_format($wcpu['power_cores_w'],1) ?> W</div>
      <?php endif; ?>
    </div>
    <!-- 유효 클럭 -->
    <div class="card ac-cyan">
      <div class="ct">유효 클럭</div>
      <?php $effMhz=$wcpu['freq_effective_mhz']??null; ?>
      <div class="cv" style="color:#22d3ee"><?= $effMhz!==null?fmtClk($effMhz):'N/A' ?></div>
      <?php if (($wcpu['freq_base_mhz']??null)!==null): ?>
      <div class="cs">베이스 <?= fmtClk($wcpu['freq_base_mhz']) ?></div>
      <?php endif; ?>
    </div>
    <!-- 최대 클럭 -->
    <div class="card ac-violet">
      <div class="ct">최대 부스트</div>
      <?php $maxMhz=$wcpu['clock_max_mhz']??null; ?>
      <div class="cv" style="color:#8b5cf6"><?= $maxMhz!==null?fmtClk($maxMhz):'N/A' ?></div>
      <div class="cs">Boost Clock</div>
    </div>
  </div>

  <!-- Per-core: usage + clock combined, C0~C31 ordered -->
  <?php
  $usageCores = array_values($wcpu['usage_per_core'] ?? []);
  $clkCores   = array_values($wcpu['clock_cores_mhz'] ?? []);
  /* usage_per_core가 논리 코어 수 기준(32개)이므로 그 크기로 제한 */
  $coreCount  = !empty($usageCores) ? count($usageCores) : count($clkCores);
  if ($coreCount > 0):
  ?>
  <div class="sh">🧩 코어별 사용률 · 클럭 &nbsp;<span style="font-weight:400;color:#334155">C0 ~ C<?= $coreCount-1 ?></span></div>
  <div class="cores">
    <?php for ($i = 0; $i < $coreCount; $i++):
      $pct = floatval($usageCores[$i] ?? 0);
      $mhz = floatval($clkCores[$i]   ?? 0);

      /* 사용률 → 배경색 (저:초록 → 중:노랑 → 고:주황 → 최고:빨강) */
      if ($pct >= 85)      { $r=239; $g=68;  $b=68;  }
      elseif ($pct >= 60)  { $r=249; $g=115; $b=22;  }
      elseif ($pct >= 30)  { $r=234; $g=179; $b=8;   }
      else                 { $r=34;  $g=197; $b=94;  }
      $alpha  = max(0.10, min(0.82, $pct / 100 * 0.80 + 0.10));
      $bg     = "rgba($r,$g,$b,$alpha)";
      $valClr = $pct >= 20 ? '#f1f5f9' : '#64748b';

      /* 클럭 포맷 */
      $clkStr = $mhz >= 1000 ? round($mhz / 100) / 10 . 'G' : round($mhz) . 'M';
    ?>
    <div class="core-cell" style="background:<?= $bg ?>">
      <div class="core-lbl">C<?= $i ?></div>
      <div class="core-val" style="color:<?= $valClr ?>"><?= round($pct) ?>%</div>
      <div class="core-sub"><?= $clkStr ?></div>
    </div>
    <?php endfor; ?>
  </div>
  <?php endif; ?>
</div>


<!-- ══════════════════════════════════════
     GPU
══════════════════════════════════════ -->
<div class="sec sec-gpu">
  <div class="sec-hdr">
    <span style="font-size:1.1rem">🟠</span>
    <span class="sec-title" style="color:#c084fc">GPU</span>
    <span style="font-size:.8rem;color:#475569"><?= htmlspecialchars($wgpu['name']??'N/A') ?></span>
  </div>

  <div class="g1 g5">
    <div class="card ac-purple">
      <div class="ct">GPU 사용률</div>
      <?php $gpuPct=floatval($wgpu['usage_pct']??0); ?>
      <div class="cv" style="color:<?= usageColor($gpuPct) ?>"><?= number_format($gpuPct,1) ?>%</div>
      <?= bar($gpuPct) ?>
    </div>
    <div class="card ac-red">
      <div class="ct">GPU 온도</div>
      <?php $gpuT=$wgpu['temp_c']??null; ?>
      <div class="cv" style="color:<?= $gpuT!==null?tempColor($gpuT):'#334155' ?>">
        <?= $gpuT!==null?number_format($gpuT,1).'°C':'N/A' ?>
      </div>
      <?php if (($wgpu['fan_pct']??null)!==null): ?>
      <div class="cs">팬 <?= $wgpu['fan_pct'] ?>%</div>
      <?php endif; ?>
    </div>
    <div class="card ac-pink">
      <div class="ct">GPU 전력</div>
      <?php $gpuW=$wgpu['power_w']??null; ?>
      <div class="cv" style="color:#ec4899"><?= $gpuW!==null?number_format($gpuW,1).' W':'N/A' ?></div>
      <?php if (($wgpu['power_limit_w']??null)!==null): ?>
      <div class="cs">TDP 한계 <?= number_format($wgpu['power_limit_w'],0) ?> W</div>
      <?php endif; ?>
    </div>
    <div class="card ac-cyan">
      <div class="ct">코어 클럭</div>
      <?php $gClk=$wgpu['clock_core_mhz']??null; ?>
      <div class="cv" style="color:#22d3ee"><?= $gClk!==null?fmtClk($gClk):'N/A' ?></div>
      <?php if (($wgpu['clock_mem_mhz']??null)!==null): ?>
      <div class="cs">VRAM <?= round($wgpu['clock_mem_mhz']) ?> MHz</div>
      <?php endif; ?>
    </div>
    <div class="card ac-green">
      <div class="ct">VRAM</div>
      <?php
        $vPct   = floatval($wgpu['mem_pct']??0);
        $vUsed  = ($wgpu['mem_used_mb']??null)!==null?round($wgpu['mem_used_mb']/1024,1):null;
        $vTotal = ($wgpu['mem_total_mb']??null)!==null?round($wgpu['mem_total_mb']/1024,1):null;
      ?>
      <div class="cv" style="color:<?= usageColor($vPct) ?>"><?= number_format($vPct,1) ?>%</div>
      <?php if ($vUsed!==null): ?>
      <div class="cs"><?= $vUsed ?> / <?= $vTotal ?> GB</div>
      <?php endif; ?>
      <?= bar($vPct,70,90) ?>
    </div>
  </div>
</div>


<!-- ══════════════════════════════════════
     RAM
══════════════════════════════════════ -->
<div class="sec sec-mem">
  <div class="sec-hdr">
    <span style="font-size:1.1rem">🟣</span>
    <span class="sec-title" style="color:#34d399">RAM</span>
  </div>

  <div class="g1 g4">
    <div class="card ac-teal span2">
      <div class="ct">메모리 사용률</div>
      <?php $ramPct=floatval($wmem['percent']??0); ?>
      <div style="display:flex;align-items:flex-end;gap:14px">
        <div class="cv" style="color:<?= usageColor($ramPct) ?>"><?= number_format($ramPct,1) ?>%</div>
        <div style="font-size:1.15rem;color:#94a3b8;margin-bottom:3px">
          <?= number_format($wmem['used_gb']??0,1) ?> / <?= number_format($wmem['total_gb']??0,1) ?> GB
        </div>
        <div style="font-size:.82rem;color:#475569;margin-bottom:4px">
          여유 <?= number_format($wmem['available_gb']??0,1) ?> GB
        </div>
      </div>
      <?= bar($ramPct,70,85,10) ?>
    </div>
    <div class="card ac-violet">
      <div class="ct">메모리 클럭</div>
      <div class="cv" style="color:#8b5cf6">
        <?= ($wmem['clock_mhz']??null)!==null?$wmem['clock_mhz'].' MHz':'N/A' ?>
      </div>
      <div class="cs">DDR5</div>
    </div>
    <div class="card">
      <div class="ct">스왑 (페이징)</div>
      <div class="cv-md" style="color:#94a3b8">
        <?= ($wmem['swap_used_gb']??null)!==null?number_format($wmem['swap_used_gb'],1).' GB':'N/A' ?>
      </div>
      <?php if (($wmem['swap_total_gb']??null)!==null): ?>
      <div class="cs">전체 <?= number_format($wmem['swap_total_gb'],1) ?> GB
        (<?= number_format($wmem['swap_percent']??0,1) ?>%)</div>
      <?php endif; ?>
    </div>
  </div>
</div>


<!-- ══════════════════════════════════════
     Disk
══════════════════════════════════════ -->
<?php if (!empty($wdsk)): ?>
<div class="sec sec-disk">
  <div class="sec-hdr">
    <span style="font-size:1.1rem">💾</span>
    <span class="sec-title" style="color:#86efac">디스크</span>
  </div>

  <!-- 카드 형태로 각 드라이브 표시 -->
  <div class="g1" style="grid-template-columns:repeat(<?= min(count($wdsk),4) ?>,1fr)">
    <?php foreach($wdsk as $d):
      $dp = floatval($d['percent']??0);
      $accentColor = $dp>=90?'#ef4444':($dp>=75?'#f59e0b':'#22c55e');
    ?>
    <div class="card" style="border-top:2px solid <?= $accentColor ?>">
      <div class="ct"><?= htmlspecialchars($d['device']) ?> (<?= $d['fstype'] ?>)</div>
      <div class="cv" style="color:<?= usageColor($dp) ?>"><?= $dp ?>%</div>
      <div class="cs">
        사용 <?= $d['used_gb'] ?> GB<br>
        여유 <span style="color:#22c55e"><?= $d['free_gb'] ?> GB</span> / <?= $d['total_gb'] ?> GB
      </div>
      <?= bar($dp,75,90,9) ?>
    </div>
    <?php endforeach; ?>
  </div>
</div>
<?php endif; ?>


<!-- ══════════════════════════════════════
     Network
══════════════════════════════════════ -->
<?php
$netFiltered = array_filter($wnet, fn($k)=>!str_contains($k,'VMware')&&!str_contains($k,'Loopback'), ARRAY_FILTER_USE_KEY);
if (!empty($netFiltered)):
?>
<div class="sec sec-net">
  <div class="sec-hdr">
    <span style="font-size:1.1rem">🌐</span>
    <span class="sec-title" style="color:#6ee7b7">네트워크</span>
  </div>
  <div class="card" style="padding:0;overflow:hidden">
    <table>
      <thead>
        <tr><th>인터페이스</th><th>수신 총량</th><th>송신 총량</th><th>수신 패킷</th><th>송신 패킷</th><th>오류</th></tr>
      </thead>
      <tbody>
        <?php foreach($netFiltered as $iface=>$nd): ?>
        <tr>
          <td><b style="color:#f1f5f9"><?= htmlspecialchars($iface) ?></b></td>
          <td style="color:#22d3ee"><?= fmtBytes($nd['bytes_recv']??0) ?></td>
          <td style="color:#f97316"><?= fmtBytes($nd['bytes_sent']??0) ?></td>
          <td style="color:#94a3b8"><?= number_format($nd['packets_recv']??0) ?></td>
          <td style="color:#94a3b8"><?= number_format($nd['packets_sent']??0) ?></td>
          <td style="color:<?= (($nd['errin']??0)+($nd['errout']??0))>0?'#ef4444':'#334155' ?>">
            <?= ($nd['errin']??0)+($nd['errout']??0) ?>
          </td>
        </tr>
        <?php endforeach; ?>
      </tbody>
    </table>
  </div>
</div>
<?php endif; ?>

<?php endif; /* win_online */ ?>


<!-- ══════════════════════════════════════
     시스템 정보 요약 (항상 표시)
══════════════════════════════════════ -->
<?php if ($win_online): ?>
<div class="sec sec-stat">
  <div class="sec-hdr">
    <span style="font-size:1.1rem">ℹ️</span>
    <span class="sec-title" style="color:#94a3b8">시스템 정보</span>
  </div>
  <div class="g1 g4">
    <div class="card">
      <div class="ct">호스트명 / OS</div>
      <div class="cv-md" style="color:#f1f5f9"><?= htmlspecialchars($win['hostname']??'') ?></div>
      <div class="cs"><?= htmlspecialchars($win['os']??'') ?></div>
    </div>
    <div class="card">
      <div class="ct">업타임</div>
      <div class="cv-md" style="color:#38bdf8"><?= $uptimeStr ?: 'N/A' ?></div>
      <div class="cs">부팅: <?= substr($win['boot_time']??'',0,16) ?></div>
    </div>
    <div class="card">
      <div class="ct">센서 상태</div>
      <div style="display:flex;gap:16px;margin-top:6px">
        <div>
          <div class="cs">LibreHardwareMonitor</div>
          <div style="font-size:1rem;font-weight:700;margin-top:3px;color:<?= ($win['lhm_active']??false)?'#22c55e':'#ef4444' ?>">
            <?= ($win['lhm_active']??false)?'✓ 활성':'✗ 비활성' ?>
          </div>
        </div>
        <div>
          <div class="cs">NVML (NVIDIA)</div>
          <div style="font-size:1rem;font-weight:700;margin-top:3px;color:<?= ($win['nvml_active']??false)?'#22c55e':'#ef4444' ?>">
            <?= ($win['nvml_active']??false)?'✓ 활성':'✗ 비활성' ?>
          </div>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="ct">마지막 업데이트</div>
      <div class="cv-md" style="color:#22c55e">
        <?= str_replace(['T','Z'],' ',substr($win['timestamp']??'',0,19)) ?> UTC
      </div>
      <div style="margin-top:7px;display:flex;align-items:center;gap:6px">
        <span class="dot dot-on"></span>
        <span style="font-size:.75rem;color:#22c55e">Live · 5초 갱신</span>
      </div>
    </div>
  </div>
</div>
<?php endif; ?>


<!-- ══════════════════════════════════════
     MySQL 누적 통계
══════════════════════════════════════ -->
<?php if ($wstats && intval($wstats['total'])>0): ?>
<div class="sec sec-stat">
  <div class="sec-hdr">
    <span style="font-size:1.1rem">📊</span>
    <span class="sec-title" style="color:#94a3b8">누적 통계 (MySQL · <?= number_format($wstats['total']) ?>건)</span>
    <span style="margin-left:auto;font-size:.72rem;color:#334155">
      첫 수집: <?= $wstats['first_rec'] ?>
    </span>
  </div>
  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-lbl">평균 CPU</div>
      <div class="stat-v" style="color:#60a5fa"><?= $wstats['avg_cpu'] ?>%</div>
      <div class="stat-sub">최대 <?= $wstats['max_cpu'] ?>%</div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">평균 CPU 온도</div>
      <div class="stat-v" style="color:#fb923c"><?= $wstats['avg_cpu_t'] ?>°C</div>
      <div class="stat-sub">최대 <?= $wstats['max_cpu_t'] ?>°C</div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">평균 GPU</div>
      <div class="stat-v" style="color:#c084fc"><?= $wstats['avg_gpu'] ?>%</div>
      <div class="stat-sub">최대 <?= $wstats['max_gpu'] ?>%</div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">평균 GPU 온도</div>
      <div class="stat-v" style="color:#f87171"><?= $wstats['avg_gpu_t'] ?>°C</div>
      <div class="stat-sub">최대 <?= $wstats['max_gpu_t'] ?>°C</div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">평균 RAM</div>
      <div class="stat-v" style="color:#34d399"><?= $wstats['avg_ram'] ?>%</div>
      <div class="stat-sub">32 GB 기준</div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">평균 CPU 전력</div>
      <div class="stat-v" style="color:#fbbf24"><?= $wstats['avg_cpu_w'] ?> W</div>
      <div class="stat-sub">패키지 소비전력</div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">평균 GPU 전력</div>
      <div class="stat-v" style="color:#f472b6"><?= $wstats['avg_gpu_w'] ?> W</div>
      <div class="stat-sub">RTX 4070 Laptop</div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">수집 기간</div>
      <div class="stat-v" style="color:#38bdf8;font-size:1rem"><?= $wstats['first_rec'] ?></div>
      <div class="stat-sub">~ 현재</div>
    </div>
  </div>
</div>
<?php endif; ?>


<!-- ══════════════════════════════════════
     트랜드 차트 (30분)
══════════════════════════════════════ -->
<?php if (!empty($history)): ?>
<div class="sec sec-chart">
  <div class="sec-hdr">
    <span style="font-size:1.1rem">📈</span>
    <span class="sec-title" style="color:#94a3b8">30분 트랜드 (MySQL · <?= count($history) ?>포인트)</span>
  </div>

  <div class="chart-grid">
    <div class="card">
      <div class="ct" style="margin-bottom:10px">CPU / GPU 사용률 (%)</div>
      <div class="chart-wrap tall"><canvas id="c-usage"></canvas></div>
    </div>
    <div class="card">
      <div class="ct" style="margin-bottom:10px">CPU / GPU 온도 (°C)</div>
      <div class="chart-wrap tall"><canvas id="c-temp"></canvas></div>
    </div>
  </div>
  <div class="chart-grid">
    <div class="card">
      <div class="ct" style="margin-bottom:10px">RAM / VRAM 사용률 (%)</div>
      <div class="chart-wrap tall"><canvas id="c-mem"></canvas></div>
    </div>
    <div class="card">
      <div class="ct" style="margin-bottom:10px">CPU / GPU 전력 (W)</div>
      <div class="chart-wrap tall"><canvas id="c-power"></canvas></div>
    </div>
  </div>
  <div class="card">
    <div class="ct" style="margin-bottom:10px">CPU 유효 클럭 (GHz)</div>
    <div class="chart-wrap"><canvas id="c-clk"></canvas></div>
  </div>
</div>
<?php endif; ?>

</div><!-- /wrap -->

<footer>
  PHP <?= PHP_VERSION ?> · Apache · MySQL · Django API · Docker &copy; <?= gmdate('Y') ?>
  · Windows 하드웨어 모니터 — AMD Ryzen + NVIDIA RTX
</footer>

<?php if (!empty($history)): ?>
<script>
Chart.defaults.color = '#475569';
Chart.defaults.borderColor = '#111e33';
const L = <?= $jLabels ?>;

const cfg = (datasets, yMax) => ({
  type: 'line',
  data: { labels: L, datasets },
  options: {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode:'index', intersect:false },
    plugins: { legend:{ labels:{ boxWidth:10, padding:14, font:{size:11} } } },
    scales: {
      x: { ticks:{ maxTicksLimit:8, font:{size:10} }, grid:{ color:'#0d1929' } },
      y: { min:0, max:yMax, grid:{ color:'#0d1929' }, ticks:{ font:{size:10} } }
    }
  }
});

const line = (label, data, color, fill=false) => ({
  label, data,
  borderColor: color,
  backgroundColor: fill ? color+'22' : 'transparent',
  borderWidth: 1.8,
  pointRadius: 0,
  tension: 0.3,
  fill
});

/* Usage */
new Chart(document.getElementById('c-usage'), cfg([
  line('CPU %',  <?= $jCpu  ?>, '#3b82f6', true),
  line('GPU %',  <?= $jGpu  ?>, '#a855f7', true),
], 100));

/* Temp */
new Chart(document.getElementById('c-temp'), cfg([
  line('CPU °C', <?= $jCpuT ?>, '#f97316'),
  line('GPU °C', <?= $jGpuT ?>, '#ef4444'),
], null));

/* Mem */
new Chart(document.getElementById('c-mem'), cfg([
  line('RAM %',  <?= $jRam  ?>, '#14b8a6', true),
  line('VRAM %', <?= $jVram ?>, '#8b5cf6', true),
], 100));

/* Power */
new Chart(document.getElementById('c-power'), cfg([
  line('CPU W',  <?= $jCpuW ?>, '#eab308'),
  line('GPU W',  <?= $jGpuW ?>, '#ec4899'),
], null));

/* Clock */
new Chart(document.getElementById('c-clk'), cfg([
  line('GHz', <?= $jClk ?>, '#22d3ee', true),
], null));
</script>
<?php endif; ?>
</body>
</html>
