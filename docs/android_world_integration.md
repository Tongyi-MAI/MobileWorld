# AndroidWorld Integration

This document describes how [AndroidWorld](https://github.com/google-research/android_world) is integrated into MobileWorld, and the key differences from the official AndroidWorld environment.

## Overview

AndroidWorld is added as a git submodule at `resources/android_world/` and exposed as an alternative evaluation suite via `--suite-family android_world`. Both suites share the same emulator and Docker container — switching between them swaps snapshots without restarting the emulator.

## Emulator Differences

| | Official AndroidWorld | MobileWorld |
|---|---|---|
| Device | Pixel 6 | Pixel 8 |
| API Level | 33 | 34 |
| GPU | Host GPU / standard | swiftshader_indirect |
| Screen | 2400 x 1080 | 2400 x 1080 (same) |

Both suites use the same AVD (`Pixel_8_API_34_x86_64`). This avoids doubling the container image size by installing a second emulator. The API 33 vs 34 difference is minor for most tasks, but causes a few compatibility issues documented below.

## App Installation

Official AndroidWorld runs `setup.setup_apps(env)` which installs APKs and performs UI-based onboarding. We replicate this with a custom script (`docker/setup_aw_apps.py`) that handles emulator differences:

**All 24 apps install successfully.** Known issues addressed:

| App | Issue | Workaround |
|---|---|---|
| **Clipper** | Original APK targets SDK 0, rejected by API 34 (`INSTALL_FAILED_DEPRECATED_SDK_VERSION`) | Rebuilt from [source](https://github.com/majido/clipper) targeting SDK 34; patched APK shipped at `docker/apks/clipper.apk` |
| **Markor** | Default notebook directory not created on Pixel 8 | Setup script pre-creates `/Documents/Markor/` with default files |
| **Chrome** | Onboarding text differs on API 34 ("Accept & continue" not found) | Permissions granted via ADB fallback; onboarding skipped |
| **Contacts** | "Don't allow" button text differs | Skipped gracefully |

The setup script also grants permissions via `appops` as fallback when UI-based onboarding fails, and saves per-app data snapshots for task evaluation.

### Setup Flow

```
docker exec <container> /app/docker/setup_android_world_apps.sh
```

1. Loads MobileWorld's `init_state` snapshot as base
2. Installs all APKs (downloaded from Google Cloud Storage)
3. Runs per-app onboarding with error handling
4. Saves per-app data snapshots to `/data/data/android_world/snapshots/`
5. Saves emulator snapshot as `aw_init_state`
6. Commit container: `docker commit <container> mobile_world:aw-apps`

## Task Eval Patches

Patches to AndroidWorld's task code are stored in `docker/patches/` and applied during Docker build (since the submodule points to Google's upstream repo and can't be modified).

### BrowserDraw Canvas Fix (`docker/patches/aw_browser.py`)

Chrome's Canvas 2D `stroke()` API silently fails to rasterize on the swiftshader GPU backend. The fix replaces path-based drawing (`moveTo/lineTo/stroke`) with interpolated `fillRect()` calls. This affects only `BrowserDraw` — `BrowserMaze` and `BrowserMultiply` use DOM elements, not Canvas.

Applied in `Dockerfile.update`:
```dockerfile
COPY docker/patches/aw_browser.py /app/service/resources/android_world/android_world/task_evals/single/browser.py
```

The patch also adds a **logcat-based success check** as fallback. UIAutomator cannot see WebView content inside Chrome, so the patched HTML emits `console.log('MOBILEWORLD_TASK_SUCCESS')` on completion and `is_successful()` checks Chrome's logcat output via `adb shell logcat -d -s chromium:I` when the UIAutomator check fails. This fixes `BrowserDraw`, `BrowserMaze`, and `BrowserMultiply`.

### AudioRecorder Fix (`docker/patches/aw_audio_recorder.py`)

The upstream evaluator appends `.m4a` to `file_name`, but `generate_random_params()` already produces filenames with the `.m4a` extension (e.g., `"2023_05_21_debate.m4a"`). This causes the evaluator to look for `"2023_05_21_debate.m4a.m4a"`. The patch checks if the extension is already present before appending.

### Clipper APK Rebuild (`docker/apks/clipper.apk`)

The original Clipper app ([majido/clipper](https://github.com/majido/clipper)) targets SDK 0, which is rejected by API 34 (`INSTALL_FAILED_DEPRECATED_SDK_VERSION`). The Clipper submodule is at `resources/clipper/` and patches in `docker/patches/clipper_*.{java,xml}` modernize it for SDK 34:

- `clipper_AndroidManifest.xml`: sets `targetSdkVersion="24"` (>=23 to install on API 34, <26 to avoid implicit broadcast restrictions), adds `android:exported` attributes
- `clipper_ClipperReceiver.java`: uses `android.content.ClipboardManager` + `ClipData` (replaces deprecated `android.text.ClipboardManager`)
- `clipper_Main.java`: removes resource dependencies (`R.layout.main`, `ClipboardService`)

Build with `docker/build_clipper.sh` (requires Android SDK with `build-tools;34.0.0` and `platforms;android-34`). The pre-built APK is shipped at `docker/apks/clipper.apk` and installed during setup instead of downloading from GCS. This fixes 3 clipboard tasks: `SystemCopyToClipboard`, `SimpleSmsSendClipboardContent`, `MarkorCreateNoteFromClipboard`.

## Adapter Layer

AndroidWorld tasks expect an `env` object backed by `android_env` (protobuf-based ADB interface). MobileWorld uses raw ADB commands via `AndroidController`. The adapter layer bridges these:

```
AndroidWorld TaskEval
    -> EnvAdapter (env interface: execute_adb, get_state, pull_file, push_file)
        -> ControllerAdapter (protobuf translation: execute_adb_call, get_ui_elements)
            -> AndroidController (raw ADB commands)
```

Key adaptations in `src/mobile_world/runtime/aw_env_adapter.py`:

- **Protobuf request translation**: Handles generic, tap, press_button, input_text, start_activity, settings, package_manager, install_apk, pull, and push request types
- **List-based subprocess**: All generic ADB commands use `subprocess.run(list)` instead of shell strings to handle multiline scripts and paths with spaces
- **pull_file yields a directory**: AndroidWorld expects `pull_file()` to return a temp directory path (not a file path), with the caller constructing the full path
- **push_file clears then copies**: Matches AndroidWorld's pattern of clearing the remote directory before pushing

## Task Wrapper

`AWTaskWrapper` (`src/mobile_world/tasks/aw_task_wrapper.py`) bridges AndroidWorld's `TaskEval` to MobileWorld's `BaseTask`:

- Overrides `initialize_task()` entirely — skips MobileWorld-specific cleanup (Mattermost, Mastodon, mall) and loads `aw_init_state` snapshot instead of `init_state`
- Supports `--seed` for reproducible random params via `generate_random_params()`
- Delegates `is_successful()` and `tear_down()` to the wrapped TaskEval
- **Runtime emulator fixes** applied after snapshot load:
  - `screen_off_timeout` set to max — prevents screen sleep during evaluation, which causes UIAutomator dumps to fail (fixes Clock stopwatch tasks)
  - Revokes `READ_CALENDAR`/`WRITE_CALENDAR` from Simple Calendar Pro — forces app to use its internal SQLite DB (which the evaluator reads) instead of the system CalendarProvider (fixes all 8 calendar tasks)
  - Clears logcat buffer — prevents stale browser success markers from previous tasks

`AWTaskRegistry` (`src/mobile_world/tasks/aw_registry.py`) discovers all AndroidWorld tasks and wraps them.

## Docker Setup

### Building the aw-apps image (recommended: `Dockerfile.aw`)

`docker/Dockerfile.aw` builds a single-layer image from scratch, avoiding Docker layer duplication that inflates image size (~22-24GB vs ~30GB with commit-based approach).

**Prerequisites**: An extracted AVD directory with the `aw_init_state` snapshot (all AW apps pre-installed). Extract from an existing image:

```bash
docker create --name avd_extract mobile_world:aw-apps true
docker cp avd_extract:/root/.android/avd/Pixel_8_API_34_x86_64.avd docker/Pixel_8_API_34_x86_64.avd
docker rm avd_extract
# Clean stale lock files
find docker/Pixel_8_API_34_x86_64.avd/ -name "*.lock" -type f -delete
```

**Build**:
```bash
docker build -f docker/Dockerfile.aw -t mobile_world:aw-apps .
# Clean up extracted AVD after build (it's .gitignored)
rm -rf docker/Pixel_8_API_34_x86_64.avd
```

Build time: ~15-20 min. Expected image size: ~22-24GB.

### Alternative: incremental update (`Dockerfile.update`)

`docker/Dockerfile.update` layers on top of the base `ghcr.io/tongyi-mai/mobile_world:latest` image. Faster to build but requires a subsequent `docker commit` after app setup, which duplicates the AVD data across layers (~30GB).

### First-time app setup (only needed to create initial AVD snapshot)

If building from scratch without an existing `aw_init_state` snapshot:

```bash
# 1. Build base image with Dockerfile.update
docker build -f docker/Dockerfile.update -t mobile_world:aw-base .

# 2. Run container and install apps (~20-30 min)
docker run -d --privileged --name aw_setup mobile_world:aw-base
docker exec aw_setup /app/docker/setup_android_world_apps.sh

# 3. Commit (creates bloated image due to layer duplication)
docker commit aw_setup mobile_world:aw-apps-unflat

# 4. Extract AVD and rebuild with Dockerfile.aw for slim image
docker create --name avd_extract mobile_world:aw-apps-unflat true
docker cp avd_extract:/root/.android/avd/Pixel_8_API_34_x86_64.avd docker/Pixel_8_API_34_x86_64.avd
docker rm avd_extract
docker build -f docker/Dockerfile.aw -t mobile_world:aw-apps .
rm -rf docker/Pixel_8_API_34_x86_64.avd
```

The entrypoint cleans stale emulator lock files (left from `docker commit` of running containers) to prevent multi-container boot failures.

## CLI Usage

```bash
# Run all AndroidWorld tasks with 5 parallel containers
uv run mw env run --count 5 --prefix aw_test --image mobile_world:aw-apps
uv run mw eval \
  --agent_type seed_agent \
  --tasks ALL \
  --suite-family android_world \
  --seed 42 \
  --env-prefix aw_test \
  --env-image mobile_world:aw-apps \
  --max-concurrency 5 \
  --max_round 50 \
  --model_name <model> \
  --llm_base_url <url> \
  --log_file_root traj_logs/aw_run

# Run specific tasks
uv run mw eval \
  --tasks MarkorCreateNote,SimpleSmsSend,ExpenseAddSingle \
  --suite-family android_world \
  --seed 42 \
  ...
```

The `--seed` flag is only valid with `--suite-family android_world` and enables reproducible task parameter generation.
