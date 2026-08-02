// ---------------------------------------------------------------------------
// What a shader pipeline costs on the device.
//
// Licence: MIT - Copyright (c) 2026 sinedied
//
// The target has no GPU timer query: GL_EXT_disjoint_timer_query appears in no
// driver report for this vendor, so there is nothing to ask the GPU how long it
// took. Everything here is wall clock around glFinish, which forces a full
// pipeline drain, and the method is built around that being the only tool:
//
//   - Time a BATCH of whole-pipeline renders, never one draw. A tiler schedules
//     per render target, so a single draw has no timeable boundary.
//   - Take the SLOPE of time against batch size, from two batch sizes. That
//     subtracts the fixed cost of the barrier and the first pass out of every
//     figure, so no absolute number has to be trusted.
//   - Interleave the cases, rotate which one goes first, and throw away a
//     run-in. Measuring each case to completion in turn lets clock drift land
//     on whichever ran first.
//   - Report the median and the IQR. One hitch anywhere decides a min-to-max
//     range, and the runs are minutes long.
//
// The one thing that could make all of this quietly meaningless is hidden
// surface removal: this GPU is documented as removing overdraw entirely for
// opaque renders, so a repeated draw can cost nothing while looking healthy.
// --self-test measures that directly, and nothing here should be believed until
// it passes. See docs/device-perf.md.
//
//   bench --self-test            check the instrument, not the shaders
//   bench                        the table
//   bench --list                 what it would run
//   bench --out FILE             also write the TSV there
// ---------------------------------------------------------------------------

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "bench.h"

#ifndef SHADER_ROOT
#define SHADER_ROOT "."
#endif

// How long a timed batch should take. Long enough that the barrier at each end
// is a rounding error, short enough that the run stays minutes rather than
// hours. Fixed batch counts do not work: the same 16 renders is 60ms of work on
// the handheld and under a millisecond on a desktop, where it measured the
// glFinish round trip and reported an r2 of 0.68.
static double TARGET_BATCH_MS = 20.0;

static int PASSES = 11;
static int WARMUP = 5;
// Unmeasured renders before each pass. The GPU drops its clocks while the CPU
// does bookkeeping between passes, and whatever is measured first eats the
// ramp.
static int BURST = 40;

static const double CORE_ASPECT = 4.0 / 3.0;

typedef struct {
    Pipeline p;
    double   slope[64];
    int      n;
    // Batch sizes, chosen from this pipeline's own measured cost.
    int      n_lo, n_hi;
    // Fragment cost of the chain, measured without the render passes around it.
    double   frag_ms;
} Case;

// ---------------------------------------------------------------------------
// statistics

static int cmp_double(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return x < y ? -1 : x > y ? 1 : 0;
}

static double percentile(double *sorted, int n, double f)
{
    if (n <= 0)
        return 0.0;
    if (n == 1)
        return sorted[0];
    double pos = (n - 1) * f;
    int lo = (int)pos;
    int hi = lo + 1 < n ? lo + 1 : lo;
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

static void summarise(double *values, int n, double *median, double *iqr)
{
    double sorted[64];
    if (n > 64)
        n = 64;
    memcpy(sorted, values, (size_t)n * sizeof(double));
    qsort(sorted, (size_t)n, sizeof(double), cmp_double);
    *median = percentile(sorted, n, 0.5);
    *iqr = percentile(sorted, n, 0.75) - percentile(sorted, n, 0.25);
}

// ---------------------------------------------------------------------------
// the device, as far as it will say

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1.0e6;
}

static long read_long(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f)
        return -1;
    long v = -1;
    if (fscanf(f, "%ld", &v) != 1)
        v = -1;
    fclose(f);
    return v;
}

// Thermals and CPU clock, because GPU DVFS is not exposed on this platform:
// the GPU sits at a fixed operating point with dynamic scaling off, which
// cannot be verified from userspace. Drift in these is the only warning
// available that a long run stopped being comparable to its own start.
static void read_sensors(long *cpu_temp, long *gpu_temp, long *cpu_khz)
{
    *cpu_temp = read_long("/sys/devices/virtual/thermal/thermal_zone0/temp");
    *gpu_temp = read_long("/sys/devices/virtual/thermal/thermal_zone2/temp");
    *cpu_khz  = read_long("/sys/devices/system/cpu/cpu0/cpufreq/"
                          "scaling_cur_freq");
}

// ---------------------------------------------------------------------------
// declarations, read from tools/baseline.toml
//
// Only [settings.device] and the [[pipeline]] stanzas are understood. Reading
// the same file the Python tools read is the point: a pipeline that exists in
// one place and not the other is the defect this avoids.

typedef struct {
    char label[MAX_NAME];
    char cfg[MAX_NAME];
} Declared;

static char *toml_string(const char *line, const char *key, char *out,
                         size_t out_size)
{
    size_t klen = strlen(key);
    const char *p = line;
    while (*p == ' ' || *p == '\t')
        p++;
    if (strncmp(p, key, klen) != 0)
        return NULL;
    p += klen;
    while (*p == ' ' || *p == '\t')
        p++;
    if (*p != '=')
        return NULL;
    p = strchr(p, '"');
    if (!p)
        return NULL;
    const char *end = strchr(p + 1, '"');
    if (!end)
        return NULL;
    size_t n = (size_t)(end - p - 1);
    if (n >= out_size)
        n = out_size - 1;
    memcpy(out, p + 1, n);
    out[n] = '\0';
    return out;
}

static int toml_pair(const char *line, const char *key, int *a, int *b)
{
    size_t klen = strlen(key);
    const char *p = line;
    while (*p == ' ' || *p == '\t')
        p++;
    if (strncmp(p, key, klen) != 0)
        return 0;
    p = strchr(p, '[');
    return p && sscanf(p, "[%d, %d]", a, b) == 2;
}

static int load_manifest(const char *path, Declared *out, int max,
                         Bench *bench)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return -1;
    }
    int n = 0, in_pipeline = 0;
    char line[1024], buf[MAX_NAME];
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "[[pipeline]]", 12) == 0) {
            if (n >= max)
                break;
            in_pipeline = 1;
            out[n].label[0] = '\0';
            out[n].cfg[0] = '\0';
            n++;
            continue;
        }
        if (line[0] == '[') {
            in_pipeline = 0;
            continue;
        }
        if (in_pipeline && n > 0) {
            if (toml_string(line, "label", buf, sizeof(buf)))
                snprintf(out[n - 1].label, sizeof(out[n - 1].label),
                         "%s", buf);
            else if (toml_string(line, "cfg", buf, sizeof(buf)))
                snprintf(out[n - 1].cfg, sizeof(out[n - 1].cfg), "%s", buf);
            continue;
        }
        int a, b;
        if (toml_pair(line, "source", &a, &b)) {
            bench->src_w = a;
            bench->src_h = b;
        } else if (toml_pair(line, "output", &a, &b)) {
            bench->out_w = a;
            bench->out_h = b;
        } else if (strncmp(line, "budget_ms", 9) == 0) {
            const char *eq = strchr(line, '=');
            if (eq)
                bench->budget_ms = atof(eq + 1);
        }
    }
    fclose(f);
    return n;
}

// ---------------------------------------------------------------------------
// GL setup

// A deterministic noise field. Noise rather than a picture because it defeats
// every texture cache equally, so a shader that taps more is not flattered by
// the sample happening to be flat.
static void upload_source(Bench *b)
{
    int n = b->src_w * b->src_h;
    unsigned char *px = malloc((size_t)n * 4);
    unsigned int state = 12345u;
    for (int i = 0; i < n; i++) {
        for (int c = 0; c < 3; c++) {
            state = state * 1103515245u + 12345u;
            px[i * 4 + c] = (unsigned char)((state >> 16) & 0xFF);
        }
        px[i * 4 + 3] = 255;
    }
    glGenTextures(1, &b->source_tex);
    glBindTexture(GL_TEXTURE_2D, b->source_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, b->src_w, b->src_h, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    free(px);
}

static int make_screen(Bench *b)
{
    glGenTextures(1, &b->screen_tex);
    glBindTexture(GL_TEXTURE_2D, b->screen_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, b->out_w, b->out_h, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glGenFramebuffers(1, &b->screen_fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, b->screen_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, b->screen_tex, 0);
    return glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
}

// ---------------------------------------------------------------------------
// timing

static double time_batch(Bench *b, Pipeline *p, int repeats)
{
    glFinish();
    double t0 = now_ms();
    for (int i = 0; i < repeats; i++)
        pipeline_render(b, p, i);
    glFinish();
    return now_ms() - t0;
}

// One render's cost, with the fixed cost of the barrier and the run-up removed.
static double slope_of(Bench *b, Pipeline *p, int lo, int hi)
{
    double t_lo = time_batch(b, p, lo);
    double t_hi = time_batch(b, p, hi);
    return (t_hi - t_lo) / (hi - lo);
}

static void warm(Bench *b, Pipeline *p)
{
    for (int i = 0; i < BURST; i++)
        pipeline_render(b, p, i);
    glFinish();
}

// The median of several timed batches. The table gets its stability from
// running many interleaved passes; the self-test has to buy the same stability
// inside a single check, or it reports on the scheduler instead of the GPU.
static double median_batch(Bench *b, Pipeline *p, int repeats, int reps)
{
    double v[17];
    if (reps > 17)
        reps = 17;
    for (int i = 0; i < reps; i++)
        v[i] = time_batch(b, p, repeats);
    qsort(v, (size_t)reps, sizeof(double), cmp_double);
    return v[reps / 2];
}

static double robust_slope(Bench *b, Pipeline *p, int lo, int hi, int reps)
{
    double t_lo = median_batch(b, p, lo, reps);
    double t_hi = median_batch(b, p, hi, reps);
    return (t_hi - t_lo) / (hi - lo);
}

// Batch sizes for one pipeline, from what one render of it actually costs.
static void calibrate(Bench *b, Case *k)
{
    warm(b, &k->p);
    double per = median_batch(b, &k->p, 8, 5) / 8.0;
    int n = per > 0.0 ? (int)(TARGET_BATCH_MS / per) : 64;
    if (n < 8)
        n = 8;
    if (n > 8192)
        n = 8192;
    k->n_hi = n;
    k->n_lo = n / 4 < 2 ? 2 : n / 4;
}

// Defined with the self-test helpers below, because that is where the rest of
// the overdraw machinery lives; used here for the frag_ms column.
static double overdraw_slope(Bench *b, Pipeline *p, const double *counts,
                             int n, int reps);

static void measure(Bench *b, Case *cases, int n_cases)
{
    for (int i = 0; i < n_cases; i++)
        cases[i].n = 0;

    // Every program warmed and sized before any is timed: the first render of a
    // program pays for its own upload and would be charged to whoever ran
    // first.
    for (int i = 0; i < n_cases; i++)
        calibrate(b, &cases[i]);

    for (int pass = 0; pass < WARMUP + PASSES; pass++) {
        warm(b, &cases[0].p);
        for (int k = 0; k < n_cases; k++) {
            int idx = (pass + k) % n_cases;
            double s = slope_of(b, &cases[idx].p, cases[idx].n_lo,
                                cases[idx].n_hi);
            if (pass >= WARMUP && cases[idx].n < 64)
                cases[idx].slope[cases[idx].n++] = s;
        }
    }

    // Fragment cost last, once, from the batch sizes already calibrated. It
    // answers a different question from the frame figure: which shader is
    // dearer, rather than whether the frame fits.
    double counts[5];
    for (int i = 0; i < n_cases; i++) {
        for (int k = 0; k < 5; k++)
            counts[k] = (double)(cases[i].n_hi * (k + 1)) / 5.0;
        cases[i].frag_ms = overdraw_slope(b, &cases[i].p, counts, 5, 7);
    }
}

// ---------------------------------------------------------------------------
// self-test

static double fit_r2(const double *x, const double *y, int n)
{
    double sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (int i = 0; i < n; i++) {
        sx += x[i];
        sy += y[i];
        sxx += x[i] * x[i];
        sxy += x[i] * y[i];
    }
    double denom = n * sxx - sx * sx;
    if (denom == 0.0)
        return 0.0;
    double slope = (n * sxy - sx * sy) / denom;
    double intercept = (sy - slope * sx) / n;
    double mean = sy / n, ss_res = 0, ss_tot = 0;
    for (int i = 0; i < n; i++) {
        double pred = slope * x[i] + intercept;
        ss_res += (y[i] - pred) * (y[i] - pred);
        ss_tot += (y[i] - mean) * (y[i] - mean);
    }
    return ss_tot == 0.0 ? 0.0 : 1.0 - ss_res / ss_tot;
}

static double fit_slope(const double *x, const double *y, int n)
{
    double sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (int i = 0; i < n; i++) {
        sx += x[i];
        sy += y[i];
        sxx += x[i] * x[i];
        sxy += x[i] * y[i];
    }
    double denom = n * sxx - sx * sx;
    return denom == 0.0 ? 0.0 : (n * sxy - sx * sy) / denom;
}

// A PPM of what a pipeline actually drew. Timings cannot see a pipeline that
// renders the wrong thing quickly, and in this repo a version once passed every
// number in the harness while having cropped its image off-screen.
static int dump_ppm(Bench *b, const char *path)
{
    int n = b->out_w * b->out_h;
    unsigned char *px = malloc((size_t)n * 4);
    if (!px)
        return 0;
    glBindFramebuffer(GL_FRAMEBUFFER, b->screen_fbo);
    glReadPixels(0, 0, b->out_w, b->out_h, GL_RGBA, GL_UNSIGNED_BYTE, px);
    FILE *f = fopen(path, "wb");
    if (!f) {
        free(px);
        return 0;
    }
    fprintf(f, "P6\n%d %d\n255\n", b->out_w, b->out_h);
    // glReadPixels hands back the bottom row first; PPM wants the top row.
    for (int y = b->out_h - 1; y >= 0; y--)
        for (int x = 0; x < b->out_w; x++)
            fwrite(px + ((size_t)y * b->out_w + x) * 4, 1, 3, f);
    fclose(f);
    free(px);
    return 1;
}

static int report(int ok, const char *name, const char *fmt, ...)
{
    va_list args;
    printf("  %-4s %-34s ", ok ? "ok" : "FAIL", name);
    va_start(args, fmt);
    vprintf(fmt, args);
    va_end(args);
    printf("\n");
    return ok ? 0 : 1;
}

// A check about the machine rather than about the instrument. It is worth
// printing and not worth refusing to measure over: the benchmark cannot make a
// busy laptop stop drifting, and the per-case IQR in the table says the same
// thing measured over the whole run instead of over one pair.
static void warn(int ok, const char *name, const char *fmt, ...)
{
    va_list args;
    printf("  %-4s %-34s ", ok ? "ok" : "warn", name);
    va_start(args, fmt);
    vprintf(fmt, args);
    va_end(args);
    printf("%s\n", ok ? "" : "   <- read the IQR column with suspicion");
}

static double overdraw_batch(Bench *b, Pipeline *p, int index, int n,
                             int blend)
{
    glFinish();
    double t0 = now_ms();
    pipeline_overdraw(b, p, index, n, blend);
    glFinish();
    return now_ms() - t0;
}

// A batch-time series over several sizes, measured in rotated rounds. Taking
// the sizes in order does not work: the smallest is always measured first,
// while the GPU is still coming up to clock, so the curve bends and reads as
// non-linear. That cost an r2 of 0.95 on a series that was fine.
static void series_batch(Bench *b, Pipeline *p, const double *sizes, int n,
                         double *out, int reps)
{
    double v[5][17];
    if (n > 5)
        n = 5;
    if (reps > 17)
        reps = 17;
    for (int r = 0; r < reps; r++)
        for (int k = 0; k < n; k++) {
            int i = (k + r) % n;
            v[i][r] = time_batch(b, p, (int)sizes[i]);
        }
    for (int i = 0; i < n; i++) {
        qsort(v[i], (size_t)reps, sizeof(double), cmp_double);
        out[i] = v[i][reps / 2];
    }
}

static void series_overdraw(Bench *b, Pipeline *p, int index,
                            const double *counts, int n,
                            int blend, double *out, int reps)
{
    double v[5][17];
    if (n > 5)
        n = 5;
    if (reps > 17)
        reps = 17;
    for (int r = 0; r < reps; r++)
        for (int k = 0; k < n; k++) {
            int i = (k + r) % n;
            v[i][r] = overdraw_batch(b, p, index, (int)counts[i],
                                     blend);
        }
    for (int i = 0; i < n; i++) {
        qsort(v[i], (size_t)reps, sizeof(double), cmp_double);
        out[i] = v[i][reps / 2];
    }
}

// Fragment cost alone: N quads in ONE render pass, so the slope carries no
// per-pass tile store or driver overhead. That is the number to compare two
// shaders with; per frame, a cheap shader and an expensive one can look alike
// because the render pass around them costs more than either.
// Every pass of a chain, summed: what the fragment shaders cost between them,
// with none of the per-pass overhead the frame figure also carries.
static double overdraw_slope(Bench *b, Pipeline *p, const double *counts,
                             int n, int reps)
{
    double total = 0.0;
    for (int i = 0; i < p->n_passes; i++) {
        double t[5];
        series_overdraw(b, p, i, counts, n, 1, t, reps);
        total += fit_slope(counts, t, n < 5 ? n : 5);
    }
    return total;
}

static int self_test(Bench *b, Case *cases, int n_cases, Case *floor_case)
{
    int failures = 0;
    long t0c, t0g, f0, t1c, t1g, f1;
    read_sensors(&t0c, &t0g, &f0);

    printf("self-test\n");

    Case *ref = &cases[0];
    calibrate(b, ref);
    calibrate(b, floor_case);

    // 1. Linearity, and what one whole render costs. This has to come first,
    //    because it is the reference every later check is read against: an
    //    absolute figure proves nothing on its own, but it says what the other
    //    probes OUGHT to be measuring. If the driver were dropping whole
    //    repeats, batch time would stop growing with batch size.
    double sizes[5];
    for (int i = 0; i < 5; i++)
        sizes[i] = (double)(ref->n_hi * (i + 1)) / 5.0;
    double times[5];
    series_batch(b, &ref->p, sizes, 5, times, 9);
    double r2 = fit_r2(sizes, times, 5);
    double per_render = fit_slope(sizes, times, 5);
    printf("       %-34s", "batch");
    for (int i = 0; i < 5; i++)
        printf(" %8.0f", sizes[i]);
    printf("\n       %-34s", "ms");
    for (int i = 0; i < 5; i++)
        printf(" %8.3f", times[i]);
    printf("\n");
    // 0.98, not 0.99: what this catches is a driver dropping whole repeats,
    // which collapses the curve rather than nudging it. A threshold tight
    // enough to fail on ordinary clock wobble would be a threshold that fails
    // for reasons that have nothing to do with the question.
    failures += report(r2 >= 0.98, "batch time is linear in batch size",
                       "r2 = %.4f, %.4f ms per render", r2, per_render);

    // 2. The floor. A pipeline with no shader pass still blits to the screen,
    //    so its cost is what filling the output costs before any shader. A
    //    floor of zero means the final pass is being elided across repeats and
    //    every figure is missing it.
    double floor_ms = robust_slope(b, &floor_case->p,
                                  floor_case->n_lo, floor_case->n_hi, 9);
    failures += report(floor_ms > 0.0, "final blit is not elided",
                       "%.4f ms with no shader pass", floor_ms);

    // 3. Hidden surface removal. This GPU removes overdraw entirely for opaque
    //    renders, so a repeated draw can cost nothing while looking healthy,
    //    and any figure built on repeats would be fiction. Blending is what
    //    stops it.
    //
    //    MEASURED AGAINST WHAT A QUAD SHOULD COST, not against zero. The
    //    reference pipeline is one shader pass plus the final blit, so one more
    //    quad of that shader is about (per_render - floor). Asserting only that
    //    the slope is positive is not a test: on the device it passed at 0.016
    //    ms per quad against an expected 11.9, because 7 of every 8 draws had
    //    been removed and the eighth had not.
    double counts[5];
    for (int i = 0; i < 5; i++) {
        counts[i] = (double)(ref->n_hi * (i + 1)) / 5.0;
        if (counts[i] < 2.0)
            counts[i] = 2.0;
    }
    double opaque[5], blended[5];
    series_overdraw(b, &ref->p, 0, counts, 5, 0, opaque, 7);
    series_overdraw(b, &ref->p, 0, counts, 5, 1, blended, 7);
    double s_opaque = fit_slope(counts, opaque, 5);
    double s_blended = fit_slope(counts, blended, 5);
    double expect = per_render - floor_ms;
    printf("       %-34s", "quads");
    for (int i = 0; i < 5; i++)
        printf(" %8.0f", counts[i]);
    printf("\n       %-34s", "opaque ms");
    for (int i = 0; i < 5; i++)
        printf(" %8.3f", opaque[i]);
    printf("\n       %-34s", "blended ms");
    for (int i = 0; i < 5; i++)
        printf(" %8.3f", blended[i]);
    printf("\n");
    failures += report(expect > 0.0 && s_blended > expect * 0.5,
                       "a blended repeat costs what it should",
                       "%.4f ms per quad, against %.4f expected",
                       s_blended, expect);
    printf("       %-34s %.4f ms per quad%s\n", "opaque repeat",
           s_opaque,
           (expect > 0.0 && s_opaque < expect * 0.5)
           ? "   <- removed, as the vendor documents" : "");

    // 4. Repeatability. The two runs are INTERLEAVED, not run one after the
    //    other: measured in sequence, the whole of any clock drift lands on
    //    the second one and the check reports the drift rather than the
    //    repeatability. That read -21% on a laptop.
    double sa[13], sc[13];
    for (int i = 0; i < 13; i++) {
        sa[i] = slope_of(b, &ref->p, ref->n_lo, ref->n_hi);
        sc[i] = slope_of(b, &ref->p, ref->n_lo, ref->n_hi);
    }
    qsort(sa, 13, sizeof(double), cmp_double);
    qsort(sc, 13, sizeof(double), cmp_double);
    double a = sa[6], c = sc[6];
    double drift = a > 0 ? (c - a) / a * 100.0 : 0.0;
    warn(drift > -10.0 && drift < 10.0, "two interleaved runs agree",
         "%+.1f%% between them", drift);

    // 5. Direction. sharp-shimmerless takes one tap and no transcendental, so
    //    it cannot be the expensive one. Read per frame, which is the column
    //    the table publishes.
    //
    //    Matched exactly, not by substring. Substring matching took the LAST
    //    label containing "shimmerless", which the moment the reference stacks
    //    were declared was "shimmerless -> lcd1x -> adjust" - three passes, and
    //    the check then failed for measuring something else entirely.
    Case *cheapest = NULL;
    for (int i = 0; i < n_cases && !cheapest; i++)
        if (strcmp(cases[i].p.label, "sharp-shimmerless") == 0)
            cheapest = &cases[i];
    if (cheapest) {
        calibrate(b, cheapest);
        double one_tap = robust_slope(b, &cheapest->p, cheapest->n_lo,
                                      cheapest->n_hi, 9);
        failures += report(one_tap <= per_render * 1.05,
                           "the one-tap shader is the cheaper",
                           "%.4f vs %.4f ms per frame", one_tap, per_render);
    }

    read_sensors(&t1c, &t1g, &f1);
    if (t0c > 0)
        printf("       %-34s %ld -> %ld mC cpu, %ld -> %ld mC gpu\n",
               "temperature over the run", t0c, t1c, t0g, t1g);

    printf("\nself-test: %s\n", failures ? "FAILED" : "passed");
    if (failures)
        printf("The instrument is measuring something other than the shader. "
               "Do not read the table.\n");
    return failures;
}

// ---------------------------------------------------------------------------

static void print_table(Bench *b, Case *cases, int n_cases, FILE *out)
{
    double median[MAX_PIPELINES], iqr[MAX_PIPELINES];
    for (int i = 0; i < n_cases; i++)
        summarise(cases[i].slope, cases[i].n, &median[i], &iqr[i]);
    double base = median[0] > 0 ? median[0] : 1.0;

    fprintf(out, "# %dx%d source into %dx%d output, %.4f ms budget\n",
            b->src_w, b->src_h, b->out_w, b->out_h, b->budget_ms);
    fprintf(out, "# renderer\t%s\n", (const char *)glGetString(GL_RENDERER));
    fprintf(out, "# version\t%s\n", (const char *)glGetString(GL_VERSION));
    fprintf(out, "# method\tslope of wall clock over two batch sizes, each "
                 "sized to about %.0f ms of work, median of %d interleaved "
                 "passes after %d discarded\n", TARGET_BATCH_MS, PASSES,
            WARMUP);
    long tc, tg, khz;
    read_sensors(&tc, &tg, &khz);
    if (tc > 0)
        fprintf(out, "# sensors\tcpu %ld mC, gpu %ld mC, cpu clock %ld kHz\n",
                tc, tg, khz);
    fprintf(out, "# ms is one whole frame: every pass plus the final blit.\n");
    fprintf(out, "# frag_ms is the fragment shaders alone, with the render "
                 "passes around them removed.\n");
    fprintf(out, "pipeline\tpasses\tms\tiqr_pct\tbudget_pct\trelative_pct"
                 "\tfrag_ms\n");
    for (int i = 0; i < n_cases; i++) {
        fprintf(out, "%s\t%d\t%.4f\t%.1f\t%.1f\t%.1f\t%.4f\n",
                cases[i].p.label, cases[i].p.n_passes, median[i],
                median[i] > 0 ? iqr[i] / median[i] * 100.0 : 0.0,
                median[i] / b->budget_ms * 100.0,
                base / median[i] * 100.0, cases[i].frag_ms);
    }
}

static int usage(void)
{
    fprintf(stderr,
            "usage: bench [--self-test] [--list] [--out FILE] [--root DIR]\n"
            "             [--passes N] [--warmup N] [--batch-ms MS]\n");
    return 2;
}

int main(int argc, char **argv)
{
    const char *root = SHADER_ROOT;
    const char *out_path = NULL;
    const char *dump_dir = NULL;
    int want_self_test = 0, want_list = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--self-test") == 0)
            want_self_test = 1;
        else if (strcmp(argv[i], "--list") == 0)
            want_list = 1;
        else if (strcmp(argv[i], "--out") == 0 && i + 1 < argc)
            out_path = argv[++i];
        else if (strcmp(argv[i], "--dump") == 0 && i + 1 < argc)
            dump_dir = argv[++i];
        else if (strcmp(argv[i], "--root") == 0 && i + 1 < argc)
            root = argv[++i];
        else if (strcmp(argv[i], "--passes") == 0 && i + 1 < argc)
            PASSES = atoi(argv[++i]);
        else if (strcmp(argv[i], "--warmup") == 0 && i + 1 < argc)
            WARMUP = atoi(argv[++i]);
        else if (strcmp(argv[i], "--batch-ms") == 0 && i + 1 < argc)
            TARGET_BATCH_MS = atof(argv[++i]);
        else
            return usage();
    }

    Bench b;
    memset(&b, 0, sizeof(b));
    b.src_w = 320;
    b.src_h = 240;
    b.out_w = 1024;
    b.out_h = 768;
    b.budget_ms = 1000.0 / 60.0;

    char manifest[512], pipedir[512], vendordir[512], shaderdir[512];
    char optimizeddir[512], iterdir[512];
    snprintf(manifest, sizeof(manifest), "%s/tools/baseline.toml", root);
    snprintf(pipedir, sizeof(pipedir), "%s/tools/device/pipelines", root);
    snprintf(vendordir, sizeof(vendordir), "%s/tools/vendor", root);
    snprintf(shaderdir, sizeof(shaderdir), "%s/shaders", root);
    snprintf(optimizeddir, sizeof(optimizeddir), "%s/tools/optimized", root);
    snprintf(iterdir, sizeof(iterdir), "%s/tools/iterations", root);

    Declared declared[MAX_PIPELINES];
    int n_declared = load_manifest(manifest, declared, MAX_PIPELINES, &b);
    if (n_declared <= 0) {
        fprintf(stderr, "no pipelines declared in %s\n", manifest);
        return 1;
    }

    if (want_list) {
        printf("%dx%d -> %dx%d, %.4f ms budget\n", b.src_w, b.src_h,
               b.out_w, b.out_h, b.budget_ms);
        for (int i = 0; i < n_declared; i++)
            printf("  %-24s %s\n", declared[i].label, declared[i].cfg);
        return 0;
    }

    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
#if defined(BENCH_GLES)
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_ES);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 0);
#else
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,
                        SDL_GL_CONTEXT_PROFILE_CORE);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 4);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 1);
#endif
    // Shown on the device, hidden on the desktop. Nothing is ever presented, so
    // the window only exists to hang a GL context off - but a hidden window is
    // not reliably enough to get one from a framebuffer driver, and on the
    // device there is no desktop for it to interrupt anyway.
#if defined(BENCH_GLES)
    Uint32 window_flags = SDL_WINDOW_OPENGL | SDL_WINDOW_SHOWN;
#else
    Uint32 window_flags = SDL_WINDOW_OPENGL | SDL_WINDOW_HIDDEN;
#endif
    SDL_Window *window = SDL_CreateWindow("shaderbench",
                                          SDL_WINDOWPOS_UNDEFINED,
                                          SDL_WINDOWPOS_UNDEFINED,
                                          b.out_w, b.out_h, window_flags);
    if (!window) {
        fprintf(stderr, "SDL_CreateWindow: %s\n", SDL_GetError());
        return 1;
    }
    SDL_GLContext gl = SDL_GL_CreateContext(window);
    if (!gl) {
        fprintf(stderr, "SDL_GL_CreateContext: %s\n", SDL_GetError());
        return 1;
    }
    // Nothing is ever presented, so the swap interval only matters in that a
    // vsync wait must never land inside a measurement. It is a no-op on this
    // platform anyway.
    SDL_GL_SetSwapInterval(0);

#if !defined(BENCH_GLES)
    GLuint vao = 0;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
#endif

    upload_source(&b);
    if (!make_screen(&b)) {
        fprintf(stderr, "screen framebuffer incomplete\n");
        return 1;
    }
    static const GLfloat quad[] = {
        -1.0f,  1.0f, 0.0f, 1.0f,  0.0f, 1.0f, 0.0f, 0.0f,
        -1.0f, -1.0f, 0.0f, 1.0f,  0.0f, 0.0f, 0.0f, 0.0f,
         1.0f,  1.0f, 0.0f, 1.0f,  1.0f, 1.0f, 0.0f, 0.0f,
         1.0f, -1.0f, 0.0f, 1.0f,  1.0f, 0.0f, 0.0f, 0.0f,
    };
    glGenBuffers(1, &b.quad_vbo);
    glBindBuffer(GL_ARRAY_BUFFER, b.quad_vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);

    char devicedir[512];
    snprintf(devicedir, sizeof(devicedir), "%s/tools/device", root);
    if (!shader_load(&b.final_pass, devicedir, "final-pass.glsl")) {
        fprintf(stderr, "cannot load the final scale pass\n");
        return 1;
    }

    const char *dirs[5] = { shaderdir, vendordir, optimizeddir, iterdir,
                            devicedir };
    static Case cases[MAX_PIPELINES];
    int n_cases = 0;
    for (int i = 0; i < n_declared; i++) {
        char path[600];
        snprintf(path, sizeof(path), "%s/%s", pipedir, declared[i].cfg);
        Pipeline *p = &cases[n_cases].p;
        memset(p, 0, sizeof(*p));
        if (!cfg_load(p, path))
            return 1;
        snprintf(p->label, sizeof(p->label), "%s", declared[i].label);
        Rect dst = pipeline_dst_rect(p->scaling, b.src_w, b.src_h,
                                     b.out_w, b.out_h, CORE_ASPECT);
        // Every pipeline in one table has to fill the same area, or the ms
        // column is comparing a shader against a smaller picture of one.
        if (i > 0 && (dst.w != b.dst.w || dst.h != b.dst.h)) {
            fprintf(stderr, "%s: %s scaling gives %dx%d, but the table is "
                            "%dx%d\n", p->label, p->scaling, dst.w, dst.h,
                    b.dst.w, b.dst.h);
            return 1;
        }
        b.dst = dst;
        if (!pipeline_build(p, &b, dirs, 5))
            return 1;
        n_cases++;
    }

    // The floor: the same chain with nothing in it, so the final blit and the
    // clear are measured on their own.
    static Case floor_case;
    memset(&floor_case, 0, sizeof(floor_case));
    snprintf(floor_case.p.label, sizeof(floor_case.p.label), "%s",
             "no shader (floor)");
    floor_case.p.n_passes = 0;
    floor_case.p.scale_filter = GL_NEAREST;
    snprintf(floor_case.p.scaling, sizeof(floor_case.p.scaling), "Aspect");

    int status = 0;
    if (dump_dir) {
        for (int i = 0; i < n_cases; i++) {
            char path[700];
            char safe[MAX_NAME + 8];
            snprintf(safe, sizeof(safe), "%s", cases[i].p.label);
            for (char *s = safe; *s; s++)
                if (*s == ' ' || *s == '>')
                    *s = '_';
            snprintf(path, sizeof(path), "%s/%s.ppm", dump_dir, safe);
            pipeline_render(&b, &cases[i].p, 0);
            glFinish();
            if (!dump_ppm(&b, path)) {
                fprintf(stderr, "cannot write %s\n", path);
                status = 1;
            } else {
                printf("%s\n", path);
            }
        }
    } else if (want_self_test) {
        status = self_test(&b, cases, n_cases, &floor_case);
    } else {        measure(&b, cases, n_cases);
        print_table(&b, cases, n_cases, stdout);
        if (out_path) {
            FILE *f = fopen(out_path, "w");
            if (f) {
                print_table(&b, cases, n_cases, f);
                fclose(f);
            } else {
                fprintf(stderr, "cannot write %s\n", out_path);
                status = 1;
            }
        }
    }

    for (int i = 0; i < n_cases; i++)
        pipeline_free(&cases[i].p);
    shader_free(&b.final_pass);
    SDL_GL_DeleteContext(gl);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return status;
}
