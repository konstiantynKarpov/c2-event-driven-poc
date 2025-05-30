from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import json
import logging
from kafka import KafkaProducer
from kafka.errors import KafkaError
import os
import uuid
from contextlib import asynccontextmanager


KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:29092').split(',')
KAFKA_ORDER_EVENTS_TOPIC = os.getenv('KAFKA_ORDER_EVENTS_TOPIC', 'order-events')

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
            logger.info("Kafka Producer for Order Service initialized.")
        except KafkaError as e:
            logger.error(f"Order Service: Kafka Producer connection error: {e}")
            kafka_producer_instance = None
    return kafka_producer_instance


class OrderCreate(BaseModel):
    order_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()),
                                    description="Unique order identifier (auto-generated if not provided)")
    issued_by: str = Field(..., description="Identifier of the command/user issuing the order")
    issued_to: str = Field(..., description="Identifier of the unit the order is issued to")
    order_type: str = Field(..., alias="type", description="Type of order (e.g., 'move', 'attack', 'recon')")
    details: Optional[Dict[str, Any]] = Field({}, description="Specific details of the order, flexible structure")
    timestamp: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrderResponse(BaseModel):
    order_id: str
    message: str = "Order received and event queued for publication."
    data_received: OrderCreate


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Simplified Order Service...")
    get_kafka_producer()  # Initialize producer on startup
    yield
    logger.info("Shutting down Simplified Order Service...")
    global kafka_producer_instance
    if kafka_producer_instance:
        kafka_producer_instance.flush(timeout=5)
        kafka_producer_instance.close()
        logger.info("Order Service: Kafka producer closed.")


app = FastAPI(
    title="Simplified Order Service",
    description="Receives orders and publishes 'order.created' events to Kafka.",
    version="0.5.0",
    lifespan=lifespan
)


# --- API Endpoints ---
@app.get("/health", tags=["Health"])
async def health_check():
    if get_kafka_producer() is not None:
        return {"status": "healthy", "service": "order-service-simplified",
                "dependencies": {"kafka_producer": "initialized"}}
    else:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "service": "order-service-simplified",
                "dependencies": {"kafka_producer": "error"}
            }
        )


def _publish_order_event_task(order_data: dict, event_type: str = "order.created"):
    """Synchronous function to publish order data to Kafka."""
    producer = get_kafka_producer()
    if not producer:
        logger.error(
            f"Kafka producer not available. Failed to send {event_type} event for order {order_data.get('order_id')}")
        return

    event = {
        "eventType": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),  # Event creation time
        "data": order_data  # This contains the original order data and its timestamp
    }
    try:
        producer.send(KAFKA_ORDER_EVENTS_TOPIC, value=event)
        producer.flush(timeout=5)
        logger.info(f"Published {event_type} event for order {order_data['order_id']}")
    except KafkaError as e:
        logger.error(f"Error publishing {event_type} event for order {order_data['order_id']}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during Kafka publish for {event_type} event {order_data['order_id']}: {str(e)}")


@app.post("/api/orders", response_model=OrderResponse, status_code=202, tags=["Orders"])
async def create_order(order_data: OrderCreate, background_tasks: BackgroundTasks):
    """
    Receive a new order and publish an 'order.created' event to Kafka.
    """
    logger.info(f"Received new order request: {order_data.order_id}")

    data_for_event = order_data.dict(by_alias=True)
    if isinstance(data_for_event['timestamp'], datetime):
        data_for_event['timestamp'] = data_for_event['timestamp'].isoformat()

    if 'order_id' not in data_for_event or not data_for_event['order_id']:
        data_for_event['order_id'] = str(uuid.uuid4())

    background_tasks.add_task(_publish_order_event_task, data_for_event, "order.created")

    return OrderResponse(
        order_id=data_for_event['order_id'],
        data_received=order_data
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")