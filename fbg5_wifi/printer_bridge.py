import websocket
import json
import time
import re
import socket
import os
import paho.mqtt.client as mqtt
import logging
import sys

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,  # Можно изменить на DEBUG для более детального вывода
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("fbg5_bridge")

# Чтение переменных окружения
PRINTER_IP = os.getenv("PRINTER_IP")
WS_PORT = int(os.getenv("WS_PORT"))
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
INTERVAL = int(os.getenv("INTERVAL"))

logger.info(f"Запуск с параметрами: PRINTER_IP={PRINTER_IP}, WS_PORT={WS_PORT}, "
            f"MQTT_HOST={MQTT_HOST}, MQTT_PORT={MQTT_PORT}, INTERVAL={INTERVAL}")

# Настройка MQTT клиента
try:
    # Используем новое API, чтобы избежать DeprecationWarning
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    # Запускаем фоновый поток для поддержания соединения
    mqtt_client.loop_start()
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    logger.info("MQTT клиент инициализирован и запущен")
except Exception as e:
    logger.error(f"Ошибка подключения к MQTT брокеру: {e}")
    sys.exit(1)

device = {
    "identifiers": ["fbg5_printer"],
    "name": "Flying Bear Ghost 5",
    "manufacturer": "Flying Bear"
}

def publish(topic, value):
    """Публикация значения в MQTT с логированием."""
    logger.debug(f"Публикация: {topic} = {value}")
    result = mqtt_client.publish(topic, value, retain=True)
    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        logger.debug(f"Успешно опубликовано: {topic} = {value}")
    else:
        logger.warning(f"Ошибка публикации в топик {topic}: {result.rc}")

def set_all_unavailable():
    """Установка всех сенсоров в состояние 'unavailable'."""
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
        mqtt_client.publish(
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
    mqtt_client.publish(
        "homeassistant/binary_sensor/fbg5/connection/config",
        json.dumps(connection_payload),
        retain=True
    )
    logger.info("Отправлена discovery для connection")

def printer_reachable():
    """Проверка доступности порта принтера."""
    try:
        socket.create_connection((PRINTER_IP, WS_PORT), 3)
        logger.debug(f"Принтер доступен по {PRINTER_IP}:{WS_PORT}")
        return True
    except Exception as e:
        logger.debug(f"Принтер недоступен: {e}")
        return False

def parse_line(line):
    """Парсинг строки от принтера и публикация данных."""
    logger.debug(f"Парсинг строки: {line}")
    try:
        if line.startswith("T:"):
            nozzle = re.search(r"T:(\d+)", line)
            bed = re.search(r"B:(\d+)", line)
            if nozzle:
                value = nozzle.group(1)
                publish("fbg5/nozzle_temp", value)
                logger.info(f"Температура сопла: {value}")
            if bed:
                value = bed.group(1)
                publish("fbg5/bed_temp", value)
                logger.info(f"Температура стола: {value}")
        elif line.startswith("WIFI:"):
            value = line.split(":")[1]
            publish("fbg5/wifi", value)
            logger.info(f"Сигнал WiFi: {value}")
        elif line.startswith("M997"):
            value = line.split(" ")[1] if len(line.split()) > 1 else "unknown"
            publish("fbg5/status", value)
            logger.info(f"Статус: {value}")
        elif line.startswith("M27"):
            value = line.split(" ")[1] if len(line.split()) > 1 else "0"
            publish("fbg5/progress", value)
            logger.info(f"Прогресс: {value}")
        elif line.startswith("M994"):
            data = line.split(" ", 1)[1] if " " in line else ""
            if ";" in data:
                filename = data.split(";")[0]
                publish("fbg5/file", filename)
                logger.info(f"Файл: {filename}")
        elif line.startswith("M992"):
            value = line.split(" ")[1] if len(line.split()) > 1 else "0"
            publish("fbg5/time_left", value)
            logger.info(f"Оставшееся время: {value}")
        else:
            logger.debug(f"Неизвестная команда: {line}")
    except Exception as e:
        logger.error(f"Ошибка при парсинге строки '{line}': {e}")

# Отправка discovery при старте
discovery()

# Основной цикл
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
        logger.info(f"Подключение к WebSocket: ws://{PRINTER_IP}:{WS_PORT}")

        ws = websocket.create_connection(f"ws://{PRINTER_IP}:{WS_PORT}", timeout=10)
        logger.debug("WebSocket соединение установлено")

        # Отправка команд
        commands = "M105\nM27\nM994\nM992\nM997\n"
        ws.send(commands)
        logger.debug(f"Отправлены команды: {commands.strip()}")

        # Получение ответа
        msg = ws.recv()
        logger.debug(f"Получен ответ:\n{msg}")

        lines = msg.split("\n")
        for line in lines:
            line = line.strip()
            if not line or line == "ok":
                continue
            parse_line(line)

        ws.close()
        logger.debug("WebSocket соединение закрыто")

    except websocket.WebSocketTimeoutException as e:
        logger.error(f"Таймаут WebSocket: {e}")
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