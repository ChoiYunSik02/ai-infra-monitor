from django.db import models


class SystemMetric(models.Model):
    hostname       = models.CharField(max_length=100, default='zorin-vm')
    cpu_usage      = models.FloatField()
    mem_total      = models.BigIntegerField()
    mem_used       = models.BigIntegerField()
    mem_percent    = models.FloatField()
    disk_total     = models.BigIntegerField()
    disk_used      = models.BigIntegerField()
    disk_percent   = models.FloatField()
    net_bytes_sent = models.BigIntegerField(default=0)
    net_bytes_recv = models.BigIntegerField(default=0)
    recorded_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'system_metrics'
        ordering = ['-recorded_at']

    def mem_used_gb(self):
        return round(self.mem_used / (1024 ** 3), 2)

    def mem_total_gb(self):
        return round(self.mem_total / (1024 ** 3), 2)

    def disk_used_gb(self):
        return round(self.disk_used / (1024 ** 3), 2)

    def disk_total_gb(self):
        return round(self.disk_total / (1024 ** 3), 2)


class AiAnalysis(models.Model):
    SEVERITY_CHOICES = [
        ('info',     '정보'),
        ('warning',  '경고'),
        ('critical', '위험'),
    ]
    metric     = models.ForeignKey(SystemMetric, on_delete=models.SET_NULL, null=True, blank=True)
    severity   = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='info')
    title      = models.CharField(max_length=200)
    analysis   = models.TextField()
    suggestion = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_analysis'
        ordering = ['-created_at']


class AlertHistory(models.Model):
    alert_type   = models.CharField(max_length=50)
    threshold    = models.FloatField()
    actual_value = models.FloatField()
    message      = models.TextField()
    triggered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'alert_history'
        ordering = ['-triggered_at']


class ChatMessage(models.Model):
    ROLE_CHOICES = [('user', '사용자'), ('assistant', 'AI')]
    role       = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class AlertThreshold(models.Model):
    vm_cpu_pct     = models.FloatField(default=80)
    vm_ram_pct     = models.FloatField(default=85)
    vm_disk_pct    = models.FloatField(default=90)
    win_cpu_pct    = models.FloatField(default=80)
    win_cpu_temp_c = models.FloatField(default=85)
    win_gpu_pct    = models.FloatField(default=85)
    win_gpu_temp_c = models.FloatField(default=85)
    win_vram_pct   = models.FloatField(default=90)
    win_ram_pct    = models.FloatField(default=85)
    cooldown_min   = models.IntegerField(default=5)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'alert_threshold'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class AlertCooldown(models.Model):
    alert_type   = models.CharField(max_length=60, unique=True)
    last_sent_at = models.DateTimeField()

    class Meta:
        db_table = 'alert_cooldown'


class TelegramBotLog(models.Model):
    alert_type = models.CharField(max_length=60, blank=True)
    message    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'telegram_bot_log'
        ordering = ['-created_at']


class WindowsMetric(models.Model):
    hostname      = models.CharField(max_length=100)
    cpu_usage     = models.FloatField(null=True)
    cpu_temp_c    = models.FloatField(null=True)
    cpu_power_w   = models.FloatField(null=True)
    cpu_clock_mhz = models.IntegerField(null=True)
    gpu_usage     = models.FloatField(null=True)
    gpu_temp_c    = models.FloatField(null=True)
    gpu_power_w   = models.FloatField(null=True)
    vram_pct      = models.FloatField(null=True)
    ram_pct       = models.FloatField(null=True)
    recorded_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'windows_metrics_sql'
        ordering = ['-recorded_at']
