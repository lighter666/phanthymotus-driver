#!/bin/sh
set -eu
mkdir -p assets
espeak-ng -v cmn -s 150 -w /tmp/meeting-five.wav '本议程还剩五分钟。'
espeak-ng -v cmn -s 150 -w /tmp/meeting-end.wav '本议程时间到了，请进入下一项。'
ffmpeg -loglevel error -y -i /tmp/meeting-five.wav -ac 1 -ar 16000 -c:a pcm_s16le assets/five_minutes.wav
ffmpeg -loglevel error -y -i /tmp/meeting-end.wav -ac 1 -ar 16000 -c:a pcm_s16le assets/time_up.wav
