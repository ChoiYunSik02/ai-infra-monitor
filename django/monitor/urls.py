from django.urls import path
from . import views

urlpatterns = [
    path('',                    views.dashboard,        name='dashboard'),
    path('api/metrics/',        views.api_metrics,      name='api-metrics'),
    path('api/analysis/',       views.api_analysis,     name='api-analysis'),
    path('api/analyze/',         views.api_analyze,          name='api-analyze'),
    path('api/analyze/windows/', views.api_analyze_windows,  name='api-analyze-windows'),
    path('api/alerts/',         views.api_alerts,       name='api-alerts'),
    path('api/alerts/stats/',   views.api_alerts_stats, name='api-alerts-stats'),
    path('api/log/',            views.api_log,          name='api-log'),
    path('api/logs/',           views.api_logs,         name='api-logs'),
    path('api/chat/',           views.api_chat,         name='api-chat'),
    path('api/chat/history/',   views.api_chat_history, name='api-chat-history'),
    path('api/chat/clear/',     views.api_chat_clear,       name='api-chat-clear'),
    path('api/windows/',         views.api_windows_receive, name='api-windows-receive'),
    path('api/windows/latest/',  views.api_windows_latest,  name='api-windows-latest'),
    path('api/windows/history/', views.api_windows_history, name='api-windows-history'),
    path('api/windows/logs/',    views.api_windows_logs,    name='api-windows-logs'),
    path('api/db/overview/',     views.api_db_overview,     name='api-db-overview'),
    path('api/thresholds/',      views.api_thresholds,      name='api-thresholds'),
    path('api/bot/logs/',        views.api_bot_logs,        name='api-bot-logs'),
]
