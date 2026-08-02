FROM python:3.11-slim
# Install ffmpeg (required for MP3 conversion and 
# video/audio merging)
RUN apt-get update && \ apt-get install -y 
    --no-install-recommends ffmpeg && \ rm -rf 
    /var/lib/apt/lists/*
WORKDIR /app COPY requirements.txt . RUN pip install 
--no-cache-dir -r requirements.txt COPY . . RUN mkdir -p 
downloads EXPOSE 5000
# Shell form so $PORT is expanded at runtime — Render 
# assigns its own PORT and will fail with "no open ports 
# detected" if you bind a fixed port instead.
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 120 app:app
