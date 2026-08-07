#!/usr/bin/env node
/*
 * redroid phone-page unified proxy
 * --------------------------------
 * One HTTP origin (single port) that serves the whole ws-scrcpy phone page AND
 * the on-screen keyboard, so only ONE port needs forwarding over SSH.
 *
 *   /kbd/health           -> list adb devices                  (handled here)
 *   /kbd/text   {udid,text}-> type text via ADBKeyboard         (handled here)
 *   /kbd/key    {udid,key} -> input keyevent                    (handled here)
 *   everything else        -> reverse-proxied to ws-scrcpy (incl. the video
 *                             WebSocket upgrade) on UPSTREAM_PORT
 *
 * Why this exists: the page's keyboard must run `adb shell am broadcast
 * ADB_INPUT_B64 ...` on the device, but ws-scrcpy's only adb path (proxy-adb)
 * crashes on those long commands and its action=shell is disabled. So keyboard
 * input is served out-of-band -- but mounted under the SAME origin as the page
 * by proxying all non-/kbd traffic to ws-scrcpy. Node's http server dispatches
 * per-request, so HTTP keep-alive and the long-lived video WebSocket are both
 * handled correctly (a naive TCP splicer would mis-route pooled connections).
 *
 * Security: keyboard endpoints run adb. udid is validated against the live
 * `adb devices` list, key against a strict allow pattern, and text is passed to
 * ADBKeyboard base64-encoded via an argv list (never shell-interpolated).
 * Intended to be reached over an SSH tunnel, not exposed publicly.
 */
'use strict';

const http = require('http');
const net = require('net');
const { execFile } = require('child_process');

const LISTEN_HOST = process.env.PHONE_PROXY_HOST || '0.0.0.0';
const LISTEN_PORT = parseInt(process.env.PHONE_PROXY_PORT || '8080', 10);
const UPSTREAM_HOST = '127.0.0.1';
const UPSTREAM_PORT = parseInt(process.env.WS_SCRCPY_PORT || '8000', 10);

const ADB_IME = 'com.android.adbkeyboard/.AdbIME';
const KEY_RE = /^(KEYCODE_[A-Z0-9_]+|\d+)$/;

// NOTE: the device-side scrcpy server (tcp:8886) is owned by ws-scrcpy — its device
// tracker spawns/respawns it per connected device. This proxy must NOT start or kill
// it: doing so races ws-scrcpy and SIGTERMs the stream it is using ("Server exited:
// Terminated" -> client "socket hang up"). We only relay; ws-scrcpy owns lifecycle.

function adb(args, timeout, cb) {
  execFile('adb', args, { timeout: timeout, encoding: 'utf8' }, (err, stdout) => {
    cb(err, stdout || '');
  });
}

function adbDevices(cb) {
  adb(['devices'], 10000, (err, out) => {
    const devs = new Set();
    if (!err) {
      out.split('\n').slice(1).forEach((line) => {
        const parts = line.trim().split(/\s+/);
        if (parts.length >= 2 && parts[1] === 'device') devs.add(parts[0]);
      });
    }
    cb(devs);
  });
}

// pm enable -> ime enable -> ime set, then run `next`. Errors ignored: the IME
// component ships disabled, so this is idempotent best-effort setup.
function ensureAdbIme(udid, next) {
  adb(['-s', udid, 'shell', 'pm', 'enable', ADB_IME], 10000, () => {
    adb(['-s', udid, 'shell', 'ime', 'enable', ADB_IME], 10000, () => {
      adb(['-s', udid, 'shell', 'ime', 'set', ADB_IME], 10000, () => next());
    });
  });
}

function typeText(udid, text, cb) {
  ensureAdbIme(udid, () => {
    const b64 = Buffer.from(text, 'utf8').toString('base64');
    adb(['-s', udid, 'shell', 'am', 'broadcast', '-a', 'ADB_INPUT_B64', '--es', 'msg', b64], 15000,
      (err) => cb(!err));
  });
}

function sendJson(res, code, obj) {
  const body = Buffer.from(JSON.stringify(obj));
  res.writeHead(code, {
    'Content-Type': 'application/json',
    'Content-Length': body.length,
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  });
  res.end(body);
}

function readBody(req, cb) {
  let data = '';
  req.on('data', (c) => { data += c; if (data.length > 1 << 20) req.destroy(); });
  req.on('end', () => {
    try { cb(null, data ? JSON.parse(data) : {}); } catch (e) { cb(e); }
  });
}

function handleKbd(req, res) {
  const path = req.url.split('?')[0];
  if (req.method === 'OPTIONS') return sendJson(res, 204, {});

  if (req.method === 'GET' && path === '/kbd/health') {
    return adbDevices((devs) => sendJson(res, 200, { ok: true, devices: [...devs].sort() }));
  }

  if (req.method !== 'POST') return sendJson(res, 404, { error: 'not found' });

  readBody(req, (err, data) => {
    if (err) return sendJson(res, 400, { error: 'bad json' });
    const udid = String(data.udid || '');
    adbDevices((devs) => {
      if (!devs.has(udid)) return sendJson(res, 400, { error: 'unknown udid', udid: udid });

      if (path === '/kbd/text') {
        const text = data.text;
        if (typeof text !== 'string') return sendJson(res, 400, { error: 'text must be string' });
        typeText(udid, text, (ok) => sendJson(res, ok ? 200 : 500, { ok: ok }));
      } else if (path === '/kbd/key') {
        const key = String(data.key || '');
        if (!KEY_RE.test(key)) return sendJson(res, 400, { error: 'bad key' });
        adb(['-s', udid, 'shell', 'input', 'keyevent', key], 15000,
          (e) => sendJson(res, e ? 500 : 200, { ok: !e }));
      } else {
        sendJson(res, 404, { error: 'not found' });
      }
    });
  });
}

const server = http.createServer((req, res) => {
  if (req.url.startsWith('/kbd/')) return handleKbd(req, res);
  // reverse-proxy everything else to ws-scrcpy
  const up = http.request(
    { host: UPSTREAM_HOST, port: UPSTREAM_PORT, method: req.method, path: req.url, headers: req.headers },
    (ur) => { res.writeHead(ur.statusCode, ur.headers); ur.pipe(res); }
  );
  up.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end('upstream error'); });
  req.pipe(up);
});

// relay the scrcpy video WebSocket (and any other Upgrade) to ws-scrcpy, which
// owns the device-side scrcpy server lifecycle.
server.on('upgrade', (req, clientSocket, head) => {
  const upstream = net.connect(UPSTREAM_PORT, UPSTREAM_HOST, () => {
    let raw = `${req.method} ${req.url} HTTP/${req.httpVersion}\r\n`;
    for (let i = 0; i < req.rawHeaders.length; i += 2) {
      raw += `${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}\r\n`;
    }
    raw += '\r\n';
    upstream.write(raw);
    if (head && head.length) upstream.write(head);
    clientSocket.pipe(upstream);
    upstream.pipe(clientSocket);
  });
  upstream.on('error', () => clientSocket.destroy());
  clientSocket.on('error', () => upstream.destroy());
});

server.listen(LISTEN_PORT, LISTEN_HOST, () => {
  console.log(`redroid-phone-proxy listening on ${LISTEN_HOST}:${LISTEN_PORT} -> ws-scrcpy ${UPSTREAM_HOST}:${UPSTREAM_PORT}`);
});
