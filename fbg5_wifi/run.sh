#!/usr/bin/with-contenv bash

export PRINTER_IP=$(jq -r '.printer_ip' /data/options.json)
export WS_PORT=$(jq -r '.ws_port' /data/options.json)
export MQTT_HOST=$(jq -r '.mqtt_host' /data/options.json)
export MQTT_PORT=$(jq -r '.mqtt_port' /data/options.json)
export INTERVAL=$(jq -r '.interval' /data/options.json)

python3 /app/printer_bridge.py