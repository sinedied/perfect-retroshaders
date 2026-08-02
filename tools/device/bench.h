// ---------------------------------------------------------------------------
// Shared types for the device benchmark.
//
// Licence: MIT - Copyright (c) 2026 sinedied
//
// Nothing here is copied from NextUI or from RetroShader Lab, both of which are
// GPL-3.0. The frontend behaviour this reproduces is written from its
// documented description, which is also what tools/check.py already encodes in
// Python.
// ---------------------------------------------------------------------------

#ifndef BENCH_H
#define BENCH_H

#include <SDL2/SDL.h>

#if defined(BENCH_GLES)
#include <GLES3/gl3.h>
#elif defined(__APPLE__)
#define GL_SILENCE_DEPRECATION 1
#include <OpenGL/gl3.h>
#else
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#endif

#define MAX_PASSES 3
#define MAX_PARAMS 32
#define MAX_PIPELINES 64
#define MAX_NAME 128

// srctype and scaletype, in the order the .cfg names them.
enum { SIZE_SOURCE = 0, SIZE_RELATIVE = 1, SIZE_VIEWPORT = 2 };

// The sentinel upscale: "screen" means the destination rect, not a multiple of
// the input.
#define SCALE_SCREEN 9

typedef struct {
    char  name[64];
    float value;
} Param;

typedef struct {
    char   name[MAX_NAME];
    GLuint program;
    GLint  u_frame_direction, u_frame_count;
    GLint  u_output_size, u_texture_size, u_input_size;
    GLint  u_orig_texture_size, u_orig_input_size;
    GLint  u_texture, u_mvp;
    GLint  a_vertex, a_texcoord, a_color;
    int    n_params;
    Param  params[MAX_PARAMS];
    GLint  u_params[MAX_PARAMS];
} Shader;

typedef struct {
    char   shader_name[MAX_NAME];
    Shader shader;
    GLenum filter;
    int    srctype, scaletype, scale;
    GLuint target_tex, target_fbo;
    int    srcw, srch, texw, texh, dstw, dsth;
} Pass;

typedef struct {
    char   label[MAX_NAME];
    char   cfg[MAX_NAME];
    char   scaling[32];
    GLenum scale_filter;
    int    n_passes;
    Pass   passes[MAX_PASSES];
    // Parameter values the cfg sets, applied to whichever pass declares them.
    int    n_params;
    Param  params[MAX_PARAMS];
} Pipeline;

typedef struct {
    int    x, y, w, h;
} Rect;

typedef struct {
    int    src_w, src_h, out_w, out_h;
    double budget_ms;
    GLuint source_tex;
    GLuint quad_vbo;
    GLuint screen_tex, screen_fbo;   // the display: never presented
    Shader final_pass;
    Rect   dst;
} Bench;

// glsl.c
int  shader_load(Shader *s, const char *dir, const char *filename);
void shader_free(Shader *s);
void shader_set_param(Shader *s, const char *name, float value);

// cfg.c
int  cfg_load(Pipeline *p, const char *path);

// pipeline.c
Rect pipeline_dst_rect(const char *scaling, int src_w, int src_h,
                       int out_w, int out_h, double core_aspect);
int  pipeline_build(Pipeline *p, Bench *b, const char *dirs[], int n_dirs);
void pipeline_free(Pipeline *p);
void pipeline_render(Bench *b, Pipeline *p, int frame);
void pipeline_overdraw(Bench *b, Pipeline *p, int index, int n, int blend);

#endif
