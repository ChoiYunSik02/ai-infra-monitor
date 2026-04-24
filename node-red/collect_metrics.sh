#!/bin/bash
# CPU
read_cpu() { grep 'cpu ' /proc/stat | awk '{print $2+$3+$4, $5, $2+$3+$4+$5+$6+$7+$8}'; }
read cpu1_busy cpu1_idle cpu1_total < <(read_cpu)
sleep 0.5
read cpu2_busy cpu2_idle cpu2_total < <(read_cpu)
diff_total=$((cpu2_total - cpu1_total))
diff_idle=$((cpu2_idle  - cpu1_idle))
if [ "$diff_total" -gt 0 ]; then
    cpu_pct=$(awk "BEGIN {printf \"%.2f\", (1 - $diff_idle/$diff_total)*100}")
else
    cpu_pct="0.00"
fi

# Memory (bytes)
read mem_total mem_used <<< $(free -b | awk 'NR==2{print $2,$3}')

# Disk (bytes + percent)
read disk_total disk_used disk_pct <<< $(df -B1 / | awk 'NR==2{gsub(/%/,""); print $2,$3,$5}')

# Network (bytes, first ethernet interface)
read net_sent net_recv <<< $(awk 'NR>2{
    gsub(/:/," ",$0)
    if($1~/eth|ens|enp/){print $10,$2; exit}
}' /proc/net/dev 2>/dev/null || echo "0 0")

# Load average
read load1 load5 load15 _ proc_count _ < <(cat /proc/loadavg | sed 's|/| |')

# Uptime (hours, 1 decimal)
uptime_h=$(awk '{printf "%.1f", $1/3600}' /proc/uptime)

# Kernel version
kernel=$(uname -r)

echo "$cpu_pct $mem_total $mem_used $disk_total $disk_used $disk_pct ${net_sent:-0} ${net_recv:-0} $load1 $load5 $load15 $uptime_h $proc_count $kernel"
