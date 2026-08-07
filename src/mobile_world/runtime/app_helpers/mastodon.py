import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime

import imagehash
import psycopg2
import pytz
import requests
import urllib3
from loguru import logger
from PIL import Image
from psycopg2 import Error

from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import execute_adb

# All host-FS / connection constants are env-overridable so the same code drives the
# dind/emulator image (no env set -> original /app/* defaults) and a redroid host, where
# env points at a host-side sibling-container layout.
MASTODON_DOCKER_DIR = os.getenv("MASTODON_DOCKER_DIR", "/app/mastodon-docker")
COMPOSE_FILE = "docker-compose.yml"
MASTODON_DB_HOST = os.getenv("MASTODON_DB_HOST", "localhost")  # database host address
MASTODON_DB_DATABASE = os.getenv("MASTODON_DB_DATABASE", "mastodon")  # database name
MASTODON_DB_USER = os.getenv("MASTODON_DB_USER", "postgres")  # database user
MASTODON_DB_PASSWORD = os.getenv("MASTODON_DB_PASSWORD", "postgres")  # database password
MASTODON_DB_PORT = os.getenv("MASTODON_DB_PORT", "5432")  # database port
MASTODON_LOCAL_DOMAIN = os.getenv("MASTODON_LOCAL_DOMAIN", "10.0.2.2")  # local domain (Android -> instance)
MASTODON_STATUS_DIR = os.getenv("MASTODON_STATUS_DIR", "/app/mastodon-docker-bk")

# Host header stays 10.0.2.2; the URL host/port is overridable in case the host
# publishes the mastodon nginx TLS port somewhere other than 443.
MASTODON_HEALTH_URL = os.getenv("MASTODON_HEALTH_URL", "https://localhost/api/v1/instance")

PUBLIC_SYSTEM_ROOT = "/opt/mastodon/public/system"  # media directory inside the container
MEDIA_ROOT = os.getenv("MASTODON_MEDIA_ROOT", "/app/mastodon-docker/data/media")


def copytree_with_ownership(src, dst):
    """Copy a directory tree from src to dst, preserving ownership."""
    subprocess.run(["cp", "-rp", src, dst], check=True)


def get_mastodon_backend_status() -> str:
    """Get the status of the Mastodon backend."""
    if not os.path.exists(MASTODON_DOCKER_DIR):
        return "stopped"

    try:
        cmd = ["docker", "compose", "ps", "--format", "json"]
        result = subprocess.run(
            cmd,
            cwd=MASTODON_DOCKER_DIR,
            capture_output=True,
            text=True,
            check=True,
        )

        if not result.stdout.strip():
            return "stopped"

        services = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    service = json.loads(line)
                    services.append(service)
                except json.JSONDecodeError:
                    continue

        if not services:
            return "stopped"

        # Check if all services are running
        running_services = 0
        total_services = len(services)

        if total_services == 0:
            return "stopped"

        for service in services:
            state = service.get("State", "").lower()
            if state == "running":
                running_services += 1

        if running_services == total_services and total_services > 0:
            return "running"
        elif running_services > 0:
            return "partial"
        else:
            return "stopped"

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get Mastodon backend status: {e}")
        return "error"
    except Exception as e:
        logger.error(f"Unexpected error getting Mastodon backend status: {e}")
        return "error"


def get_mastodon_services_info() -> str | None:
    """Get detailed information about Mastodon services."""
    try:
        cmd = ["docker", "compose", "ps"]
        result = subprocess.run(
            cmd,
            cwd=MASTODON_DOCKER_DIR,  # Change to mastodon docker directory
            capture_output=True,  # Capture the output
            text=True,  # Decode bytes to string
            check=True,  # Raise exception on non-zero exit code
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get Mastodon services info: {e}")
        return f"Error: {e.stderr}"
    except Exception as e:
        logger.error(f"Unexpected error getting Mastodon services info: {e}")
        return f"Error: {str(e)}"


def start_mastodon_backend(mastodon_backend_status_dir=MASTODON_STATUS_DIR) -> bool:
    """Start the Mastodon backend."""
    status = get_mastodon_backend_status()
    if status in ["running", "partial"]:
        logger.info("Mastodon backend is already running, stop and reset it to default")
        stop_mastodon_backend()
    shutil.rmtree(MASTODON_DOCKER_DIR, ignore_errors=True)

    try:
        # copy the backend status directory to the docker directory
        if mastodon_backend_status_dir:
            copytree_with_ownership(mastodon_backend_status_dir, MASTODON_DOCKER_DIR)

        # start services
        cmd = ["docker", "compose", "up", "-d"]
        subprocess.run(cmd, cwd=MASTODON_DOCKER_DIR, capture_output=True, text=True, check=True)

        # mastodon backend ready to use check
        while not _is_mastodon_ready():
            time.sleep(3)

        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to start Mastodon backend: {e}")
        logger.error(f"Error output: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error starting Mastodon backend: {e}")
        return False


def stop_mastodon_backend() -> bool:
    """Stop the Mastodon backend."""
    try:
        status = get_mastodon_backend_status()
        if status == "stopped":
            return True
        # Change to mastodon docker directory and stop services
        cmd = ["docker", "compose", "down"]
        result = subprocess.run(
            cmd, cwd=MASTODON_DOCKER_DIR, capture_output=True, text=True, check=True
        )
        logger.info("Mastodon backend stopped successfully")
        logger.debug(f"Docker compose output: {result.stdout}\n{result.stderr}")

        shutil.rmtree(MASTODON_DOCKER_DIR)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to stop Mastodon backend: {e}")
        logger.error(f"Error output: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error stopping Mastodon backend: {e}")
        return False


def restart_mastodon_backend() -> bool:
    """Restart the Mastodon backend."""
    logger.info("Restarting Mastodon backend...")

    # Stop the backend first
    if not stop_mastodon_backend():
        logger.error("Failed to stop Mastodon backend during restart")
        return False

    # Wait a moment for services to fully stop
    time.sleep(2)

    # Start the backend again
    if not start_mastodon_backend():
        logger.error("Failed to start Mastodon backend during restart")
        return False

    logger.info("Mastodon backend restarted successfully")
    return True


def _is_mastodon_ready() -> bool:
    """Check whether the Mastodon ready"""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        resp = requests.get(
            MASTODON_HEALTH_URL,
            timeout=3,
            headers={"Host": MASTODON_LOCAL_DOMAIN},
            verify=False,
        )
        if 200 <= resp.status_code < 300:
            return True
        logger.info("Mastodon web not ready")
        return False
    except Exception as e:
        logger.info(f"Mastodon HTTP health check exception when calling {MASTODON_HEALTH_URL}: {e}")
        return False


def is_mastodon_healthy() -> bool:
    """Check if the Mastodon backend is healthy."""
    status = get_mastodon_backend_status()
    return status == "running"


def get_mastodon_table_schema(table_name: str) -> list[tuple]:
    """Get the schema of a specific table in the Mastodon database."""
    connection, cursor = connect_to_postgres()
    if connection is None or cursor is None:
        return []

    try:
        query = """
            SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position;
        """
        cursor.execute(query, (table_name,))
        schema = cursor.fetchall()
        return schema

    except Exception as e:
        logger.error(f"Error fetching schema for table {table_name}: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def connect_to_postgres() -> tuple[
    psycopg2.extensions.connection | None, psycopg2.extensions.cursor | None
]:
    """Connect to the PostgreSQL database."""
    try:
        connection = psycopg2.connect(
            host=MASTODON_DB_HOST,
            database=MASTODON_DB_DATABASE,
            user=MASTODON_DB_USER,
            password=MASTODON_DB_PASSWORD,
            port=MASTODON_DB_PORT,
        )
        cursor = connection.cursor()
        logger.info("Connected to PostgreSQL database successfully!")
        return connection, cursor
    except Error as e:
        logger.error(f"Error connecting to PostgreSQL database: {e}")
        return None, None


# ================================================
# database size query related
# ================================================


def _format_size_pretty(size_bytes: int) -> str:
    """
    Format size in bytes to human-readable format with one decimal place.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string with one decimal place (e.g., "1.5 GB", "1024.0 kB")
    """
    units = ["B", "kB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    size = float(size_bytes)

    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1

    return f"{size:.1f} {units[unit_index]}"


def get_database_size(database_name: str | None = None, human_readable: bool = True) -> dict | None:
    """
    Get the size of a PostgreSQL database.

    Args:
        database_name: Name of the database to query. If None, uses MASTODON_DB_DATABASE.
        human_readable: If True, returns human-readable format (e.g., "1.5 GB").
                       If False, returns size in bytes.

    Returns:
        Dictionary with database size information, or None if error.
        Example:
        {
            "database": "mastodon",
            "size_bytes": 1610612736,
            "size_pretty": "1.5 GB"
        }
    """
    connection, cursor = connect_to_postgres()
    if connection is None or cursor is None:
        return None

    try:
        db_name = database_name or MASTODON_DB_DATABASE

        # Query database size (only query once to avoid duplicate calls)
        query = "SELECT pg_database_size(%s) as size_bytes"
        cursor.execute(query, (db_name,))

        result = cursor.fetchone()

        if result:
            size_bytes = result[0]
            if human_readable:
                size_pretty = _format_size_pretty(size_bytes)
                return {"database": db_name, "size_bytes": size_bytes, "size_pretty": size_pretty}
            else:
                return {"database": db_name, "size_bytes": size_bytes}
        return None

    except Exception as e:
        logger.error(f"Error querying database size: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def get_table_sizes(schema_name: str = "public", human_readable: bool = True) -> list[dict] | None:
    """
    Get the size of all tables in a schema.

    Args:
        schema_name: Name of the schema to query. Default is "public".
        human_readable: If True, returns human-readable format. If False, returns size in bytes.

    Returns:
        List of dictionaries with table size information, or None if error.
        Example:
        [
            {
                "schema": "public",
                "table": "statuses",
                "size_bytes": 1073741824,
                "size_pretty": "1 GB",
                "rows": 1000000
            },
            ...
        ]
    """
    connection, cursor = connect_to_postgres()
    if connection is None or cursor is None:
        return None

    try:
        query = """
            SELECT
                schemaname as schema,
                tablename as table,
                pg_total_relation_size(schemaname||'.'||tablename) as size_bytes,
                (SELECT n_live_tup FROM pg_stat_user_tables WHERE schemaname = t.schemaname AND relname = t.tablename) as rows
            FROM pg_tables t
            WHERE schemaname = %s
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
        """

        cursor.execute(query, (schema_name,))
        results = cursor.fetchall()

        tables = []
        for row in results:
            schema, table, size_bytes, rows = row
            table_info = {
                "schema": schema,
                "table": table,
                "size_bytes": size_bytes,
                "rows": rows or 0,
            }
            if human_readable:
                table_info["size_pretty"] = _format_size_pretty(size_bytes)
            tables.append(table_info)

        return tables

    except Exception as e:
        logger.error(f"Error querying table sizes: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ================================================
# table query related
# recommended schema reference: https://github.com/mastodon/mastodon/blob/v4.3.7/db/schema.rb
# ================================================


def get_user_info(username: str) -> dict | None:
    """
    Get comprehensive user information for a specific user by username.

    TABLE: users, accounts
    Args:
        username: The username to retrieve user info for

    Returns:
        User dictionary with all user fields or None if error/not found
        e.g.:
        {
            "user_id": 1,
            "email": "test@example.com",
            "created_at": "2025-10-08 11:59:11.660453",
            "updated_at": "2025-10-21 07:00:25.487622",
            "encrypted_password": "...",
            "reset_password_token": null,
            "reset_password_sent_at": null,
            "sign_in_count": 10,
            "current_sign_in_at": "2025-10-21 07:00:25.487622",
            "last_sign_in_at": "2025-10-20 15:30:00.000000",
            "confirmation_token": null,
            "confirmed_at": "2025-10-08 12:00:00.000000",
            "confirmation_sent_at": "2025-10-08 11:59:11.660453",
            "unconfirmed_email": null,
            "locale": "en",     # language
            "encrypted_otp_secret": null,
            "encrypted_otp_secret_iv": null,
            "encrypted_otp_secret_salt": null,
            "consumed_timestep": null,
            "otp_required_for_login": false,
            "last_emailed_at": null,
            "otp_backup_codes": null,
            "account_id": 115338428522805842,
            "disabled": false,
            "invite_id": null,
            "chosen_languages": ["en"],
            "created_by_application_id": null,
            "approved": true,
            "sign_in_token": null,
            "sign_in_token_sent_at": null,
            "webauthn_id": null,
            "sign_up_ip": null,
            "skip_sign_in_token": false,
            "role_id": null,
            "settings": "{}",
            "time_zone": "UTC",
            "otp_secret": null
        }
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            u.id,
            u.email,
            u.created_at,
            u.updated_at,
            u.encrypted_password,
            u.reset_password_token,
            u.reset_password_sent_at,
            u.sign_in_count,
            u.current_sign_in_at,
            u.last_sign_in_at,
            u.confirmation_token,
            u.confirmed_at,
            u.confirmation_sent_at,
            u.unconfirmed_email,
            u.locale,
            u.encrypted_otp_secret,
            u.encrypted_otp_secret_iv,
            u.encrypted_otp_secret_salt,
            u.consumed_timestep,
            u.otp_required_for_login,
            u.last_emailed_at,
            u.otp_backup_codes,
            u.account_id,
            u.disabled,
            u.invite_id,
            u.chosen_languages,
            u.created_by_application_id,
            u.approved,
            u.sign_in_token,
            u.sign_in_token_sent_at,
            u.webauthn_id,
            u.sign_up_ip,
            u.skip_sign_in_token,
            u.role_id,
            u.settings,
            u.time_zone,
            u.otp_secret
        FROM users u
        JOIN accounts a ON u.account_id = a.id
        WHERE a.username = %s
        AND a.domain IS NULL
        LIMIT 1
    """

    try:
        cur.execute(query, (username,))
        row = cur.fetchone()

        if not row:
            logger.warning(f"User with username {username} not found")
            return None

        # Convert tuple to dictionary
        (
            id,
            email,
            created_at,
            updated_at,
            encrypted_password,
            reset_password_token,
            reset_password_sent_at,
            sign_in_count,
            current_sign_in_at,
            last_sign_in_at,
            confirmation_token,
            confirmed_at,
            confirmation_sent_at,
            unconfirmed_email,
            locale,
            encrypted_otp_secret,
            encrypted_otp_secret_iv,
            encrypted_otp_secret_salt,
            consumed_timestep,
            otp_required_for_login,
            last_emailed_at,
            otp_backup_codes,
            account_id,
            disabled,
            invite_id,
            chosen_languages,
            created_by_application_id,
            approved,
            sign_in_token,
            sign_in_token_sent_at,
            webauthn_id,
            sign_up_ip,
            skip_sign_in_token,
            role_id,
            settings,
            time_zone,
            otp_secret,
        ) = row

        user = {
            "user_id": id,
            "email": email,
            "created_at": created_at,
            "updated_at": updated_at,
            "encrypted_password": encrypted_password,
            "reset_password_token": reset_password_token,
            "reset_password_sent_at": reset_password_sent_at,
            "sign_in_count": sign_in_count,
            "current_sign_in_at": current_sign_in_at,
            "last_sign_in_at": last_sign_in_at,
            "confirmation_token": confirmation_token,
            "confirmed_at": confirmed_at,
            "confirmation_sent_at": confirmation_sent_at,
            "unconfirmed_email": unconfirmed_email,
            "locale": locale,
            "encrypted_otp_secret": encrypted_otp_secret,
            "encrypted_otp_secret_iv": encrypted_otp_secret_iv,
            "encrypted_otp_secret_salt": encrypted_otp_secret_salt,
            "consumed_timestep": consumed_timestep,
            "otp_required_for_login": otp_required_for_login,
            "last_emailed_at": last_emailed_at,
            "otp_backup_codes": otp_backup_codes,
            "account_id": account_id,
            "disabled": disabled,
            "invite_id": invite_id,
            "chosen_languages": chosen_languages or [],
            "created_by_application_id": created_by_application_id,
            "approved": approved,
            "sign_in_token": sign_in_token,
            "sign_in_token_sent_at": sign_in_token_sent_at,
            "webauthn_id": webauthn_id,
            "sign_up_ip": str(sign_up_ip) if sign_up_ip else None,
            "skip_sign_in_token": skip_sign_in_token,
            "role_id": role_id,
            "settings": settings,
            "time_zone": time_zone,
            "otp_secret": otp_secret,
        }

        logger.info(f"Found user info for username {username}")
        return user

    except Exception as e:
        logger.error(f"Error fetching user info for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_user_account_info(username: str) -> dict | None:
    """
    Get comprehensive account information for a specific user by username.

    TABLE: accounts
    Args:
        username: The username to retrieve account info for

    Returns:
        Account dictionary with all account fields or None if error/not found
        e.g.:
        {
            "account_id": 115338428522805842,
            "username": "test",
            "domain": null,
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMI...-----END RSA PRIVATE KEY-----\n",
            "public_key": "-----BEGIN PUBLIC KEY-----\nMI...\n-----END PUBLIC KEY-----\n",
            "created_at": "2025-10-08 11:59:11.660453",
            "updated_at": "2025-10-21 07:00:25.487622",
            "note": "This is MobileWorld test account!",
            "display_name": "TEST",
            "uri": "",
            "url": null,
            "avatar_file_name": "90706f1fe83887cd.jpg",
            "avatar_content_type": "image/jpeg",
            "avatar_file_size": 11183,
            "avatar_updated_at": "2025-10-16 12:32:03.828884",
            "header_file_name": "055f1a0a8e88da1c.jpeg",
            "header_content_type": "image/jpeg",
            "header_file_size": 4829,
            "header_updated_at": "2025-10-21 07:00:25.466439",
            "avatar_remote_url": null,
            "locked": false,
            "header_remote_url": "",
            "last_webfingered_at": null,
            "inbox_url": "",
            "outbox_url": "",
            "shared_inbox_url": "",
            "followers_url": "",
            "protocol": 0,
            "memorial": false,
            "moved_to_account_id": null,
            "featured_collection_url": null,
            "fields": [
                {
                    "name": "student",
                    "value": "Open University"
                }
            ],
            "actor_type": "Person",
            "discoverable": true,
            "also_known_as": [],
            "silenced_at": null,
            "suspended_at": null,
            "hide_collections": null,
            "avatar_storage_schema_version": 1,
            "header_storage_schema_version": 1,
            "sensitized_at": null,
            "suspension_origin": null,
            "trendable": null,
            "reviewed_at": null,
            "requested_review_at": null,
            "indexable": true,
            "attribution_domains": []
        }
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            a.id,
            a.username,
            a.domain,
            a.private_key,
            a.public_key,
            a.created_at,
            a.updated_at,
            a.note,
            a.display_name,
            a.uri,
            a.url,
            a.avatar_file_name,
            a.avatar_content_type,
            a.avatar_file_size,
            a.avatar_updated_at,
            a.header_file_name,
            a.header_content_type,
            a.header_file_size,
            a.header_updated_at,
            a.avatar_remote_url,
            a.locked,
            a.header_remote_url,
            a.last_webfingered_at,
            a.inbox_url,
            a.outbox_url,
            a.shared_inbox_url,
            a.followers_url,
            a.protocol,
            a.memorial,
            a.moved_to_account_id,
            a.featured_collection_url,
            a.fields,
            a.actor_type,
            a.discoverable,
            a.also_known_as,
            a.silenced_at,
            a.suspended_at,
            a.hide_collections,
            a.avatar_storage_schema_version,
            a.header_storage_schema_version,
            a.sensitized_at,
            a.suspension_origin,
            a.trendable,
            a.reviewed_at,
            a.requested_review_at,
            a.indexable,
            a.attribution_domains
        FROM accounts a
        WHERE a.username = %s
        AND a.domain IS NULL
        LIMIT 1
    """

    try:
        cur.execute(query, (username,))
        row = cur.fetchone()

        if not row:
            logger.warning(f"Account with username {username} not found")
            return None

        # Convert tuple to dictionary
        (
            id,
            username,
            domain,
            private_key,
            public_key,
            created_at,
            updated_at,
            note,
            display_name,
            uri,
            url,
            avatar_file_name,
            avatar_content_type,
            avatar_file_size,
            avatar_updated_at,
            header_file_name,
            header_content_type,
            header_file_size,
            header_updated_at,
            avatar_remote_url,
            locked,
            header_remote_url,
            last_webfingered_at,
            inbox_url,
            outbox_url,
            shared_inbox_url,
            followers_url,
            protocol,
            memorial,
            moved_to_account_id,
            featured_collection_url,
            fields,
            actor_type,
            discoverable,
            also_known_as,
            silenced_at,
            suspended_at,
            hide_collections,
            avatar_storage_schema_version,
            header_storage_schema_version,
            sensitized_at,
            suspension_origin,
            trendable,
            reviewed_at,
            requested_review_at,
            indexable,
            attribution_domains,
        ) = row

        account = {
            "account_id": id,
            "username": username,
            "domain": domain,
            "private_key": private_key,
            "public_key": public_key,
            "created_at": created_at,
            "updated_at": updated_at,
            "note": note,
            "display_name": display_name,
            "uri": uri,
            "url": url,
            "avatar_file_name": avatar_file_name,
            "avatar_content_type": avatar_content_type,
            "avatar_file_size": avatar_file_size,
            "avatar_updated_at": avatar_updated_at,
            "header_file_name": header_file_name,
            "header_content_type": header_content_type,
            "header_file_size": header_file_size,
            "header_updated_at": header_updated_at,
            "avatar_remote_url": avatar_remote_url,
            "locked": locked,
            "header_remote_url": header_remote_url,
            "last_webfingered_at": last_webfingered_at,
            "inbox_url": inbox_url,
            "outbox_url": outbox_url,
            "shared_inbox_url": shared_inbox_url,
            "followers_url": followers_url,
            "protocol": protocol,
            "memorial": memorial,
            "moved_to_account_id": moved_to_account_id,
            "featured_collection_url": featured_collection_url,
            "fields": fields or [],
            "actor_type": actor_type,
            "discoverable": discoverable,
            "also_known_as": also_known_as or [],
            "silenced_at": silenced_at,
            "suspended_at": suspended_at,
            "hide_collections": hide_collections,
            "avatar_storage_schema_version": avatar_storage_schema_version,
            "header_storage_schema_version": header_storage_schema_version,
            "sensitized_at": sensitized_at,
            "suspension_origin": suspension_origin,
            "trendable": trendable,
            "reviewed_at": reviewed_at,
            "requested_review_at": requested_review_at,
            "indexable": indexable,
            "attribution_domains": attribution_domains or [],
        }

        logger.info(f"Found account info for username {username}")
        return account

    except Exception as e:
        logger.error(f"Error fetching account info for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_latest_toots_by_username(username: str, limit: int = 1) -> list[dict] | None:
    """
    Get latest limit number of toots for a specific user.

    TABLE: statuses, accounts
    Args:
        username: The username to retrieve toots for
        limit: Number of toots to retrieve

    Returns:
        List of toot dictionaries with comprehensive status fields or None if error
        e.g.:
        [
            {
                "id": 1234567890,
                "text": "Hello, world!",
                "content": "Hello, world!",  # same as text
                "created_at": "2025-10-14 12:13:23.712869",
                "updated_at": "2025-10-14 12:13:23.712869",
                "in_reply_to_id": null,
                "reblog_of_id": null,
                "account_id": 12345,
                "visibility": 0,  # 0: public, 1: unlisted, 2: private, 3: direct
                "sensitive": false,
                "spoiler_text": "",
                "language": "en",
                "uri": "https://example.com/statuses/1234567890",
                "url": "https://example.com/@user/1234567890",
                "in_reply_to_account_id": null,
                "poll_id": null,
                "application_id": null,
                "local": true,
                "reply": false,
                "conversation_id": null,
                "deleted_at": null,
                "edited_at": null,
                "trendable": null,
                "ordered_media_attachment_ids": null
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            s.id,
            s.text,
            s.created_at,
            s.updated_at,
            s.in_reply_to_id,
            s.reblog_of_id,
            s.account_id,
            s.visibility,
            s.sensitive,
            s.spoiler_text,
            s.language,
            s.uri,
            s.url,
            s.in_reply_to_account_id,
            s.poll_id,
            s.application_id,
            s.local,
            s.reply,
            s.conversation_id,
            s.deleted_at,
            s.edited_at,
            s.trendable,
            s.ordered_media_attachment_ids
        FROM statuses s
        JOIN accounts a ON s.account_id = a.id
        WHERE a.username = %s
        ORDER BY s.created_at DESC
        LIMIT %s
    """
    try:
        cur.execute(query, (username, limit))
        rows = cur.fetchall()

        # Convert tuples to dictionaries
        toots = []
        for row in rows:
            (
                id,
                text,
                created_at,
                updated_at,
                in_reply_to_id,
                reblog_of_id,
                account_id,
                visibility,
                sensitive,
                spoiler_text,
                language,
                uri,
                url,
                in_reply_to_account_id,
                poll_id,
                application_id,
                local,
                reply,
                conversation_id,
                deleted_at,
                edited_at,
                trendable,
                ordered_media_attachment_ids,
            ) = row

            toots.append(
                {
                    "id": id,
                    "text": text,
                    "content": text,  # content is the same as text
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "in_reply_to_id": in_reply_to_id,
                    "reblog_of_id": reblog_of_id,
                    "account_id": account_id,
                    "visibility": visibility,
                    "sensitive": sensitive,
                    "spoiler_text": spoiler_text,
                    "language": language,
                    "uri": uri,
                    "url": url,
                    "in_reply_to_account_id": in_reply_to_account_id,
                    "poll_id": poll_id,
                    "application_id": application_id,
                    "local": local,
                    "reply": reply,
                    "conversation_id": conversation_id,
                    "deleted_at": deleted_at,
                    "edited_at": edited_at,
                    "trendable": trendable,
                    "ordered_media_attachment_ids": ordered_media_attachment_ids,
                }
            )

        return toots
    except Exception as e:
        logger.error(f"Error fetching latest toots: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_toot_by_status_id(status_id: int) -> dict | None:
    """
    Get a specific toot by status ID.

    TABLE: statuses
    Args:
        status_id: The ID of the status to retrieve

    Returns:
        Toot dictionary with comprehensive status fields or None if error/not found
        e.g.:
        {
            "id": 1234567890,
            "text": "Hello, world!",
            "content": "Hello, world!",  # same as text
            "created_at": "2025-10-14 12:13:23.712869",
            "updated_at": "2025-10-14 12:13:23.712869",
            "in_reply_to_id": null,
            "reblog_of_id": null,
            "account_id": 12345,
            "visibility": 0,    # 0: public, 1: quiet public, 2: followers, 3: private mentioned
            "sensitive": false,
            "spoiler_text": "",
            "language": "en",
            "uri": "https://example.com/statuses/1234567890",
            "url": "https://example.com/@user/1234567890",
            "in_reply_to_account_id": null,
            "poll_id": null,
            "application_id": null,
            "local": true,
            "reply": false,
            "conversation_id": null,
            "deleted_at": null,
            "edited_at": null,
            "trendable": null,
            "ordered_media_attachment_ids": null
        }
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            s.id,
            s.text,
            s.created_at,
            s.updated_at,
            s.in_reply_to_id,
            s.reblog_of_id,
            s.account_id,
            s.visibility,
            s.sensitive,
            s.spoiler_text,
            s.language,
            s.uri,
            s.url,
            s.in_reply_to_account_id,
            s.poll_id,
            s.application_id,
            s.local,
            s.reply,
            s.conversation_id,
            s.deleted_at,
            s.edited_at,
            s.trendable,
            s.ordered_media_attachment_ids
        FROM statuses s
        WHERE s.id = %s
    """
    try:
        cur.execute(query, (status_id,))
        row = cur.fetchone()

        if not row:
            logger.warning(f"Status with ID {status_id} not found")
            return None

        # Convert tuple to dictionary
        (
            id,
            text,
            created_at,
            updated_at,
            in_reply_to_id,
            reblog_of_id,
            account_id,
            visibility,
            sensitive,
            spoiler_text,
            language,
            uri,
            url,
            in_reply_to_account_id,
            poll_id,
            application_id,
            local,
            reply,
            conversation_id,
            deleted_at,
            edited_at,
            trendable,
            ordered_media_attachment_ids,
        ) = row

        toot = {
            "id": id,
            "text": text,
            "content": text,  # content is the same as text
            "created_at": created_at,
            "updated_at": updated_at,
            "in_reply_to_id": in_reply_to_id,  # status_id, if the toot is a reply to another toot
            "reblog_of_id": reblog_of_id,  # the ID of the toot being reblogged
            "account_id": account_id,
            "visibility": visibility,
            "sensitive": sensitive,
            "spoiler_text": spoiler_text,
            "language": language,
            "uri": uri,
            "url": url,
            "in_reply_to_account_id": in_reply_to_account_id,
            "poll_id": poll_id,
            "application_id": application_id,
            "local": local,
            "reply": reply,
            "conversation_id": conversation_id,
            "deleted_at": deleted_at,
            "edited_at": edited_at,
            "trendable": trendable,
            "ordered_media_attachment_ids": ordered_media_attachment_ids,
        }

        logger.info(f"Found toot with ID {status_id}")
        return toot

    except Exception as e:
        logger.error(f"Error fetching toot {status_id}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_polls(poll_id: int) -> dict | None:
    """
    Get a specific poll by poll_id.

    TABLE: polls
    Args:
        poll_id: The ID of the poll to retrieve

    Returns:
        Poll dictionary with all poll fields or None if error/not found
        e.g.:
        {
            "id": 123,
            "account_id": 456,  # the poll creator
            "status_id": 789,   # the toot ID that the poll is attached to
            "expires_at": "2025-10-25 12:00:00",
            "options": ["Option 1", "Option 2", "Option 3"],
            "cached_tallies": [10, 5, 3],
            "multiple": false,  # whether the poll allows multiple choices
            "hide_totals": false,  # whether to hide the total votes
            "votes_count": 18,  # the total number of votes
            "last_fetched_at": "2025-10-23 10:30:00",  # the last time the poll was fetched
            "created_at": "2025-10-23 10:00:00",  # the time the poll was created
            "updated_at": "2025-10-23 10:30:00",  # the time the poll was updated
            "lock_version": 0,  # the lock version of the poll
            "voters_count": 15
        }
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        logger.error("Failed to connect to PostgreSQL database")
        return None

    query = """
        SELECT
            p.id,
            p.account_id,
            p.status_id,
            p.expires_at,
            p.options,
            p.cached_tallies,
            p.multiple,
            p.hide_totals,
            p.votes_count,
            p.last_fetched_at,
            p.created_at,
            p.updated_at,
            p.lock_version,
            p.voters_count
        FROM polls p
        WHERE p.id = %s
    """

    try:
        cur.execute(query, (poll_id,))
        row = cur.fetchone()

        if not row:
            logger.warning(f"Poll with ID {poll_id} not found")
            return None

        # Convert tuple to dictionary
        (
            id,
            account_id,
            status_id,
            expires_at,
            options,
            cached_tallies,
            multiple,
            hide_totals,
            votes_count,
            last_fetched_at,
            created_at,
            updated_at,
            lock_version,
            voters_count,
        ) = row

        poll = {
            "id": id,
            "account_id": account_id,
            "status_id": status_id,
            "expires_at": expires_at,
            "options": options or [],
            "cached_tallies": cached_tallies or [],
            "multiple": multiple,
            "hide_totals": hide_totals,
            "votes_count": votes_count,
            "last_fetched_at": last_fetched_at,
            "created_at": created_at,
            "updated_at": updated_at,
            "lock_version": lock_version,
            "voters_count": voters_count,
        }

        logger.info(f"Found poll with ID {poll_id}")
        return poll

    except Exception as e:
        logger.error(f"Error fetching poll {poll_id}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_toot_tags(status_id: int) -> list[str] | None:
    """Get the tags of a specific toot by ID from the PostgreSQL database.

    TABLE: statuses, statuses_tags, tags
    Args:
        statuses_id: The ID of the status to retrieve tags for

    Returns:
        List of tags or None if error/not found
        e.g.:
        ["tag1", "tag2", "tag3"]
    """

    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT COALESCE(
            ARRAY_AGG(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL),
            ARRAY[]::text[]
        ) AS tags
        FROM statuses s
        LEFT JOIN statuses_tags st ON st.status_id = s.id
        LEFT JOIN tags t ON t.id = st.tag_id
        WHERE s.id = %s
        GROUP BY s.id
    """
    try:
        cur.execute(query, (status_id,))
        row = cur.fetchone()
        if not row:
            logger.warning(f"No tags found for status ID {status_id}")
            return None

        tags = row[0]
        # if the tags array is empty, return None
        if not tags or len(tags) == 0:
            return None
        return tags
    except Exception as e:
        logger.error(f"Error fetching toot tags: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_images_by_status_id(status_id: int) -> list[dict] | None:
    """
    Get all images/media attachments for a specific toot by status_id.

    TABLE: media_attachments, statuses
    Args:
        toot_id: The ID of the toot/status to retrieve images for

    Returns:
        List of image dictionaries with media attachment fields or None if error/not found
        e.g.:
        [
            {
                "media_attachment_id": 115401014049282675,
                "type": 0,
                "file_name": "77e55f1fda40e92c.jpg",
                "remote_url": "",
                "description": null,
                "content_type": "image/jpeg",
                "file_size": 12345,
                "file_updated_at": "2025-10-19 13:15:32.441154",
                "created_at": "2025-10-19 13:15:32.441154",
                "updated_at": "2025-10-19 13:15:32.441154",
                "shortcode": null,
                "file_meta": null,
                "account_id": 12345,
                "scheduled_status_id": null,
                "blurhash": "L6PZfSi_.AyE_3t7t7R**0o#DgR4",
                "processing": null,
                "file_storage_schema_version": null,
                "thumbnail_file_name": "thumbnail.jpg",
                "thumbnail_content_type": "image/jpeg",
                "thumbnail_file_size": 5432,
                "thumbnail_updated_at": "2025-10-19 13:15:32.441154",
                "thumbnail_remote_url": "https://example.com/thumbnails/thumbnail.jpg"
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            m.id,
            m.type,
            m.file_file_name,
            m.file_content_type,
            m.file_file_size,
            m.file_updated_at,
            m.remote_url,
            m.created_at,
            m.updated_at,
            m.shortcode,
            m.file_meta,
            m.account_id,
            m.description,
            m.scheduled_status_id,
            m.blurhash,
            m.processing,
            m.file_storage_schema_version,
            m.thumbnail_file_name,
            m.thumbnail_content_type,
            m.thumbnail_file_size,
            m.thumbnail_updated_at,
            m.thumbnail_remote_url
        FROM media_attachments m
        WHERE m.status_id = %s
        AND m.id = ANY(
            -- get the valid media attachment IDs for the current status
            SELECT unnest(COALESCE(
                s.ordered_media_attachment_ids,
                ARRAY[]::bigint[]
            ))
            FROM statuses s
            WHERE s.id = %s
        )
        ORDER BY array_position(
            (SELECT ordered_media_attachment_ids FROM statuses WHERE id = %s),
            m.id
        )
    """
    try:
        cur.execute(query, (status_id, status_id, status_id))
        rows = cur.fetchall()

        if not rows:
            logger.warning(f"No images found for status ID {status_id}")
            return None

        # Convert tuples to dictionaries
        images = []
        for row in rows:
            (
                id,
                type,
                file_name,
                content_type,
                file_size,
                file_updated_at,
                remote_url,
                created_at,
                updated_at,
                shortcode,
                file_meta,
                account_id,
                description,
                scheduled_status_id,
                blurhash,
                processing,
                file_storage_schema_version,
                thumbnail_file_name,
                thumbnail_content_type,
                thumbnail_file_size,
                thumbnail_updated_at,
                thumbnail_remote_url,
            ) = row

            images.append(
                {
                    "media_attachment_id": id,
                    "type": type,
                    "file_name": file_name,
                    "content_type": content_type,
                    "file_size": file_size,
                    "file_updated_at": file_updated_at,
                    "remote_url": remote_url,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "shortcode": shortcode,
                    "file_meta": file_meta,
                    "account_id": account_id,
                    "description": description,
                    "scheduled_status_id": scheduled_status_id,
                    "blurhash": blurhash,
                    "processing": processing,
                    "file_storage_schema_version": file_storage_schema_version,
                    "thumbnail_file_name": thumbnail_file_name,
                    "thumbnail_content_type": thumbnail_content_type,
                    "thumbnail_file_size": thumbnail_file_size,
                    "thumbnail_updated_at": thumbnail_updated_at,
                    "thumbnail_remote_url": thumbnail_remote_url,
                }
            )

        logger.info(f"Found {len(images)} image(s) for status ID {status_id}")
        return images

    except Exception as e:
        logger.error(f"Error fetching images for status {status_id}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_report_info(status_id: int) -> dict | None:
    """
    Get the report info for a specific toot by status_id.

    TABLE: reports, accounts
    Args:
        status_id: The ID of the status to retrieve report info for

    Returns:
        Report dictionary with all report fields or None if error/not found
        e.g.:
        {
            "report_id": 123,
            "status_ids": [115423439308602944],
            "comment": "This post contains inappropriate content",
            "created_at": "2025-10-23 12:00:00",
            "updated_at": "2025-10-23 12:30:00",
            "account_id": 456,
            "action_taken_by_account_id": 789,
            "target_account_id": 101,
            "assigned_account_id": 202,
            "uri": "https://example.com/reports/123",
            "forwarded": false,
            "category": 1,
            "action_taken_at": "2025-10-23 12:30:00",
            "rule_ids": [1, 2, 3],
            "application_id": 303,
            "reporter_username": "reporter_user",
            "reporter_display_name": "Reporter User",
            "target_username": "target_user",
            "target_display_name": "Target User",
            "action_taken_by_username": "admin_user",
            "assigned_username": "moderator_user"
        }
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            r.id,
            r.status_ids,
            r.comment,
            r.created_at,
            r.updated_at,
            r.account_id,
            r.action_taken_by_account_id,
            r.target_account_id,
            r.assigned_account_id,
            r.uri,
            r.forwarded,
            r.category,
            r.action_taken_at,
            r.rule_ids,
            r.application_id,
            reporter.username as reporter_username,
            reporter.display_name as reporter_display_name,
            target.username as target_username,
            target.display_name as target_display_name,
            action_taker.username as action_taken_by_username,
            assigned.username as assigned_username
        FROM reports r
        JOIN accounts reporter ON reporter.id = r.account_id
        JOIN accounts target ON target.id = r.target_account_id
        LEFT JOIN accounts action_taker ON action_taker.id = r.action_taken_by_account_id
        LEFT JOIN accounts assigned ON assigned.id = r.assigned_account_id
        WHERE %s = ANY(r.status_ids)
        ORDER BY r.created_at DESC
        LIMIT 1
    """
    try:
        cur.execute(query, (status_id,))
        row = cur.fetchone()

        if not row:
            logger.warning(f"No report found for status ID {status_id}")
            return None

        # Convert tuple to dictionary
        (
            id,
            status_ids,
            comment,
            created_at,
            updated_at,
            account_id,
            action_taken_by_account_id,
            target_account_id,
            assigned_account_id,
            uri,
            forwarded,
            category,
            action_taken_at,
            rule_ids,
            application_id,
            reporter_username,
            reporter_display_name,
            target_username,
            target_display_name,
            action_taken_by_username,
            assigned_username,
        ) = row

        report = {
            "report_id": id,
            "status_ids": status_ids or [],
            "comment": comment,
            "created_at": created_at,
            "updated_at": updated_at,
            "account_id": account_id,
            "action_taken_by_account_id": action_taken_by_account_id,
            "target_account_id": target_account_id,
            "assigned_account_id": assigned_account_id,
            "uri": uri,
            "forwarded": forwarded,
            "category": category,
            "action_taken_at": action_taken_at,
            "rule_ids": rule_ids or [],
            "application_id": application_id,
            "reporter_username": reporter_username,
            "reporter_display_name": reporter_display_name,
            "target_username": target_username,
            "target_display_name": target_display_name,
            "action_taken_by_username": action_taken_by_username,
            "assigned_username": assigned_username,
        }

        logger.info(f"Found report for status ID {status_id}")
        return report

    except Exception as e:
        logger.error(f"Error fetching report for status {status_id}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_blocked_users(username: str) -> list[dict] | None:
    """
    Get the users blocked by a specific user.

    TABLE: blocks, accounts
    Args:
        username: The username to retrieve blocked users for

    Returns:
        List of blocked users or None if error/not found
        e.g.:
        [
            {
                'id': 1,
                'created_at': '2025-10-14 12:13:23.712869',
                'updated_at': '2025-10-14 12:13:23.712869',
                'account_id': 1,
                'target_account_id': 2,
                'uri': 'https://example.com/1',
                'blocked_username': 'test',
                'blocked_display_name': 'Test User',
                'domain': 'example.com'
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            b.id,
            b.created_at,
            b.updated_at,
            b.account_id,
            b.target_account_id,
            b.uri,
            a.username,
            a.display_name,
            a.domain
        FROM blocks b
        JOIN accounts a ON a.id = b.target_account_id
        JOIN accounts blocker ON blocker.id = b.account_id
        WHERE blocker.username = %s
        ORDER BY b.created_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        # Convert to list of dictionaries
        blocked_users = []
        for row in rows:
            (
                id,
                created_at,
                updated_at,
                account_id,
                target_account_id,
                uri,
                username,
                display_name,
                domain,
            ) = row
            blocked_users.append(
                {
                    "id": id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "account_id": account_id,
                    "target_account_id": target_account_id,
                    "uri": uri,
                    "blocked_username": username,
                    "blocked_display_name": display_name,
                    "domain": domain,
                }
            )

        return blocked_users
    except Exception as e:
        logger.error(f"Error fetching blocked users for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_muted_users(username: str) -> list[dict] | None:
    """
    Get the users muted by a specific user(username).

    TABLE: mutes, accounts
    Args:
        username: The username to retrieve muted users for

    Returns:
        List of muted users or None if error/not found
    e.g.:
    [
        {
            'id': 1,
            'created_at': '2025-10-14 12:13:23.712869',
            'updated_at': '2025-10-14 12:13:23.712869',
            'hide_notifications': True,
            'account_id': 1,
            'target_account_id': 2,
            'expires_at': '2025-10-14 12:13:23.712869',
            'muted_username': 'test',
            'muted_display_name': 'Test User',
            'domain': 'example.com'
        }
    ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            m.id,
            m.created_at,
            m.updated_at,
            m.hide_notifications,
            m.account_id,
            m.target_account_id,
            m.expires_at,
            a.username,
            a.display_name,
            a.domain
        FROM mutes m
        JOIN accounts a ON a.id = m.target_account_id
        JOIN accounts muter ON muter.id = m.account_id
        WHERE muter.username = %s
        ORDER BY m.created_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        # Convert to list of dictionaries
        muted_users = []
        for row in rows:
            (
                id,
                created_at,
                updated_at,
                hide_notifications,
                account_id,
                target_account_id,
                expires_at,
                username,
                display_name,
                domain,
            ) = row
            muted_users.append(
                {
                    "id": id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "hide_notifications": hide_notifications,
                    "account_id": account_id,
                    "target_account_id": target_account_id,
                    "expires_at": expires_at,
                    "muted_username": username,
                    "muted_display_name": display_name,
                    "domain": domain,
                }
            )

        return muted_users
    except Exception as e:
        logger.error(f"Error fetching muted users for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_invite_info(username: str, limit: int = 1) -> list[dict] | None:
    """
    Get the latest limit number of invite info for a specific user by username.

    TABLE: invites, users, accounts
    Args:
        username: The username to retrieve invite info for

    Returns:
        Invite dictionary with all invite fields or None if error/not found
        e.g.:
        {
            "id": 42,
            "code": "kPA2DfcB",
            "max_uses": 10,
            "uses": 2,
            "expires_at": "2025-10-14 12:13:23.712869",
            "created_at": "2025-10-13 12:13:23.715918",
            "updated_at": "2025-10-13 12:13:23.715918",
            "autofollow": true,
            "comment": "Welcome to our instance!",
            "is_active": true,
            "invite_url": "https://10.0.2.2/invite/kPA2DfcB"
        }
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            i.id,
            i.code,
            i.max_uses,
            i.uses,
            i.expires_at,
            i.created_at,
            i.updated_at,
            i.autofollow,
            i.comment,
            CASE
                WHEN (i.expires_at IS NOT NULL AND i.expires_at < NOW())
                OR (i.max_uses IS NOT NULL AND i.uses >= i.max_uses)
                THEN FALSE ELSE TRUE
            END AS is_active
        FROM invites i
        JOIN users u ON u.id = i.user_id
        JOIN accounts a ON a.id = u.account_id
        WHERE a.username = %s
        AND a.domain IS NULL
        ORDER BY i.id DESC
        LIMIT %s
    """

    try:
        cur.execute(query, (username, limit))
        rows = cur.fetchall()
        if not rows:
            return None

        # Convert to list of dictionaries
        invites = []
        for row in rows:
            (
                id,
                code,
                max_uses,
                uses,
                expires_at,
                created_at,
                updated_at,
                autofollow,
                comment,
                is_active,
            ) = row
            invite = {
                "id": id,
                "code": code,
                "max_uses": max_uses,
                "uses": uses,
                "expires_at": expires_at,
                "created_at": created_at,
                "updated_at": updated_at,
                "autofollow": autofollow,
                "comment": comment,
                "is_active": is_active,
                "invite_url": f"https://{MASTODON_LOCAL_DOMAIN}/invite/{code}",
            }
            invites.append(invite)

        logger.info(f"Found {len(invites)} invites for username {username}")
        return invites

    except Exception as e:
        logger.error(f"Error fetching invite for username {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_follower_users(username: str) -> list[dict] | None:
    """
    Get the users followed by a specific user(username).

    TABLE: follows, accounts
    Args:
        username: The username to retrieve follower users for

    Returns:
        List of follower users or None if error/not found
        e.g.:
        [
            {
                'id': 1,
                'created_at': '2025-10-14 12:13:23.712869',
                'updated_at': '2025-10-14 12:13:23.712869',
                'account_id': 1,
                'target_account_id': 2,
                'show_reblogs': True,
                'uri': 'https://example.com/1',
                'notify': True,
                'language': ['en'],
                'username': 'test',
                'display_name': 'Test User',
                'target_username': 'test2',
                'target_display_name': 'Test User 2'
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            f.id,
            f.created_at,
            f.updated_at,
            f.account_id,
            f.target_account_id,
            f.show_reblogs,
            f.uri,
            f.notify,
            f.languages,
            a.username,
            a.display_name,
            b.username,
            b.display_name
        FROM follows f
        JOIN accounts a ON a.id = f.target_account_id
        JOIN accounts b ON b.id = f.account_id
        WHERE a.username = %s
        AND a.domain IS NULL
        ORDER BY f.created_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        # Convert to list of dictionaries
        following_users = []
        for row in rows:
            (
                id,
                created_at,
                updated_at,
                account_id,
                target_account_id,
                show_reblogs,
                uri,
                notify,
                language,
                username,
                display_name,
                target_username,
                target_display_name,
            ) = row
            following_users.append(
                {
                    "id": id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "account_id": account_id,
                    "target_account_id": target_account_id,
                    "show_reblogs": show_reblogs,
                    "uri": uri,
                    "notify": notify,
                    "language": language,
                    "username": username,
                    "display_name": display_name,
                    "target_username": target_username,
                    "target_display_name": target_display_name,
                }
            )

        return following_users
    except Exception as e:
        logger.error(f"Error fetching following users for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_following_users(username: str) -> list[dict] | None:
    """
    Get the users a specific user(username) is following.

    TABLE: follows, accounts
    Args:
        username: The username to retrieve following users for

    Returns:
        List of following users or None if error/not found
        e.g.:
        [
            {
                'id': 1,
                'created_at': '2025-10-14 12:13:23.712869',
                'updated_at': '2025-10-14 12:13:23.712869',
                'account_id': 1,
                'target_account_id': 2,
                'show_reblogs': True,
                'uri': 'https://example.com/1',
                'notify': True,
                'language': ['en'],
                'username': 'test',
                'display_name': 'Test User',
                'target_username': 'test2',
                'target_display_name': 'Test User 2'
            }
        ]
    """

    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            f.id,
            f.created_at,
            f.updated_at,
            f.account_id,
            f.target_account_id,
            f.show_reblogs,
            f.uri,
            f.notify,
            f.languages,
            a.username,
            a.display_name,
            b.username,
            b.display_name
        FROM follows f
        JOIN accounts a ON a.id = f.account_id
        JOIN accounts b ON b.id = f.target_account_id
        WHERE a.username = %s
        AND a.domain IS NULL
        ORDER BY f.created_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        # Convert to list of dictionaries
        following_users = []
        for row in rows:
            (
                id,
                created_at,
                updated_at,
                account_id,
                target_account_id,
                show_reblogs,
                uri,
                notify,
                language,
                username,
                display_name,
                target_username,
                target_display_name,
            ) = row
            following_users.append(
                {
                    "id": id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "account_id": account_id,
                    "target_account_id": target_account_id,
                    "show_reblogs": show_reblogs,
                    "uri": uri,
                    "notify": notify,
                    "language": language,
                    "username": username,
                    "display_name": display_name,
                    "target_username": target_username,
                    "target_display_name": target_display_name,
                }
            )

        return following_users
    except Exception as e:
        logger.error(f"Error fetching following users for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_filters_by_username(username: str) -> list[dict] | None:
    """
    Get the filters info for a specific user(username).

    TABLES: custom_filters, custom_filter_keywords
    Args:
        username: The username to retrieve filters for

    Returns:
        List of filters with keywords and action or None if error/not found
        e.g.:
        [
            {
                'id': 1,
                'created_at': '2025-10-14 12:13:23.712869',
                'updated_at': '2025-10-14 12:13:23.712869',
                'account_id': 1,
                'phrase': 'Anti-Spoiler–BCS',
                'context': ['home', 'notifications', 'public', 'thread', 'account'],
                'expires_at': '2025-10-20 16:36:02.593695',
                'action': 1,
                'keywords': [
                    {
                        'keyword': 'season 6',
                        'whole_word': True
                    },
                    {
                        'keyword': 'Better Call Saul',
                        'whole_word': True
                    }
                ]
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            cf.id,
            cf.created_at,
            cf.updated_at,
            cf.account_id,
            cf.phrase,
            cf.context,
            cf.expires_at,
            cf.action,
            COALESCE(
                json_agg(
                    json_build_object('keyword', k.keyword, 'whole_word', k.whole_word)
                    ORDER BY k.id
                ) FILTER (WHERE k.id IS NOT NULL),
                '[]'::json
            ) AS keywords
        FROM custom_filters cf
        JOIN accounts a ON a.id = cf.account_id
        LEFT JOIN custom_filter_keywords k ON k.custom_filter_id = cf.id
        WHERE a.username = %s
        AND a.domain IS NULL
        GROUP BY cf.id, cf.created_at, cf.updated_at, cf.account_id,
                 cf.phrase, cf.context, cf.expires_at, cf.action
        ORDER BY cf.created_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        # Convert to list of dictionaries
        filters = []
        for row in rows:
            (
                id,
                created_at,
                updated_at,
                account_id,
                phrase,
                context,
                expires_at,
                action,
                keywords_json,
            ) = row

            # Convert context to list if it's a string
            if isinstance(context, str):
                context_str = context.strip()
                if context_str.startswith("{") and context_str.endswith("}"):
                    contexts = [x.strip() for x in context_str[1:-1].split(",") if x.strip()]
                else:
                    contexts = [context_str] if context_str else []
            elif isinstance(context, list):
                contexts = context
            else:
                contexts = []

            # Convert keywords_json to list
            if isinstance(keywords_json, str):
                try:
                    import json

                    keywords = json.loads(keywords_json)
                except json.JSONDecodeError:
                    keywords = []
            else:
                keywords = keywords_json or []

            filters.append(
                {
                    "id": id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "account_id": account_id,
                    "phrase": phrase,
                    "context": contexts,
                    "expires_at": expires_at,
                    "action": action,
                    "keywords": keywords,
                }
            )

        return filters
    except Exception as e:
        logger.error(f"Error fetching filters for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_favorites_by_username(username: str) -> list[dict] | None:
    """
    Get the favorites for a specific user(username).

    TABLES: favourites, accounts
    Args:
        username: The username to retrieve favorites for

    Returns:
        List of favorites with status information or None if error/not found
        e.g.:
        [
            {
                'id': 1,
                'created_at': '2025-10-14 12:13:23.712869',
                'updated_at': '2025-10-14 12:13:23.712869',
                'account_id': 1,
                'status_id': 115348102480027134,
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
        f.id,
        f.created_at,
        f.updated_at,
        f.account_id,
        f.status_id
        FROM favourites f
        JOIN accounts a ON f.account_id = a.id
        WHERE a.username = %s
        AND a.domain IS NULL
        ORDER BY f.created_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        favorites = []
        for row in rows:
            (id, created_at, updated_at, account_id, status_id) = row
            favorites.append(
                {
                    "id": id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "account_id": account_id,
                    "status_id": status_id,
                }
            )
        return favorites
    except Exception as e:
        logger.error(f"Error fetching favorites for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_lists_by_username(username: str) -> list[dict] | None:
    """
    Get the lists for a specific user with members information.

    TABLES: lists, list_accounts, accounts
    Args:
        username: The username to retrieve lists for

    Returns:
        List of lists with list information and members or None if error/not found
        e.g.:
        [
            {
                'list_id': 1,
                'created_at': '2025-10-14 12:13:23.712869',
                'updated_at': '2025-10-14 12:13:23.712869',
                'account_id': 1,
                'title': 'Family',
                'replies_policy': 0,
                'exclusive': False,
                'members': [
                    {
                        'list_id': 1,
                        'account_id': 2,
                        'follow_id': 1,
                        'follow_request_id': None,
                        'username': 'alex',
                        'display_name': 'Alex'
                    },
                    {
                        'list_id': 1,
                        'account_id': 3,
                        'follow_id': 2,
                        'follow_request_id': None,
                        'username': 'emma',
                        'display_name': 'Emma'
                    }
                ]
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    # First, get all lists for the user
    lists_query = """
        SELECT
            l.id,
            l.created_at,
            l.updated_at,
            l.account_id,
            l.title,
            l.replies_policy,
            l.exclusive
        FROM lists l
        JOIN accounts a ON l.account_id = a.id
        WHERE a.username = %s
        AND a.domain IS NULL
        ORDER BY l.created_at DESC
    """

    try:
        cur.execute(lists_query, (username,))
        lists_rows = cur.fetchall()

        if not lists_rows:
            return None

        # Get members for each list
        lists = []
        for list_row in lists_rows:
            (list_id, created_at, updated_at, account_id, title, replies_policy, exclusive) = (
                list_row
            )

            # Get members for this list
            members_query = """
                SELECT
                    la.list_id,
                    la.account_id,
                    la.follow_id,
                    la.follow_request_id,
                    a.username,
                    a.display_name
                FROM list_accounts la
                JOIN accounts a ON la.account_id = a.id
                WHERE la.list_id = %s
                ORDER BY la.id
            """

            cur.execute(members_query, (list_id,))
            members_rows = cur.fetchall()

            # Convert members to list of dictionaries
            members = []
            for member_row in members_rows:
                (
                    m_list_id,
                    m_account_id,
                    m_follow_id,
                    m_follow_request_id,
                    m_username,
                    m_display_name,
                ) = member_row
                members.append(
                    {
                        "list_id": m_list_id,
                        "account_id": m_account_id,
                        "follow_id": m_follow_id,
                        "follow_request_id": m_follow_request_id,
                        "username": m_username,
                        "display_name": m_display_name,
                    }
                )

            # Create list dictionary
            list_dict = {
                "list_id": list_id,
                "created_at": created_at,
                "updated_at": updated_at,
                "account_id": account_id,
                "title": title,
                "replies_policy": replies_policy,
                "exclusive": exclusive,
                "members": members,
            }

            lists.append(list_dict)

        return lists

    except Exception as e:
        logger.error(f"Error fetching lists for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_bookmarks_by_username(username: str) -> list[dict] | None:
    """
    Get the bookmarks for a specific user(username).

    TABLE: bookmarks, accounts
    Args:
        username: The username to retrieve bookmarks for

    Returns:
        List of bookmarks with bookmark information or None if error/not found
        e.g.:
            [
                {
                    "id": 5,
                    "account_id": 115338428522805842,
                    "status_id": 115384014916118822,
                    "created_at": "2025-10-30 03:11:47.679730",
                    "updated_at": "2025-10-30 03:11:47.679730"
                },
                {
                    "id": 4,
                    "account_id": 115338428522805842,
                    "status_id": 115353533205151985,
                    "created_at": "2025-10-29 08:12:59.931354",
                    "updated_at": "2025-10-29 08:12:59.931354"
                }
            ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            b.id,
            b.created_at,
            b.updated_at,
            b.account_id,
            b.status_id
        FROM bookmarks b
        JOIN accounts a ON b.account_id = a.id
        WHERE a.username = %s
        AND a.domain IS NULL
        ORDER BY b.created_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        bookmarks = []
        for row in rows:
            (id, created_at, updated_at, account_id, status_id) = row
            bookmarks.append(
                {
                    "id": id,
                    "account_id": account_id,
                    "status_id": status_id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return bookmarks
    except Exception as e:
        logger.error(f"Error fetching bookmarks for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_hashtags_by_username(username: str) -> list[dict] | None:
    """
    Get the tags (hashtags) followed by a specific user(username).

    TABLE: tag_follows, tags, accounts
    Args:
        username: The username to retrieve followed tags for

    Returns:
        List of followed tags or None if error/not found
        e.g.:
        [
            {
                "id": 1,
                "tag_id": 5,
                "tag_name": "technology",
                "account_id": 115338428522805842,
                "created_at": "2025-10-14 12:13:23.712869",
                "updated_at": "2025-10-14 12:13:23.712869"
            },
            {
                "id": 2,
                "tag_id": 8,
                "tag_name": "programming",
                "account_id": 115338428522805842,
                "created_at": "2025-10-15 10:20:30.123456",
                "updated_at": "2025-10-15 10:20:30.123456"
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            tf.id,
            tf.tag_id,
            t.name AS tag_name,
            tf.account_id,
            tf.created_at,
            tf.updated_at
        FROM tag_follows tf
        JOIN tags t ON t.id = tf.tag_id
        JOIN accounts a ON a.id = tf.account_id
        WHERE a.username = %s
        AND a.domain IS NULL
        ORDER BY tf.created_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        # Convert to list of dictionaries
        followed_tags = []
        for row in rows:
            (
                id,
                tag_id,
                tag_name,
                account_id,
                created_at,
                updated_at,
            ) = row
            followed_tags.append(
                {
                    "id": id,
                    "tag_id": tag_id,
                    "tag_name": tag_name,
                    "account_id": account_id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )

        logger.info(f"Found {len(followed_tags)} followed tags for username {username}")
        return followed_tags
    except Exception as e:
        logger.error(f"Error fetching followed tags for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_featured_tags_by_username(username: str) -> list[dict] | None:
    """
    Get the featured tags (hashtags) for a specific user(username).

    TABLES: featured_tags, tags, accounts
    Args:
        username: The username to retrieve featured tags for

    Returns:
        List of featured tags or None if error/not found
        e.g.:
        [
            {
                "account_id": 115338428522805842,
                "tag_id": 5,
                "statuses_count": 100,
                "last_status_at": "2025-10-14 12:13:23.712869",
                "created_at": "2025-10-14 12:13:23.712869",
                "updated_at": "2025-10-14 12:13:23.712869",
                "name": "technology"
            },
            {
                "account_id": 115338428522805842,
                "tag_id": 8,
                "statuses_count": 50,
                "last_status_at": "2025-10-15 10:20:30.123456",
                "created_at": "2025-10-15 10:20:30.123456",
                "updated_at": "2025-10-15 10:20:30.123456",
                "name": "programming"
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            ft.account_id,
            ft.tag_id,
            ft.statuses_count,
            ft.last_status_at,
            ft.created_at,
            ft.updated_at,
            COALESCE(ft.name, t.name) AS name
        FROM featured_tags ft
        JOIN accounts a ON a.id = ft.account_id
        LEFT JOIN tags t ON t.id = ft.tag_id
        WHERE a.username = %s
        AND a.domain IS NULL
        ORDER BY ft.statuses_count DESC, ft.last_status_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        # Convert to list of dictionaries
        featured_tags = []
        for row in rows:
            (
                account_id,
                tag_id,
                statuses_count,
                last_status_at,
                created_at,
                updated_at,
                name,
            ) = row
            featured_tags.append(
                {
                    "account_id": account_id,
                    "tag_id": tag_id,
                    "statuses_count": statuses_count,
                    "last_status_at": last_status_at,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "name": name,
                }
            )

        logger.info(f"Found {len(featured_tags)} featured tags for username {username}")
        return featured_tags
    except Exception as e:
        logger.error(f"Error fetching featured tags for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_pinned_toots_by_username(username: str) -> list[dict] | None:
    """
    Get the pinned toots for a specific user(username).

    TABLE: status_pins, accounts
    Args:
        username: The username to retrieve pinned toots for

    Returns:
        List of pinned toots with pinned toot information or None if error/not found
        e.g.:
        [
            {
                "id": 3,
                "account_id": 115338428522805842,
                "status_id": 115457433766445196,
                "created_at": "2025-10-30 04:54:16.705947",
                "updated_at": "2025-10-30 04:54:16.705947"
            },
            {
                "id": 2,
                "account_id": 115338428522805842,
                "status_id": 115457314121479609,
                "created_at": "2025-10-30 04:48:30.030152",
                "updated_at": "2025-10-30 04:48:30.030152"
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            p.id,
            p.created_at,
            p.updated_at,
            p.account_id,
            p.status_id
        FROM status_pins p
        JOIN accounts a ON p.account_id = a.id
        WHERE a.username = %s
        AND a.domain IS NULL
        ORDER BY p.created_at DESC
    """
    try:
        cur.execute(query, (username,))
        rows = cur.fetchall()
        if not rows:
            return None

        pinned = []
        for row in rows:
            (id, created_at, updated_at, account_id, status_id) = row
            pinned.append(
                {
                    "id": id,
                    "account_id": account_id,
                    "status_id": status_id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return pinned
    except Exception as e:
        logger.error(f"Error fetching pinned toots for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_automated_post_deletions_setting(username: str) -> dict | None:
    """
    Get automated post deletion settings for a specific user (username).

    TABLE: account_statuses_cleanup_policies, accounts

    Args:
        username: The local username to retrieve settings for

    Returns:
        Dictionary of cleanup policy fields or None if not found/error, e.g.:
        {
            "account_id": 115338428522805842,
            "enabled": True,
            "min_status_age": 1209600,            # seconds
            "min_status_age_days": 14,            # derived days
            "keep_direct": True,
            "keep_pinned": True,
            "keep_polls": False,
            "keep_media": False,
            "keep_self_fav": True,
            "keep_self_bookmark": True,
            "min_favs": None,
            "min_reblogs": None,
            "created_at": "...",
            "updated_at": "..."
        }
    """

    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            p.account_id,
            p.enabled,
            p.min_status_age,
            p.keep_direct,
            p.keep_pinned,
            p.keep_polls,
            p.keep_media,
            p.keep_self_fav,
            p.keep_self_bookmark,
            p.min_favs,
            p.min_reblogs,
            p.created_at,
            p.updated_at
        FROM account_statuses_cleanup_policies p
        JOIN accounts a ON p.account_id = a.id
        WHERE a.username = %s
          AND a.domain IS NULL
        ORDER BY p.updated_at DESC
        LIMIT 1
    """

    try:
        cur.execute(query, (username,))
        row = cur.fetchone()
        if not row:
            return None

        (
            account_id,
            enabled,
            min_status_age,
            keep_direct,
            keep_pinned,
            keep_polls,
            keep_media,
            keep_self_fav,
            keep_self_bookmark,
            min_favs,
            min_reblogs,
            created_at,
            updated_at,
        ) = row

        # Derive days from seconds if min_status_age is present
        min_status_age_days = None
        try:
            if isinstance(min_status_age, int) and min_status_age is not None:
                min_status_age_days = min_status_age // 86400
        except Exception:
            min_status_age_days = None

        return {
            "account_id": account_id,
            "enabled": enabled,
            "min_status_age": min_status_age,
            "min_status_age_days": min_status_age_days,
            "keep_direct": keep_direct,
            "keep_pinned": keep_pinned,
            "keep_polls": keep_polls,
            "keep_media": keep_media,
            "keep_self_fav": keep_self_fav,
            "keep_self_bookmark": keep_self_bookmark,
            "min_favs": min_favs,
            "min_reblogs": min_reblogs,
            "created_at": created_at,
            "updated_at": updated_at,
        }
    except Exception as e:
        logger.error(f"Error fetching automated deletion settings for {username}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_all_reports_info() -> list[dict] | None:
    """
    Get all reports info.

    TABLE: reports, accounts
    Returns:
        List of reports info or None if error/not found
        e.g.:
        [
            {
                "id": 2,
                "status_ids": [
                115348126416869763
                ],
                "comment": "",
                "created_at": "2025-10-13T20:09:03.722329",
                "updated_at": "2025-10-13T20:09:03.722329",
                "account_id": 115338428522805842,
                "action_taken_by_account_id": null, # null means not tackle yet
                "target_account_id": 115338428325536028,
                "assigned_account_id": null,
                "uri": "https://10.0.2.2/357855ad-e2a2-4794-9e6f-657d7a1912b7",
                "forwarded": false,
                "category": 1000,
                "action_taken_at": null,
                "rule_ids": null,
                "application_id": 10,
                "reporter_username": "test",
                "reporter_display_name": "TEST",
                "target_username": "demo",
                "target_display_name": "demo",
                "action_taken_by_username": null,
                "assigned_username": null
            },
            ...
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            r.id,
            r.status_ids,
            r.comment,
            r.created_at,
            r.updated_at,
            r.account_id,
            r.action_taken_by_account_id,
            r.target_account_id,
            r.assigned_account_id,
            r.uri,
            r.forwarded,
            r.category,
            r.action_taken_at,
            r.rule_ids,
            r.application_id,
            reporter.username as reporter_username,
            reporter.display_name as reporter_display_name,
            target.username as target_username,
            target.display_name as target_display_name,
            action_taker.username as action_taken_by_username,
            assigned.username as assigned_username
        FROM reports r
        JOIN accounts reporter ON reporter.id = r.account_id
        JOIN accounts target ON target.id = r.target_account_id
        LEFT JOIN accounts action_taker ON action_taker.id = r.action_taken_by_account_id
        LEFT JOIN accounts assigned ON assigned.id = r.assigned_account_id
        ORDER BY r.created_at DESC
        LIMIT 100
    """
    try:
        cur.execute(query)
        rows = cur.fetchall()
        if not rows:
            return None

        reports = []
        for row in rows:
            (
                id,
                status_ids,
                comment,
                created_at,
                updated_at,
                account_id,
                action_taken_by_account_id,
                target_account_id,
                assigned_account_id,
                uri,
                forwarded,
                category,
                action_taken_at,
                rule_ids,
                application_id,
                reporter_username,
                reporter_display_name,
                target_username,
                target_display_name,
                action_taken_by_username,
                assigned_username,
            ) = row
            reports.append(
                {
                    "id": id,
                    "status_ids": status_ids,
                    "comment": comment,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "account_id": account_id,
                    "action_taken_by_account_id": action_taken_by_account_id,
                    "target_account_id": target_account_id,
                    "assigned_account_id": assigned_account_id,
                    "uri": uri,
                    "forwarded": forwarded,
                    "category": category,
                    "action_taken_at": action_taken_at,
                    "rule_ids": rule_ids,
                    "application_id": application_id,
                    "reporter_username": reporter_username,
                    "reporter_display_name": reporter_display_name,
                    "target_username": target_username,
                    "target_display_name": target_display_name,
                    "action_taken_by_username": action_taken_by_username,
                    "assigned_username": assigned_username,
                }
            )
        return reports
    except Exception as e:
        logger.error(f"Error fetching reports info: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_mentions_by_status_id(status_id: int) -> list[dict] | None:
    """
    Get all mentioned users for a specific toot by status_id.

    TABLE: mentions, accounts
    Args:
        status_id: The ID of the status to retrieve mentions for

    Returns:
        List of mention dictionaries with mentioned user information or None if error/not found
        e.g.:
        [
            {
                "mention_id": 123,
                "status_id": 115423439308602944,
                "account_id": 456,
                "created_at": "2025-10-23 12:00:00",
                "updated_at": "2025-10-23 12:00:00",
                "username": "mentioned_user",
                "display_name": "Mentioned User",
                "domain": null,
                "uri": "https://example.com/users/mentioned_user",
                "url": "https://example.com/@mentioned_user"
            }
        ]
    """
    conn, cur = connect_to_postgres()
    if conn is None or cur is None:
        return None

    query = """
        SELECT
            m.id,
            m.status_id,
            m.account_id,
            m.created_at,
            m.updated_at,
            a.username,
            a.display_name,
            a.domain,
            a.uri,
            a.url
        FROM mentions m
        JOIN accounts a ON m.account_id = a.id
        WHERE m.status_id = %s
        ORDER BY m.created_at ASC
    """
    try:
        cur.execute(query, (status_id,))
        rows = cur.fetchall()
        if not rows:
            logger.info(f"No mentions found for status ID {status_id}")
            return None

        mentions = []
        for row in rows:
            (
                mention_id,
                status_id,
                account_id,
                created_at,
                updated_at,
                username,
                display_name,
                domain,
                uri,
                url,
            ) = row
            mentions.append(
                {
                    "mention_id": mention_id,
                    "status_id": status_id,
                    "account_id": account_id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "username": username,
                    "display_name": display_name,
                    "domain": domain,
                    "uri": uri,
                    "url": url,
                }
            )

        logger.info(f"Found {len(mentions)} mention(s) for status ID {status_id}")
        return mentions
    except Exception as e:
        logger.error(f"Error fetching mentions for status {status_id}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# ================================================
# Helper functions
# ================================================


def parse_dt(dt: str | int | float | datetime | None, tz: str = "Europe/London") -> datetime | None:
    """
    Parse datetime from DB field or Unix timestamp, return naive local datetime.

    Args:
        dt: datetime string or Unix timestamp
        tz: timezone string, default is "Europe/London" (GMT+0)

    Returns:
        datetime object
        e.g.:
            dt = 1761289200-> 2025-10-24 15:00:00
    """

    local_tz = pytz.timezone(tz)

    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=None)  # remove timezone info
    if isinstance(dt, (int, float)):  # Unix timestamp
        return datetime.fromtimestamp(dt, local_tz).replace(tzinfo=None)
    if isinstance(dt, str) and dt.isdigit():  # string format timestamp
        return datetime.fromtimestamp(int(dt), local_tz).replace(tzinfo=None)

    try:
        return datetime.strptime(dt, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return datetime.fromisoformat(dt).replace(tzinfo=None)


def get_toot_images_path(media_id: int, file_name: str) -> str:
    """
    get local media file path in Mastodon container by media id and file name.

    Args:
        media_id: Media ID
        file_name: File name

    Returns:
        Local media file path

    e.g.:
      id = 115400054279678081
      -> MEDIA_ROOT/media_attachments/files/115/400/054/279/678/081/original/<file_name>
    """
    id_str = str(media_id)
    # 3 number per folder
    parts = [id_str[i : i + 3] for i in range(0, len(id_str), 3)]
    return os.path.join(MEDIA_ROOT, "media_attachments", "files", *parts, "original", file_name)


def get_header_path(account_id: int, file_name: str) -> str:
    """
    get local header file path by account id and file name.

    Args:
        account_id: Account ID
        file_name: File name

    Returns:
        Local header file path

    e.g.:
      account_id = 115400054279678081
      -> /MEDIA_ROOT/accounts/headers/115/400/054/279/678/081/original/<file_name>
    """
    id_str = str(account_id)
    # 3 numbers per folder
    parts = [id_str[i : i + 3] for i in range(0, len(id_str), 3)]
    return os.path.join(MEDIA_ROOT, "accounts", "headers", *parts, "original", file_name)


def get_device_file_path(controller: AndroidController, image_name: str) -> str:
    """
    Find image file on device and return local path by image name.

    Args:
        controller: AndroidController instance
        image_name: Name of the image to find

    Returns:
        Device path to the image or empty string if not found
    """
    try:
        # First, try to find the image using MediaStore content provider
        query_cmd = f"adb -s {controller.device} shell \"content query --uri content://media/external/images/media --projection _display_name:_data 2>&1 | grep -i '{image_name}'\""
        result = execute_adb(query_cmd, output=False)

        if result.success and "_data=" in result.output:
            # Extract path from: Row: X _display_name=tiger.jpg, _data=/storage/0000-0000/Pictures/tiger.jpg
            match = re.search(r"_data=([^\s,]+)", result.output)
            if match:
                device_path = match.group(1)
                logger.info(f"Found image in MediaStore: {device_path}")
                return device_path

        # Fallback: Try common gallery paths
        logger.info("MediaStore query failed, trying common paths...")
        possible_paths = [
            f"/sdcard/DCIM/Camera/{image_name}",
            f"/sdcard/Pictures/{image_name}",
            f"/sdcard/Download/{image_name}",
            f"/storage/emulated/0/DCIM/Camera/{image_name}",
            f"/storage/emulated/0/Pictures/{image_name}",
            f"/storage/emulated/0/Download/{image_name}",
        ]

        for path in possible_paths:
            # Check if file exists on device
            check_cmd = f"adb -s {controller.device} shell test -f {path} && echo 'exists'"
            result = execute_adb(check_cmd, output=False)
            if result.success and "exists" in result.output:
                logger.info(f"Found image at: {path}")
                return path

        logger.warning(f"Image '{image_name}' not found on device")
        return ""

    except Exception as e:
        logger.error(f"Error finding image on device: {e}")
        return ""


def save_file_to_local(controller: AndroidController, remote_path: str, local_path: str) -> bool:
    """
    Save file from device to local path.

    Args:
        controller: AndroidController instance
        remote_path: Path to file on device
        local_path: Path to save file to
    """
    try:
        controller.pull_file(remote_path, local_path)
        return True
    except Exception as e:
        logger.error(f"Error saving file to local: {e}")
        return False


def compute_md5(file_path: str) -> str:
    """
    Compute MD5 hash from file path.

    Args:
        file_path: Path to file to compute hash for

    Returns:
        MD5 hash string or empty string if failed
    """
    try:
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        logger.error(f"Error computing MD5: {e}")
        return ""


def compute_phash(file_path: str) -> int:
    """
    Compute perceptual hash from file path.

    Args:
        file_path: Path to file to compute hash for

    Returns:
        Perceptual hash string or empty string if failed
    """
    try:
        with Image.open(file_path) as img:
            phash = imagehash.average_hash(img)
            return phash
    except Exception as e:
        logger.error(f"Error computing perceptual hash: {e}")
        return ""


def phone_number_strip(phone_number: str) -> str:
    """
    Strip phone number to remove + and spaces.

    Args:
        phone_number: Phone number to strip

    Returns:
        Stripped phone number

    e.g.:
      phone_number = "+1 427 778 3563"
      -> "14277783563"
    """
    return re.sub(r"[^0-9]", "", phone_number)
