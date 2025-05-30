# services/enemy-marking/main.py (Simplified Version)
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime, timezone
import json
import logging
from kafka import KafkaProducer
from kafka.errors import KafkaError
import os
from contextlib import asynccontextmanager

# --- Configuration ---
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:29092')
KAFKA_ENEMY_EVENTS_TOPIC = os.getenv('KAFKA_ENEMY_EVENTS_TOPIC', 'enemy-events')

# --- Kafka Setup ---
kafka_producer_instance = None

def get_kafka_producer():
    global kafka_producer_instance
    if kafka_producer_instance is None:
        try:
            kafka_producer_instance = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                retries=3
            )
            logger.info("Kafka Producer for Enemy Marking Service initialized.")
        except KafkaError as e:
            logger.error(f"Enemy Marking Service: Kafka Producer connection error: {e}")
            kafka_producer_instance = None
    return kafka_producer_instance

# --- Pydantic Models (based on your original PoC description for enemy units) ---
class EnemyUnitCreate(BaseModel):
    unit_id: str = Field(..., description="Unique identifier for the enemy unit")
    unit_type: Literal["infantry", "armor", "artillery", "vehicle", "aircraft", "unknown"] = Field(..., description="Type of enemy unit")
    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    confidence: Literal["low", "medium", "high"] = Field(..., description="Confidence level of the sighting")
    marked_by: Optional[str] = Field(None, description="Unit ID that marked this enemy") # Made optional for simplicity if not always available
    estimated_strength: Optional[str] = Field(None, description="Estimated enemy strength")
    timestamp: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))

class EnemyMarkingResponse(BaseModel):
    unit_id: str
    message: str = "Enemy unit data received and queued for event publication."
    data_received: EnemyUnitCreate # Echo back what was received

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FastAPI Lifespan Events ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Simplified Enemy Marking Service...")
    get_kafka_producer() # Initialize producer on startup
    yield
    logger.info("Shutting down Simplified Enemy Marking Service...")
    global kafka_producer_instance
    if kafka_producer_instance:
        kafka_producer_instance.flush(timeout=5)
        kafka_producer_instance.close()
        logger.info("Enemy Marking Service: Kafka producer closed.")

app = FastAPI(
    title="Simplified Enemy Marking Service",
    description="Receives enemy unit markings and publishes them to Kafka.",
    version="0.5.0",
    lifespan=lifespan
)

# --- API Endpoints ---
@app.get("/health", tags=["Health"])
async def health_check():
    if get_kafka_producer() is not None:
        return {"status": "healthy", "service": "enemy-marking-simplified", "dependencies": {"kafka_producer": "initialized"}}
    else:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "service": "enemy-marking-simplified",
                "dependencies": {"kafka_producer": "error"}
            }
        )

def _publish_enemy_event_task(enemy_data: dict, event_type: str = "enemy.spotted"):
    """Synchronous function to publish enemy data to Kafka."""
    producer = get_kafka_producer()
    if not producer:
        logger.error(f"Kafka producer not available. Failed to send {event_type} event for unit {enemy_data.get('unit_id')}")
        return

    event = {
        "eventType": event_type, # e.g., "enemy.spotted", "enemy.updated"
        "timestamp": datetime.now(timezone.utc).isoformat(), # Event creation time
        "data": enemy_data # This contains the original enemy data timestamp
    }
    try:
        producer.send(KAFKA_ENEMY_EVENTS_TOPIC, value=event)
        producer.flush(timeout=5)
        logger.info(f"Published {event_type} event for enemy unit {enemy_data['unit_id']}")
    except KafkaError as e:
        logger.error(f"Error publishing {event_type} event for {enemy_data['unit_id']}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during Kafka publish for {event_type} event {enemy_data['unit_id']}: {str(e)}")


@app.post("/api/enemy-units", response_model=EnemyMarkingResponse, status_code=202, tags=["EnemyMarking"])
async def mark_enemy_unit(enemy_unit_data: EnemyUnitCreate, background_tasks: BackgroundTasks):
    """
    Receive enemy unit marking and publish to Kafka.
    (Database and Redis interactions removed for speed of PoC development).
    """
    logger.info(f"Received enemy marking for unit {enemy_unit_data.unit_id}")

    # Convert Pydantic model to dict for Kafka publishing
    # Ensure timestamp is in ISO format string
    data_for_event = enemy_unit_data.dict()
    if isinstance(data_for_event['timestamp'], datetime):
        data_for_event['timestamp'] = data_for_event['timestamp'].isoformat()

    # For a PoC, we can assume a new spotting is always "enemy.spotted".
    # A more complex system might differentiate between create and update.
    background_tasks.add_task(_publish_enemy_event_task, data_for_event, "enemy.spotted")

    return EnemyMarkingResponse(
        unit_id=enemy_unit_data.unit_id,
        data_received=enemy_unit_data
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info") # Standard port 8000 for the service internally