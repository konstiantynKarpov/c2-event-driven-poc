# C2 Event-Driven Proof-of-Concept 

## 1. Overview

This simplified Proof-of-Concept (PoC) demonstrates an event-driven Command & Control (C2) architecture. It uses Apache Kafka for messaging and Python (FastAPI) for microservices. Its primary focus is showcasing the core event flow: API data ingestion, Kafka event publishing, event processing, and notification consumption/display.

**Key Simplifications for this PoC:**
* No database persistence (in-memory/transient data).
* No Redis caching (Redis available in Docker Compose for future use).
* Focus on core event production, consumption, and basic processing logic.

## 2. Architecture

The system comprises microservices communicating asynchronously via Apache Kafka:

* **API Services (Event Producers):**
    * `Blue Force Tracker Service`: Ingests friendly unit positions (HTTP POST) and publishes `blue.position.updated` events.
    * `Enemy Marking Service`: Ingests enemy unit sightings (HTTP POST) and publishes `enemy.spotted` events.
    * `Order Service`: Ingests command orders (HTTP POST) and publishes `order.created` events.
* **Processing Service (Event Consumer/Producer):**
    * `Proximity Processor`: Consumes position/enemy events, detects proximity, and produces `proximity.alert` events.
* **Notification Service (Event Consumer):**
    * `Notification Service`: Consumes various events and logs them (simulating notifications).
* **Infrastructure:**
    * `Apache Zookeeper`: Manages Kafka cluster state.
    * `Apache Kafka`: Central event bus.
    * `Kafka UI (Provectus UI)`: Web interface for Kafka monitoring.
    * `Redis`: Included in Docker Compose for potential future use.

## 3. Prerequisites

* **Docker Desktop:** Latest stable version.
* A terminal or command prompt.

## 4. Getting Started

From the project root (`c2-event-driven-poc/`):

1.  **Build Docker Images:**
    ```bash
    docker-compose build
    ```
    Builds images for all custom Python services as defined in `docker-compose.yml`.

2.  **Start All Services:**
    ```bash
    docker-compose up -d
    ```
    Runs containers in detached mode. Allow time for Zookeeper/Kafka initialization.

3.  **Verify Container Status:**
    ```bash
    docker-compose ps
    ```
    Ensures all services are 'Up' or 'Running'.

4.  **Create Kafka Topics:** Essential for service communication.
    * Make executable:
        ```bash
        chmod +x ./kafka-setup/create-topics.sh
        ```
    * Run script:
        ```bash
        ./kafka-setup/create-topics.sh
        ```
    Creates `blue-force-events`, `enemy-events`, `order-events`, `proximity-alerts` and lists topics for verification.

## 5. Services & Testing

Interact with APIs using `curl`/Postman. Monitor via Kafka UI and Docker logs.

* **Kafka UI:**
    * Access: `http://localhost:8080`
    * For topic/message viewing.

* **Blue Force Tracker Service:**
    * Access: `http://localhost:8001`
    * API Endpoint: `POST /api/positions`
    * Publishes to: `blue-force-events`
    * Example Test:
        ```bash
        curl -X POST http://localhost:8001/api/positions \
          -H "Content-Type: application/json" \
          -d '{"unit_id":"B001","latitude":50.4501,"longitude":30.5234,"speed":60,"heading":90,"brigade":1}'
        ```

* **Enemy Marking Service:**
    * Access: `http://localhost:8002`
    * API Endpoint: `POST /api/enemy-units`
    * Publishes to: `enemy-events`
    * Example Test:
        ```bash
        curl -X POST http://localhost:8002/api/enemy-units \
          -H "Content-Type: application/json" \
          -d '{"unit_id":"E001","unit_type":"armor","latitude":50.4550,"longitude":30.5250,"confidence":"high","marked_by":"B001"}'
        ```

* **Order Service:**
    * Access: `http://localhost:8003`
    * API Endpoint: `POST /api/orders`
    * Publishes to: `order-events`
    * Example Test:
        ```bash
        curl -X POST http://localhost:8003/api/orders \
          -H "Content-Type: application/json" \
          -d '{"issued_by":"HQ","issued_to":"B001","type":"recon","details":{"area":"sector_gamma"}}'
        ```

* **Proximity Processor Service:**
    * Consumes from: `blue-force-events`, `enemy-events`.
    * Produces to: `proximity-alerts`.
    * Logs: `docker-compose logs -f proximity-processor`

* **Notification Service:**
    * Consumes from: `enemy-events`, `proximity-alerts`, `order-events`.
    * Logs simulated notifications.
    * Logs: `docker-compose logs -f notification-service`

## 6. Monitoring the System

* **Kafka UI (`http://localhost:8080`):** Primary tool for message/topic monitoring.
* **Docker Logs:** Essential for service debugging and observation.
    ```bash
    docker-compose logs <service_name>
    # To follow logs in real-time:
    docker-compose logs -f <service_name>
    # Examples:
    # docker-compose logs -f blue-force-tracker
    # docker-compose logs -f proximity-processor
    ```

## 7. Stopping the System

* To stop and remove all containers, networks, and non-named volumes:
    ```bash
    docker-compose down
    ```
* To just stop services:
    ```bash
    docker-compose stop
    ```

## 8. Key Event Flow Example

1.  Post position for `B001` (Blue Force Tracker).
2.  Post enemy marking for `E001` near `B001` (Enemy Marking Service).
3.  Proximity Processor consumes, calculates distance, and if close, publishes to `proximity-alerts`.
4.  Notification Service consumes `enemy-events` and `proximity-alerts`, logging them.
5.  Post order for `B001` (Order Service).
6.  Notification Service consumes `order-events`, logging the new order.

