FROM apify/actor-python:3.12

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy repository source code
COPY . ./

# Set runtime environment
ENV WEALTHPILOT_MODE=live
ENV PYTHONUNBUFFERED=1

# Execute Apify Actor Entry Point
CMD ["python", "actor_main.py"]
