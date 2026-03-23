#!/bin/bash
# Setup script for AndroidWorld apps.
# Run this INSIDE a running container after the emulator has booted.
#
# Usage:
#   docker exec <container_id> /app/docker/setup_android_world_apps.sh
#
# After this script completes, commit the container to save the snapshot:
#   docker commit <container_id> mobile_world:aw

set -e

echo "=== AndroidWorld App Setup ==="
echo "This script installs AndroidWorld apps and saves an emulator snapshot."
echo ""

# Wait for emulator to be ready
echo "Waiting for emulator to boot..."
timeout=300
elapsed=0
while [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]; do
    sleep 5
    elapsed=$((elapsed + 5))
    if [ $elapsed -ge $timeout ]; then
        echo "ERROR: Emulator did not boot within ${timeout}s"
        exit 1
    fi
    echo "  Still waiting... (${elapsed}s)"
done
echo "Emulator is ready."

# Load the base MobileWorld snapshot as starting point
echo "Loading init_state snapshot as base..."
adb emu avd snapshot load init_state
sleep 5

# Run AndroidWorld app installation
echo "Installing AndroidWorld apps..."
cd /app/service
python -c "
import sys
sys.path.insert(0, 'resources/android_world')

from android_world.env.setup_device import apps

print('Starting app installation...')
# This calls AndroidWorld's setup which downloads and installs APKs
try:
    apps.setup_apps()
    print('App installation complete.')
except Exception as e:
    print(f'Warning: Some apps may have failed to install: {e}')
    print('Continuing with snapshot...')
"

# Save the snapshot
echo "Saving aw_init_state snapshot..."
adb emu avd snapshot save aw_init_state
sleep 3

# Verify snapshot was saved
echo "Verifying snapshot..."
adb emu avd snapshot list | grep -q "aw_init_state" && \
    echo "SUCCESS: aw_init_state snapshot saved." || \
    echo "WARNING: Could not verify snapshot. Check manually."

echo ""
echo "=== Setup Complete ==="
echo "To finalize, commit this container:"
echo "  docker commit <container_id> mobile_world:aw"
