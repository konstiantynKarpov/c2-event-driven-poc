# services/notification_service/main.py (Modified for Kafka Connection Retry)

import json
import time
from datetime import datetime, timezone
from kafka import KafkaConsumer
from kafka.errors import KafkaError, NoBrokersAvailable  # Import NoBrokersAvailable specifically
import os

# --- Configuration ---
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:29092').split(',')
PROXIMITY_ALERTS_TOPIC = os.getenv('PROXIMITY_ALERTS_TOPIC', 'proximity-alerts')
ENEMY_EVENTS_TOPIC = os.getenv('ENEMY_EVENTS_TOPIC', 'enemy-events')
ORDER_EVENTS_TOPIC = os.getenv('KAFKA_ORDER_EVENTS_TOPIC', 'order-events')  # Added for orders
CONSUMER_GROUP_ID = os.getenv('NOTIFICATION_CONSUMER_GROUP_ID', 'notification-service-group')

# Updated to include order-events
TOPICS_TO_CONSUME = [PROXIMITY_ALERTS_TOPIC, ENEMY_EVENTS_TOPIC, ORDER_EVENTS_TOPIC]

MAX_KAFKA_CONNECTION_RETRIES = 5
KAFKA_RETRY_DELAY_SECONDS = 10


# --- Logging ---
def log_info(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] INFO: [NotificationService] {message}", flush=True)


def log_error(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] ERROR: [NotificationService] {message}", flush=True)


def log_warning(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] WARNING: [NotificationService] {message}", flush=True)


# --- Kafka Consumer Setup (will be initialized in main) ---
kafka_consumer = None


def initialize_kafka_consumer():
    global kafka_consumer
    for attempt in range(1, MAX_KAFKA_CONNECTION_RETRIES + 1):
        try:
            log_info(f"Attempting to connect to Kafka (Attempt {attempt}/{MAX_KAFKA_CONNECTION_RETRIES})...")
            temp_consumer = KafkaConsumer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                auto_offset_reset='earliest',
                group_id=CONSUMER_GROUP_ID,
                value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                consumer_timeout_ms=1000
            )
            temp_consumer.subscribe(TOPICS_TO_CONSUME)
            log_info(f"Kafka consumer initialized and subscribed to topics: {', '.join(TOPICS_TO_CONSUME)}")
            kafka_consumer = temp_consumer  # Assign to global if successful
            return True  # Indicate success
        except NoBrokersAvailable:  # Specifically catch this error
            log_error(f"NoBrokersAvailable on attempt {attempt}. Kafka might not be ready yet.")
            if attempt < MAX_KAFKA_CONNECTION_RETRIES:
                log_info(f"Retrying in {KAFKA_RETRY_DELAY_SECONDS} seconds...")
                time.sleep(KAFKA_RETRY_DELAY_SECONDS)
            else:
                log_error("Max Kafka connection retries reached. Could not connect.")
                return False  # Indicate failure
        except KafkaError as e:  # Catch other potential Kafka errors during setup
            log_error(f"Fatal KafkaError during consumer setup on attempt {attempt}: {e}")
            # For other KafkaErrors, you might not want to retry indefinitely or at all
            return False
        except Exception as e:
            log_error(f"Fatal unexpected error during Kafka consumer setup on attempt {attempt}: {e}")
            return False
    return False


# --- Main Processing Loop ---
def main():
    log_info("Starting Notification Service...")

    if not initialize_kafka_consumer():  # Try to initialize with retries
        log_error("Kafka consumer could not be initialized. Notification Service cannot start.")
        return

    running = True
    while running:
        try:
            for message in kafka_consumer:
                if message is None:
                    continue

                log_info(f"Received event from Topic '{message.topic}'")
                event_data = message.value

                if not isinstance(event_data, dict) or "eventType" not in event_data or "data" not in event_data:
                    log_warning(f"Received malformed message on topic {message.topic}: {event_data}")
                    continue

                event_type = event_data.get("eventType")
                data = event_data.get("data")
                notification_message = f"EVENT: {event_type} | "

                if event_type == "proximity.alert":
                    blue_unit = data.get('blue_unit_id', 'N/A')
                    enemy_unit = data.get('enemy_unit_id', 'N/A')
                    distance = data.get('distance_meters', 'N/A')
                    notification_message += (
                        f"Proximity Alert! Friendly: {blue_unit} is {distance}m from Enemy: {enemy_unit}.")

                elif event_type == "enemy.spotted":
                    enemy_unit = data.get('unit_id', 'N/A')
                    enemy_type = data.get('unit_type', 'N/A')
                    notification_message += (f"Enemy Spotted! Unit: {enemy_unit}, Type: {enemy_type}.")

                elif event_type == "order.created":
                    order_id = data.get('order_id', 'N/A')
                    issued_to = data.get('issued_to', 'N/A')
                    order_type_val = data.get('type', data.get('order_type', 'N/A'))
                    notification_message += (
                        f"New Order Created! ID: {order_id}, For: {issued_to}, Type: {order_type_val}.")

                else:
                    notification_message += f"Raw Data: {json.dumps(data)}"

                log_info(f"NOTIFICATION: {notification_message}")

        except KeyboardInterrupt:
            log_info("Shutdown signal received (KeyboardInterrupt). Exiting loop.")
            running = False
        except json.JSONDecodeError as e:
            log_warning(
                f"Failed to decode JSON message: {e}. Message: {message.value if 'message' in locals() and message else 'N/A'}")
        except Exception as e:
            log_error(f"An unexpected error occurred in the main loop: {e}")
            time.sleep(5)

    log_info("Notification Service shutting down...")


if __name__ == "__main__":
    try:
        main()
    finally:
        if kafka_consumer:
            log_info("Closing Kafka consumer.")
            kafka_consumer.close()
        log_info("Notification Service has finished.")