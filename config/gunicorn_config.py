# https://docs.gunicorn.org/en/stable/settings.html
bind = "0.0.0.0:8080"
# Enable prints to be shown immediately
accesslog = "-"  # Print access log to stdout
errorlog = "-"   # Print error log to stdout
capture_output = True
enable_stdio_inheritance = True

workers = 2
threads = 1
timeout = 360
reload = True
