# processing_services/proximity_processor/proximity_processor.py

import json
import time
import math
from datetime import datetime, timezone
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
import os  # For environment variables

# --- Configuration ---
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:29092').split(',')
BLUE_POSITIONS_TOPIC = os.getenv('BLUE_POSITIONS_TOPIC', 'blue-force-events')
ENEMY_UPDATES_TOPIC = os.getenv('ENEMY_UPDATES_TOPIC', 'enemy-events')  # Ensure Enemy Marking Service produces to this
PROXIMITY_ALERTS_TOPIC = os.getenv('PROXIMITY_ALERTS_TOPIC', 'proximity-alerts')
PROXIMITY_THRESHOLD_METERS = int(os.getenv('PROXIMITY_THRESHOLD_METERS', '1000'))  # Alert if units are within 1km
CONSUMER_GROUP_ID = os.getenv('CONSUMER_GROUP_ID', 'proximity-processor-group')


# --- Logging ---
def log_info(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] INFO: {message}", flush=True)


def log_error(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] ERROR: {message}", flush=True)


def log_warning(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] WARNING: {message}", flush=True)


# --- In-Memory State ---
# In a real system, use Redis or another persistent store for this state
# to allow scalability, fault tolerance, and data persistence.
latest_blue_positions = {}  # { "unit_id": {"latitude": float, "longitude": float, "timestamp": str, ...} }
latest_enemy_positions = {}  # { "unit_id": {"latitude": float, "longitude": float, "timestamp": str, ...} }

# --- Kafka Clients ---
kafka_producer = None
kafka_consumer = None

try:
    kafka_producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        retries=5,
        linger_ms=10  # Add a small linger_ms for batching
    )
    log_info("Kafka producer initialized successfully.")
except KafkaError as e:
    log_error(f"Fatal: Error creating Kafka producer: {e}")
    # In a real service, you might exit or have a more robust retry/fallback
    # For this script, subsequent produce calls will fail if kafka_producer is None

try:
    kafka_consumer = KafkaConsumer(
        # BLUE_POSITIONS_TOPIC, # Subscribing below
        # ENEMY_UPDATES_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset='earliest',
        group_id=CONSUMER_GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode('utf-8')),
        consumer_timeout_ms=1000  # To allow periodic checks, e.g., for shutdown
    )
    kafka_consumer.subscribe([BLUE_POSITIONS_TOPIC, ENEMY_UPDATES_TOPIC])
    log_info(f"Kafka consumer initialized and subscribed to topics: {BLUE_POSITIONS_TOPIC}, {ENEMY_UPDATES_TOPIC}")
except KafkaError as e:
    log_error(f"Fatal: Error creating Kafka consumer: {e}")
    if kafka_producer:
        kafka_producer.close()
    # exit(1) # Or handle more gracefully


# --- Helper Functions ---
def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two lat/lon points in meters."""
    R = 6371000  # Radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    return distance


def check_proximity_and_alert():
    """
    Checks proximity between all blue units and enemy units.
    This is a naive O(N*M) check. For large numbers of units,
    consider spatial indexing (e.g., GeoHashes in Redis) for efficiency.
    """
    if not kafka_producer:
        log_error("Kafka producer is not available. Skipping proximity check.")
        return

    alerts_sent_this_cycle = set()  # To avoid duplicate alerts for the same pair in one processing pass

    # Create copies of keys to iterate over to avoid issues if dicts are modified during iteration (less likely here)
    blue_unit_ids = list(latest_blue_positions.keys())
    enemy_unit_ids = list(latest_enemy_positions.keys())

    for blue_id in blue_unit_ids:
        blue_pos = latest_blue_positions.get(blue_id)
        if not blue_pos: continue  # Should not happen if key is from .keys() but good practice

        for enemy_id in enemy_unit_ids:
            enemy_pos = latest_enemy_positions.get(enemy_id)
            if not enemy_pos: continue

            pair_key = tuple(sorted((blue_id, enemy_id)))

            # Basic validation of position data
            if not all(k in blue_pos for k in ['latitude', 'longitude']) or \
                    not all(k in enemy_pos for k in ['latitude', 'longitude']):
                log_warning(f"Incomplete position data for pair {blue_id}, {enemy_id}. Skipping.")
                continue

            try:
                distance = haversine_distance(
                    float(blue_pos['latitude']), float(blue_pos['longitude']),
                    float(enemy_pos['latitude']), float(enemy_pos['longitude'])
                )
            except (ValueError, TypeError) as e:
                log_warning(f"Could not calculate distance for {blue_id} and {enemy_id} due to invalid lat/lon: {e}")
                continue

            if distance < PROXIMITY_THRESHOLD_METERS:
                if pair_key in alerts_sent_this_cycle:
                    continue

                alert_event = {
                    "eventType": "proximity.alert",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "blue_unit_id": blue_id,
                        "blue_position": blue_pos,  # Send the whole position dict
                        "enemy_unit_id": enemy_id,
                        "enemy_position": enemy_pos,  # Send the whole position dict
                        "distance_meters": round(distance, 2),
                        "threshold_meters": PROXIMITY_THRESHOLD_METERS,
                        "detected_at": datetime.now(timezone.utc).isoformat()
                    }
                }
                try:
                    kafka_producer.send(PROXIMITY_ALERTS_TOPIC, value=alert_event)
                    # Consider flushing in batches or based on time/message count for performance
                    # For this script, a flush here ensures the message is sent promptly.
                    kafka_producer.flush(timeout=5)
                    log_info(
                        f"Proximity Alert: Blue {blue_id} and Enemy {enemy_id} are {distance:.2f}m apart. Event sent.")
                    alerts_sent_this_cycle.add(pair_key)
                except KafkaError as e:
                    log_error(f"Error sending proximity alert to Kafka for {blue_id}/{enemy_id}: {e}")
                except Exception as e:
                    log_error(f"Unexpected error sending proximity alert for {blue_id}/{enemy_id}: {e}")


# --- Main Processing Loop ---
def main():
    log_info("Starting Proximity Processor...")
    log_info(f"Consuming from Kafka topics: {BLUE_POSITIONS_TOPIC}, {ENEMY_UPDATES_TOPIC}")
    log_info(f"Consumer Group ID: {CONSUMER_GROUP_ID}")
    log_info(f"Producing proximity alerts to Kafka topic: {PROXIMITY_ALERTS_TOPIC}")
    log_info(f"Proximity Threshold: {PROXIMITY_THRESHOLD_METERS} meters")

    if not kafka_consumer:
        log_error("Kafka consumer not initialized. Exiting.")
        if kafka_producer:
            kafka_producer.close()
        return

    running = True
    while running:
        try:
            # Poll for messages with a timeout to allow for graceful shutdown
            # The consumer_timeout_ms in constructor makes this non-blocking if no messages.
            for message in kafka_consumer:  # This will block until consumer_timeout_ms if no messages
                if message is None:  # Reached timeout
                    continue

                # log_info(f"Received message: Topic={message.topic}, Partition={message.partition}, Offset={message.offset}")
                event_data = message.value  # Already deserialized

                if not isinstance(event_data, dict) or "eventType" not in event_data or "data" not in event_data:
                    log_warning(f"Received malformed message on topic {message.topic}: {event_data}")
                    continue

                event_type = event_data.get("eventType")
                payload = event_data.get("data")

                if not isinstance(payload, dict) or "unit_id" not in payload or \
                        "latitude" not in payload or "longitude" not in payload:
                    log_warning(f"Received event on topic {message.topic} with incomplete data: {payload}")
                    continue

                unit_id = payload['unit_id']

                # Store the entire payload.data as it might have other useful fields.
                # Ensure core fields are present. Timestamp handling is important.
                position_details = payload.copy()  # Keep all data fields
                position_details.setdefault('timestamp', datetime.now(timezone.utc).isoformat())

                updated = False
                if message.topic == BLUE_POSITIONS_TOPIC and event_type == "blue.position.updated":
                    latest_blue_positions[unit_id] = position_details
                    # log_info(f"Updated Blue Force: {unit_id} at {position_details['latitude']},{position_details['longitude']}")
                    updated = True

                elif message.topic == ENEMY_UPDATES_TOPIC and event_type in ["enemy.spotted", "enemy.updated"]:
                    latest_enemy_positions[unit_id] = position_details
                    # log_info(f"Updated Enemy Unit: {unit_id} at {position_details['latitude']},{position_details['longitude']}")
                    updated = True

                else:
                    log_warning(f"Unhandled event type '{event_type}' or topic '{message.topic}'.")

                if updated:
                    # Perform proximity check whenever any relevant position is updated
                    check_proximity_and_alert()

            # If you want less frequent global checks, you could move check_proximity_and_alert()
            # out of the message loop and call it periodically, e.g., based on time,
            # but checking on each relevant update is more real-time for a PoC.

        except KeyboardInterrupt:
            log_info("Shutdown signal received (KeyboardInterrupt). Exiting loop.")
            running = False
        except Exception as e:
            log_error(f"An unexpected error occurred in the main loop: {e}")
            # Depending on the error, you might want to break or continue with a delay
            time.sleep(5)  # Brief pause before retrying loop

    log_info("Proximity Processor shutting down...")


if __name__ == "__main__":
    try:
        main()
    finally:
        if kafka_consumer:
            log_info("Closing Kafka consumer.")
            kafka_consumer.close()
        if kafka_producer:
            log_info("Flushing and closing Kafka producer.")
            kafka_producer.flush()
            kafka_producer.close()
        log_info("Proximity Processor has finished.")

