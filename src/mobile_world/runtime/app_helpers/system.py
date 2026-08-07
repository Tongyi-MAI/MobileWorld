import datetime
import os
import re

from loguru import logger

from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.device import is_redroid
from mobile_world.runtime.utils.helpers import execute_adb, execute_root_sql


def set_flight_mode(controller: AndroidController, is_open: bool):
    if is_open:
        result = execute_adb(
            f"adb -s {controller.device} shell cmd connectivity airplane-mode enable"
        )
    else:
        result = execute_adb(
            f"adb -s {controller.device} shell cmd connectivity airplane-mode disable"
        )
    return result


def get_flight_mode_status(controller: AndroidController):
    result = execute_adb(f"adb -s {controller.device} shell settings get global airplane_mode_on")
    return result.success and result.output.strip() == "1"


def get_font_scale(controller: AndroidController) -> float:
    """Get current font scale setting."""
    result = execute_adb(f"adb -s {controller.device} shell settings get system font_scale")
    if result.success and result.output.strip():
        try:
            return float(result.output.strip())
        except ValueError:
            logger.warning(f"Invalid font_scale value: {result.output}")
            return 1.0  # Default value
    return 1.0


def get_display_density(controller: AndroidController) -> int:
    """Get current display density (DPI) setting."""
    result = execute_adb(f"adb -s {controller.device} shell wm density")
    if result.success and result.output.strip():
        # Output format: "Physical density: 420" or "Override density: 280"
        # Check Override density first (set when user changes Display size in settings)
        match = re.search(r"Override density:\s*(\d+)", result.output)
        if match:
            return int(match.group(1))
        # Fall back to physical density if no override
        match = re.search(r"Physical density:\s*(\d+)", result.output)
        if match:
            return int(match.group(1))
    return 420  # Default density for common devices


def get_physical_density(controller: AndroidController) -> int:
    """Physical (base) display density, ignoring any user Display-size override."""
    result = execute_adb(f"adb -s {controller.device} shell wm density")
    if result.success and result.output.strip():
        match = re.search(r"Physical density:\s*(\d+)", result.output)
        if match:
            return int(match.group(1))
    return 0


def get_min_screen_dimension(controller: AndroidController) -> int:
    """Smallest physical screen dimension in px (from ``wm size``)."""
    result = execute_adb(f"adb -s {controller.device} shell wm size")
    if result.success and result.output.strip():
        match = re.search(r"Physical size:\s*(\d+)x(\d+)", result.output)
        if match:
            return min(int(match.group(1)), int(match.group(2)))
    return 0


def get_display_size_density_bounds(controller: AndroidController) -> tuple[int, int]:
    """Return ``(min_density, max_density)`` the system "Display size" control offers
    on this device, derived from the device's physical density and screen size — so it
    is resolution-independent and needs no hardcoded DPI.

    Mirrors AOSP ``DisplayDensityUtils``: the offered densities are scales of the
    *physical* density from 0.85x (smallest) up to min(1.5x, the largest density that
    keeps the smallest screen edge >= 320dp). Returns ``(0, 0)`` if the device can't be
    queried. Callers should compare with a small tolerance to absorb Android's integer
    rounding (the slider steps are ~9% of the physical density apart, far larger than
    that rounding, so any tolerance up to a few DPI is unambiguous).
    """
    physical = get_physical_density(controller)
    min_dim = get_min_screen_dimension(controller)
    if physical <= 0 or min_dim <= 0:
        return 0, 0
    min_density = round(physical * 0.85)
    cap = 160 * min_dim // 320  # largest density keeping the smallest edge >= 320dp
    max_density = min(round(physical * 1.5), cap)
    return min_density, max_density


def get_screen_brightness(controller: AndroidController) -> int:
    """Get current screen brightness setting (0-255)."""
    result = execute_adb(f"adb -s {controller.device} shell settings get system screen_brightness")
    if result.success and result.output.strip():
        try:
            return int(result.output.strip())
        except ValueError:
            logger.warning(f"Invalid screen_brightness value: {result.output}")
            return 128  # Default middle value
    return 128


def enable_auto_time_sync(controller: AndroidController) -> bool:
    logger.info("Enabling automatic time synchronization...")
    result_auto_time = execute_adb(
        f"adb -s {controller.device} shell settings put global auto_time 1"
    )
    result_auto_timezone = execute_adb(
        f"adb -s {controller.device} shell settings put global auto_time_zone 1"
    )

    time_sync_success = time_sync_to_now()
    if result_auto_time.success and result_auto_timezone.success and time_sync_success:
        logger.info("✓ Automatic time synchronization enabled successfully")
        return True
    else:
        logger.warning(
            f"Failed to enable time sync: auto_time={result_auto_time.success}, "
            f"auto_timezone={result_auto_timezone.success}, time_sync={time_sync_success}"
        )
        return False


def time_sync_to_now() -> bool:
    # redroid has no per-guest RTC; the libtimeshift shim drives the device clock. Re-sync
    # the guest to the active timeshift offset (base.set_task_timeframe picks the frame:
    # real time for time-sync tasks, else the benchmark date). No host clock change.
    if is_redroid():
        from mobile_world.runtime.utils import redroid_device

        redroid_device.reapply_timeshift(os.environ.get("ANDROID_DEVICE", "emulator-5554"))
        redroid_device.set_task_timeframe(
            os.environ.get("ANDROID_DEVICE", "emulator-5554"), date_str="", realtime=True
        )
        redroid_device.restart_zygote(os.environ.get("ANDROID_DEVICE", "emulator-5554"))
        return True
    result = execute_adb("adb shell su root date $(date +%m%d%H%M%Y.%S)")
    return result.success


def real_now() -> datetime.datetime:
    """Real wall-clock now, bypassing the timeshift shim this server process runs under.

    On redroid the MW server is LD_PRELOAD'd with the time-shift shim, so plain
    ``datetime.now()`` here returns the device's *current* frame (often the 2025 benchmark
    date). Task dates that must line up with the device after ``time_sync_to_now()`` have to
    be derived from this instead. On non-redroid there is no shim, so it equals ``now()``.
    """
    if is_redroid():
        from mobile_world.runtime.utils import redroid_device

        return datetime.datetime.fromtimestamp(redroid_device._real_now_epoch())
    return datetime.datetime.now()


def reset_chrome(controller: AndroidController):
    if is_redroid(controller.device):
        return
    pkg = "com.android.chrome"
    # Stop and clear data to ensure a predictable clean start
    execute_adb(f"adb -s {controller.device} shell am force-stop {pkg}")
    execute_adb(f"adb -s {controller.device} shell pm clear {pkg}")


def reset_maps(controller: AndroidController):
    if is_redroid(controller.device):
        # No Google Maps app on redroid; map flows degrade to web. Nothing to reset.
        return
    pkg = "com.google.android.apps.maps"
    execute_adb(f"adb -s {controller.device} shell am force-stop {pkg}")
    execute_adb(f"adb -s {controller.device} shell pm clear {pkg}")


def extract_sms_body(line: str) -> str | None:
    """Extract SMS body from an ADB 'content query' output line.

    The body field is the last column in the output, so we take everything
    after 'body=' to the end of line. This avoids splitting on commas that
    are part of the message text.
    """
    if "body=" not in line:
        return None
    value = line.split("body=", 1)[-1].strip()
    if value and value != "NULL":
        return value
    return None


def extract_sms_address(line: str) -> str | None:
    """Extract the SMS `address` (recipient) field from a content-query row.

    The value may contain spaces (e.g. '345 6784 3456'), so capture everything up
    to the next ', <key>=' field rather than stopping at the first space.
    """
    match = re.search(r"address=(.*?),\s+\w+=", line)
    if not match:
        return None
    value = match.group(1).strip()
    if value and value != "NULL":
        return value
    return None


def _redroid_phone_match(line: str, phone_number: str) -> bool:
    """Digits-only, country-code-tolerant phone match for the redroid backend.

    Old Google Messages normalized typed numbers to digits in the SMS provider, so
    the emulator verifier's literal match worked. Fossify (redroid) stores the
    address verbatim ('345 6784 3456'), so compare digits-only with a suffix rule.
    """
    address = extract_sms_address(line)
    if address is None:
        return False
    want = "".join(filter(str.isdigit, phone_number))
    have = "".join(filter(str.isdigit, address))
    if not want or not have:
        return False
    return want == have or have.endswith(want) or want.endswith(have)


def check_sms_via_adb(
    controller: AndroidController, phone_number: str, content: str | list[str]
) -> bool:
    """
    Check if an SMS with specific content was sent to a phone number via ADB.

    Args:
        controller: AndroidController instance
        phone_number: Phone number to check (e.g., "15551234567")
        content: Message content to verify (required)

    Returns:
        bool: True if matching SMS is found, False otherwise
    """
    try:
        # Query SMS database using content provider
        # Filter by sent messages (type=2)
        query_cmd = f"adb -s {controller.device} shell content query --uri content://sms/sent"
        result = execute_adb(query_cmd, output=False, root_required=True)
        if not result.success or not result.output:
            logger.warning(f"Failed to query SMS database: {result.error}")
            return False

        # Parse the result line by line
        # Each line represents a row with format: Row: X address=Y, body=Z, ...
        lines = result.output.strip().replace("", "", 5).split("\nRow")
        for line in lines:
            if not line.strip():
                continue

            # Check if this line contains the expected content
            content_match = False
            phone_match = False

            body_text_lower = ""
            if "body=" in line:
                body_text = extract_sms_body(line)
                if body_text:
                    body_text_lower = body_text.lower()

            if not isinstance(content, list):
                content = [str(content)]

            content_match = all(
                str(content_item).lower() in body_text_lower
                or str(content_item).lower() in line.lower()
                for content_item in content
            )

            if f"address={phone_number}" in line or phone_number in line:
                phone_match = True
            elif is_redroid(controller.device) and _redroid_phone_match(line, phone_number):
                # redroid only: Fossify stores the address verbatim (spaces/dashes/+),
                # so fall back to a digits-only suffix match. Emulator path unchanged.
                phone_match = True

            if content_match and phone_match:
                logger.info(f"Found matching SMS: phone={phone_number}, content found")
                return True

        logger.info(f"No matching SMS found for phone={phone_number}")
        return False

    except Exception as e:
        logger.error(f"Error checking SMS via ADB: {e}")
        return False


def get_sms_list_via_adb(controller: AndroidController) -> list[dict]:
    result = execute_adb(
        f"adb -s {controller.device} shell content query --uri content://sms/inbox"
    )
    if result.success:
        return result.output.strip().split("\n")
    return []


def get_file_list(path: str) -> list[str]:
    result = execute_adb(f"adb shell ls {path}")
    if result.success:
        return result.output.strip().split("\n")
    return []


def check_alarm_via_adb(controller: AndroidController, hour: int, minute: int) -> dict:
    # Google DeskClock on both emulator and redroid; its schema has blackout_end.
    clock_pkg = "com.google.android.deskclock"
    db_path = f"/data/user_de/0/{clock_pkg}/databases/alarms.db"
    sql_query = (
        f"SELECT hour, minutes, enabled, daysofweek, vibrate, ringtone, label, blackout_end "
        f"FROM alarm_templates WHERE hour={hour} AND minutes={minute};"
    )

    try:
        result = execute_root_sql(db_path, sql_query, device=controller.device)

        if not result:
            logger.info(f"No alarm found or query failed for {hour}:{minute:02d}")
            return None

        parts = result.strip().split("|")

        if len(parts) < 6:
            logger.warning(f"Unexpected query result format: {result}")
            return None

        alarm_info = {
            "hour": int(parts[0]),
            "minutes": int(parts[1]),
            "enabled": bool(int(parts[2])),
            "daysofweek": int(parts[3]) if parts[3] else 0,
            "vibrate": bool(int(parts[4])) if parts[4] else False,
            "ringtone": parts[5] if len(parts) > 5 else "",
            "label": parts[6] if len(parts) > 6 else "",
            "blackout_end": parts[7] if len(parts) > 7 else "",
        }

        logger.info(f"Found alarm: {alarm_info}")
        return alarm_info

    except Exception as e:
        logger.error(f"Error querying alarm via adb: {e}")
        return None


def get_contacts_via_adb(
    controller: AndroidController, name: str | None = None, phone_number: str | None = None
) -> list[dict] | None:
    """
    Get contacts information via ADB using content provider.

    Args:
        controller: AndroidController instance
        name: Optional contact name to search for (partial match)
        phone_number: Optional phone number to search for

    Returns:
        List of contact dictionaries or None if error/not found
        Each dictionary contains:
        {
            "contact_id": "123",
            "display_name": "John Doe",
            "phones": [  # List of phone dictionaries with labels
                {"number": "+1234567890", "label": "MOBILE"},
                {"number": "+0987654321", "label": "WORK"}
            ],
            "emails": [  # List of email dictionaries with labels
                {"address": "john@example.com", "label": "HOME"},
                {"address": "john@work.com", "label": "WORK"}
            ],
            "addresses": [  # List of address dictionaries
                {
                    "full_address": "123 Main St City State 12345 Country",
                    "street": "123 Main St",
                    "city": "City",
                    "state": "State",
                    "postal_code": "12345",
                    "country": "Country"
                }
            ],
            "organization": "Company Name"
        }
    """
    try:
        # Step 1: Query all contact data including phones, emails, addresses, and organizations
        # Query phones with type and label information
        phones_query_cmd = (
            f"adb -s {controller.device} shell content query --uri "
            f'"content://com.android.contacts/data" --projection "contact_id:mimetype:data1:data2:data3"'
        )
        phones_result = execute_adb(phones_query_cmd, output=False, root_required=False)

        # Query emails with type and label information
        emails_query_cmd = (
            f"adb -s {controller.device} shell content query --uri "
            f'"content://com.android.contacts/data" --projection "contact_id:mimetype:data1:data2:data3"'
        )
        emails_result = execute_adb(emails_query_cmd, output=False, root_required=False)

        # Query addresses
        addresses_query_cmd = (
            f"adb -s {controller.device} shell content query --uri "
            f'"content://com.android.contacts/data" --projection "contact_id:mimetype:data1:data4:data7:data8:data9:data10"'
        )
        addresses_result = execute_adb(addresses_query_cmd, output=False, root_required=False)

        # Query organization (company) information
        org_query_cmd = (
            f"adb -s {controller.device} shell content query --uri "
            f'"content://com.android.contacts/data" --projection "contact_id:mimetype:data1"'
        )
        org_result = execute_adb(org_query_cmd, output=False, root_required=False)

        # Query contact names
        names_query_cmd = (
            f"adb -s {controller.device} shell content query --uri "
            f'"content://com.android.contacts/contacts" --projection "_id:display_name"'
        )
        names_result = execute_adb(names_query_cmd, output=False, root_required=False)

        # Step 2: Build maps for all contact data
        phones_map: dict[str, list[dict]] = {}
        if phones_result.success and phones_result.output:
            for line in phones_result.output.strip().split("\n"):
                if not line.strip() or not line.startswith("Row:"):
                    continue
                if "phone_v2" in line or "vnd.android.cursor.item/phone_v2" in line:
                    contact_id_match = re.search(r"contact_id=([^,]+)", line)
                    if not contact_id_match:
                        continue
                    contact_id = contact_id_match.group(1).strip()

                    phone_match = re.search(r"data1=([^,]+)", line)
                    if not phone_match:
                        continue
                    phone_number_val = phone_match.group(1).strip()
                    if not phone_number_val or phone_number_val.upper() == "NULL":
                        continue

                    label_match = re.search(r"data3=([^,]+)", line)
                    label = ""
                    if label_match:
                        label_str = label_match.group(1).strip()
                        if label_str and label_str.upper() != "NULL":
                            label = label_str

                    if not label:
                        type_match = re.search(r"data2=([^,]+)", line)
                        if type_match:
                            type_str = type_match.group(1).strip()
                            if type_str and type_str.upper() != "NULL":
                                try:
                                    type_num = int(type_str)
                                    type_map = {1: "HOME", 2: "MOBILE", 3: "WORK", 7: "OTHER"}
                                    label = type_map.get(type_num, "")
                                except (ValueError, TypeError):
                                    pass

                    if contact_id not in phones_map:
                        phones_map[contact_id] = []
                    phones_map[contact_id].append({"number": phone_number_val, "label": label})

        emails_map: dict[str, list[dict]] = {}
        if emails_result.success and emails_result.output:
            for line in emails_result.output.strip().split("\n"):
                if not line.strip() or not line.startswith("Row:"):
                    continue
                if "email_v2" in line or "vnd.android.cursor.item/email_v2" in line:
                    contact_id_match = re.search(r"contact_id=([^,]+)", line)
                    if not contact_id_match:
                        continue
                    contact_id = contact_id_match.group(1).strip()

                    email_match = re.search(r"data1=([^,]+)", line)
                    if not email_match:
                        continue
                    email_val = email_match.group(1).strip()
                    if not email_val or email_val.upper() == "NULL":
                        continue

                    label_match = re.search(r"data3=([^,]+)", line)
                    label = ""
                    if label_match:
                        label_str = label_match.group(1).strip()
                        if label_str and label_str.upper() != "NULL":
                            label = label_str

                    if not label:
                        type_match = re.search(r"data2=([^,]+)", line)
                        if type_match:
                            type_str = type_match.group(1).strip()
                            if type_str and type_str.upper() != "NULL":
                                try:
                                    type_num = int(type_str)
                                    type_map = {1: "HOME", 2: "WORK", 3: "OTHER"}
                                    label = type_map.get(type_num, "")
                                except (ValueError, TypeError):
                                    pass

                    if contact_id not in emails_map:
                        emails_map[contact_id] = []
                    emails_map[contact_id].append({"address": email_val, "label": label})

        addresses_map: dict[str, list[dict]] = {}
        if addresses_result.success and addresses_result.output:
            for line in addresses_result.output.strip().split("\n"):
                if not line.strip() or not line.startswith("Row:"):
                    continue
                if (
                    "postal-address_v2" in line
                    or "vnd.android.cursor.item/postal-address_v2" in line
                ):
                    contact_id_match = re.search(r"contact_id=([^,]+)", line)
                    if contact_id_match:
                        contact_id = contact_id_match.group(1).strip()
                        addr: dict[str, str] = {}

                        match = re.search(r"data1=([^,]+)", line)
                        if match:
                            addr["full_address"] = match.group(1).strip()

                        match = re.search(r"data4=([^,]+)", line)
                        if match:
                            street = match.group(1).strip()
                            if street and street.upper() != "NULL":
                                addr["street"] = street

                        match = re.search(r"data7=([^,]+)", line)
                        if match:
                            city = match.group(1).strip()
                            if city and city.upper() != "NULL":
                                addr["city"] = city

                        match = re.search(r"data8=([^,]+)", line)
                        if match:
                            state = match.group(1).strip()
                            if state and state.upper() != "NULL":
                                addr["state"] = state

                        match = re.search(r"data9=([^,]+)", line)
                        if match:
                            postal = match.group(1).strip()
                            if postal and postal.upper() != "NULL":
                                addr["postal_code"] = postal

                        match = re.search(r"data10=([^,]+)", line)
                        if match:
                            country = match.group(1).strip()
                            if country and country.upper() != "NULL":
                                addr["country"] = country

                        if addr:
                            if contact_id not in addresses_map:
                                addresses_map[contact_id] = []
                            addresses_map[contact_id].append(addr)

        org_map: dict[str, str] = {}
        if org_result.success and org_result.output:
            for line in org_result.output.strip().split("\n"):
                if not line.strip() or not line.startswith("Row:"):
                    continue
                if "organization" in line or "vnd.android.cursor.item/organization" in line:
                    contact_id_match = re.search(r"contact_id=([^,]+)", line)
                    if contact_id_match:
                        contact_id = contact_id_match.group(1).strip()
                        org_match = re.search(r"data1=([^,]+)", line)
                        if org_match:
                            org_val = org_match.group(1).strip()
                            if org_val and org_val.upper() != "NULL":
                                org_map[contact_id] = org_val

        names_map: dict[str, str] = {}
        if names_result.success and names_result.output:
            for line in names_result.output.strip().split("\n"):
                if not line.strip() or not line.startswith("Row:"):
                    continue
                id_match = re.search(r"_id=([^,]+)", line)
                if id_match:
                    contact_id = id_match.group(1).strip()
                    name_match = re.search(r"display_name=([^,]+)", line)
                    if name_match:
                        display_name = name_match.group(1).strip()
                        if display_name and display_name.upper() != "NULL":
                            names_map[contact_id] = display_name

        # Step 3: Build contacts list from all collected data
        all_contact_ids = set()
        all_contact_ids.update(phones_map.keys())
        all_contact_ids.update(emails_map.keys())
        all_contact_ids.update(addresses_map.keys())
        all_contact_ids.update(org_map.keys())
        all_contact_ids.update(names_map.keys())

        contacts: list[dict] = []
        for contact_id in all_contact_ids:
            display_name = names_map.get(contact_id, "")
            if not display_name:
                continue

            if name and name.lower() not in display_name.lower():
                continue

            if phone_number:
                found_phone = False
                if contact_id in phones_map:
                    for phone_dict in phones_map[contact_id]:
                        phone = phone_dict.get("number", "")
                        if phone:
                            phone_clean = (
                                phone.replace("-", "")
                                .replace(" ", "")
                                .replace("(", "")
                                .replace(")", "")
                                .replace("+", "")
                            )
                            phone_number_clean = (
                                phone_number.replace("-", "")
                                .replace(" ", "")
                                .replace("(", "")
                                .replace(")", "")
                                .replace("+", "")
                            )
                            if phone_number_clean in phone_clean or phone_number in phone:
                                found_phone = True
                                break
                if not found_phone:
                    continue

            contact_data: dict[str, object] = {
                "contact_id": contact_id,
                "display_name": display_name,
            }

            if contact_id in phones_map:
                contact_data["phones"] = phones_map[contact_id]

            if contact_id in emails_map:
                contact_data["emails"] = emails_map[contact_id]

            if contact_id in addresses_map:
                contact_data["addresses"] = addresses_map[contact_id]

            if contact_id in org_map:
                contact_data["organization"] = org_map[contact_id]

            contacts.append(contact_data)

        if not contacts:
            if name or phone_number:
                logger.info(f"No contacts found matching name={name}, phone={phone_number}")
            else:
                logger.info("No contacts found in database")
            return []

        logger.info(f"Found {len(contacts)} contact(s) matching criteria")
        return contacts

    except Exception as e:
        logger.error(f"Error getting contacts via ADB: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return None


def check_contact_starred_via_adb(controller: AndroidController, phone_number: str) -> bool:
    """
    Check if a contact with the given phone number is marked as starred (favorite) via ADB.

    Args:
        controller: AndroidController instance
        phone_number: Phone number to check (e.g., "15551234567")

    Returns:
        bool: True if contact is starred, False otherwise
    """
    try:
        # Step 1: Find the contact_id for the given phone number
        # Query the phone numbers in contacts
        phone_query_cmd = (
            f"adb -s {controller.device} shell content query --uri "
            f'"content://com.android.contacts/data" --projection "contact_id:data1:mimetype"'
        )
        phone_result = execute_adb(phone_query_cmd, output=False, root_required=False)

        if not phone_result.success or not phone_result.output:
            logger.warning(f"Failed to query phone numbers: {phone_result.error}")
            return False

        if is_redroid(controller.device):
            # redroid only: the golden /data carries junk/duplicate contacts. Match
            # robustly — skip junk/short numbers (a 'data1=-' row normalizes to '' and
            # str.endswith('') is always True, which would match every input), collect
            # ALL matching contacts, and treat the number as starred if ANY of them is.
            normalized_input = "".join(filter(str.isdigit, phone_number))
            matched_contact_ids: list[str] = []
            for line in phone_result.output.strip().split("\n"):
                if not line.strip() or not line.startswith("Row:"):
                    continue
                if "phone_v2" not in line and "vnd.android.cursor.item/phone_v2" not in line:
                    continue
                phone_match = re.search(r"data1=([^,]+)", line)
                if not phone_match:
                    continue
                normalized_db = "".join(filter(str.isdigit, phone_match.group(1).strip()))
                if not normalized_input or len(normalized_db) < 7:
                    continue
                if (
                    normalized_input == normalized_db
                    or normalized_db.endswith(normalized_input)
                    or normalized_input.endswith(normalized_db)
                ):
                    contact_id_match = re.search(r"contact_id=([^,]+)", line)
                    if contact_id_match:
                        cid = contact_id_match.group(1).strip()
                        if cid not in matched_contact_ids:
                            matched_contact_ids.append(cid)

            if not matched_contact_ids:
                logger.warning(f"No contact found with phone number: {phone_number}")
                return False
            logger.info(f"Found contact_id(s)={matched_contact_ids} for phone={phone_number}")

            for contact_id in matched_contact_ids:
                contact_query_cmd = (
                    f"adb -s {controller.device} shell content query --uri "
                    f'"content://com.android.contacts/contacts" --projection "_id:starred" '
                    f'--where "_id={contact_id}"'
                )
                contact_result = execute_adb(contact_query_cmd, output=False, root_required=False)
                if not contact_result.success or not contact_result.output:
                    continue
                for line in contact_result.output.strip().split("\n"):
                    if not line.strip() or not line.startswith("Row:"):
                        continue
                    starred_match = re.search(r"starred=([^,]+)", line)
                    if starred_match and starred_match.group(1).strip() == "1":
                        logger.info(f"Contact {contact_id} is starred (phone={phone_number})")
                        return True

            logger.info(f"No starred contact for phone={phone_number} among {matched_contact_ids}")
            return False

        # ---- emulator path (unchanged) ----
        # Find the contact_id that matches the phone number
        contact_id = None
        for line in phone_result.output.strip().split("\n"):
            if not line.strip() or not line.startswith("Row:"):
                continue

            # Check if this is a phone entry
            if "phone_v2" not in line and "vnd.android.cursor.item/phone_v2" not in line:
                continue

            # Extract phone number from data1
            phone_match = re.search(r"data1=([^,]+)", line)
            if not phone_match:
                continue

            phone_in_db = phone_match.group(1).strip()
            # Normalize phone numbers for comparison (remove spaces, dashes, etc.)
            normalized_input = "".join(filter(str.isdigit, phone_number))
            normalized_db = "".join(filter(str.isdigit, phone_in_db))

            if (
                normalized_input == normalized_db
                or normalized_db.endswith(normalized_input)
                or normalized_input.endswith(normalized_db)
            ):
                # Found matching phone number, get contact_id
                contact_id_match = re.search(r"contact_id=([^,]+)", line)
                if contact_id_match:
                    contact_id = contact_id_match.group(1).strip()
                    logger.info(f"Found contact_id={contact_id} for phone={phone_number}")
                    break

        if not contact_id:
            logger.warning(f"No contact found with phone number: {phone_number}")
            return False

        # Step 2: Query the contacts table to check starred field
        contact_query_cmd = (
            f"adb -s {controller.device} shell content query --uri "
            f'"content://com.android.contacts/contacts" --projection "_id:starred" '
            f'--where "_id={contact_id}"'
        )
        contact_result = execute_adb(contact_query_cmd, output=False, root_required=False)

        if not contact_result.success or not contact_result.output:
            logger.warning(f"Failed to query contact starred status: {contact_result.error}")
            return False

        # Parse the starred field
        for line in contact_result.output.strip().split("\n"):
            if not line.strip() or not line.startswith("Row:"):
                continue

            # Look for starred field
            starred_match = re.search(r"starred=([^,]+)", line)
            if starred_match:
                starred_value = starred_match.group(1).strip()
                is_starred = starred_value == "1"
                logger.info(
                    f"Contact {contact_id} starred status: {is_starred} (value={starred_value})"
                )
                return is_starred

        logger.warning(f"Could not find starred field for contact_id={contact_id}")
        return False

    except Exception as e:
        logger.error(f"Error checking contact starred status via ADB: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


def check_contact_via_adb(
    controller: AndroidController, name: str, phone: str, company: str
) -> bool:
    """
    Check if a contact with specific name, phone and company exists via ADB.

    Args:
        controller: AndroidController instance
        name: Contact name to check (e.g., "Kevin Zhang")
        phone: Phone number to verify (e.g., "+86 571 85022088")
        company: Company name (should contain "alibaba")

    Returns:
        bool: True if matching contact is found with correct info, False otherwise
    """
    try:
        # Query contacts database using content provider
        # We need to check: display_name, phone number, and company (organization)
        query_cmd = f"adb -s {controller.device} shell content query --uri content://com.android.contacts/data"
        result = execute_adb(query_cmd, output=False, root_required=True)
        if not result.success or not result.output:
            logger.warning(f"Failed to query contacts database: {result.error}")
            return False

        # Parse the result line by line
        lines = result.output.strip().split("\n")

        # Track contact by raw_contact_id
        contact_info = {}  # raw_contact_id -> {name, phone, company}

        for line in lines:
            if not line.strip() or "Row:" not in line:
                continue

            # Parse fields from the line
            fields = {}
            # Split by comma, but be careful with values that might contain commas
            parts = line.split(", ")
            for part in parts:
                if "=" in part:
                    key_value = part.split("=", 1)
                    if len(key_value) == 2:
                        key = key_value[0].strip()
                        value = key_value[1].strip()
                        fields[key] = value

            # Get raw_contact_id
            raw_contact_id = fields.get("raw_contact_id")
            if not raw_contact_id:
                continue

            # Initialize contact_info for this raw_contact_id if not exists
            if raw_contact_id not in contact_info:
                contact_info[raw_contact_id] = {"name": None, "phone": None, "company": None}

            # Get mimetype to determine what kind of data this is
            mimetype = fields.get("mimetype", "")
            data1 = fields.get("data1", "")

            # Check for name (mimetype: vnd.android.cursor.item/name)
            if "name" in mimetype.lower():
                contact_info[raw_contact_id]["name"] = data1

            # Check for phone (mimetype: vnd.android.cursor.item/phone_v2)
            elif "phone" in mimetype.lower():
                contact_info[raw_contact_id]["phone"] = data1

            # Check for organization/company (mimetype: vnd.android.cursor.item/organization)
            elif "organization" in mimetype.lower():
                contact_info[raw_contact_id]["company"] = data1

        # Now check if any contact matches our criteria
        name_lower = name.lower().strip()
        phone_normalized = phone.replace(" ", "").replace("-", "").replace("+", "")
        company_lower = company.lower().strip()

        for raw_id, info in contact_info.items():
            contact_name = (info.get("name") or "").lower().strip()
            contact_phone = (
                (info.get("phone") or "").replace(" ", "").replace("-", "").replace("+", "")
            )
            contact_company = (info.get("company") or "").lower().strip()

            # Check if all three fields match
            name_match = name_lower in contact_name or contact_name in name_lower
            phone_match = phone_normalized in contact_phone
            company_match = company_lower in contact_company

            logger.info(
                f"Checking contact {raw_id}: name={info.get('name')}, phone={info.get('phone')}, company={info.get('company')}"
            )
            logger.info(f"Matches: name={name_match}, phone={phone_match}, company={company_match}")

            if name_match and phone_match and company_match:
                logger.info(f"Found matching contact: {info}")
                return True

        logger.warning(f"No matching contact found for {name}, {phone}, {company}")
        return False

    except Exception as e:
        logger.error(f"Error querying contacts via adb: {e}")
        return False


def get_device_datetime() -> datetime.datetime:
    """Get current date and time from Android device in UTC."""
    # Use epoch seconds (timezone-independent) and parse as UTC. The previous
    # implementation parsed a "YYYY-MM-DD HH:MM:SS" string with the date-only
    # format "%Y-%m-%d", which always raised and silently fell back to now().
    result = execute_adb("shell date -u +%s")
    if result.success:
        try:
            return datetime.datetime.fromtimestamp(int(result.output.strip()), datetime.UTC)
        except (ValueError, TypeError):
            pass
    return datetime.datetime.now(datetime.UTC)
