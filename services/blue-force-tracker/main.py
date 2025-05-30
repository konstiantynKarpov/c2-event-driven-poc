# services/blue-force-tracker/main.py (Simplified Version)
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional  # List might not be needed if GET all is removed
from datetime import datetime, timezone
import json
import logging
from kafka import KafkaProducer
from kafka.errors import KafkaError
import os
from contextlib import asynccontextmanager

# --- Configuration ---
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:29092')
KAFKA_BLUE_FORCE_TOPIC = 'blue-force-events'

# --- Kafka Setup ---
kafka_producer_instance = None


def get_kafka_producer():
    global kafka_producer_instance
    if kafka_producer_instance is None:
        try:
            kafka_producer_instance = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                retries=3  # Simplified retries
            )
            logger.info("Kafka Producer initialized.")
        except KafkaError as e:
            logger.error(f"Kafka Producer connection error: {e}")
            kafka_producer_instance = None
    return kafka_producer_instance


# --- Pydantic Models ---
class PositionUpdate(BaseModel):
    unit_id: str = Field(..., description="Unique identifier for the unit")
    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    speed: Optional[float] = Field(None, ge=0, description="Speed in km/h")
    heading: Optional[float] = Field(None, ge=0, lt=360, description="Heading in degrees")
    brigade: Optional[int] = Field(None, description="Brigade number")
    timestamp: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))


class PositionResponse(BaseModel):  # Simplified response
    unit_id: str
    latitude: float
    longitude: float
    timestamp: datetime
    message: str = "Position received and queued for processing."


# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- FastAPI Lifespan Events ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Simplified Blue Force Tracker Service...")
    get_kafka_producer()  # Initialize producer on startup
    yield
    logger.info("Shutting down Simplified Blue Force Tracker Service...")
    global kafka_producer_instance
    if kafka_producer_instance:
        kafka_producer_instance.flush(timeout=5)
        kafka_producer_instance.close()
        logger.info("Kafka producer closed.")


app = FastAPI(
    title="Simplified Blue Force Tracker Service",
    description="Receives unit positions and publishes them to Kafka.",
    version="0.5.0",  # Indicate it's a simplified version
    lifespan=lifespan
)


# --- API Endpoints ---
@app.get("/health", tags=["Health"])
async def health_check():
    if get_kafka_producer() is not None:
        return {"status": "healthy", "service": "blue-force-tracker-simplified",
                "dependencies": {"kafka_producer": "initialized"}}
    else:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "service": "blue-force-tracker-simplified",
                "dependencies": {"kafka_producer": "error"}
            }
        )


def _publish_to_kafka_task(position_payload: dict):
    """Synchronous function to publish data to Kafka."""
    producer = get_kafka_producer()
    if not producer:
        logger.error(f"Kafka producer not available. Failed to send event for unit {position_payload.get('unit_id')}")
        return

    event = {
        "eventType": "blue.position.updated",
        "timestamp": datetime.now(timezone.utc).isoformat(),  # Event creation time
        "data": position_payload  # Original payload with its own timestamp
    }
    try:
        producer.send(KAFKA_BLUE_FORCE_TOPIC, value=event)
        # Flush might be better handled in batches or on shutdown for high throughput
        # For a rapid PoC and fewer messages, flushing here is okay.
        producer.flush(timeout=5)
        logger.info(f"Published position event for unit {position_payload['unit_id']}")
    except KafkaError as e:
        logger.error(f"Error publishing position event for {position_payload['unit_id']}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during Kafka publish for {position_payload['unit_id']}: {str(e)}")


@app.post("/api/positions", response_model=PositionResponse, status_code=202, tags=["Positions"])
async def receive_position(position: PositionUpdate, background_tasks: BackgroundTasks):
    """
    Receive unit position and publish to Kafka.
    (Database and Redis interactions removed for speed of PoC development).
    """
    logger.info(f"Received position update for unit {position.unit_id}")

    # Convert Pydantic model to dict for Kafka publishing
    # Ensure timestamp is in ISO format string for consistent serialization
    position_data_for_event = position.dict()
    if isinstance(position_data_for_event['timestamp'], datetime):
        position_data_for_event['timestamp'] = position_data_for_event['timestamp'].isoformat()

    background_tasks.add_task(_publish_to_kafka_task, position_data_for_event)

    return PositionResponse(
        unit_id=position.unit_id,
        latitude=position.latitude,
        longitude=position.longitude,
        timestamp=position.timestamp  # Return the original timestamp from input or Pydantic default
    )


@app.post("/api/simulate-movement", status_code=202, tags=["Simulation"])
async def simulate_movement_endpoint(background_tasks: BackgroundTasks, count: int = 3, units_prefix: str = "SIM_FAST"):
    """Simulate position updates for a number of units and publish to Kafka."""
    import random
    logger.info(f"Starting simplified movement simulation for {count} units with prefix {units_prefix}.")

    for i in range(count):
        unit_id = f"{units_prefix}{i + 1:03}"
        base_lat, base_lon = 50.4501, 30.5234

        lat_offset = random.uniform(-0.05, 0.05)
        lon_offset = random.uniform(-0.05, 0.05)

        # Create the PositionUpdate object
        position_payload_model = PositionUpdate(
            unit_id=unit_id,
            latitude=round(base_lat + lat_offset, 6),
            longitude=round(base_lon + lon_offset, 6),
            speed=random.uniform(0, 80),
            heading=random.uniform(0, 359.9),
            brigade=random.choice([1, 2, None]),
            timestamp=datetime.now(timezone.utc)  # Fresh timestamp for simulated event
        )

        # Convert to dict for Kafka publishing, ensuring timestamp is ISO string
        position_data_for_event = position_payload_model.dict()
        if isinstance(position_data_for_event['timestamp'], datetime):
            position_data_for_event['timestamp'] = position_data_for_event['timestamp'].isoformat()

        background_tasks.add_task(_publish_to_kafka_task, position_data_for_event)
        logger.info(f"Simulated and queued Kafka event for {unit_id}")

    return {"status": "success", "message": f"Simplified movement simulation queued for {count} units."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")