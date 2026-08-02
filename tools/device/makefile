# The device benchmark.
#
#   make                 desktop smoke build - does it compile, does it run
#   make device          cross-compile for the Brick, via the NextUI toolchain
#   make run             build and run the desktop binary
#   make selftest        build and run the desktop self-test
#   make clean
#
# The desktop build is a smoke test and NOT a source of numbers. It runs desktop
# GL on whatever GPU is in the machine, which is the exact thing this benchmark
# exists to stop relying on. It is here so a missing semicolon costs a second
# instead of a device round-trip.
#
# The device build runs inside the NextUI tg5040 toolchain image, which carries
# the SDL2 and GLES headers and the aarch64 cross-compiler. NEXTUI points at a
# NextUI checkout only so the toolchain can be found; nothing is compiled from
# it and nothing is linked against it.

TARGET  = bench
SOURCE  = bench.c glsl.c cfg.c pipeline.c
BUILD   = build

NEXTUI ?= $(HOME)/projects/nextui
IMAGE  ?= ghcr.io/loveretro/tg5040-toolchain:latest
REPO    = $(abspath ../..)

UNAME_S := $(shell uname -s)

CFLAGS  = -O2 -std=gnu99 -Wall -Wextra -Wno-unused-parameter
LDFLAGS = -lm

ifeq ($(UNAME_S),Darwin)
CFLAGS  += $(shell pkg-config --cflags sdl2) -DSHADER_ROOT=\"$(REPO)\"
LDFLAGS += $(shell pkg-config --libs sdl2) -framework OpenGL
else
CFLAGS  += $(shell pkg-config --cflags sdl2) -DSHADER_ROOT=\"$(REPO)\"
LDFLAGS += $(shell pkg-config --libs sdl2) -lGL
endif

all: $(BUILD)/$(TARGET)

$(BUILD)/$(TARGET): $(SOURCE) bench.h
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) $(SOURCE) -o $@ $(LDFLAGS)

run: $(BUILD)/$(TARGET)
	./$(BUILD)/$(TARGET)

selftest: $(BUILD)/$(TARGET)
	./$(BUILD)/$(TARGET) --self-test

# The container build. Docker has to be running; the toolchain image is pulled
# on first use. ~/.bashrc inside the image is what defines CROSS_COMPILE, PREFIX
# and PKG_CONFIG_PATH - without sourcing it the compile succeeds and the link
# picks up the host libc.
#
# The include and library paths mirror workspace/tg5040/platform/makefile.env in
# the NextUI tree, which is the known-good recipe for this image.
device:
	@mkdir -p $(BUILD)
	docker run --rm -v $(REPO):/work -w /work/tools/device $(IMAGE) \
		/bin/bash -c '. ~/.bashrc && \
		$$CROSS_COMPILE\gcc -O3 -std=gnu99 -Wall \
		-DBENCH_GLES -DSHADER_ROOT=\"/mnt/SDCARD/Tools/tg5040/ShaderBench.pak\" \
		-I$$PREFIX/include -I$$PREFIX_LOCAL/include \
		-I$$PREFIX/include/$$CROSS_TRIPLE \
		$$(pkg-config --cflags sdl2 glesv2) \
		$(SOURCE) -o $(BUILD)/$(TARGET).elf \
		-L$$PREFIX/lib -L$$PREFIX_LOCAL/lib -L$$PREFIX/lib/$$CROSS_TRIPLE \
		$$(pkg-config --libs sdl2 glesv2) -lm'
	@file $(BUILD)/$(TARGET).elf 2>/dev/null || true

# Everything the pak needs, laid out the way it sits on the SD card.
pak: device
	@rm -rf $(BUILD)/ShaderBench.pak
	@mkdir -p $(BUILD)/ShaderBench.pak/shaders \
	          $(BUILD)/ShaderBench.pak/tools/device/pipelines \
	          $(BUILD)/ShaderBench.pak/tools/vendor \
	          $(BUILD)/ShaderBench.pak/tools/optimized \
	          $(BUILD)/ShaderBench.pak/tools/iterations
	cp $(BUILD)/$(TARGET).elf $(BUILD)/ShaderBench.pak/
	cp launch.sh $(BUILD)/ShaderBench.pak/
	chmod +x $(BUILD)/ShaderBench.pak/launch.sh
	cp final-pass.glsl $(BUILD)/ShaderBench.pak/tools/device/
	cp pipelines/*.cfg $(BUILD)/ShaderBench.pak/tools/device/pipelines/
	cp $(REPO)/tools/baseline.toml $(BUILD)/ShaderBench.pak/tools/
	cp $(REPO)/shaders/*.glsl $(BUILD)/ShaderBench.pak/shaders/
	cp $(REPO)/tools/vendor/*.glsl $(BUILD)/ShaderBench.pak/tools/vendor/
	cp $(REPO)/tools/optimized/*.glsl $(BUILD)/ShaderBench.pak/tools/optimized/
	cp $(REPO)/tools/iterations/*.glsl $(BUILD)/ShaderBench.pak/tools/iterations/
	@echo "built $(BUILD)/ShaderBench.pak - copy it to Tools/tg5040/ on the card"

clean:
	rm -rf $(BUILD)

.PHONY: all run selftest device pak clean
