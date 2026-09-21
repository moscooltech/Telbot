# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install system dependencies:
# - ffmpeg (video/audio pipeline, includes libass for karaoke subtitles)
# - fonts-dejavu-core (bold font for libass subtitle rendering)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p assets/music assets/fonts temp

# Run the web server
CMD ["python", "app.py"]
