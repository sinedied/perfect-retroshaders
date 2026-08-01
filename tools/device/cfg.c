// ---------------------------------------------------------------------------
// Reading a minarch .cfg.
//
// Licence: MIT - Copyright (c) 2026 sinedied
//
// The benchmark takes the same file a user installs rather than a format of its
// own, so a measured pipeline is a pipeline somebody can actually run. Only the
// keys that describe the shader chain are understood; everything else in the
// file is a core option and is ignored, exactly as it is on the device.
//
// Any remaining "key = number" line is taken as a shader parameter, keyed by
// its raw #pragma name. That is how the host does it, and it is why a core
// option that happened to be numeric would be read as one - harmless, since a
// parameter no shader declares is dropped when the pipeline is built.
// ---------------------------------------------------------------------------

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bench.h"

static char *trim(char *s)
{
    while (*s && isspace((unsigned char)*s))
        s++;
    char *end = s + strlen(s);
    while (end > s && isspace((unsigned char)end[-1]))
        *--end = '\0';
    return s;
}

static int size_type(const char *value)
{
    if (strcmp(value, "source") == 0)
        return SIZE_SOURCE;
    if (strcmp(value, "viewport") == 0)
        return SIZE_VIEWPORT;
    return SIZE_RELATIVE;
}

static int is_number(const char *s)
{
    if (!*s)
        return 0;
    char *end = NULL;
    strtod(s, &end);
    return end && *end == '\0';
}

static void set_param(Pipeline *p, const char *name, float value)
{
    for (int i = 0; i < p->n_params; i++) {
        if (strcmp(p->params[i].name, name) == 0) {
            p->params[i].value = value;
            return;
        }
    }
    if (p->n_params >= MAX_PARAMS)
        return;
    snprintf(p->params[p->n_params].name,
             sizeof(p->params[p->n_params].name), "%s", name);
    p->params[p->n_params].value = value;
    p->n_params++;
}

int cfg_load(Pipeline *p, const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return 0;
    }

    snprintf(p->scaling, sizeof(p->scaling), "%s", "Aspect");
    p->scale_filter = GL_NEAREST;
    p->n_passes = 0;
    p->n_params = 0;
    for (int i = 0; i < MAX_PASSES; i++) {
        p->passes[i].filter = GL_NEAREST;
        p->passes[i].srctype = SIZE_SOURCE;
        p->passes[i].scaletype = SIZE_SOURCE;
        p->passes[i].scale = SCALE_SCREEN;
        p->passes[i].shader_name[0] = '\0';
    }

    int declared = 0;
    char line[1024];
    while (fgets(line, sizeof(line), f)) {
        char *text = trim(line);
        if (!*text || *text == '#')
            continue;
        char *eq = strchr(text, '=');
        if (!eq)
            continue;
        *eq = '\0';
        char *key = trim(text);
        char *value = trim(eq + 1);
        if (*key == '-')
            key++;  // a locked option, in the host's sense

        if (strcmp(key, "minarch_nrofshaders") == 0) {
            declared = strcmp(value, "off") == 0 ? 0 : atoi(value);
            if (declared > MAX_PASSES)
                declared = MAX_PASSES;
            continue;
        }
        if (strcmp(key, "minarch_screen_scaling") == 0) {
            snprintf(p->scaling, sizeof(p->scaling), "%s", value);
            continue;
        }
        if (strcmp(key, "minarch_scale_filter") == 0) {
            p->scale_filter = strcmp(value, "LINEAR") == 0
                            ? GL_LINEAR : GL_NEAREST;
            continue;
        }
        if (strncmp(key, "minarch_shader", 14) == 0
            && isdigit((unsigned char)key[14])) {
            int slot = key[14] - '1';
            if (slot < 0 || slot >= MAX_PASSES)
                continue;
            Pass *pass = &p->passes[slot];
            const char *field = key + 15;
            if (*field == '\0')
                snprintf(pass->shader_name, sizeof(pass->shader_name),
                         "%s", value);
            else if (strcmp(field, "_filter") == 0)
                pass->filter = strcmp(value, "LINEAR") == 0
                             ? GL_LINEAR : GL_NEAREST;
            else if (strcmp(field, "_srctype") == 0)
                pass->srctype = size_type(value);
            else if (strcmp(field, "_scaletype") == 0)
                pass->scaletype = size_type(value);
            else if (strcmp(field, "_upscale") == 0)
                pass->scale = strcmp(value, "screen") == 0
                            ? SCALE_SCREEN : atoi(value);
            continue;
        }
        if (strncmp(key, "minarch_", 8) == 0)
            continue;
        if (is_number(value))
            set_param(p, key, (float)atof(value));
    }
    fclose(f);

    // Trust the shader names, not the count: a cfg declaring two passes and
    // naming one is a typo that should fail loudly here rather than render a
    // pass with no program.
    p->n_passes = 0;
    for (int i = 0; i < MAX_PASSES && i < declared; i++) {
        if (p->passes[i].shader_name[0] == '\0') {
            fprintf(stderr, "%s: declares %d passes but pass %d has no "
                            "shader\n", path, declared, i + 1);
            return 0;
        }
        p->n_passes++;
    }
    return 1;
}
