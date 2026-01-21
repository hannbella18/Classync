# 1. Use a stable Python version (same as your local venv)
FROM python:3.11

# 2. Set up the working directory inside the cloud server
WORKDIR /code

# 3. Copy your "Shopping List" first (for speed)
COPY requirements.txt .

# 4. Install dependencies
# We upgrade pip first to avoid errors, then install your list
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of your project files
COPY . .

# 6. Create a special folder for temporary files (needed for some libraries)
# and give permission to the "user" (Hugging Face security rule)
RUN mkdir -p /code/cache && chmod 777 /code/cache
ENV XDG_CACHE_HOME=/code/cache

# 7. Open the "Door" (Port 7860 is the standard for Hugging Face)
EXPOSE 7860

# 8. The Command to Start the Server
# We use Gunicorn (Production Server) instead of "python app.py"
# --worker-class eventlet is REQUIRED for SocketIO to work
CMD ["gunicorn", "-k", "gthread", "--threads", "4", "-w", "1", "-b", "0.0.0.0:7860", "server.app:app"]