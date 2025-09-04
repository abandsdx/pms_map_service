#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# Check if MASTER_KEY is set and not an empty string
if [ -z "$MASTER_KEY" ]; then
  # If not set, generate a new one using openssl
  MASTER_KEY=$(openssl rand -hex 16)
  export MASTER_KEY

  # Print a prominent warning and the new key to the console
  echo "#####################################################################"
  echo "#                                                                   #"
  echo "#  WARNING: MASTER_KEY environment variable not set.                #"
  echo "#  A new random Master Key has been generated for you.              #"
  echo "#  Please save this key and set it in your docker-compose.yml       #"
  echo "#  to ensure it persists across restarts.                           #"
  echo "#                                                                   #"
  echo "#  Your Master Key is:                                              #"
  echo "#                                                                   #"
  echo "#      $MASTER_KEY"
  echo "#                                                                   #"
  echo "#  Please add this to your docker-compose.yml file like this:       #"
  echo "#                                                                   #"
  echo "#  services:                                                         #"
  echo "#    fastapi-server:                                                 #"
  echo "#      environment:                                                  #"
  echo "#        - MASTER_KEY=$MASTER_KEY"
  echo "#                                                                   #"
  echo "#####################################################################"
else
  # If it is set, print a confirmation message
  echo "INFO: Using existing MASTER_KEY from environment."
fi

# Execute the main command passed to the script (e.g., uvicorn)
exec "$@"
