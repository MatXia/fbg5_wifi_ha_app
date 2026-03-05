FROM python:3.11-slim

WORKDIR /app

RUN pip install websocket-client paho-mqtt

COPY printer_bridge.py /app/printer_bridge.py
COPY run.sh /app/run.sh

RUN chmod +x /app/run.sh

CMD ["ls /; ls /app; sh /app/run.sh"]