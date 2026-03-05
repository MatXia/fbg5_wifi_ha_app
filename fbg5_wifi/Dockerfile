FROM python:3.11-slim

WORKDIR /app

RUN pip install websocket-client paho-mqtt

COPY printer_bridge.py .
COPY run.sh .

CMD ["/app/run.sh"]