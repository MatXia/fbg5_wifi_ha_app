import websocket
import json
import time
import re
import socket
import os
import paho.mqtt.client as mqtt
import logging
import sys

# Настройка логирования (уровень INFO, чтобы видеть все важные шаги)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("fbg5_bridge")

# Параметры из окружения
PRINTER_IP = os.getenv("PRINTER_IP")
WS_PORT = int(os.getenv("WS_PORT"))
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
INTERVAL = int(os.getenv("INTERVAL"))

logger.info(f"Запуск с параметрами: PRINTER_IP={PRINTER_IP}, WS_PORT={WS_PORT}, "
            f"MQTT_HOST={MQTT_HOST}, MQTT_PORT={MQTT_PORT}, "
            f"MQTT_USER={'задан' if MQTT_USER else 'не задан'}, INTERVAL={INTERVAL}")

# Колбэки MQTT
def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        logger.info("MQTT брокер: подключено успешно")
        discovery()
    else:
        logger.error(f"MQTT брокер: ошибка подключения, код {reason_code} - {mqtt.connack_string(reason_code)}")

def on_disconnect(client, userdata, flags, reason_code, properties=None):
    logger.warning(f"MQTT брокер: отключено, код {reason_code}. Попытка переподключения...")

# Создание клиента MQTT
try:
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)

    if MQTT_USER and MQTT_PASSWORD:
        mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        logger.info("Установлены учётные данные для MQTT")
    else:
        logger.info("Авторизация MQTT не требуется (логин/пароль не заданы)")

    logger.info(f"Попытка подключения к MQTT брокеру {MQTT_HOST}:{MQTT_PORT}")
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    mqtt_client.loop_start()
    while not mqtt_client.is_connected():
        logger.info("Ожидание подключения MQTT...")
        time.sleep(1)
    logger.info("MQTT клиент запущен, ожидание подключения...")
except Exception as e:
    logger.error(f"Ошибка создания MQTT клиента: {e}", exc_info=True)
    sys.exit(1)

# Устройство для Home Assistant
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
    """Установка всех сенсоров в 'unavailable'."""
    sensors = ["status", "nozzle_temp", "bed_temp", "wifi", "progress", "file", "time_left"]
    for s in sensors:
        publish(f"fbg5/{s}", "unavailable")
    logger.info("Все сенсоры переведены в unavailable")

def discovery():
    """Отправка конфигурации сенсоров в Home Assistant."""
    sensors = {
        "status": "Статус принтера",
        "nozzle_temp": "Температура сопла",
        "bed_temp": "Температура стола",
        "wifi": "Сигнал Wifi",
        "progress": "Прогресс печати",
        "file": "Название файла",
        "time_left": "Оставшееся время"
    }
    for key, name in sensors.items():
        payload = {
            "name": name,
            "state_topic": f"fbg5/{key}",
            "unique_id": f"fbg5_{key}",
            "device": device
        }
        publish(
            f"homeassistant/sensor/fbg5/{key}/config",
            json.dumps(payload),
            retain=True
        )
        logger.info(f"Отправлена discovery для {key}")

    connection_payload = {
        "name": "Статус подключения",
        "state_topic": "fbg5/connection",
        "payload_on": "ON",
        "payload_off": "OFF",
        "unique_id": "fbg5_connection",
        "device_class": "connectivity",
        "device": device
    }
    publish(
        "homeassistant/binary_sensor/fbg5/connection/config",
        json.dumps(connection_payload),
        retain=True
    )
    logger.info("Отправлена discovery для connection")

def printer_reachable():
    """Проверка доступности принтера по порту."""
    try:
        socket.create_connection((PRINTER_IP, WS_PORT), 3)
        logger.debug(f"Принтер доступен по {PRINTER_IP}:{WS_PORT}")
        return True
    except Exception as e:
        logger.debug(f"Принтер недоступен: {e}")
        return False

def parse_line(line):
    """Парсинг строки от принтера и публикация."""
    logger.debug(f"Парсинг строки: {line}")
    try:
        if line.startswith("T:"):
            nozzle = re.search(r"T:(\d+)", line)
            bed = re.search(r"B:(\d+)", line)
            if nozzle:
                value = nozzle.group(1)
                publish("fbg5/nozzle_temp", value)
                logger.info(f"Извлечена температура сопла: {value}")
            if bed:
                value = bed.group(1)
                publish("fbg5/bed_temp", value)
                logger.info(f"Извлечена температура стола: {value}")
        elif line.startswith("WIFI:"):
            value = line.split(":", 1)[1] if ":" in line else ""
            publish("fbg5/wifi", value)
            logger.info(f"Извлечён сигнал WiFi: {value}")
        elif line.startswith("M997"):
            parts = line.split()
            value = parts[1] if len(parts) > 1 else "unknown"
            publish("fbg5/status", value)
            logger.info(f"Извлечён статус: {value}")
        elif line.startswith("M27"):
            parts = line.split()
            value = parts[1] if len(parts) > 1 else "0"
            publish("fbg5/progress", value)
            logger.info(f"Извлечён прогресс: {value}")
        elif line.startswith("M994"):
            if " " in line:
                data = line.split(" ", 1)[1]
                if ";" in data:
                    filename = data.split(";")[0]
                    publish("fbg5/file", filename)
                    logger.info(f"Извлечено имя файла: {filename}")
        elif line.startswith("M992"):
            parts = line.split()
            value = parts[1] if len(parts) > 1 else "0"
            publish("fbg5/time_left", value)
            logger.info(f"Извлечено оставшееся время: {value}")
        else:
            logger.debug(f"Неизвестная команда: {line}")
    except Exception as e:
        logger.error(f"Ошибка парсинга строки '{line}': {e}", exc_info=True)

# Основной цикл
logger.info("Запуск основного цикла")
while True:
    try:
        # Проверка доступности принтера
        if not printer_reachable():
            logger.warning("Принтер недоступен по TCP")
            publish("fbg5/connection", "OFF")
            set_all_unavailable()
            time.sleep(INTERVAL)
            continue

        publish("fbg5/connection", "ON")
        logger.info(f"Попытка подключения к WebSocket: ws://{PRINTER_IP}:{WS_PORT}")

        # Создание WebSocket соединения с таймаутом
        ws = websocket.create_connection(f"ws://{PRINTER_IP}:{WS_PORT}", timeout=10)
        logger.info("WebSocket соединение установлено")

        # Устанавливаем таймаут на чтение
        ws.settimeout(10)

        # Отправка команд
        commands = "M105\nM27\nM994\nM992\nM997\n"
        logger.info(f"Отправка команд:\n{commands.strip()}")
        ws.send(commands)
        logger.info("Команды отправлены, ожидание ответа...")

        # Получение ответа
        msg = ws.recv()
        logger.info(f"ПОЛУЧЕН ОТВЕТ ОТ ПРИНТЕРА:\n{msg}")

        # Закрываем соединение
        ws.close()
        logger.info("WebSocket соединение закрыто")

        # Парсинг ответа
        lines = msg.split("\n")
        for line in lines:
            line = line.strip()
            if not line or line == "ok":
                continue
            parse_line(line)

    except websocket.WebSocketTimeoutException as e:
        logger.error(f"Таймаут WebSocket (нет ответа от принтера): {e}")
        publish("fbg5/connection", "OFF")
        set_all_unavailable()
    except websocket.WebSocketException as e:
        logger.error(f"Ошибка WebSocket: {e}")
        publish("fbg5/connection", "OFF")
        set_all_unavailable()
    except Exception as e:
        logger.error(f"Необработанная ошибка: {e}", exc_info=True)
        publish("fbg5/connection", "OFF")
        set_all_unavailable()

    logger.info(f"Ожидание {INTERVAL} секунд до следующего опроса")
    time.sleep(INTERVAL)