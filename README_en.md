# Nuwa Map and Log Service

## Overview

This application serves as a bridge and utility tool for interacting with Nuwa Robotics services. It performs two primary functions:

1.  **Map Data Downloader**: It fetches map data and images from the Nuwa Robotics Mission (RMS) API, processes them, and serves them through a local API.
2.  **Real-time Log Viewer**: It connects to an MQTT broker to receive and send robot-related events, displaying them in real-time on a web interface.

The application is built with FastAPI, features a dynamic API key management system, and is designed to be run with Docker.

## Features

-   **Dynamic API Key Management**: Securely manage user access via a master key-protected admin interface. Generate, list, and revoke user keys without restarting the service.
-   **Automatic Master Key Generation**: On first launch, a secure master key is automatically generated if one isn't provided, simplifying initial setup.
-   **Dynamic Map Fetching**: Trigger a background task to download and parse the latest map data from the Nuwa RMS API.
-   **Data Persistence**: Map images, processed JSON data, and user API keys are stored on local volumes to prevent data loss.
-   **Segregated Outputs**: Handles multiple Nuwa RMS tokens by storing map data in separate directories based on a hash of the token.
-   **Real-time Event/Log Monitoring**: A WebSocket-based web UI for viewing live logs from an MQTT message broker, protected by user API keys.
-   **Containerized**: Easy to deploy and run using Docker and Docker Compose.

## Key Management

This service uses a two-tier authentication system:
-   **Master Key**: A high-privilege key used exclusively to access the admin interface at `/admin` for managing user keys. It is configured via the `MASTER_KEY` environment variable.
-   **User API Keys**: Standard keys used to access the regular features of the service, such as the log viewer WebSocket and the MQTT configuration API. These keys are managed by the administrator via the `/admin` page.

## Getting Started

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **First-time Launch & Master Key Setup:**
    Run Docker Compose to build and start the service.
    ```bash
    docker-compose up
    ```
    On the very first run, the service will detect that no `MASTER_KEY` is set, generate a new one, and print it to your console in a prominent block.

    **Look for this message in the logs:**
    ```
    #####################################################################
    #  WARNING: MASTER_KEY environment variable not set.                #
    #  Your Master Key is:                                              #
    #      some_long_randomly_generated_hex_string                        #
    #  Please add this to your docker-compose.yml file...               #
    #####################################################################
    ```

3.  **Configure the Master Key:**
    -   Copy the generated master key from the log.
    -   Stop the service (`Ctrl+C`).
    -   Open `docker-compose.yml` and set the `MASTER_KEY` environment variable with the key you copied.
        ```yaml
        services:
          fastapi-server:
            environment:
              - MASTER_KEY=your_super_secret_master_key # Paste your key here
        ```
    -   Save the file.

4.  **Run in Detached Mode:**
    Now that the key is configured, you can run the service in the background.
    ```bash
    docker-compose up -d
    ```

## Usage

### 1. Generate a User API Key

-   Navigate to `http://localhost:8000/admin`.
-   Enter the **Master Key** you configured in `docker-compose.yml`.
-   Click "Generate New Key" to create a user-level API key. Copy this key for the next steps.

### 2. Use the Service

-   **Real-time Log Viewer**: Navigate to `http://localhost:8000/`. You will be prompted to enter a **User API Key**.
-   **MQTT & Event APIs**: When calling endpoints like `/api/config-mqtt` or `/api/status`, include the **User API Key** in the Authorization header:
    ```bash
    curl -X POST http://localhost:8000/api/config-mqtt \
         -H "Authorization: Bearer YOUR_USER_API_KEY" \
         -d '{...}'
    ```
-   **Map Download APIs**: These endpoints use the **Nuwa RMS Token**, not the service's User API Key.
    ```bash
    curl -X POST http://localhost:8000/trigger-refresh \
         -H "Authorization: Bearer YOUR_NUWA_API_TOKEN"
    ```

## API Endpoints

-   `GET /`: Main log viewer UI.
-   `GET /admin`: Admin page for key management.
-   `POST /api/admin/generate-key`: (Admin) Generate a new user key.
-   `POST /api/admin/revoke-key`: (Admin) Revoke a user key.
-   `GET /api/admin/keys`: (Admin) List all user keys.
-   `POST /api/config-mqtt`: (User) Configure MQTT connection.
-   `POST /api/{event_type}`: (User) Post an event.
-   `WS /ws`: (User) WebSocket for log streaming.
-   `POST /trigger-refresh`: (Nuwa Token) Trigger map download.
-   `GET /field-map`: (Nuwa Token) Get map data.
-   `GET /health`: Health check.

## Project Structure

```
.
├── app/
│   ├── auth.py             # Authentication & key management logic
│   ├── main.py             # FastAPI application, API endpoints
│   ├── map_downloader.py   # Logic for fetching map data
│   └── templates/
│       └── admin.html      # HTML/JS for the admin page
├── api_keys.txt            # Stores user API keys
├── docker-compose.yml      # Docker Compose configuration
├── Dockerfile              # Instructions for building the image
├── entrypoint.sh           # Startup script for key generation
└── requirements.txt        # Python dependencies
```
