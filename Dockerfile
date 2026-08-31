FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PNL_DB_PATH=/data/pnl.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pnlbot ./pnlbot
COPY run.py .

VOLUME ["/data"]
CMD ["python", "run.py"]
