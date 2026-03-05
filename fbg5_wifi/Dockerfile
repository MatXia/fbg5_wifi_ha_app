FROM python:3.11-slim

RUN apt-get update && apt-get install -y jq && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install websocket-client paho-mqtt

COPY printer_bridge.py /app/printer_bridge.py
COPY run.sh /app/run.sh

RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]