import websocket
import json
import time
import re
import socket
import os
import paho.mqtt.client as mqtt
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("fbg5_bridge")

PRINTER_IP = os.getenv("PRINTER_IP")
WS_PORT = int(os.getenv("WS_PORT"))
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
INTERVAL = int(os.getenv("INTERVAL"))

logger.info(
    f"Запуск с параметрами: PRINTER_IP={PRINTER_IP}, WS_PORT={WS_PORT}, "
    f"MQTT_HOST={MQTT_HOST}, MQTT_PORT={MQTT_PORT}, "
    f"MQTT_USER={'задан' if MQTT_USER else 'не задан'}, INTERVAL={INTERVAL}"
)

device = {
    "identifiers": ["fbg5_printer"],
    "name": "Flying Bear Ghost 5",
    "manufacturer": "Flying Bear"
}


def publish(topic, value):
    if not mqtt_client.is_connected():
        logger.warning("MQTT не подключён")
        return

    result = mqtt_client.publish(topic, value, retain=True)
    result.wait_for_publish()

    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        logger.info(f"MQTT -> {topic} = {value}")
    else:
        logger.warning(f"Ошибка публикации {topic}: {result.rc}")


def set_all_unavailable():
    sensors = ["status", "nozzle_temp", "bed_temp", "wifi", "progress", "file", "time_left"]
    for s in sensors:
        publish(f"fbg5/{s}", "unavailable")


def discovery():

    sensors = {
        "status": "Статус принтера",
        "nozzle_temp": "Температура сопла",
        "bed_temp": "Температура стола",
        "wifi": "Сигнал WiFi",
        "progress": "Прогресс печати",
        "file": "Файл печати",
        "time_left": "Оставшееся время"
    }

    for key, name in sensors.items():

        payload = {
            "name": name,
            "state_topic": f"fbg5/{key}",
            "unique_id": f"fbg5_{key}",
            "device": device
        }

        mqtt_client.publish(
            f"homeassistant/sensor/fbg5/{key}/config",
            json.dumps(payload),
            retain=True
        )

    connection_payload = {
        "name": "Printer Connection",
        "state_topic": "fbg5/connection",
        "payload_on": "ON",
        "payload_off": "OFF",
        "unique_id": "fbg5_connection",
        "device_class": "connectivity",
        "device": device
    }

    mqtt_client.publish(
        "homeassistant/binary_sensor/fbg5/connection/config",
        json.dumps(connection_payload),
        retain=True
    )

    logger.info("MQTT discovery отправлен")


def printer_reachable():

    try:
        socket.create_connection((PRINTER_IP, WS_PORT), 3)
        return True
    except:
        return False


def parse_line(line):

    if line.startswith("FWV"):
        return

    logger.info(f"Парсинг строки: {line}")

    try:

        if line.startswith("T:"):

            nozzle = re.search(r"T:(\d+)", line)
            bed = re.search(r"B:(\d+)", line)

            if nozzle:
                publish("fbg5/nozzle_temp", nozzle.group(1))

            if bed:
                publish("fbg5/bed_temp", bed.group(1))

        elif line.startswith("WIFI:"):

            publish("fbg5/wifi", line.split(":")[1])

        elif line.startswith("M997"):

            parts = line.split()
            if len(parts) > 1:
                publish("fbg5/status", parts[1])

        elif line.startswith("M27"):

            parts = line.split()
            if len(parts) > 1:
                publish("fbg5/progress", parts[1])

        elif line.startswith("M994"):

            data = line.split(" ", 1)[1]

            if ";" in data:
                filename = data.split(";")[0]
                publish("fbg5/file", filename)

        elif line.startswith("M992"):

            parts = line.split()
            if len(parts) > 1:
                publish("fbg5/time_left", parts[1])

    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")


def on_connect(client, userdata, flags, reason_code, properties=None):

    if reason_code == 0:
        logger.info("MQTT подключен")
        discovery()
    else:
        logger.error(f"MQTT ошибка подключения {reason_code}")


def on_disconnect(client, userdata, flags, reason_code, properties=None):

    logger.warning(f"MQTT отключен {reason_code}")


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect

mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)

if MQTT_USER and MQTT_PASSWORD:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)

mqtt_client.loop_start()

while not mqtt_client.is_connected():
    logger.info("Ожидание MQTT...")
    time.sleep(1)


logger.info("Запуск основного цикла")

while True:

    try:

        if not printer_reachable():

            logger.warning("Принтер недоступен")

            publish("fbg5/connection", "OFF")
            set_all_unavailable()

            time.sleep(INTERVAL)
            continue

        publish("fbg5/connection", "ON")

        logger.info(f"Подключение WS ws://{PRINTER_IP}:{WS_PORT}")

        ws = websocket.create_connection(f"ws://{PRINTER_IP}:{WS_PORT}", timeout=10)

        ws.settimeout(2)

        commands = "M105\nM27\nM994\nM992\nM997\n\n"

        logger.info(f"Отправка команд:\n{commands}")

        ws.send(commands)

        responses = []

        while True:

            try:

                msg = ws.recv()

                logger.info(f"WS сообщение: {msg}")

                responses.append(msg)

            except websocket.WebSocketTimeoutException:

                break

        ws.close()

        for msg in responses:

            lines = msg.split("\n")

            for line in lines:

                line = line.strip()

                if not line or line == "ok":
                    continue

                parse_line(line)

    except Exception as e:

        logger.error(f"Ошибка цикла: {e}")

        publish("fbg5/connection", "OFF")
        set_all_unavailable()

    logger.info(f"Ожидание {INTERVAL} секунд")

    time.sleep(INTERVAL)