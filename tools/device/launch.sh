#!/bin/sh
# ShaderBench - what each shader pipeline costs on this device.
#
# Launched from the Tools menu, so the launcher has released the display and
# there is a GL context to be had. Results land next to this script; copy
# results.tsv off the card afterwards.
#
# Runs the self-test first and stops if it fails. The instrument has a way of
# being wrong that looks exactly like a fast shader - see docs/device-perf.md -
# so a failed self-test means the table would be fiction.

cd "$(dirname "$0")" || exit 1

LOG=./log.txt
RESULTS=./results.tsv

{
    echo "# $(date)"
    echo "# $(uname -a)"

    ./bench.elf --root "$(pwd)" --self-test
    STATUS=$?

    if [ $STATUS -ne 0 ]; then
        echo
        echo "self-test failed - not measuring. See $LOG."
        exit $STATUS
    fi

    echo
    ./bench.elf --root "$(pwd)" --out "$RESULTS"
} 2>&1 | tee "$LOG"

# The screen is handed back as soon as this exits, so hold the results up long
# enough to read them off the device without an SD card reader.
sleep 20
