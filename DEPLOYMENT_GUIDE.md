# Deployment Guide for Large File Support

This guide provides instructions for deploying the Medical Legal PDF Processor with large file support (5000-10,000 pages).

## Quick Start

### Local Development

#### macOS/Linux
```bash
# Make the script executable (first time only)
chmod +x start_server.sh

# Run the server
./start_server.sh
```

#### Windows
```bash
# Run the batch file
start_server.bat
```

### Manual Start

```bash
# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate.bat  # Windows

# Install dependencies
pip install -r requirements.txt

# Run with gunicorn
gunicorn -c gunicorn_config.py app:app
```

## Deployment Options

### 1. Render.com (Recommended for Cloud)

1. **Update `render.yaml`** (if not exists, create it):

```yaml
services:
  - type: web
    name: medical-legal-pdf-processor
    env: python
    region: oregon
    plan: standard
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn -c gunicorn_config.py app:app
    envVars:
      - key: OPENAI_API_KEY
        sync: false
      - key: SECRET_KEY
        generateValue: true
      - key: PYTHON_VERSION
        value: 3.12.0
    disk:
      name: temp-storage
      mountPath: /tmp
      sizeGB: 10
```

2. **Set Environment Variables** in Render dashboard:
   - `OPENAI_API_KEY`: Your OpenAI API key
   - `SECRET_KEY`: Auto-generated or custom

3. **Deploy**: Connect your repo and deploy

**Note**: Render's free tier has limitations. Use Standard plan or higher for large files.

### 2. Railway

1. **Create `railway.json`**:

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "gunicorn -c gunicorn_config.py app:app",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

2. **Set Environment Variables**:
   - `OPENAI_API_KEY`
   - `SECRET_KEY`
   - `PORT` (Railway auto-assigns)

3. **Deploy**: Push to repository

### 3. Heroku

1. **Create `Procfile`**:

```
web: gunicorn -c gunicorn_config.py app:app
```

2. **Update `heroku.yml`** (if using container):

```yaml
build:
  docker:
    web: Dockerfile
run:
  web: gunicorn -c gunicorn_config.py app:app
```

3. **Configure dyno**:
   - Use Standard or Performance dynos (Hobby tier insufficient for large files)
   - Set timeout to 600s

4. **Set config vars**:
```bash
heroku config:set OPENAI_API_KEY=your_key
heroku config:set SECRET_KEY=your_secret
```

### 4. AWS EC2

1. **Launch Instance**:
   - t3.medium or larger (4GB+ RAM)
   - Ubuntu 22.04 LTS
   - Security group: Allow port 80/443

2. **Install Dependencies**:

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv nginx -y

# Clone repository
git clone <your-repo-url>
cd SweetButter-1

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

3. **Configure systemd service** (`/etc/systemd/system/medical-pdf.service`):

```ini
[Unit]
Description=Medical Legal PDF Processor
After=network.target

[Service]
Type=notify
User=ubuntu
WorkingDirectory=/home/ubuntu/SweetButter-1
Environment="PATH=/home/ubuntu/SweetButter-1/.venv/bin"
EnvironmentFile=/home/ubuntu/SweetButter-1/.env
ExecStart=/home/ubuntu/SweetButter-1/.venv/bin/gunicorn -c gunicorn_config.py app:app
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

4. **Configure nginx** (`/etc/nginx/sites-available/medical-pdf`):

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Large file upload support
    client_max_body_size 2G;
    client_body_timeout 600s;
    client_body_buffer_size 128k;

    # Proxy settings
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
    proxy_buffering off;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

5. **Start services**:

```bash
# Enable and start service
sudo systemctl enable medical-pdf
sudo systemctl start medical-pdf

# Enable nginx
sudo ln -s /etc/nginx/sites-available/medical-pdf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 5. Docker

1. **Create `Dockerfile`**:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create temp directory for large files
RUN mkdir -p /tmp/uploads

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/ || exit 1

# Run with gunicorn
CMD ["gunicorn", "-c", "gunicorn_config.py", "app:app"]
```

2. **Create `docker-compose.yml`**:

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - SECRET_KEY=${SECRET_KEY}
      - PORT=8080
    volumes:
      - /tmp:/tmp
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G
```

3. **Run**:

```bash
docker-compose up -d
```

## Performance Tuning

### Server Resources

Recommended specs for different workloads:

| Concurrent Users | RAM  | CPU Cores | Storage |
|-----------------|------|-----------|---------|
| 1-5             | 4GB  | 2         | 20GB    |
| 5-10            | 8GB  | 4         | 50GB    |
| 10-20           | 16GB | 8         | 100GB   |

### Gunicorn Workers

Adjust workers in `gunicorn_config.py`:

```python
# Conservative (low memory)
workers = 2

# Balanced (default)
workers = multiprocessing.cpu_count() * 2 + 1

# Aggressive (high throughput)
workers = multiprocessing.cpu_count() * 4 + 1
```

### Timeout Adjustments

For even larger files (>10,000 pages), increase timeouts:

**In `gunicorn_config.py`**:
```python
timeout = 900  # 15 minutes
graceful_timeout = 900
```

**In `app.py`**:
```python
max_wait_time = 900  # 15 minutes
```

**In `templates/index.html`**:
```javascript
setTimeout(() => controller.abort(), 900000); // 15 minutes
```

## Monitoring

### Application Metrics

```bash
# Watch logs in real-time
tail -f access.log error.log

# Filter for large files
grep "Large file upload" access.log

# Monitor memory usage
watch -n 2 free -h

# Monitor disk usage
df -h /tmp
```

### Set Up Logging

**For production**, configure proper logging:

```python
# In app.py
import logging
from logging.handlers import RotatingFileHandler

# Configure file handler
handler = RotatingFileHandler(
    'app.log',
    maxBytes=10000000,  # 10MB
    backupCount=10
)
handler.setLevel(logging.INFO)
formatter = logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
)
handler.setFormatter(formatter)
app.logger.addHandler(handler)
```

## Security Considerations

1. **API Key Protection**:
   - Never commit `.env` file
   - Use environment variables in production
   - Rotate keys regularly

2. **File Validation**:
   - Verify PDF format before processing
   - Scan for malicious content
   - Limit file types to PDF only

3. **Rate Limiting**:
   - Implement rate limiting for uploads
   - Consider using Redis for distributed rate limiting

4. **HTTPS**:
   - Always use HTTPS in production
   - Get SSL certificate (Let's Encrypt is free)

5. **Authentication**:
   - Add user authentication for production
   - Implement role-based access control

## Troubleshooting

### Common Issues

1. **"Worker timeout"**:
   - Increase `timeout` in gunicorn_config.py
   - Check system resources (RAM/CPU)

2. **"413 Request Entity Too Large"**:
   - Check nginx `client_max_body_size`
   - Verify Flask `MAX_CONTENT_LENGTH`

3. **"Out of memory"**:
   - Reduce number of workers
   - Increase server RAM
   - Enable swap space

4. **Slow uploads**:
   - Check network bandwidth
   - Verify server location
   - Consider CDN for static files

### Debug Mode

Enable debug logging:

```python
# In gunicorn_config.py
loglevel = 'debug'

# In app.py
app.config['DEBUG'] = True  # Only for development!
```

## Maintenance

### Regular Tasks

1. **Clean temporary files**:
```bash
# Add to crontab
0 2 * * * find /tmp -name "*.pdf" -mtime +1 -delete
```

2. **Log rotation**:
```bash
# Configure logrotate
/var/log/medical-pdf/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 640 www-data www-data
    sharedscripts
    postrotate
        systemctl reload medical-pdf
    endscript
}
```

3. **Backup strategy**:
   - Database backups (if applicable)
   - Configuration backups
   - User data backups

## Support

For deployment issues:
1. Check logs: `tail -f error.log`
2. Verify configuration: `gunicorn --check-config gunicorn_config.py`
3. Test connectivity: `curl -v http://localhost:8080/`
4. Review system resources: `htop` or `top`
