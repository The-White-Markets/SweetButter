# Gunicorn configuration file for handling large file uploads
import multiprocessing
import os

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = 'sync'
worker_connections = 1000

# Timeout settings for large file uploads (5000-10,000 pages)
# Increased timeouts to handle large PDF processing
timeout = 600  # 10 minutes for worker timeout
graceful_timeout = 600  # 10 minutes for graceful worker restart
keepalive = 5

# Maximum request size - set to 2GB to accommodate large PDFs
limit_request_line = 0  # No limit on request line
limit_request_fields = 32768  # Increased number of header fields
limit_request_field_size = 0  # No limit on header field size

# Logging
accesslog = '-'  # Log to stdout
errorlog = '-'  # Log to stderr
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'medical-legal-pdf-processor'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (if needed in production)
keyfile = None
certfile = None

# Server hooks
def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Starting Medical Legal PDF Processor with large file support")

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    server.log.info("Reloading workers")

def when_ready(server):
    """Called just after the server is started."""
    server.log.info("Server is ready. Accepting connections.")
    server.log.info(f"Configured for large file uploads (up to 2GB)")
    server.log.info(f"Worker timeout: {timeout}s")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info(f"Worker spawned (pid: {worker.pid})")

def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    pass

def worker_int(worker):
    """Called just after a worker exited on SIGINT or SIGQUIT."""
    worker.log.info("Worker received INT or QUIT signal")

def worker_abort(worker):
    """Called when a worker received the SIGABRT signal."""
    worker.log.info("Worker received SIGABRT signal")
