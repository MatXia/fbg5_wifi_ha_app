import websocket
import json
import time
import re
import socket
import os
import paho.mqtt.client as mqtt

PRINTER_IP = os.getenv("PRINTER_IP")
WS_PORT = int(os.getenv("WS_PORT"))
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
INTERVAL = int(os.getenv("INTERVAL"))

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)

device = {
    "identifiers": ["fbg5_printer"],
    "name": "Flying Bear Ghost 5",
    "manufacturer": "Flying Bear"
}

def publish(topic,value):
    mqtt_client.publish(topic,value,retain=True)

def set_all_unavailable():
    sensors = [
        "status",
        "nozzle_temp",
        "bed_temp",
        "wifi",
        "progress",
        "file",
        "time_left"
    ]
    for s in sensors:
        publish(f"fbg5/{s}","unavailable")

def discovery():
    sensors = {
        "status":"Статус принтера",
        "nozzle_temp":"Температура сопла",
        "bed_temp":"Температура стола",
        "wifi":"Сигнал Wifi",
        "progress":"Прогресс печати",
        "file":"Название файла",
        "time_left":"Оставшееся время"
    }
    for key,name in sensors.items():
        payload={
            "name":name,
            "state_topic":f"fbg5/{key}",
            "unique_id":f"fbg5_{key}",
            "device":device
        }
        mqtt_client.publish(
            f"homeassistant/sensor/fbg5/{key}/config",
            json.dumps(payload),
            retain=True
        )
    connection_payload={
        "name":"Статус подключения",
        "state_topic":"fbg5/connection",
        "payload_on":"ON",
        "payload_off":"OFF",
        "unique_id":"fbg5_connection",
        "device_class": "connectivity",
        "device":device
    }
    mqtt_client.publish(
        "homeassistant/binary_sensor/fbg5/connection/config",
        json.dumps(connection_payload),
        retain=True
    )

def printer_reachable():
    try:
        socket.create_connection((PRINTER_IP,WS_PORT),3)
        return True
    except:
        return False

def parse_line(line):
    if line.startswith("T:"):
        nozzle=re.search(r"T:(\d+)",line)
        bed=re.search(r"B:(\d+)",line)
        if nozzle:
            publish("fbg5/nozzle_temp",nozzle.group(1))
        if bed:
            publish("fbg5/bed_temp",bed.group(1))
    elif line.startswith("WIFI:"):
        publish("fbg5/wifi",line.split(":")[1])
    elif line.startswith("M997"):
        publish("fbg5/status",line.split(" ")[1])
    elif line.startswith("M27"):
        publish("fbg5/progress",line.split(" ")[1])
    elif line.startswith("M994"):
        data=line.split(" ",1)[1]
        if ";" in data:
            filename=data.split(";")[0]
            publish("fbg5/file",filename)
    elif line.startswith("M992"):
        publish("fbg5/time_left",line.split(" ")[1])

discovery()

while True:
    if not printer_reachable():
        publish("fbg5/connection","OFF")
        set_all_unavailable()
        time.sleep(INTERVAL)
        continue
    publish("fbg5/connection","ON")
    try:
        ws=websocket.create_connection(f"ws://{PRINTER_IP}:{WS_PORT}")
        ws.send("M105\nM27\nM994\nM992\nM997\n")
        msg=ws.recv()
        lines=msg.split("\n")
        for line in lines:
            line=line.strip()
            if not line or line=="ok":
                continue
            parse_line(line)
        ws.close()

    except:
        publish("fbg5/connection","OFF")
        set_all_unavailable()
    time.sleep(INTERVAL)