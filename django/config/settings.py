import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-secret-key')

DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'monitor.apps.MonitorConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('MYSQL_DATABASE', 'infra_monitor'),
        'USER': os.environ.get('MYSQL_USER', 'monitor_user'),
        'PASSWORD': os.environ.get('MYSQL_PASSWORD', 'monitor_pass123'),
        'HOST': os.environ.get('MYSQL_HOST', 'mysql'),
        'PORT': os.environ.get('MYSQL_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    },
    'local': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'data' / 'local.db',
    },
}

DATABASE_ROUTERS = ['config.routers.LocalDBRouter']

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = False

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'monitor' / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

OLLAMA_HOST  = os.environ.get('OLLAMA_HOST',  'http://192.168.0.11:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'gemma3:4b')

MONGODB_HOST     = os.environ.get('MONGO_HOST',     'mongodb')
MONGODB_PORT     = int(os.environ.get('MONGO_PORT', '27017'))
MONGODB_USER     = os.environ.get('MONGO_USER',     'mongo_admin')
MONGODB_PASSWORD = os.environ.get('MONGO_PASSWORD', 'mongo_pass123')
MONGODB_DB       = os.environ.get('MONGO_DB',       'infra_logs')
