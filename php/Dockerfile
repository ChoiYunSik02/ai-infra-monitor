FROM ai-infra-monitor-django:latest
RUN apt-get update && apt-get install -y \
    php-cli \
    php-mysql \
    php-curl \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /var/www/html
COPY index.php /var/www/html/index.php
EXPOSE 8080
CMD ["php", "-S", "0.0.0.0:8080", "-t", "/var/www/html"]
