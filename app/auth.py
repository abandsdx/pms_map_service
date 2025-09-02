import os
import logging
from pathlib import Path
from typing import Set

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define the path for the API keys file, relative to the app's root
KEYS_FILE_PATH = Path("api_keys.txt")

class KeyManager:
    def __init__(self, keys_file: Path):
        self.keys_file = keys_file
        self.master_key: str = os.getenv("MASTER_KEY", "")
        self.user_keys: Set[str] = set()

        if not self.master_key:
            # The entrypoint script should prevent this from being empty,
            # but we log a warning just in case.
            logger.warning("MASTER_KEY environment variable is empty. Admin functions will be disabled.")

        self._ensure_keys_file_exists()
        self.reload_keys()

    def _ensure_keys_file_exists(self):
        """Ensures the key file exists."""
        if not self.keys_file.exists():
            logger.info(f"Key file not found at {self.keys_file}. Creating an empty file.")
            try:
                self.keys_file.touch()
            except IOError as e:
                logger.error(f"Failed to create key file at {self.keys_file}: {e}")
                raise

    def reload_keys(self) -> bool:
        """
        Reads the key file and reloads the set of user keys.
        Returns True if successful, False otherwise.
        """
        logger.info(f"Reloading user keys from {self.keys_file}...")
        try:
            with open(self.keys_file, "r") as f:
                # Read lines, strip whitespace, and filter out empty lines
                keys = {line.strip() for line in f if line.strip()}
            self.user_keys = keys
            logger.info(f"Successfully loaded {len(self.user_keys)} user keys.")
            return True
        except IOError as e:
            logger.error(f"Failed to read or process key file {self.keys_file}: {e}")
            return False

    def get_all_user_keys(self) -> list[str]:
        """Returns a list of all current user keys."""
        return sorted(list(self.user_keys))

    def is_valid_user_key(self, key: str) -> bool:
        """Checks if a given key is in the set of valid user keys."""
        return key in self.user_keys

    def is_valid_master_key(self, key: str) -> bool:
        """Checks if a given key matches the master key."""
        if not self.master_key:
            return False # No master key is set, so no key can be valid.
        return key == self.master_key

    def add_key(self, new_key: str) -> bool:
        """Adds a new key to the keys file and reloads."""
        if new_key in self.user_keys:
            logger.warning(f"Attempted to add a key that already exists: {new_key}")
            return True # Idempotent, so we can return success
        try:
            with open(self.keys_file, "a") as f:
                f.write(f"{new_key}\n")
            logger.info(f"Successfully added new key to {self.keys_file}.")
            return self.reload_keys()
        except IOError as e:
            logger.error(f"Failed to write to key file {self.keys_file}: {e}")
            return False

    def revoke_key(self, key_to_revoke: str) -> bool:
        """Removes a key from the keys file and reloads."""
        if key_to_revoke not in self.user_keys:
            logger.warning(f"Attempted to revoke a key that does not exist: {key_to_revoke}")
            return False

        # Read all keys except the one to revoke
        try:
            with open(self.keys_file, "r") as f:
                current_keys = {line.strip() for line in f if line.strip()}

            updated_keys = current_keys - {key_to_revoke}

            with open(self.keys_file, "w") as f:
                for key in sorted(list(updated_keys)):
                    f.write(f"{key}\n")

            logger.info(f"Successfully revoked key: {key_to_revoke}")
            return self.reload_keys()
        except IOError as e:
            logger.error(f"Failed to update key file {self.keys_file} during revocation: {e}")
            return False


# Create a single, global instance of the KeyManager, using a path relative to the app's CWD
# In Docker, this will be /app/api_keys.txt
key_manager = KeyManager(KEYS_FILE_PATH)
