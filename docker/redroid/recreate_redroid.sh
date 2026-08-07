#!/bin/bash
set -e

echo "=== stop+rm old redroid (data volume redroid14-gms-data PERSISTS) ==="
docker stop redroid14-sandbox >/dev/null 2>&1 || true
docker rm redroid14-sandbox >/dev/null 2>&1 || true

echo "=== run new redroid 720x1600@280 fps60 ==="
docker run -d --name redroid14-sandbox --privileged --restart unless-stopped \
  -v /dev/binderfs/binder:/dev/binder \
  -v /dev/binderfs/hwbinder:/dev/hwbinder \
  -v /dev/binderfs/vndbinder:/dev/vndbinder \
  -v redroid14-gms-data:/data \
  -p 5555:5555 \
  --shm-size 64m \
  redroid/redroid:14.0.0_64only_mindthegapps \
  androidboot.redroid_width=720 androidboot.redroid_height=1600 androidboot.redroid_dpi=280 \
  androidboot.redroid_fps=60 \
  androidboot.redroid_gpu_mode=guest androidboot.use_memfd=true \
  androidboot.redroid_net_ndns=2 androidboot.redroid_net_dns1=100.100.2.136 androidboot.redroid_net_dns2=100.100.2.138
echo "run rc=$?"
sleep 3
docker ps --format '{{.Names}} | {{.Status}}' | grep redroid14 || { echo "FAILED TO START"; docker logs redroid14-sandbox 2>&1 | tail -10; exit 1; }

echo "=== reconnect adb + wait for boot ==="
ADB="docker exec -i redroid-web-scrcpy adb"
$ADB disconnect host.docker.internal:5555 >/dev/null 2>&1 || true
for i in $(seq 1 50); do
  $ADB connect host.docker.internal:5555 >/dev/null 2>&1
  BC=$($ADB -s host.docker.internal:5555 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  if [ "$BC" = "1" ]; then echo "boot_completed after ~$((i*3))s"; break; fi
  sleep 3
done
echo "=== new physical size/density ==="
$ADB -s host.docker.internal:5555 shell "wm size; wm density" 2>&1 | tr -d '\r'
