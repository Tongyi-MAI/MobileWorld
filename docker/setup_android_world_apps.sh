#!/bin/bash
# Setup script for AndroidWorld apps.
# Run this INSIDE a running container after the emulator has booted.
#
# Usage:
#   docker exec <container_id> /app/docker/setup_android_world_apps.sh
#
# After this script completes, commit the container to save the snapshot:
#   docker commit <container_id> mobile_world:aw-apps

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

# Ensure root for setup operations
echo "Setting adb root..."
adb root
sleep 3

# Run the comprehensive Python setup
echo "Running AndroidWorld app setup..."
cd /app/service
.venv/bin/python /app/docker/setup_aw_apps.py

# Save the snapshot
echo ""
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
echo "  docker commit <container_id> mobile_world:aw-apps"
