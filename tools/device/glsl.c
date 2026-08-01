// ---------------------------------------------------------------------------
// Loading a RetroArch-style single-file shader the way the frontend does.
//
// Licence: MIT - Copyright (c) 2026 sinedied
//
// Four transformations, and they have to match the host exactly or the shader
// measured here is not the shader that runs on the device:
//
//   1. every line starting with "#pragma parameter" is removed, after its
//      name / label / default / min / max / step have been read off it
//   2. a #version of 110-150 or 330-450 becomes "#version 300 es"
//   3. with no #version at all, "#version 100" is prepended - which is the case
//      for every shader in this repo, so ESSL 1.00 is what the device compiles
//   4. "#define VERTEX", or "#define FRAGMENT" plus the ES precision block and
//      "#define PARAMETER_UNIFORM", goes in right after the version line
//
// PARAMETER_UNIFORM is fragment-only, so a parameter read in the vertex stage
// falls back to its #define. That is a host quirk with visible effects, and it
// is reproduced rather than fixed.
//
// The desktop build swaps the version header for "#version 410 core" so the
// same C can be smoke-tested without a device. It is not a source of numbers:
// see docs/device-perf.md.
// ---------------------------------------------------------------------------

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bench.h"

#if defined(BENCH_GLES)
#define VERSION_ES1  "#version 100\n"
#define VERSION_ES3  "#version 300 es\n"
#else
#define VERSION_ES1  "#version 410 core\n"
#define VERSION_ES3  "#version 410 core\n"
#endif

static const char *PRECISION_BLOCK =
    "#ifdef GL_ES\n"
    "#ifdef GL_OES_standard_derivatives\n"
    "#extension GL_OES_standard_derivatives : enable\n"
    "#endif\n"
    "#ifdef GL_FRAGMENT_PRECISION_HIGH\n"
    "precision highp float;\n"
    "#else\n"
    "precision mediump float;\n"
    "#endif\n"
    "#endif\n"
    "#define PARAMETER_UNIFORM\n";

static const char *REPLACED_VERSIONS[] = {
    "#version 110", "#version 120", "#version 130", "#version 140",
    "#version 150", "#version 330", "#version 400", "#version 410",
    "#version 420", "#version 430", "#version 440", "#version 450", NULL
};

static char *read_file(const char *path, size_t *len_out)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (len < 0) {
        fclose(f);
        return NULL;
    }
    char *buf = malloc((size_t)len + 1);
    if (!buf) {
        fclose(f);
        return NULL;
    }
    size_t got = fread(buf, 1, (size_t)len, f);
    fclose(f);
    buf[got] = '\0';
    if (len_out)
        *len_out = got;
    return buf;
}

// Reads every "#pragma parameter" line into the shader's parameter table. The
// pragma carries the default, so a parameter nobody overrides still has the
// value the slider would show.
static void parse_pragmas(Shader *s, const char *source)
{
    const char *line = source;
    while (line && *line) {
        const char *end = strchr(line, '\n');
        size_t len = end ? (size_t)(end - line) : strlen(line);
        if (len > 17 && strncmp(line, "#pragma parameter", 17) == 0) {
            char buf[512];
            size_t n = len < sizeof(buf) - 1 ? len : sizeof(buf) - 1;
            memcpy(buf, line, n);
            buf[n] = '\0';
            char name[64], label[128];
            float def, lo, hi, step;
            if (sscanf(buf + 17, " %63s \"%127[^\"]\" %f %f %f %f",
                       name, label, &def, &lo, &hi, &step) == 6
                && s->n_params < MAX_PARAMS) {
                snprintf(s->params[s->n_params].name,
                         sizeof(s->params[s->n_params].name), "%s", name);
                s->params[s->n_params].value = def;
                s->n_params++;
            }
        }
        line = end ? end + 1 : NULL;
    }
}

// The cleaned body: the source minus its pragma lines, which are not GLSL.
static char *strip_pragmas(const char *source)
{
    char *out = malloc(strlen(source) + 2);
    if (!out)
        return NULL;
    size_t w = 0;
    const char *line = source;
    while (line && *line) {
        const char *end = strchr(line, '\n');
        size_t len = end ? (size_t)(end - line) : strlen(line);
        if (!(len >= 17 && strncmp(line, "#pragma parameter", 17) == 0)) {
            memcpy(out + w, line, len);
            w += len;
            out[w++] = '\n';
        }
        line = end ? end + 1 : NULL;
    }
    out[w] = '\0';
    return out;
}

static int version_is_replaced(const char *version_line, size_t len)
{
    for (int i = 0; REPLACED_VERSIONS[i]; i++) {
        size_t vl = strlen(REPLACED_VERSIONS[i]);
        if (len >= vl && strncmp(version_line, REPLACED_VERSIONS[i], vl) == 0)
            return 1;
    }
    return 0;
}

// Assembles one stage. `is_vertex` picks which define and whether the precision
// block goes in.
static char *stage_source(const char *body, int is_vertex)
{
    const char *define = is_vertex ? "#define VERTEX\n" : "#define FRAGMENT\n";
    const char *precision = is_vertex ? "" : PRECISION_BLOCK;

    const char *version_start = strstr(body, "#version");
    const char *version_end = version_start
                            ? strchr(version_start, '\n') : NULL;

    const char *header;
    const char *rest;
    char kept[64];
    if (version_start && version_end) {
        size_t len = (size_t)(version_end - version_start);
        if (version_is_replaced(version_start, len)) {
            header = VERSION_ES3;
        } else {
            size_t n = len < sizeof(kept) - 2 ? len : sizeof(kept) - 2;
            memcpy(kept, version_start, n);
            kept[n] = '\n';
            kept[n + 1] = '\0';
            header = kept;
        }
        rest = version_end + 1;
    } else {
        header = VERSION_ES1;
        rest = body;
    }

    size_t total = strlen(header) + strlen(define) + strlen(precision)
                 + strlen(rest) + 1;
    char *out = malloc(total);
    if (!out)
        return NULL;
    snprintf(out, total, "%s%s%s%s", header, define, precision, rest);
    return out;
}

static GLuint compile_stage(const char *src, GLenum type, const char *name)
{
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &src, NULL);
    glCompileShader(shader);
    GLint ok = 0;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(shader, sizeof(log), NULL, log);
        fprintf(stderr, "%s: %s stage failed to compile\n%s\n", name,
                type == GL_VERTEX_SHADER ? "vertex" : "fragment", log);
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

static void cache_locations(Shader *s)
{
    GLuint p = s->program;
    s->u_frame_direction   = glGetUniformLocation(p, "FrameDirection");
    s->u_frame_count       = glGetUniformLocation(p, "FrameCount");
    s->u_output_size       = glGetUniformLocation(p, "OutputSize");
    s->u_texture_size      = glGetUniformLocation(p, "TextureSize");
    s->u_input_size        = glGetUniformLocation(p, "InputSize");
    s->u_orig_texture_size = glGetUniformLocation(p, "OrigTextureSize");
    s->u_orig_input_size   = glGetUniformLocation(p, "OrigInputSize");
    s->u_texture           = glGetUniformLocation(p, "Texture");
    s->u_mvp               = glGetUniformLocation(p, "MVPMatrix");
    s->a_vertex            = glGetAttribLocation(p, "VertexCoord");
    s->a_texcoord          = glGetAttribLocation(p, "TexCoord");
    s->a_color             = glGetAttribLocation(p, "COLOR");
    for (int i = 0; i < s->n_params; i++)
        s->u_params[i] = glGetUniformLocation(p, s->params[i].name);
}

int shader_load(Shader *s, const char *dir, const char *filename)
{
    char path[512];
    snprintf(path, sizeof(path), "%s/%s", dir, filename);
    char *source = read_file(path, NULL);
    if (!source)
        return 0;

    memset(s, 0, sizeof(*s));
    snprintf(s->name, sizeof(s->name), "%s", filename);
    parse_pragmas(s, source);

    char *body = strip_pragmas(source);
    free(source);
    if (!body)
        return 0;

    char *vsrc = stage_source(body, 1);
    char *fsrc = stage_source(body, 0);
    free(body);
    if (!vsrc || !fsrc) {
        free(vsrc);
        free(fsrc);
        return 0;
    }

    GLuint vs = compile_stage(vsrc, GL_VERTEX_SHADER, filename);
    GLuint fs = compile_stage(fsrc, GL_FRAGMENT_SHADER, filename);
    free(vsrc);
    free(fsrc);
    if (!vs || !fs) {
        if (vs) glDeleteShader(vs);
        if (fs) glDeleteShader(fs);
        return 0;
    }

    s->program = glCreateProgram();
    glAttachShader(s->program, vs);
    glAttachShader(s->program, fs);
    glLinkProgram(s->program);
    glDeleteShader(vs);
    glDeleteShader(fs);

    GLint ok = 0;
    glGetProgramiv(s->program, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetProgramInfoLog(s->program, sizeof(log), NULL, log);
        fprintf(stderr, "%s: link failed\n%s\n", filename, log);
        glDeleteProgram(s->program);
        s->program = 0;
        return 0;
    }
    cache_locations(s);
    return 1;
}

void shader_set_param(Shader *s, const char *name, float value)
{
    for (int i = 0; i < s->n_params; i++) {
        if (strcmp(s->params[i].name, name) == 0) {
            s->params[i].value = value;
            return;
        }
    }
}

void shader_free(Shader *s)
{
    if (s->program)
        glDeleteProgram(s->program);
    s->program = 0;
}
