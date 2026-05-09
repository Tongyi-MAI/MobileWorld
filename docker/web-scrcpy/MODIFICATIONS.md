# Third-Party Notices and Modifications

This directory contains a vendored production build of
[panda-web-scrcpy](https://github.com/PandaTestGrid/panda-web-scrcpy), used by
MobileWorld as the in-container device viewer. The frontend is served as static
files by `docker/ws_adb_proxy.py`, which also relays the ADB byte stream over a
WebSocket so the browser can speak the scrcpy protocol without WebUSB.

## License

panda-web-scrcpy is distributed under the **Apache License, Version 2.0**. The
full license text is included in this directory as `LICENSE`. (The upstream
README mentions MIT, but the `LICENSE` file in the repository is Apache-2.0;
the `LICENSE` file is the authoritative document.)

## Acknowledgements

We're grateful to the upstream authors and the wider open-source ecosystem
this build depends on:

- **[panda-web-scrcpy](https://github.com/PandaTestGrid/panda-web-scrcpy)**
  by PandaTestGrid — Apache-2.0. Provides the Vue/Vuetify front end and the
  scrcpy decoding/UX layer.
- **[Genymobile/scrcpy](https://github.com/Genymobile/scrcpy)** — Apache-2.0.
  The bundled `scrcpy-server-v3.3.3` is the upstream Android-side server,
  shipped unmodified.
- **[Yume-Chan / Tango ADB](https://github.com/yume-chan/ya-webadb)** — MIT,
  © 2020-2025 Simon Chan. Powers the ADB protocol, scrcpy decoder, and stream
  primitives at runtime.
- **[Vuetify](https://vuetifyjs.com/)** and **[Vue](https://vuejs.org/)** — MIT.
- **[Material Design Icons](https://pictogrammers.com/library/mdi/)** —
  Apache-2.0.

## Modifications

Per Apache-2.0 §4(b), we hereby state that the bundled build was produced from
a **modified** copy of the upstream panda-web-scrcpy source. Changes made by
the MobileWorld team:

- **`vite.config.ts`** — changed the public base path from `/panda-web-scrcpy/`
  to `/` so the assets can be served from the root of the in-container HTTP
  server (`ws_adb_proxy.py`) without a sub-path prefix.
- **`src/components/Scrcpy/adb-client.ts`** — added a
  `connectViaWebSocket(wsUrl)` method that authenticates with the ADB daemon
  through a WebSocket transport instead of WebUSB. This lets the viewer drive
  an emulator running inside the container without requiring physical USB
  pairing in the browser.
- **`src/views/DeviceView.vue`** — refactored to use the WebSocket connection
  path by default and to drop the WebUSB-only UI flow that's not relevant in
  the containerized setup.
- **Added `src/components/Scrcpy/adb-ws-transport.ts`** — a new ADB packet
  transport implementation that wraps a WebSocket connection in the
  readable/writable streams required by `@yume-chan/adb`'s
  `AdbDaemonTransport.authenticate()`.

The `scrcpy-server-v3.3.3` server JAR and all node-module dependencies are
shipped unmodified from upstream.
