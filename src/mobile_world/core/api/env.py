"""Environment (Docker container) management APIs for MobileWorld.

This module provides programmatic access to Docker container management
for running MobileWorld environments.
"""

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import requests
from loguru import logger

from mobile_world.runtime.utils.docker import (
    build_run_command,
    docker_exec_bash,
    docker_inspect,
    docker_ps,
    docker_rm,
    list_containers_by_image_substring,
    run_command,
)
from mobile_world.runtime.utils.models import (
    DEFAULT_IMAGE,
    DEFAULT_NAME_PREFIX,
    ContainerConfig,
    ContainerInfo,
    ImageStatus,
    LaunchResult,
    PrerequisiteCheckResult,
    PrerequisiteCheckResults,
)


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """Check if a port is available for binding.

    Args:
        port: Port number to check
        host: Host address to bind to

    Returns:
        True if port is available, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            return True
    except OSError:
        return False


def find_available_ports(
    backend_start: int = 6800,
    viewer_start: int = 7860,
    adb_start: int = 5556,
    count: int = 1,
) -> list[tuple[int, int, int]]:
    """Find available port sets for containers.

    Args:
        backend_start: Starting port for backend
        viewer_start: Starting port for web-scrcpy viewer
        adb_start: Starting port for ADB
        count: Number of port sets to find

    Returns:
        List of tuples: (backend_port, viewer_port, adb_port)
    """
    port_sets = []
    backend_current = backend_start
    viewer_current = viewer_start
    adb_current = adb_start
    max_attempts = count * 1000

    attempts = 0
    while len(port_sets) < count and attempts < max_attempts:
        if (
            is_port_available(backend_current)
            and is_port_available(viewer_current)
            and is_port_available(adb_current)
        ):
            port_sets.append((backend_current, viewer_current, adb_current))

        backend_current += 1
        viewer_current += 1
        adb_current += 1
        attempts += 1

    return port_sets


def find_next_container_index(prefix: str = DEFAULT_NAME_PREFIX, dev_mode: bool = False) -> int:
    """Find the next available container index for the given prefix.

    Args:
        prefix: The container name prefix to check
        dev_mode: Whether dev mode is enabled

    Returns:
        The next available index (0-based)
    """
    containers = docker_ps(include_all=True)
    existing_indices = []
    suffix = "_dev" if dev_mode else ""

    for container in containers:
        name = container.get("Names", "")
        if name.startswith(f"{prefix}_"):
            remainder = name[len(prefix) + 1 :]
            if suffix and remainder.endswith(suffix):
                remainder = remainder[: -len(suffix)]

            try:
                idx = int(remainder)
                existing_indices.append(idx)
            except ValueError:
                continue

    if not existing_indices:
        return 0

    return max(existing_indices) + 1


def wait_for_container_ready(
    backend_port: int,
    timeout: int = 120,
    poll_interval: float = 1.0,
) -> bool:
    """Wait for container to be ready by polling the health endpoint.

    Args:
        backend_port: The backend port where the health endpoint is exposed
        timeout: Maximum time to wait in seconds
        poll_interval: Time between health checks

    Returns:
        True if container becomes ready, False if timeout
    """
    health_url = f"http://localhost:{backend_port}/health"
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok", False):
                    return True
        except (requests.ConnectionError, requests.Timeout, requests.RequestException):
            pass

        time.sleep(poll_interval)

    return False


def build_container_config(
    name_prefix: str = DEFAULT_NAME_PREFIX,
    image: str = DEFAULT_IMAGE,
    backend_port: int = 6800,
    viewer_port: int = 7860,
    adb_port: int = 5556,
    dev_mode: bool = False,
    enable_viewer: bool = False,
    env_file_path: Path | None = None,
    dev_src_path: Path | None = None,
    index: int | None = None,
) -> ContainerConfig:
    """Build a container configuration.

    Args:
        name_prefix: Prefix for container name
        image: Docker image to use
        backend_port: Backend port
        viewer_port: Web-scrcpy viewer port
        adb_port: ADB port
        dev_mode: Enable dev mode
        enable_viewer: Enable web-scrcpy viewer
        env_file_path: Path to .env file
        dev_src_path: Path to src directory for dev mode
        index: Container index (auto-determined if None)

    Returns:
        ContainerConfig object
    """
    if index is None:
        index = find_next_container_index(name_prefix, dev_mode)

    container_name = f"{name_prefix}_{index}{'_dev' if dev_mode else ''}"

    return ContainerConfig(
        name=container_name,
        backend_port=backend_port,
        viewer_port=viewer_port,
        adb_port=adb_port,
        image=image,
        dev_mode=dev_mode,
        enable_viewer=enable_viewer,
        env_file_path=env_file_path,
        dev_src_path=dev_src_path,
    )


def launch_container(
    config: ContainerConfig,
    detach: bool = True,
    wait_ready: bool = True,
    ready_timeout: int = 600,
) -> LaunchResult:
    """Launch a single Docker container.

    Args:
        config: Container configuration
        detach: Run container in detached mode
        wait_ready: Wait for container to become ready
        ready_timeout: Timeout for waiting for container to be ready

    Returns:
        LaunchResult object
    """
    result = LaunchResult(
        name=config.name,
        backend_port=config.backend_port,
        viewer_port=config.viewer_port,
        adb_port=config.adb_port,
    )

    envs: dict[str, str] = {}
    if config.dev_mode:
        envs["DEV_MODE"] = "true"
        envs["ENABLE_VIEWER"] = "true"  # dev mode implies the viewer
    if config.enable_viewer:
        envs["ENABLE_VIEWER"] = "true"

    volumes: list[tuple[str, str]] = []
    if config.dev_src_path:
        volumes.append((str(config.dev_src_path), "/app/service/src"))
    if config.env_file_path:
        volumes.append((str(config.env_file_path.resolve()), "/app/service/.env"))

    cmd = build_run_command(
        name=config.name,
        image=config.image,
        port_mappings=[
            (config.backend_port, 6800),
            (config.viewer_port, 7860),
            (config.adb_port, 5556),  # ADB port
        ],
        env_vars=envs,
        volumes=volumes,
        detach=detach,
        privileged=True,
        remove=True,
    )

    try:
        run_result = run_command(cmd)
        if run_result.returncode == 0:
            result.success = True
            logger.info(f"Container '{config.name}' launched successfully")

            if wait_ready:
                if wait_for_container_ready(config.backend_port, timeout=ready_timeout):
                    result.ready = True
                    logger.info(f"Container '{config.name}' is ready")
                else:
                    logger.warning(f"Container '{config.name}' did not become ready in time")
        else:
            result.error_message = run_result.stderr
            logger.error(f"Failed to launch container '{config.name}'")
    except Exception as e:
        result.error_message = str(e)
        logger.exception(f"Error launching container '{config.name}'")

    return result


def launch_containers(
    count: int = 1,
    name_prefix: str = DEFAULT_NAME_PREFIX,
    image: str = DEFAULT_IMAGE,
    backend_start_port: int = 6800,
    viewer_start_port: int = 7860,
    adb_start_port: int = 5556,
    dev_mode: bool = False,
    enable_viewer: bool = False,
    env_file_path: Path | None = None,
    dev_src_path: Path | None = None,
    launch_interval: int = 10,
    wait_ready: bool = True,
    ready_timeout: int = 600,
) -> list[LaunchResult]:
    """Launch multiple Docker containers.

    Args:
        count: Number of containers to launch
        name_prefix: Prefix for container names
        image: Docker image to use
        backend_start_port: Starting backend port
        viewer_start_port: Starting web-scrcpy viewer port
        adb_start_port: Starting ADB port
        dev_mode: Enable dev mode (single container only)
        enable_viewer: Enable web-scrcpy viewer
        env_file_path: Path to .env file
        dev_src_path: Path to src directory for dev mode
        launch_interval: Seconds between launching containers
        wait_ready: Wait for containers to become ready
        ready_timeout: Timeout for readiness check

    Returns:
        List of LaunchResult objects

    Raises:
        ValueError: If dev mode is requested with count > 1
    """
    if dev_mode and count > 1:
        raise ValueError("Dev mode only supports launching a single container")

    port_sets = find_available_ports(backend_start_port, viewer_start_port, adb_start_port, count)

    if len(port_sets) < count:
        logger.warning(f"Could only find {len(port_sets)} available port sets out of {count}")

    start_index = find_next_container_index(name_prefix, dev_mode)
    results = []

    for i, (backend, viewer, adb) in enumerate(port_sets):
        config = ContainerConfig(
            name=f"{name_prefix}_{start_index + i}{'_dev' if dev_mode else ''}",
            backend_port=backend,
            viewer_port=viewer,
            adb_port=adb,
            image=image,
            dev_mode=dev_mode,
            enable_viewer=enable_viewer,
            env_file_path=env_file_path,
            dev_src_path=dev_src_path,
        )

        result = launch_container(
            config,
            wait_ready=wait_ready,
            ready_timeout=ready_timeout,
        )
        results.append(result)

        if launch_interval > 0 and i < len(port_sets) - 1:
            time.sleep(launch_interval)

    return results


def list_containers(
    image_filter: str = DEFAULT_IMAGE,
    name_prefix: str | None = DEFAULT_NAME_PREFIX,
    include_all: bool = False,
) -> list[ContainerInfo]:
    """List MobileWorld containers.

    Args:
        image_filter: Filter by image name
        name_prefix: Filter by name prefix
        include_all: Include stopped containers

    Returns:
        List of ContainerInfo objects
    """
    containers = list_containers_by_image_substring(image_filter, include_all=include_all)

    result = []
    for container in containers:
        name = container.get("Names", "")

        if name_prefix and not name.startswith(name_prefix):
            continue

        ports_info = container.get("Ports", "")
        backend_port = None
        viewer_port = None
        adb_port = None

        if ports_info:
            for port_mapping in ports_info.split(", "):
                if "->" in port_mapping:
                    host_part, container_port = port_mapping.split("->")
                    container_port_num = container_port.split("/")[0]
                    try:
                        host_port = int(host_part.split(":")[-1])
                        if container_port_num == "6800":
                            backend_port = host_port
                        elif container_port_num == "7860":
                            viewer_port = host_port
                        elif container_port_num == "5556":
                            adb_port = host_port
                    except ValueError:
                        pass

        result.append(
            ContainerInfo(
                name=name,
                status=container.get("Status"),
                running="Up" in container.get("Status", ""),
                backend_port=backend_port,
                viewer_port=viewer_port,
                adb_port=adb_port,
            )
        )

    return result


def get_container_info(container_name: str) -> ContainerInfo | None:
    """Get detailed information about a container.

    Args:
        container_name: Name of the container

    Returns:
        ContainerInfo object or None if not found
    """
    container_data = docker_inspect(container_name)
    if not container_data:
        return None

    name = container_data.get("Name", "").lstrip("/")
    state = container_data.get("State", {})
    network = container_data.get("NetworkSettings", {})

    backend_port = None
    viewer_port = None
    adb_port = None

    ports = network.get("Ports", {})
    for container_port, host_bindings in ports.items():
        if host_bindings:
            container_port_num = container_port.split("/")[0]
            try:
                host_port = int(host_bindings[0].get("HostPort", 0))
                if container_port_num == "6800":
                    backend_port = host_port
                elif container_port_num == "7860":
                    viewer_port = host_port
                elif container_port_num == "5556":
                    adb_port = host_port
            except (ValueError, IndexError):
                pass

    return ContainerInfo(
        name=name,
        status=state.get("Status"),
        running=state.get("Running", False),
        started_at=state.get("StartedAt"),
        image=container_data.get("Config", {}).get("Image"),
        backend_port=backend_port,
        viewer_port=viewer_port,
        adb_port=adb_port,
    )


def remove_container(container_name: str, force: bool = True) -> bool:
    """Remove a Docker container.

    Args:
        container_name: Name of the container to remove
        force: Force removal

    Returns:
        True if successful, False otherwise
    """
    try:
        docker_rm(container_name, force=force)
        return True
    except SystemExit:
        return False


def remove_containers(
    container_names: list[str] | None = None,
    image_filter: str = DEFAULT_IMAGE,
    name_prefix: str = DEFAULT_NAME_PREFIX,
    force: bool = True,
) -> tuple[list[str], list[str]]:
    """Remove multiple Docker containers.

    Args:
        container_names: Specific container names to remove (if None, removes all matching)
        image_filter: Filter by image name
        name_prefix: Filter by name prefix
        force: Force removal

    Returns:
        Tuple of (destroyed, failed) container names
    """
    if container_names is None:
        containers = list_containers_by_image_substring(image_filter, include_all=True)
        container_names = [
            c.get("Names", "")
            for c in containers
            if not name_prefix or c.get("Names", "").startswith(name_prefix)
        ]

    destroyed = []
    failed = []

    for name in container_names:
        if remove_container(name, force=force):
            destroyed.append(name)
        else:
            failed.append(name)

    return destroyed, failed


def kill_server_in_container(container_name: str) -> bool:
    """Kill the MobileWorld server in a container.

    Args:
        container_name: Name of the container

    Returns:
        True if successful, False otherwise
    """
    try:
        # Kill existing server
        docker_exec_bash(
            container_name,
            "pkill -f 'mobile-world server' || true",
            allowed_exit_codes={143},
        )
        time.sleep(2)
    except SystemExit:
        logger.warning("Could not find existing server process (may not be running)")
        return False
    return True


def restart_server_in_container(
    container_name: str,
    detach: bool = True,
    enable_mcp: bool = True,
) -> bool:
    """Restart the MobileWorld server in a container.

    Args:
        container_name: Name of the container
        detach: Run in detached mode
        enable_mcp: Enable MCP server

    Returns:
        True if successful, False otherwise
    """

    # Start new server
    try:
        mcp_flag = "--enable-mcp" if enable_mcp else ""
        docker_exec_bash(
            container_name,
            f"cd /app/service && uv run mobile-world server --port 6800 {mcp_flag}",
            detach=detach,
        )
        return True
    except SystemExit:
        logger.error(f"Failed to start server in container '{container_name}'")
        return False


def resolve_container_name(name: str, prefix: str = DEFAULT_NAME_PREFIX) -> str:
    """Resolve container name, allowing shorthand index notation.

    If name is a number, expands to {prefix}_{name}.
    Otherwise returns name as-is.

    Args:
        name: Container name or index
        prefix: Name prefix

    Returns:
        Full container name
    """
    if name.isdigit():
        return f"{prefix}_{name}"
    return name


def check_docker_installed() -> PrerequisiteCheckResult:
    """Check if Docker is installed.

    Returns:
        PrerequisiteCheckResult with check status
    """

    docker_path = shutil.which("docker")
    if docker_path:
        return PrerequisiteCheckResult(
            name="Docker Installed",
            passed=True,
            message="Docker is installed",
            details=f"Found at: {docker_path}",
        )
    return PrerequisiteCheckResult(
        name="Docker Installed",
        passed=False,
        message="Docker is not installed",
        details="Install Docker: https://docs.docker.com/get-docker/",
    )


def check_docker_permission() -> PrerequisiteCheckResult:
    """Check if current user has permission to use Docker.

    Returns:
        PrerequisiteCheckResult with check status
    """

    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return PrerequisiteCheckResult(
                name="Docker Permission",
                passed=True,
                message="Docker is accessible",
            )
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return PrerequisiteCheckResult(
                name="Docker Permission",
                passed=False,
                message="Cannot access Docker daemon",
                details=f"Error: {error_msg}\nTry: sudo usermod -aG docker $USER && newgrp docker",
            )
    except Exception as e:
        return PrerequisiteCheckResult(
            name="Docker Permission",
            passed=False,
            message="Failed to check Docker permission",
            details=str(e),
        )


def check_docker_running() -> PrerequisiteCheckResult:
    """Check if Docker daemon is running.

    Returns:
        PrerequisiteCheckResult with check status
    """
    try:
        result = subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return PrerequisiteCheckResult(
                name="Docker Running",
                passed=True,
                message="Docker daemon is running",
            )
        else:
            return PrerequisiteCheckResult(
                name="Docker Running",
                passed=False,
                message="Docker daemon is not running",
                details="Start Docker: sudo systemctl start docker",
            )
    except Exception as e:
        return PrerequisiteCheckResult(
            name="Docker Running",
            passed=False,
            message="Failed to check Docker status",
            details=str(e),
        )


def check_kvm_available() -> PrerequisiteCheckResult:
    """Check if KVM is available for hardware virtualization.

    Returns:
        PrerequisiteCheckResult with check status
    """

    kvm_device = Path("/dev/kvm")

    if not kvm_device.exists():
        return PrerequisiteCheckResult(
            name="KVM Available",
            passed=False,
            message="/dev/kvm device not found",
            details=(
                "KVM is required for Android emulator.\n"
                "Enable virtualization in BIOS and load KVM module:\n"
                "  sudo modprobe kvm\n"
                "  sudo modprobe kvm_intel  # or kvm_amd"
            ),
        )

    # Check if readable/writable

    if os.access(kvm_device, os.R_OK | os.W_OK):
        return PrerequisiteCheckResult(
            name="KVM Available",
            passed=True,
            message="KVM is available and accessible",
            details=str(kvm_device),
        )
    else:
        return PrerequisiteCheckResult(
            name="KVM Available",
            passed=False,
            message="/dev/kvm exists but is not accessible",
            details=("Add current user to kvm group:\n  sudo usermod -aG kvm $USER\n  newgrp kvm"),
        )


def check_prerequisites() -> PrerequisiteCheckResults:
    """Run all prerequisite checks for MobileWorld environment.

    Returns:
        PrerequisiteCheckResults with all check results
    """
    checks = [
        check_docker_installed(),
        check_docker_running(),
        check_docker_permission(),
        check_kvm_available(),
    ]
    return PrerequisiteCheckResults(checks=checks)


def check_image_status(image: str = DEFAULT_IMAGE) -> ImageStatus:
    """Check if a Docker image exists locally and if it's up-to-date.

    Args:
        image: Docker image name (with tag)

    Returns:
        ImageStatus with details about the image
    """
    status = ImageStatus(image=image, exists_locally=False)

    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{index .RepoDigests 0}}"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            status.exists_locally = True
            output = result.stdout.strip()
            if "@sha256:" in output:
                status.local_digest = output.split("@sha256:")[-1]
    except Exception as e:
        status.error = f"Failed to check local image: {e}"
        return status

    try:
        result = subprocess.run(
            ["docker", "manifest", "inspect", image],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            try:
                manifest = json.loads(result.stdout)
                if "config" in manifest and "digest" in manifest["config"]:
                    remote_digest = manifest["config"]["digest"]
                    if remote_digest.startswith("sha256:"):
                        status.remote_digest = remote_digest[7:]
                elif "Descriptor" in manifest and "digest" in manifest["Descriptor"]:
                    remote_digest = manifest["Descriptor"]["digest"]
                    if remote_digest.startswith("sha256:"):
                        status.remote_digest = remote_digest[7:]
            except json.JSONDecodeError:
                pass
    except Exception:
        pass

    if not status.exists_locally:
        status.needs_update = True
    elif status.local_digest and status.remote_digest:
        status.needs_update = status.local_digest != status.remote_digest

    return status


def pull_image(image: str = DEFAULT_IMAGE) -> tuple[bool, str]:
    """Pull a Docker image.

    Args:
        image: Docker image name to pull

    Returns:
        Tuple of (success, message)
    """
    try:
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=False,  # Show output to user
            text=True,
        )
        if result.returncode == 0:
            return True, f"Successfully pulled {image}"
        else:
            return False, f"Failed to pull {image}"
    except Exception as e:
        return False, f"Error pulling image: {e}"
