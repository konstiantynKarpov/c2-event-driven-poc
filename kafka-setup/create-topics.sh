#!/bin/bash

KAFKA_CONTAINER_NAME="kafka"
KAFKA_BROKER_INTERNAL_ADDRESS="kafka:29092"

echo "Waiting for Kafka to be available..."
sleep 15

echo "Creating Kafka topics..."

TOPICS=(
  "blue-force-events"
  "enemy-events"
  "proximity-alerts"
  "order-events"
)

for TOPIC in "${TOPICS[@]}"
do
  echo "Attempting to create topic: $TOPIC"
  docker exec -it $KAFKA_CONTAINER_NAME \
    kafka-topics --create \
    --bootstrap-server $KAFKA_BROKER_INTERNAL_ADDRESS \
    --replication-factor 1 \
    --partitions 1 \
    --topic "$TOPIC" \
    --if-not-exists
done

echo "Kafka topic creation script finished."
echo "Listing topics:"
docker exec -it $KAFKA_CONTAINER_NAME \
    kafka-topics --list \
    --bootstrap-server $KAFKA_BROKER_INTERNAL_ADDRESS