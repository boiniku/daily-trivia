#!/bin/bash
PROFILES_DIR="$HOME/Library/MobileDevice/Provisioning Profiles"
mkdir -p "$PROFILES_DIR"

SOURCE_FILE="./credentials/ios/widget.mobileprovision"

if [ -f "$SOURCE_FILE" ]; then
  # Extract UUID from the provisioning profile
  UUID=$(grep -aA1 "UUID" "$SOURCE_FILE" | grep -ioE "[a-f0-9-]{36}" | head -n 1)
  
  if [ -z "$UUID" ]; then
    echo "Error: Could not extract UUID from $SOURCE_FILE"
    exit 1
  fi

  DEST_FILE="$PROFILES_DIR/$UUID.mobileprovision"
  echo "Installing widget provisioning profile with UUID $UUID to $DEST_FILE"
  cp "$SOURCE_FILE" "$DEST_FILE"
else
  echo "Warning: Widget provisioning profile not found at $SOURCE_FILE"
fi
