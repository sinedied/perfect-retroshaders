// ---------------------------------------------------------------------------
// Building and rendering a shader chain the way the frontend does.
//
// Licence: MIT - Copyright (c) 2026 sinedied
//
// Per pass:
//   dst  = last * scale, or the destination rect when upscale is "screen"
//   src  = srctype:   source | relative (the previous pass output) | viewport
//   tex  = scaletype: source | relative | viewport
// and a pass's target texture is created with the NEXT pass's filter, because
// that is the sampler the next pass will read it through.
//
// After the last pass a final scale pass blits to the destination rect. On the
// device that is the host's own default.glsl; here it is final-pass.glsl, which
// is ours and does the same trivial job, so no GPL file has to be vendored into
// an MIT repository.
// ---------------------------------------------------------------------------

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "bench.h"

// x,y,z,w, u,v,s,t - the vertex layout bench.c uploads.
static const GLfloat IDENTITY[16] = {
    1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  0, 0, 0, 1
};

static int ceil_div(int a, int b)
{
    return (a + b - 1) / b;
}

Rect pipeline_dst_rect(const char *scaling, int src_w, int src_h,
                       int out_w, int out_h, double core_aspect)
{
    Rect r;
    double aspect;
    if (strcmp(scaling, "Native") == 0 || strcmp(scaling, "Cropped") == 0)
        aspect = 0.0;
    else if (strcmp(scaling, "Aspect (screen)") == 0)
        aspect = (double)src_w / (double)src_h;
    else if (strcmp(scaling, "Fullscreen") == 0)
        aspect = -1.0;
    else
        aspect = core_aspect;

    if (aspect == 0.0) {
        int scale;
        if (strcmp(scaling, "Cropped") == 0) {
            int sw = ceil_div(out_w, src_w), sh = ceil_div(out_h, src_h);
            scale = sw < sh ? sw : sh;
        } else {
            int sw = out_w / src_w, sh = out_h / src_h;
            scale = sw < sh ? sw : sh;
        }
        if (scale < 1)
            scale = 1;
        r.w = src_w * scale;
        r.h = src_h * scale;
    } else if (aspect > 0.0) {
        double h = out_h, w = h * aspect;
        if (w > out_w) {
            w = out_w;
            h = w / aspect;
        }
        r.w = (int)floor(w);
        r.h = (int)floor(h);
    } else {
        r.x = 0;
        r.y = 0;
        r.w = out_w;
        r.h = out_h;
        return r;
    }
    r.x = (out_w - r.w) / 2;
    r.y = (out_h - r.h) / 2;
    return r;
}

static GLuint make_target(int w, int h, GLenum filter)
{
    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    return tex;
}

static int find_shader(const char *dirs[], int n_dirs, const char *name,
                       Shader *out)
{
    for (int i = 0; i < n_dirs; i++) {
        if (shader_load(out, dirs[i], name))
            return 1;
    }
    fprintf(stderr, "%s: not found in any shader directory\n", name);
    return 0;
}

int pipeline_build(Pipeline *p, Bench *b, const char *dirs[], int n_dirs)
{
    int last_w = b->src_w, last_h = b->src_h;

    for (int i = 0; i < p->n_passes; i++) {
        Pass *pass = &p->passes[i];
        if (!find_shader(dirs, n_dirs, pass->shader_name, &pass->shader))
            return 0;
        for (int k = 0; k < p->n_params; k++)
            shader_set_param(&pass->shader, p->params[k].name,
                             p->params[k].value);

        int real_w = (i == 0) ? b->src_w : last_w;
        int real_h = (i == 0) ? b->src_h : last_h;
        pass->dstw = pass->scale == SCALE_SCREEN ? b->dst.w
                                                 : last_w * pass->scale;
        pass->dsth = pass->scale == SCALE_SCREEN ? b->dst.h
                                                 : last_h * pass->scale;
        pass->srcw = pass->srctype == SIZE_SOURCE ? b->src_w
                   : pass->srctype == SIZE_VIEWPORT ? b->dst.w : real_w;
        pass->srch = pass->srctype == SIZE_SOURCE ? b->src_h
                   : pass->srctype == SIZE_VIEWPORT ? b->dst.h : real_h;
        pass->texw = pass->scaletype == SIZE_SOURCE ? b->src_w
                   : pass->scaletype == SIZE_VIEWPORT ? b->dst.w : real_w;
        pass->texh = pass->scaletype == SIZE_SOURCE ? b->src_h
                   : pass->scaletype == SIZE_VIEWPORT ? b->dst.h : real_h;

        last_w = pass->dstw;
        last_h = pass->dsth;
    }

    // Second sweep, because a target's filter belongs to whoever reads it.
    for (int i = 0; i < p->n_passes; i++) {
        Pass *pass = &p->passes[i];
        GLenum next = (i + 1 < p->n_passes) ? p->passes[i + 1].filter
                                            : p->scale_filter;
        pass->target_tex = make_target(pass->dstw, pass->dsth, next);
        glGenFramebuffers(1, &pass->target_fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, pass->target_fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, pass->target_tex, 0);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER)
            != GL_FRAMEBUFFER_COMPLETE) {
            fprintf(stderr, "%s: incomplete framebuffer at %dx%d\n",
                    pass->shader_name, pass->dstw, pass->dsth);
            return 0;
        }
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    return 1;
}

void pipeline_free(Pipeline *p)
{
    for (int i = 0; i < p->n_passes; i++) {
        shader_free(&p->passes[i].shader);
        if (p->passes[i].target_tex)
            glDeleteTextures(1, &p->passes[i].target_tex);
        if (p->passes[i].target_fbo)
            glDeleteFramebuffers(1, &p->passes[i].target_fbo);
        p->passes[i].target_tex = 0;
        p->passes[i].target_fbo = 0;
    }
}

static void bind_pass(Bench *b, Shader *s, GLuint input_tex,
                      int w, int h, int srcw, int srch,
                      int texw, int texh, int frame)
{
    glUseProgram(s->program);
    if (s->u_frame_direction >= 0) glUniform1i(s->u_frame_direction, 1);
    if (s->u_frame_count >= 0)     glUniform1i(s->u_frame_count, frame);
    if (s->u_output_size >= 0)
        glUniform2f(s->u_output_size, (GLfloat)w, (GLfloat)h);
    if (s->u_texture_size >= 0)
        glUniform2f(s->u_texture_size, (GLfloat)texw, (GLfloat)texh);
    if (s->u_input_size >= 0)
        glUniform2f(s->u_input_size, (GLfloat)srcw, (GLfloat)srch);
    if (s->u_orig_texture_size >= 0)
        glUniform2f(s->u_orig_texture_size, (GLfloat)b->src_w,
                    (GLfloat)b->src_h);
    if (s->u_orig_input_size >= 0)
        glUniform2f(s->u_orig_input_size, (GLfloat)b->src_w,
                    (GLfloat)b->src_h);
    if (s->u_mvp >= 0)
        glUniformMatrix4fv(s->u_mvp, 1, GL_FALSE, IDENTITY);
    if (s->u_texture >= 0)
        glUniform1i(s->u_texture, 0);
    for (int i = 0; i < s->n_params; i++)
        if (s->u_params[i] >= 0)
            glUniform1f(s->u_params[i], s->params[i].value);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, input_tex);

    glBindBuffer(GL_ARRAY_BUFFER, b->quad_vbo);
    if (s->a_vertex >= 0) {
        glEnableVertexAttribArray((GLuint)s->a_vertex);
        glVertexAttribPointer((GLuint)s->a_vertex, 4, GL_FLOAT, GL_FALSE,
                              8 * sizeof(GLfloat), (void *)0);
    }
    if (s->a_texcoord >= 0) {
        glEnableVertexAttribArray((GLuint)s->a_texcoord);
        glVertexAttribPointer((GLuint)s->a_texcoord, 4, GL_FLOAT, GL_FALSE,
                              8 * sizeof(GLfloat),
                              (void *)(4 * sizeof(GLfloat)));
    }
    // COLOR carries no data here, so it takes the generic value rather than an
    // array. Left at 0 a shader that modulates by it would render black.
    if (s->a_color >= 0)
        glVertexAttrib4f((GLuint)s->a_color, 1.0f, 1.0f, 1.0f, 1.0f);
}

static void unbind_pass(Shader *s)
{
    if (s->a_vertex >= 0)
        glDisableVertexAttribArray((GLuint)s->a_vertex);
    if (s->a_texcoord >= 0)
        glDisableVertexAttribArray((GLuint)s->a_texcoord);
}

static void draw_pass(Bench *b, Shader *s, GLuint input_tex, GLuint fbo,
                      int x, int y, int w, int h,
                      int srcw, int srch, int texw, int texh, int frame)
{
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glViewport(x, y, w, h);
    // A full clear is free on a tiler and saves the tile load a partial write
    // would need.
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    bind_pass(b, s, input_tex, w, h, srcw, srch, texw, texh, frame);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    unbind_pass(s);
}

// N draws of one pass into one framebuffer, with no clear between them: the
// shape the HSR self-test needs, and the shape a naive fill-rate loop takes.
void pipeline_overdraw(Bench *b, Pipeline *p, int index, int n, int blend)
{
    Pass *pass = &p->passes[index];
    GLuint input = index == 0 ? b->source_tex
                              : p->passes[index - 1].target_tex;
    glBindFramebuffer(GL_FRAMEBUFFER, pass->target_fbo);
    glViewport(0, 0, pass->dstw, pass->dsth);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    glBindTexture(GL_TEXTURE_2D, input);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, (GLint)pass->filter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, (GLint)pass->filter);

    bind_pass(b, &pass->shader, input, pass->dstw, pass->dsth,
              pass->srcw, pass->srch, pass->texw, pass->texh, 0);
    if (blend) {
        // Additive, NOT src-alpha. Every shader here writes a literal alpha of
        // 1.0, which makes a src-alpha blend arithmetically a plain replace -
        // and the driver spots that, calls the draw opaque again and removes
        // the overdraw after all. Measured on the device: 8 quads cost the same
        // as 2. An additive blend reads the destination for real, so no draw
        // can be dropped without changing the result.
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE);
    }
    for (int i = 0; i < n; i++) {
        // A per-draw uniform, so no two draws are the same expression and
        // nothing can be hoisted out of the loop.
        if (pass->shader.u_frame_count >= 0)
            glUniform1i(pass->shader.u_frame_count, i);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    }
    if (blend)
        glDisable(GL_BLEND);
    unbind_pass(&pass->shader);
}

void pipeline_render(Bench *b, Pipeline *p, int frame)
{
    // The source is sampled through whichever filter reads it first, so it
    // belongs to the pipeline and has to be set per render, not once at upload.
    glBindTexture(GL_TEXTURE_2D, b->source_tex);
    GLenum first = p->n_passes ? p->passes[0].filter : p->scale_filter;
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, (GLint)first);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, (GLint)first);

    GLuint input = b->source_tex;
    for (int i = 0; i < p->n_passes; i++) {
        Pass *pass = &p->passes[i];
        draw_pass(b, &pass->shader, input, pass->target_fbo,
                  0, 0, pass->dstw, pass->dsth,
                  pass->srcw, pass->srch, pass->texw, pass->texh, frame);
        input = pass->target_tex;
    }

    int last_w = p->n_passes ? p->passes[p->n_passes - 1].dstw : b->src_w;
    int last_h = p->n_passes ? p->passes[p->n_passes - 1].dsth : b->src_h;
    draw_pass(b, &b->final_pass, input, b->screen_fbo,
              b->dst.x, b->dst.y, b->dst.w, b->dst.h,
              last_w, last_h, last_w, last_h, frame);
}
