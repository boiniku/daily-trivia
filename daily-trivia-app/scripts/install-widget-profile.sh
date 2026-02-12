#!/bin/bash
PROFILES_DIR="$HOME/Library/MobileDevice/Provisioning Profiles"
mkdir -p "$PROFILES_DIR"

# UUID previously extracted from widget.mobileprovision
UUID="16b88775-5f67-4e25-87c9-b282302f37f1"
SOURCE_FILE="./credentials/ios/widget.mobileprovision"
DEST_FILE="$PROFILES_DIR/$UUID.mobileprovision"

if [ -f "$SOURCE_FILE" ]; then
  echo "Installing widget provisioning profile to $DEST_FILE"
  cp "$SOURCE_FILE" "$DEST_FILE"
else
  echo "Warning: Widget provisioning profile not found at $SOURCE_FILE"
fi
