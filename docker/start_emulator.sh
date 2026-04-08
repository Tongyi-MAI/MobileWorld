
# kill existing emulators
adb devices | grep emulator | cut -f1 | xargs -I {} adb -s "{}" emu kill

export options="-no-audio -no-snapshot -gpu swiftshader_indirect"
if [ "${AVD_NAME}" = "Pixel_6_API_33" ]; then
  export options="$options -grpc 8554"
fi
echo "Starting headless emulator with options: $options"
nohup emulator -avd ${AVD_NAME} -no-window $options > /var/log/emulator.log 2>&1 &

# code from: https://github.com/google-research/android_world/blob/main/docker_setup/start_emu_headless.sh
BL='\033[0;34m'
G='\033[0;32m'
RED='\033[0;31m'
YE='\033[1;33m'
NC='\033[0m' # No Color
function check_emulator_status () {
  printf "${G}==> ${BL}Checking emulator booting up status 🧐${NC}\n"
  start_time=$(date +%s)
  spinner=( "⠹" "⠺" "⠼" "⠶" "⠦" "⠧" "⠇" "⠏" )
  i=0
  # Get the timeout value from the environment variable or use the default value of 600 seconds (10 minutes)
  timeout=${EMULATOR_TIMEOUT:-600}

  while true; do
    result=$(adb shell getprop sys.boot_completed 2>&1)

    if [ "$result" == "1" ]; then
      printf "\e[K${G}==> \u2713 Emulator is ready : '$result'           ${NC}\n"
      adb devices -l
      adb shell input keyevent 82
      return 0  # Return a 0 to indicate emulator has booted successfully
    elif [ "$result" == "" ]; then
      printf "${YE}==> Emulator is partially Booted! 😕 ${spinner[$i]} ${NC}\r"
    else
      printf "${RED}==> $result, please wait ${spinner[$i]} ${NC}\r"
      i=$(( (i+1) % 8 ))
    fi

    current_time=$(date +%s)
    elapsed_time=$((current_time - start_time))
    if [ $elapsed_time -gt $timeout ]; then
      printf "${RED}==> Timeout after ${timeout} seconds elapsed 🕛.. ${NC}\n"
      return 1 # Return a 1 to indicate failure if exceeded timeout
    fi
    sleep 4
  done
};

function disable_animation() {
  adb shell "settings put global window_animation_scale 0.0"
  adb shell "settings put global transition_animation_scale 0.0"
  adb shell "settings put global animator_duration_scale 0.0"
};


if check_emulator_status; then
  sleep 1
  disable_animation
  sleep 1
else
  echo "Emulator failed to start properly, exiting..."
  exit 1
fi

adb root
