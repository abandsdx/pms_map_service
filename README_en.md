# Nuwa Map and Log Service

## Overview

This application serves as a bridge and utility tool for interacting with Nuwa Robotics services. It has been refactored into a multi-tenant capable service with advanced authentication and internationalization.

Its primary functions are:
1.  **Per-User MQTT Log Streaming**: Each user can configure their own MQTT broker settings. The service will establish a dedicated connection for them and stream logs in real-time to a web interface.
2.  **Map Data Downloader**: Fetches map data and images from the Nuwa Robotics Mission (RMS) API.
3.  **Key Management**: A secure, two-tier system for managing access to the service itself.

## Features

-   **Multi-Tenant MQTT**: Each user can have their own independent MQTT broker configuration, which is saved persistently.
-   **Dynamic API Key Management**: A secure admin panel, protected by a master key, allows for generating and revoking user API keys on-the-fly.
-   **Unified Login**: A single login page intelligently directs users to the admin panel or the log viewer based on the type of key they provide (master or user).
-   **Internationalization (i18n)**: Frontend is fully bilingual with support for English and Traditional Chinese (繁體中文), with English as the default.
-   **Automatic Master Key Generation**: On first launch, a secure master key is automatically generated if one isn't provided, simplifying initial setup.
-   **Data Persistence**: All configurations (user keys, MQTT settings) are stored in persistent JSON files mounted as volumes.

## Getting Started

### 1. Configure the Master Key (Recommended)

-   **Copy the example file**: `cp .env.example .env`
-   **Set your Master Key**: Open the new `.env` file and replace the placeholder with a real, secure key (e.g., generated with `openssl rand -hex 16`).
    ```
    MASTER_KEY=your_super_secret_master_key_here
    ```

### 2. Build and Run the Service
```bash
docker-compose up -d --build
```
The service will start at `http://localhost:8000`.

### Alternative: First-Time Auto-Generation
If you start the service without a `.env` file, it will generate a Master Key and print it to the console. Copy this key into a new `.env` file for future use.

## Usage Workflow

### 1. Login
-   Navigate to the main page: `http://localhost:8000/`.
-   You will be presented with a unified login page.

### 2. Admin: Create a User Key
-   On the login page, enter your **Master Key**.
-   You will be redirected to the `/admin` panel.
-   Click "Generate New Key" to create a User API Key. Copy it.
-   You can switch the admin panel language using the dropdown in the top right.

### 3. User: Configure MQTT and View Logs
-   Go back to the main login page (`/`).
-   Enter the **User API Key** you just generated.
-   You will be redirected to the `/log` page.
-   Use the navigation bar to go to `/settings`. Here you can enter the details for your personal MQTT broker. The settings will be saved for your key.
-   Return to the `/log` page to see the real-time logs from your configured broker.
-   The language can be switched at any time using the dropdown. Your preference will be remembered for the session.

## Project Structure

```
.
├── app/
│   ├── auth.py             # Authentication & API key logic
│   ├── main.py             # FastAPI application, endpoints, WebSocket logic
│   ├── map_downloader.py   # Logic for fetching map data
│   ├── mqtt_manager.py     # Per-user MQTT connection management
│   └── templates/
│       ├── admin.html      # Admin page
│       ├── log.html        # Log viewer page
│       ├── login.html      # Unified login page
│       └── settings.html   # MQTT settings page
├── locales/
│   ├── en.json             # English UI strings
│   └── zh_TW.json          # Traditional Chinese UI strings
├── api_keys.txt            # Persisted storage for user API keys
├── mqtt_configs.json       # Persisted storage for per-user MQTT configs
├── docker-compose.yml      # Docker Compose configuration
├── Dockerfile              # Instructions for building the image
├── entrypoint.sh           # Startup script for master key generation
├── .env.example            # Example environment file
└── requirements.txt        # Python dependencies
```
