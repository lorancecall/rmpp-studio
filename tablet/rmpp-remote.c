// rmpp-remote: drive the reMarkable Paper Pro from a script (pen, touch, UI add-on commands).
//
// Pen and touch input is written straight into the digitizer's evdev nodes (/dev/input/event2 "Elan marker input",
// /dev/input/event3 "Elan touch input"). Writing to an evdev node injects the events into that input device, so
// xochitl reads them exactly like real hardware events (no uinput device, nothing to hot-plug).
// Coordinates are screen pixels of xochitl's window (portrait 1620 x 2160); the affine maps below turn them into
// device units (see `cal` and `rmpp-remote calibrate` in the README).
//
// Usage:
//   rmpp-remote [cmd ...]          run one command (the arguments) or, with none, a script from stdin
//   rmpp-remote ui <command>       send a command to the xochitl add-on (librmpp-remote.so) and print the reply
// Script commands (one per line, '#' comments, ';' also separates commands):
//   tap X Y [ms]                   finger tap (hold ms, default 60)
//   longpress X Y [ms]             finger long press (default 900 ms)
//   swipe X1 Y1 X2 Y2 [ms]         finger swipe
//   touch down|move X Y [slot] | touch up [slot]
//   pen down|move X Y [P] | pen hover X Y | pen up | pen out      P = pressure 0..1 (default 0.5)
//   stroke [P] [speed] : X,Y[,P] X,Y[,P] ...   pen polyline, interpolated (speed px/s, default 1200)
//   line X1 Y1 X2 Y2 [P] [speed]   straight pen line
//   eraser on|off                  following pen strokes use the eraser end (BTN_TOOL_RUBBER)
//   sleep MS
//   raw pen|touch TYPE CODE VALUE  one raw event (debugging)
//   ui <command>                   add-on command (reply printed)
//   cal                            print the screen->device maps
//   watch                          stream where the real pen / fingers are, read-only (see watch() below)
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <poll.h>
#include <signal.h>
#include <sys/time.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define PEN_DEV "/dev/input/event2"
#define TOUCH_DEV "/dev/input/event3"
#define CAL_FILE "/home/root/.config/rmpp-remote/cal"

// device = a*x + b*y + c (x, y = screen pixels); pen and touch digitizers have their own scales
typedef struct { double ax, bx, cx, ay, by, cy; } Map;
static Map pen_map = {11180.0 / 1620, 0, 0, 0, 15340.0 / 2160, 0};
static Map touch_map = {2064.0 / 1620, 0, 0, 0, 2832.0 / 2160, 0};
static const int PEN_MAX_X = 11180, PEN_MAX_Y = 15340, PEN_MAX_P = 4096;
static const int TOUCH_MAX_X = 2064, TOUCH_MAX_Y = 2832;

static int pen_fd = -1, touch_fd = -1;
static int pen_in = 0, pen_down = 0, rubber = 0;
static int tracking = 100;
static int touch_active[10];

static void die(const char *m) { fprintf(stderr, "rmpp-remote: %s: %s\n", m, strerror(errno)); exit(1); }

static void msleep(double ms) {
    if (ms <= 0) return;
    struct timespec ts = {(time_t)(ms / 1000), (long)(fmod(ms, 1000) * 1e6)};
    while (nanosleep(&ts, &ts) < 0 && errno == EINTR) {}
}

static int clampi(double v, int lo, int hi) { int i = (int)lround(v); return i < lo ? lo : i > hi ? hi : i; }

static void emit(int fd, int type, int code, int value) {
    struct input_event ev;
    memset(&ev, 0, sizeof ev);
    struct timeval tv;
    gettimeofday(&tv, NULL);
    ev.input_event_sec = tv.tv_sec;
    ev.input_event_usec = tv.tv_usec;
    ev.type = type;
    ev.code = code;
    ev.value = value;
    if (write(fd, &ev, sizeof ev) != sizeof ev) die("write event");
}
static void syn(int fd) { emit(fd, EV_SYN, SYN_REPORT, 0); }

static int pen(void) { if (pen_fd < 0 && (pen_fd = open(PEN_DEV, O_WRONLY | O_CLOEXEC)) < 0) die(PEN_DEV); return pen_fd; }
static int touch(void) { if (touch_fd < 0 && (touch_fd = open(TOUCH_DEV, O_WRONLY | O_CLOEXEC)) < 0) die(TOUCH_DEV); return touch_fd; }

static void load_cal(void) {
    FILE *f = fopen(CAL_FILE, "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof line, f)) {
        Map m;
        char which[16];
        if (sscanf(line, "%15s %lf %lf %lf %lf %lf %lf", which, &m.ax, &m.bx, &m.cx, &m.ay, &m.by, &m.cy) == 7) {
            if (!strcmp(which, "pen")) pen_map = m;
            else if (!strcmp(which, "touch")) touch_map = m;
        }
    }
    fclose(f);
}

// ---------- pen ----------

static void pen_xy(double x, double y) {
    int fd = pen();
    emit(fd, EV_ABS, ABS_X, clampi(pen_map.ax * x + pen_map.bx * y + pen_map.cx, 0, PEN_MAX_X));
    emit(fd, EV_ABS, ABS_Y, clampi(pen_map.ay * x + pen_map.by * y + pen_map.cy, 0, PEN_MAX_Y));
    emit(fd, EV_ABS, ABS_TILT_X, 0);
    emit(fd, EV_ABS, ABS_TILT_Y, 0);
}

static void pen_enter(double x, double y) {
    int fd = pen();
    if (pen_in) return;
    pen_xy(x, y);
    emit(fd, EV_ABS, ABS_DISTANCE, 60);
    emit(fd, EV_ABS, ABS_PRESSURE, 0);
    emit(fd, EV_KEY, rubber ? BTN_TOOL_RUBBER : BTN_TOOL_PEN, 1);
    syn(fd);
    pen_in = 1;
    msleep(20);
}

static void pen_hover(double x, double y) {
    pen_enter(x, y);
    pen_xy(x, y);
    emit(pen(), EV_ABS, ABS_DISTANCE, 60);
    syn(pen());
}

static void pen_press(double x, double y, double p) {
    int fd = pen();
    pen_enter(x, y);
    pen_xy(x, y);
    emit(fd, EV_ABS, ABS_DISTANCE, 0);
    emit(fd, EV_ABS, ABS_PRESSURE, clampi(p * PEN_MAX_P, 1, PEN_MAX_P));
    if (!pen_down) emit(fd, EV_KEY, BTN_TOUCH, 1);
    syn(fd);
    pen_down = 1;
}

static void pen_lift(void) {
    int fd = pen();
    if (pen_down) {
        emit(fd, EV_ABS, ABS_PRESSURE, 0);
        emit(fd, EV_ABS, ABS_DISTANCE, 60);
        emit(fd, EV_KEY, BTN_TOUCH, 0);
        syn(fd);
        pen_down = 0;
        msleep(10);
    }
}

static void pen_out(void) {
    pen_lift();
    if (!pen_in) return;
    int fd = pen();
    emit(fd, EV_ABS, ABS_DISTANCE, 255);
    emit(fd, EV_KEY, rubber ? BTN_TOOL_RUBBER : BTN_TOOL_PEN, 0);
    syn(fd);
    pen_in = 0;
}

// a polyline at `speed` px/s, one event every ~5 ms
typedef struct { double x, y, p; } Pt;
static void pen_poly(const Pt *pts, int n, double speed) {
    if (n <= 0) return;
    if (speed <= 0) speed = 1200;
    pen_press(pts[0].x, pts[0].y, pts[0].p);
    msleep(5);
    for (int i = 1; i < n; ++i) {
        double dx = pts[i].x - pts[i - 1].x, dy = pts[i].y - pts[i - 1].y;
        double len = sqrt(dx * dx + dy * dy);
        int steps = (int)ceil(len / (speed * 0.005));
        if (steps < 1) steps = 1;
        for (int s = 1; s <= steps; ++s) {
            double t = (double)s / steps;
            pen_press(pts[i - 1].x + dx * t, pts[i - 1].y + dy * t, pts[i - 1].p + (pts[i].p - pts[i - 1].p) * t);
            msleep(5);
        }
    }
    pen_lift();
}

// ---------- touch (multitouch protocol B) ----------

static void touch_xy(int slot, double x, double y) {
    int fd = touch();
    emit(fd, EV_ABS, ABS_MT_SLOT, slot);
    emit(fd, EV_ABS, ABS_MT_POSITION_X, clampi(touch_map.ax * x + touch_map.bx * y + touch_map.cx, 0, TOUCH_MAX_X));
    emit(fd, EV_ABS, ABS_MT_POSITION_Y, clampi(touch_map.ay * x + touch_map.by * y + touch_map.cy, 0, TOUCH_MAX_Y));
}

static void touch_down(int slot, double x, double y) {
    int fd = touch();
    emit(fd, EV_ABS, ABS_MT_SLOT, slot);
    if (!touch_active[slot]) {
        emit(fd, EV_ABS, ABS_MT_TRACKING_ID, tracking++);
        emit(fd, EV_ABS, ABS_MT_TOOL_TYPE, MT_TOOL_FINGER);
    }
    touch_xy(slot, x, y);
    emit(fd, EV_ABS, ABS_MT_PRESSURE, 80);
    emit(fd, EV_ABS, ABS_MT_TOUCH_MAJOR, 20);
    int any = 0;
    for (int i = 0; i < 10; ++i) any |= touch_active[i];
    if (!any) emit(fd, EV_KEY, BTN_TOUCH, 1);
    syn(fd);
    touch_active[slot] = 1;
}

static void touch_up(int slot) {
    int fd = touch();
    if (!touch_active[slot]) return;
    emit(fd, EV_ABS, ABS_MT_SLOT, slot);
    emit(fd, EV_ABS, ABS_MT_TRACKING_ID, -1);
    touch_active[slot] = 0;
    int any = 0;
    for (int i = 0; i < 10; ++i) any |= touch_active[i];
    if (!any) emit(fd, EV_KEY, BTN_TOUCH, 0);
    syn(fd);
}

static void swipe(double x1, double y1, double x2, double y2, double ms) {
    if (ms <= 0) ms = 300;
    int steps = (int)(ms / 8);
    if (steps < 2) steps = 2;
    touch_down(0, x1, y1);
    for (int s = 1; s <= steps; ++s) {
        msleep(ms / steps);
        double t = (double)s / steps;
        touch_down(0, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t);
    }
    msleep(20);
    touch_up(0);
}

// ---------- add-on socket ----------

static int ui(const char *cmd) {
    int s = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (s < 0) die("socket");
    struct sockaddr_un a;
    memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX;
    const char name[] = "rmpp-remote";
    memcpy(a.sun_path + 1, name, sizeof name - 1);
    socklen_t len = offsetof(struct sockaddr_un, sun_path) + 1 + sizeof name - 1;
    if (connect(s, (struct sockaddr *)&a, len) < 0) {
        fprintf(stderr, "rmpp-remote: add-on not reachable (is librmpp-remote.so loaded in xochitl?)\n");
        close(s);
        return 1;
    }
    struct timeval tv = {20, 0};
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    size_t n = strlen(cmd);
    if (write(s, cmd, n) != (ssize_t)n || write(s, "\n", 1) != 1) die("send");
    char buf[8192];
    ssize_t r;
    int err = 0, first = 1;
    while ((r = read(s, buf, sizeof buf)) > 0) {
        if (first && r >= 6 && !strncmp(buf, "error:", 6)) err = 1;
        first = 0;
        fwrite(buf, 1, r, stdout);
    }
    fflush(stdout);
    close(s);
    return err;
}

// ---------- script ----------

static int run(char *line) {
    while (*line == ' ' || *line == '\t') ++line;
    char *nl = strpbrk(line, "\r\n");
    if (nl) *nl = 0;
    if (!*line || *line == '#') return 0;
    if (!strncmp(line, "ui ", 3)) return ui(line + 3);

    char *argv[64];
    int argc = 0;
    char *colon = NULL;
    if (!strncmp(line, "stroke", 6) && (colon = strchr(line, ':'))) *colon++ = 0;
    for (char *t = strtok(line, " \t"); t && argc < 64; t = strtok(NULL, " \t")) argv[argc++] = t;
    if (!argc) return 0;
#define A(i, d) (argc > (i) ? atof(argv[i]) : (d))
    const char *c = argv[0];
    if (!strcmp(c, "sleep")) msleep(A(1, 100));
    else if (!strcmp(c, "tap")) { touch_down(0, A(1, 0), A(2, 0)); msleep(A(3, 60)); touch_up(0); }
    else if (!strcmp(c, "longpress")) { touch_down(0, A(1, 0), A(2, 0)); msleep(A(3, 900)); touch_up(0); }
    else if (!strcmp(c, "swipe")) swipe(A(1, 0), A(2, 0), A(3, 0), A(4, 0), A(5, 300));
    else if (!strcmp(c, "touch") && argc >= 2) {
        if (!strcmp(argv[1], "up")) touch_up((int)A(2, 0));
        else touch_down((int)A(4, 0), A(2, 0), A(3, 0));
    } else if (!strcmp(c, "pen") && argc >= 2) {
        if (!strcmp(argv[1], "down") || !strcmp(argv[1], "move")) pen_press(A(2, 0), A(3, 0), A(4, 0.5));
        else if (!strcmp(argv[1], "hover")) pen_hover(A(2, 0), A(3, 0));
        else if (!strcmp(argv[1], "up")) pen_lift();
        else if (!strcmp(argv[1], "out")) pen_out();
    } else if (!strcmp(c, "eraser") && argc >= 2) {
        pen_out();
        rubber = !strcmp(argv[1], "on");
    } else if (!strcmp(c, "line")) {
        double p = A(5, 0.5);
        Pt pts[2] = {{A(1, 0), A(2, 0), p}, {A(3, 0), A(4, 0), p}};
        pen_poly(pts, 2, A(6, 1200));
    } else if (!strcmp(c, "stroke")) {
        if (!colon) { fprintf(stderr, "stroke needs ': X,Y ...'\n"); return 1; }
        double p = A(1, 0.5), speed = A(2, 1200);
        int cap = 256, n = 0;
        Pt *pts = malloc(cap * sizeof *pts);
        for (char *t = strtok(colon, " \t"); t; t = strtok(NULL, " \t")) {
            Pt q = {0, 0, p};
            if (sscanf(t, "%lf,%lf,%lf", &q.x, &q.y, &q.p) < 2) continue;
            if (n == cap) pts = realloc(pts, (cap *= 2) * sizeof *pts);
            pts[n++] = q;
        }
        pen_poly(pts, n, speed);
        free(pts);
    } else if (!strcmp(c, "raw") && argc >= 5) {
        int fd = !strcmp(argv[1], "pen") ? pen() : touch();
        emit(fd, atoi(argv[2]), atoi(argv[3]), atoi(argv[4]));
    } else if (!strcmp(c, "cal")) {
        printf("pen   %g %g %g %g %g %g\ntouch %g %g %g %g %g %g\n", pen_map.ax, pen_map.bx, pen_map.cx, pen_map.ay,
               pen_map.by, pen_map.cy, touch_map.ax, touch_map.bx, touch_map.cx, touch_map.ay, touch_map.by, touch_map.cy);
    } else {
        fprintf(stderr, "rmpp-remote: unknown command '%s'\n", c);
        return 1;
    }
#undef A
    return 0;
}

// ---------- watch: report real pen / finger positions (read-only, for a cursor on the PC) ----------
// Lines (at most ~30 per second, plus every state change):
//   pen X Y P hover|down|eraser-hover|eraser-down     pen in range (P = pressure 0..1)
//   pen out                                           pen left the range
//   touch X Y[;X Y ...]                               fingers down (screen pixels)
//   touch none
// Several readers may open an evdev node, so this does not disturb xochitl.

static void inv(const Map *m, double dx, double dy, double *x, double *y) {
    double det = m->ax * m->by - m->bx * m->ay;
    if (det == 0) { *x = *y = 0; return; }
    dx -= m->cx;
    dy -= m->cy;
    *x = (m->by * dx - m->bx * dy) / det;
    *y = (-m->ay * dx + m->ax * dy) / det;
}

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}

static int watch(void) {
    int pfd = open(PEN_DEV, O_RDONLY | O_CLOEXEC), tfd = open(TOUCH_DEV, O_RDONLY | O_CLOEXEC);
    if (pfd < 0 || tfd < 0) die("open input devices");
    setvbuf(stdout, NULL, _IOLBF, 0);
    int px = 0, py = 0, pp = 0, in = 0, down = 0, rub = 0, slot = 0;
    int tx[10] = {0}, ty[10] = {0}, tid[10];
    for (int i = 0; i < 10; ++i) tid[i] = -1;
    int pen_dirty = 0, touch_dirty = 0;
    double last_pen = 0, last_touch = 0;
    // fds[2]: our stdout; POLLERR/POLLHUP there means the PC side went away (ssh closed), so exit instead of
    // lingering (a lingering process also keeps a replaced binary busy, so / cannot be remounted read-only)
    struct pollfd fds[3] = {{pfd, POLLIN, 0}, {tfd, POLLIN, 0}, {STDOUT_FILENO, 0, 0}};
    signal(SIGPIPE, SIG_DFL);
    double last_beat = now_ms();
    printf("watch ok\n");
    for (;;) {
        if (poll(fds, 3, 100) < 0 && errno != EINTR) die("poll");
        if (fds[2].revents & (POLLERR | POLLHUP | POLLNVAL)) return 0;
        if (now_ms() - last_beat > 10000) {   // heartbeat: writing to a closed pipe ends us too (SIGPIPE)
            printf("tick\n");
            last_beat = now_ms();
        }
        struct input_event ev[64];
        if (fds[0].revents & POLLIN) {
            ssize_t n = read(pfd, ev, sizeof ev);
            for (int i = 0; i < n / (ssize_t)sizeof ev[0]; ++i) {
                const struct input_event *e = &ev[i];
                if (e->type == EV_ABS && e->code == ABS_X) px = e->value;
                else if (e->type == EV_ABS && e->code == ABS_Y) py = e->value;
                else if (e->type == EV_ABS && e->code == ABS_PRESSURE) pp = e->value;
                else if (e->type == EV_KEY && (e->code == BTN_TOOL_PEN || e->code == BTN_TOOL_RUBBER)) {
                    in = e->value; rub = e->code == BTN_TOOL_RUBBER; pen_dirty = 2;
                } else if (e->type == EV_KEY && e->code == BTN_TOUCH) { down = e->value; pen_dirty = 2; }
                else if (e->type == EV_SYN && !pen_dirty) pen_dirty = 1;
            }
        }
        if (fds[1].revents & POLLIN) {
            ssize_t n = read(tfd, ev, sizeof ev);
            for (int i = 0; i < n / (ssize_t)sizeof ev[0]; ++i) {
                const struct input_event *e = &ev[i];
                if (e->type != EV_ABS) { if (e->type == EV_SYN && !touch_dirty) touch_dirty = 1; continue; }
                if (e->code == ABS_MT_SLOT && e->value >= 0 && e->value < 10) slot = e->value;
                else if (e->code == ABS_MT_TRACKING_ID) { tid[slot] = e->value; touch_dirty = 2; }
                else if (e->code == ABS_MT_POSITION_X) tx[slot] = e->value;
                else if (e->code == ABS_MT_POSITION_Y) ty[slot] = e->value;
            }
        }
        double t = now_ms();
        if (pen_dirty == 2 || (pen_dirty == 1 && t - last_pen >= 33)) {
            if (in) {
                double x, y;
                inv(&pen_map, px, py, &x, &y);
                printf("pen %d %d %.2f %s%s\n", (int)lround(x), (int)lround(y), pp / (double)PEN_MAX_P,
                       rub ? "eraser-" : "", down ? "down" : "hover");
            } else {
                printf("pen out\n");
            }
            pen_dirty = 0;
            last_pen = t;
        }
        if (touch_dirty == 2 || (touch_dirty == 1 && t - last_touch >= 33)) {
            char line[512] = "touch";
            int any = 0;
            for (int i = 0; i < 10; ++i) {
                if (tid[i] < 0) continue;
                double x, y;
                inv(&touch_map, tx[i], ty[i], &x, &y);
                char buf[32];
                snprintf(buf, sizeof buf, "%s%d %d", any ? ";" : " ", (int)lround(x), (int)lround(y));
                strncat(line, buf, sizeof line - strlen(line) - 1);
                any = 1;
            }
            printf("%s\n", any ? line : "touch none");
            touch_dirty = 0;
            last_touch = t;
        }
        if (ferror(stdout)) return 0;   // the PC side went away
    }
}

static int run_multi(char *s) {   // ';'-separated commands (not inside "ui ..." lines)
    int rc = 0;
    while (s && *s) {
        while (*s == ' ') ++s;
        if (!strncmp(s, "ui ", 3)) return rc | run(s);
        char *semi = strchr(s, ';');
        if (semi) *semi = 0;
        rc |= run(s);
        s = semi ? semi + 1 : NULL;
    }
    return rc;
}

int main(int argc, char **argv) {
    load_cal();
    if (argc == 2 && !strcmp(argv[1], "watch")) return watch();
    int rc = 0;
    if (argc > 1) {
        size_t n = 1;
        for (int i = 1; i < argc; ++i) n += strlen(argv[i]) + 1;
        char *line = calloc(n, 1);
        for (int i = 1; i < argc; ++i) { strcat(line, argv[i]); if (i + 1 < argc) strcat(line, " "); }
        rc = run_multi(line);
        free(line);
    } else {
        char *line = NULL;
        size_t cap = 0;
        while (getline(&line, &cap, stdin) > 0) rc |= run_multi(line);
        free(line);
    }
    pen_out();
    for (int i = 0; i < 10; ++i) touch_up(i);
    return rc;
}
