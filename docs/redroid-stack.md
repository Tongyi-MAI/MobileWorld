# MobileWorld on redroid — a containerized device stack

This document describes the **MobileWorld V1-compatible** runtime packaged as
`ghcr.io/tongyi-mai/mobile_world:v1-redroid`. The tag names the redroid runtime
variant; it does not denote a new MobileWorld benchmark version.

The runtime replaces the
Android **emulator-in-docker-in-docker (dind)** image with a **redroid**
(containerized Android) device plus **host-side application backends**. It
compares the two stacks, lists the advantages, records the migration actions
taken, and notes the caveats.

---

## TL;DR

- **No more QEMU / nested KVM.** redroid runs Android *as a container* on the host
  kernel. Horizontal scale is no longer coupled to KVM-capable machines.
- **Scale by cloning, not provisioning.** The whole environment (device + backends +
  seed data + the `10.0.2.2` alias) bakes into one VM image; launch N independent,
  self-contained copies with no shared state.
- **Faster and lighter.** Boot drops from tens-of-seconds-to-minutes to **~10 s** to
  `sys.boot_completed`; per-instance cost goes from full-machine emulation to
  container overhead.
- **Backends keep the exact `10.0.2.2` address.** The *host* owns `10.0.2.2` as an IP
  alias on the Docker bridge and publishes backend ports there — so apps and
  databases need **no data rewrite** and the guest needs **no changes**.
- **Per-container virtual clock without touching the host.** A tiny `LD_PRELOAD`
  time-shift shim gives the guest (and the verifier) any wall-clock date while the
  host clock stays real — reproducing the emulator's per-guest virtual RTC, safe
  across many concurrent containers running different dates. See
  [§4.5](#45-per-container-virtual-clock-time-shift-shim).
- **Backends are ordinary sibling containers.** Mattermost / Mastodon run as plain
  `docker compose` stacks (standard logs, restart policies) instead of nested
  docker-in-docker.
- **One codebase, both stacks.** A single device-kind detector gates every
  emulator-only path (SMS injection, snapshot lifecycle, health check, package map,
  UI dump) — the **original emulator path is unchanged**.
- **Per-task reset = whole-`/data` restore.** With no QEMU snapshots, each task
  restores the **entire golden `/data` volume in lockstep with the backend reset**,
  so the phone app's local state never drifts from the freshly-seeded server.
- **Known gaps, handled.** No modem/SIM or camera HAL, software GL only, and
  FOSS/AOSP substitutes for the Google apps (Chrome / Maps / Messages). See
  [§5 Caveats](#5-caveats-and-limitations).

---

## 1. Background: the original dind stack

The shipped MobileWorld runtime is a single, self-contained Docker image built on
a docker-in-docker base. One container runs:

- a full **Android emulator** (QEMU / AVD, `-gpu swiftshader_indirect`) holding the
  golden `init_state` snapshot;
- the **application backends** (Mattermost, Mastodon) as *nested* Docker Compose
  stacks, started on demand, reached from the guest at the emulator's standard
  host-loopback alias `10.0.2.2`;
- the MobileWorld controller server driving the device over `adb`.

Per-task isolation comes from QEMU snapshots (`adb emu avd snapshot load`), and
per-task SMS comes from the emulator console (`adb emu sms send`).

**Scaling** this stack means running many copies of the heavy dind image, each of
which needs a host that can nest KVM/QEMU. That couples horizontal scale to
KVM-capable machines.

---

## 2. The redroid stack

redroid runs Android **as a container** on the host kernel — no QEMU, no nested
KVM. The new topology, all on one ordinary host:

```
┌───────────────────────────────── host (one VM) ─────────────────────────────────┐
│                                                                                  │
│   redroid container (Android 14)        scrcpy web viewer        backend stacks  │
│   ─ apps + /data (named volume)         ─ streams the screen     ─ mattermost    │
│   ─ adb over tcp                          over the web              (compose)     │
│        │                                                          ─ mastodon      │
│        │  off-subnet traffic to 10.0.2.2                            (compose)     │
│        ▼  routes via the bridge gateway                                ▲          │
│   host bridge holds an IP alias 10.0.2.2  ───── published ports ───────┘          │
│   (so the guest reaches the backends at the exact address it already expects)    │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Key idea: the backends keep the **same `10.0.2.2` address** the apps and the
backend databases are already keyed to. Instead of QEMU providing that alias, the
**host owns `10.0.2.2` as an IP alias on the Docker bridge**, and the backend
container ports are published there. The containerized Android guest routes
off-subnet traffic through the bridge gateway, so a request to `10.0.2.2:<port>`
lands on the host-published backend — with **no server-side data rewrite** and
**no changes inside the guest**.

---

## 3. Advantages over the dind stack

| Dimension | dind + emulator | redroid stack |
|---|---|---|
| **Virtualization** | Needs nested KVM/QEMU on every host | None — Android runs on the host kernel |
| **Scaling unit** | KVM-capable machines | Any container host / plain VM image clone |
| **Boot time** | Tens of seconds to minutes (full-system emulation + snapshot) | ~10 s to `sys.boot_completed` |
| **Per-instance cost** | Heavy (full machine emulation) | Light (shared kernel, container overhead) |
| **Backends** | Nested Docker-in-Docker | Ordinary sibling containers (`docker compose`) — standard ops, logs, restart policies |
| **Device I/O** | adb through the emulator | adb to a local container |
| **State** | Snapshot inside the image | Named `/data` volume survives container recreate (e.g. resolution changes) without losing apps/data |
| **Packaging** | One large dind image | Device + backends + data snapshot into one host/VM image |

**Scaling model.** Because nothing needs KVM, the entire host — redroid + backend
images + the golden backend seed + the `10.0.2.2` alias unit + container restart
policies — can be captured as one VM image and launched as **N independent
instances**. Each clone is a complete, self-contained MobileWorld environment with
no shared state. Horizontal scale becomes "clone the image," not "provision a
KVM host."

---

## 4. Migration actions taken

### 4.1 Device content
- Installed the emulator's application APKs into redroid (same x86_64 ABI, so the
  emulator splits are valid). Where an emulator app is unavailable or arm-only on
  the container, substituted an AOSP/FOSS equivalent (see caveats).
- Copied per-app `/data/data/<pkg>` directories and `/sdcard` content. The copy
  excludes each app's `lib` symlink (it points at the source device's APK path),
  re-owns to the **target** app uid (uids differ across devices), and restores the
  SELinux context.
- Seeded the system content providers from the emulator's authoritative data:
  - **SMS** — rebuilt the telephony inbox (messages + threads + canonical
    addresses) from the emulator's live `content://sms` dump.
  - **Contacts** — re-created provider-aggregated contacts.
  - **Calendar** — restored the calendar app's own database.

### 4.2 Application backends
- Took the **golden backend seed** from the emulator image's built-in backup
  (the only complete copy — it contains the backend databases, environment files,
  and TLS material that are not checked into the repository).
- Brought the Mattermost and Mastodon Compose stacks up **directly on the host**.
  The stacks come up with their seeded databases/media intact; Mattermost's config
  is patched for the `10.0.2.2` site URL / CORS / non-expiring sessions exactly as
  the in-emulator helper does.
- Added the **host IP alias** so the guest reaches both backends (and the
  controller's mall/verification-code callback) at the unchanged `10.0.2.2`.
- Verified end to end from the device UI: the Mastodon timeline loads from the
  re-hosted server, and Mattermost connects and serves its seeded workspace.

### 4.3 Environment alignment
Matched the container's device state to the emulator so GUI automation behaves the
same: **animations disabled**, **timezone / manual-time** matched, default
**SMS / browser** roles set to the substitute apps, and the **screen aspect ratio**
set to match the reference device (recreating the container at a matching
resolution while preserving the `/data` volume).

### 4.4 Framework patches
Added a single **device-kind detector** and gated every emulator-only code path on
it, so one codebase drives either backend and the **emulator path is unchanged**:

- **SMS injection** — on the container, inject inbound SMS into the telephony
  provider instead of using the (absent) emulator console.
- **Snapshot lifecycle → whole-`/data` restore.** With no QEMU snapshots, the
  per-task `init_state` "snapshot load" is reimplemented on the container as a
  **restore of the whole golden `/data` volume**, run **in lockstep with the
  backend reset** (rationale in §5). The golden `/data` baseline is captured once
  after migration + alignment — before any task — and *is* the redroid
  `init_state`. Each task init: stop the container → restore golden `/data` on the
  host → start → wait `sys.boot_completed` → reconnect adb → reset the backends,
  then layer on per-task provider/SMS seeding. `save`/`list`/`delete` stay no-ops
  (or map to baseline capture). Restoring the data *directory* (not `pm clear`)
  preserves the golden app auth token, which matches the golden `sessions` row the
  backend reset restores — so the app returns logged-in and consistent.
- **Health check** — use `adb getprop sys.boot_completed` instead of looking for a
  QEMU process.
- **Default device id** — environment-overridable.
- **App package map** — substitute packages for Chrome / Maps / Messages / Clock /
  Files / Gallery when running on the container.
- **Accessibility XML dump** — fall back to the standard `uiautomator` dump when the
  custom dumper app is absent.

(Plus a few device-agnostic correctness fixes surfaced during the audit, e.g. a
date-parsing bug and a couple of task-setup hooks returning the wrong type.)

### 4.5 Per-container virtual clock (time-shift shim)

The emulator gave each guest a private virtual RTC, so a task could run the device
at an arbitrary wall-clock (e.g. `2025-10-16`) while the host stayed real. redroid
has no such luxury: an Android container shares the host kernel, and Linux time
namespaces virtualize only `CLOCK_MONOTONIC` / `CLOCK_BOOTTIME` — **not**
`CLOCK_REALTIME`. So the guest wall-clock is *always* exactly the host's, and the
old approach of stepping the host clock is both a single-container bottleneck and
unsafe on a shared host (it clobbers co-located containers and breaks the agent
LLM's TLS certificate validation, which needs real time).

The fix is a small **`LD_PRELOAD` time-shift shim** that adds a per-container
offset to every wall-clock read, leaving the host clock untouched:

- **One C source, two builds.** It compiles to a **bionic** `.so` for the guest and
  a **glibc** `.so` for the host-side MobileWorld server from a single file
  (`#ifdef __BIONIC__` reconciles the `gettimeofday` signature and the
  bionic-only property read). Both interpose `clock_gettime` / `gettimeofday` /
  `time` and add an offset (seconds, guest − real) read from a file — and, on the
  guest, an Android property — refreshed at most once per real second.
- **Global guest preload via the zygote.** The guest copy is preloaded with
  `setenv LD_PRELOAD …` in `init.zygote64.rc`, so it loads once in the zygote and
  every forked app *and* `system_server` inherit the shifted clock. The host copy
  is preloaded when the controller launches, so the **verifier sees the same
  shifted time as the device** — date-relative checks (calendar windows, message
  timestamps) stay consistent across guest and grader.
- **Per-container and per-task.** The entrypoint computes the default offset from a
  target datetime against real host time and writes it to the offset file before
  the boot reboot; `base.set_task_timeframe` re-points it per task — real-time for
  apps that need "now" (Chrome / Maps / arXiv), otherwise the frozen reference
  date. `time_sync_to_now` re-applies the offset after a `/data` wipe (the wipe
  drops the guest property).

Net effect: the guest and the verifier both believe it is the configured date while
the host clock stays real — the emulator's per-guest virtual RTC reproduced for the
container, and safe to run many instances at once with *different* dates. The old
`set_host_clock` path is retired.

**Mock-user LLM call skips TLS date-validation.** The host-side server is itself
clock-shifted (the verifier must see the device's date), so an outbound HTTPS call
made *from* the server inherits the shifted clock. The simulated-user endpoint
behind `ask_user` (`user_agent_answer_question`) calls an LLM over HTTPS, and when
the shift predates the cert's `notBefore` the handshake fails with "certificate is
not yet valid". That one trusted-endpoint call therefore disables cert verification
(`httpx.Client(verify=False)`) — the connection is still TLS, just not date-validated.
The agent's own LLM client runs in an unshifted process and is unaffected.

### 4.6 Packaging and per-task performance

- **Runtime assets are an explicit allowlist.** The public repository keeps the
  custom helper sources (camera, SMS notifier, time shim, viewer, and Fossify
  patch), but not compiled APKs/HAL binaries or golden device databases. Those
  release inputs are supplied out of band for from-source image builds. The
  Dockerfile copies only the ARM runtime files it names explicitly; it never
  copies the whole `docker/redroid_assets` directory.
- **Backend images baked in, zero startup load.** The inner redroid + Mattermost +
  Mastodon images are loaded into the image's Docker storage **at build time**
  (`RUN --security=insecure` runs an inner dockerd during the build and
  `docker load`s the tars into the `/var/lib/docker` volume; copy-up seeds the
  runtime volume). A launched container does **no** `docker load`, so cold start is
  not gated on unpacking gigabytes of layers. Build inputs are bind-mounted into the
  bake `RUN` rather than `COPY`d, so they never become image layers.
- **Golden `/data` restore is zstd + pre-extract + rsync.** The golden `/data`
  baseline is stored once as a **zstd** archive, **pre-extracted** to a host
  directory at startup, and each per-task restore is an `rsync -a --delete` from
  that tree (not a decompress + untar per task). This cut the per-task reset from
  ~38 s to ~24 s — now floored by the inherent ~15 s device reboot of the
  `/data`-volume swap.

### 4.7 Benchmark-gap fixes

A cross-stack benchmark (redroid vs the dind emulator) surfaced env-specific gaps
where a *correct* agent action was graded as a failure. These were closed at the
environment level, without regressing verifier logic:

- **File manager — Google DocumentsUI in place of AOSP.** redroid's stock
  `com.android.documentsui` (AOSP) exposes no file-operation UI, so file tasks
  (rename / copy / move / delete / compress) could never succeed. The emulator uses
  Google's `com.google.android.documentsui` (`DocumentsUIGoogle.apk`), a full file
  manager with those operations. The two packages **share provider authorities and
  cannot coexist**, and a per-user uninstall does *not* free the authority — so the
  AOSP package is removed from `/system` and the Google APK installed as a
  `/system/priv-app` (redroid's root is a writable overlay and
  `ro.control_privapp_permissions=disable`, so no privapp whitelist is required). A
  startup setup step applies the swap **before** the boot reboot, so PackageManager
  rescans `/system`; because the change lives in `/system` (not `/data`) it survives
  every per-task golden `/data` restore and needs **no** golden re-capture. The
  package map routes "Files" to the Google package.
  - *Launch caveat:* the Google launcher activity is a **translucent trampoline**, so
    `monkey -c LAUNCHER` can exit non-zero or fail to bring it to the foreground. On
    redroid, `launch_app` therefore decides success by the **actual foreground
    activity** (not monkey's exit code) and, if needed, falls back to an explicit
    `am start` of the resolved launcher activity. Apps that launch fine under monkey
    are unaffected.

- **Display-size grading is resolution-independent.** The "increase/decrease font and
  icons to the max/min setting" tasks hardcoded the emulator's display densities
  (540 / 356), which fail on redroid's different resolution even when the slider is
  correctly maxed or minned. The check now **computes the bounds from the live
  device**: Android's "Display size" options are scales of the *physical* density,
  from 0.85× up to `min(1.5×, the largest density keeping the smallest screen edge
  ≥ 320 dp)` (mirroring AOSP `DisplayDensityUtils`). It compares the current density
  with a small tolerance to absorb Android's integer rounding (the slider steps are
  ~9 % of the physical density apart, far larger than the rounding). This reproduces
  the emulator's 540 / 356 and adapts to redroid (360 / ~238) and any future
  resolution; the font-scale targets (2.0 / 0.85) were already resolution-independent.

- **Scroll distance matches the old env.** `AndroidController.swipe` derived the swipe
  distance from screen **width** (≈ 0.4 × width per vertical scroll). On redroid's
  narrower 720-px screen that is far fewer absolute pixels than the emulator's 1080-px
  screen, and at the same 400 ms duration the lower fling velocity scrolls much less
  content per gesture. On redroid the swipe is now **height-based** (≈ 0.33 × height
  vertically, a wider fraction horizontally) with a shorter 340 ms duration so it
  flings comparably — measured ~730 px of content displacement per up-swipe vs ~320 px
  before (emulator reference ~495 px). Gated on `is_redroid`; the emulator path is
  unchanged.

- **Injected SMS posts a system notification.** With no SIM, inbound SMS are written
  straight into the telephony provider + the Fossify cache (see §4.4), bypassing
  Fossify's `SMS_DELIVER` receiver — so no notification was posted (a real device shows
  one). A shell `cmd notification post` is torn down as soon as the command process
  exits on this build, so a small headless helper app (`smsnotifier`, installed at
  startup) posts a **persistent** SMS-style notification when broadcast; the
  inbound-SMS injection fires that broadcast after the dual-write. Best-effort: the SMS
  is in the inbox either way.

- **Home-screen app icons survive the first boot.** The golden `/data` carries a
  Launcher3 workspace with Files and Camera pinned to the home screen. The current ARM
  image bakes Google DocumentsUI into `/system` before the first Android boot, so the
  Files component resolves when Launcher3 first loads and its favorite is not pruned.
  The ARM baseline predates the Taodian and Firefox favorites, so startup and every
  golden-data restore idempotently add those shortcuts beside Mail and Camera. Existing
  component rows are detected first, preventing duplicate icons across resets.

- **Files (DocumentsUI) opens in list view, matching the reference.** Google
  DocumentsUI defaults to grid view; the reference env has it set to list. That setting
  lives in `com.google.android.documentsui`'s `shared_prefs`, but the package's golden
  `/data` is orphan-cleared on the first boot (its APK isn't in `/system` until the
  swap, so PMS discards the restored data) — losing the pref. The entrypoint re-seeds
  the preferences XML from golden **after** the post-swap reboot — once the package is
  installed and its data dir exists — re-owning it to the app uid. Per-task golden
  `/data` restores don't need this: DocumentsUI now lives in `/system`, so its data dir
  is never orphaned again.

---

## 5. Caveats and limitations

- **Release data is synthetic and local-only.** The root `.env`, trajectory logs,
  workstation paths, private service endpoints, and model credentials are excluded
  from the image build context. The fixed Mattermost/Mastodon secrets and the
  `10.0.2.2` TLS key are benchmark fixtures required to restore their synthetic
  golden databases; they are not production credentials. Do not expose the viewer,
  controller, backend, or unauthenticated redroid ADB ports directly to an untrusted
  network—bind them to loopback, use SSH forwarding, or apply an equivalent firewall.
- **No QEMU snapshots — per-task reset is a whole-`/data` restore.** There is no
  in-image snapshot; instead each task restores the **entire golden `/data`
  volume** and resets the backends **together**. This lockstep is required for
  correctness: the backend is reset to golden every task, but if the phone app's
  local `/data` (cached posts, sync cursors, read markers, drafts) is *not* also
  reset, the frontend drifts out of sync with the freshly-seeded backend — the
  consistency the QEMU snapshot used to provide implicitly. The cost is a container
  restart per task (~24 s, floored by the inherent ~15 s device reboot of the
  `/data`-volume swap, vs an in-place per-app data restore); the whole-volume
  approach is chosen for faithfulness and simplicity. The restore itself is cheap —
  the golden baseline is a zstd archive pre-extracted once at startup, and each task
  restore is an `rsync -a --delete` from that tree (see §4.6). Tasks that inject
  per-task state still layer their `initialize_task_hook` seeding on top of the
  restored baseline.
- **No modem / SIM.** Inbound SMS is injected at the provider level. Outbound-SMS
  evaluation depends on the messaging app writing the "sent" provider on a device
  with no radio — verify per messaging app.
- **No camera HAL.** Camera / selfie capture tasks are unsupported on the container
  (a small number of tasks). A v4l2loopback + external-camera-HAL approach is
  possible but heavy.
- **No Google apps for Chrome / Maps / Messages.** Substitutes are used
  (System-WebView browser, Fossify Messages, AOSP DeskClock / Gallery; for Files, the
  Google DocumentsUI is swapped in for AOSP's — see §4.7). Tasks that need the **Maps
  app specifically** degrade to web fidelity; the underlying location services are
  present.
- **Zip extraction via Files (DocumentsUI) — AppFuse mount rejected by the host kernel
  (root-caused; fix is a one-byte vold patch).** DocumentsUI serves a file's bytes *out*
  of an archive through `StorageManager.openProxyFileDescriptor()`, backed by an
  **AppFuse** per-app `/dev/fuse` mount. vold formats that mount's options as
  `…,user_id=0,group_id=0,context="u:object_r:app_fuse_file:s0",fscontext=u:object_r:app_fusefs:s0`.
  The container shares the **host kernel**. On a validated Linux configuration,
  SELinux was compiled in but **not an active LSM** (active =
  apparmor/landlock/yama/…; no
  `/sys/fs/selinux`). With no SELinux LSM to consume `context=`/`fscontext=`, FUSE's own
  parameter parser sees them, rejects the unknown params, and `mount(2)` returns
  **EINVAL** (`dmesg: fuse: Unknown parameter 'context'` → `vold: Failed to mount
  /mnt/appfuse/<uid>_<id>: Invalid argument`). The main `/storage` FUSE mount works
  precisely because it omits `context=`. *Browsing/listing inside* a zip works (no proxy
  FD); only *reading an entry out* (Extract / open-from-archive) fails, and DocumentsUI
  swallows it — the extract job deletes its half-written output, so the "extracting…"
  notification just vanishes. **Compress** is unaffected (normal FDs), so the
  `send_zip_files_*` *compress* tasks still pass; previewing a file from inside a zip
  fails identically. Container flags/caps cannot help (the rejection is in the host-kernel
  FUSE parser; the container is already `--privileged`). **Fix:** strip the
  `context=`/`fscontext=` options from vold's appfuse mount — a single length-preserving
  byte patch of `/system/bin/vold` (NUL the comma before `,context=`), restart vold;
  verified to make extraction land byte-correct files. Like the DocumentsUI `/system`
  swap above (§4.7), it must be applied at startup **before the boot reboot** so it
  survives container recreate and `/data` restores — fold a `setup_vold_appfuse` step into
  the image setup (needs an image rebuild). App-level alternative (non-infra): a
  self-contained file manager that unzips via `java.util.zip` (e.g. Fossify File Manager).
- **Device-bound credential stores don't migrate.** App sessions backed by the
  hardware-bound keystore cannot be carried over by copying app data; those apps
  must be **re-logged-in** on the container (the server data itself is unaffected).
- **Software GL only (no host GPU).** Apps that bundle their own Chromium/WebView
  engine crash on the software GL stack; use System-WebView–based apps. The
  standalone Chromium browser flickers and should not be launched.
- **Backends must be reachable at `10.0.2.2`.** The host IP alias is **not**
  reboot-persistent by default; bake a small boot-time unit that re-adds it after
  the container runtime starts, and give the backend/device containers restart
  policies, so a rebooted (or freshly cloned) image comes up complete.

---

## 6. Summary

The redroid stack delivers the same MobileWorld device + backend environment
without QEMU or nested KVM, so it can be packaged as a single host/VM image and
scaled horizontally by cloning. The cost is a set of capability gaps (snapshots,
modem, camera, Google-app specifics) that are handled by provider-level seeding,
AOSP/FOSS substitutes, and device-gated framework patches that leave the original
emulator path intact.
