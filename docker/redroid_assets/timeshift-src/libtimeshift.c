// libtimeshift.c — minimal CLOCK_REALTIME offset shim for bionic (Android/redroid).
//
// Goal: make the GUEST believe wall-clock = real_time + offset, so a redroid
// container can be pinned to the benchmark frame (e.g. 2025-10-16) while the
// host kernel CLOCK_REALTIME stays real. Each container reads its own offset,
// so containers can hold different datetimes concurrently (matches the QEMU
// emulator's per-guest virtual RTC). LD_PRELOAD this into zygote + shell + apps.
//
// Offset source (whole signed seconds, "guest - real"):
//   1) Android property  persist.sys.timeshift_off   (fast; set via `setprop`)
//   2) file              /data/local/tmp/timeshift_offset   (fallback)
// Re-read at most once/sec so the eval can change the frame at runtime cheaply.
//
// Only CLOCK_REALTIME is shifted. MONOTONIC/BOOTTIME are left untouched so
// timers, schedulers, and SystemClock.elapsedRealtime keep working normally.

#define _GNU_SOURCE
#include <time.h>
#include <sys/time.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <pthread.h>

#define TS_PROP "persist.sys.timeshift_off"
#define TS_FILE "/data/local/tmp/timeshift_offset"

// bionic property API (declared here to avoid pulling sys/system_properties.h deps).
// glibc (the verifier/MW-server side) has no properties — file path only.
#ifdef __BIONIC__
extern int __system_property_get(const char *name, char *value);
#endif

// bionic declares gettimeofday's 2nd arg as struct timezone*, glibc as void*.
#ifdef __BIONIC__
#define TZ_T struct timezone
#else
#define TZ_T void
#endif

typedef int (*cg_t)(clockid_t, struct timespec *);
typedef int (*gtod_t)(struct timeval *, TZ_T *);
typedef time_t (*time_fn)(time_t *);

static cg_t   real_cg;
static gtod_t real_gtod;
static time_fn real_time;

static int64_t g_off_ns = 0;
static time_t  g_last = 0;
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;

static void init_real(void) {
    if (!real_cg)   real_cg   = (cg_t)dlsym(RTLD_NEXT, "clock_gettime");
    if (!real_gtod) real_gtod = (gtod_t)dlsym(RTLD_NEXT, "gettimeofday");
    if (!real_time) real_time = (time_fn)dlsym(RTLD_NEXT, "time");
}

static const char *offset_file(void) {
    const char *e = getenv("TIMESHIFT_OFFSET_FILE");
    return (e && *e) ? e : TS_FILE;
}

static int64_t read_offset_seconds(void) {
#ifdef __BIONIC__
    char buf[64] = {0};
    if (__system_property_get(TS_PROP, buf) > 0 && buf[0]) {
        char *end = NULL;
        long long s = strtoll(buf, &end, 10);
        if (end != buf) return (int64_t)s;
    }
#endif
    FILE *f = fopen(offset_file(), "r");
    if (f) {
        long long s = 0;
        int ok = fscanf(f, "%lld", &s);
        fclose(f);
        if (ok == 1) return (int64_t)s;
    }
    return 0;
}

static void refresh(time_t now_real) {
    if (now_real - g_last < 1) return;            // throttle: once/sec
    pthread_mutex_lock(&g_lock);
    if (now_real - g_last >= 1) {
        g_last = now_real;
        g_off_ns = read_offset_seconds() * 1000000000LL;
    }
    pthread_mutex_unlock(&g_lock);
}

int clock_gettime(clockid_t clk, struct timespec *ts) {
    init_real();
    int r = real_cg(clk, ts);
    if (r == 0 && clk == CLOCK_REALTIME && ts) {
        refresh(ts->tv_sec);
        int64_t t = (int64_t)ts->tv_sec * 1000000000LL + ts->tv_nsec + g_off_ns;
        ts->tv_sec  = (time_t)(t / 1000000000LL);
        ts->tv_nsec = (long)(t % 1000000000LL);
    }
    return r;
}

int gettimeofday(struct timeval *tv, TZ_T *tz) {
    init_real();
    int r = real_gtod(tv, tz);
    if (r == 0 && tv) {
        refresh(tv->tv_sec);
        int64_t us = (int64_t)tv->tv_sec * 1000000LL + tv->tv_usec + g_off_ns / 1000LL;
        tv->tv_sec  = (time_t)(us / 1000000LL);
        tv->tv_usec = (long)(us % 1000000LL);
    }
    return r;
}

time_t time(time_t *tp) {
    struct timespec ts;
    if (clock_gettime(CLOCK_REALTIME, &ts) == 0) {
        if (tp) *tp = ts.tv_sec;
        return ts.tv_sec;
    }
    init_real();
    return real_time ? real_time(tp) : (time_t)-1;
}
