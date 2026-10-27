#!/bin/bash
# Генерация картинок: stable-diffusion.cpp + SD-Turbo (работает на CPU, 1-3 мин на картинку)
set -e
cd "$(dirname "$0")"
[ -d sdcpp ] || git clone --recursive https://github.com/leejet/stable-diffusion.cpp sdcpp
cmake -S sdcpp -B sdcpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build sdcpp/build -j"$(nproc)"
mkdir -p models
[ -f models/sd_turbo.safetensors ] || curl -L -o models/sd_turbo.safetensors https://huggingface.co/stabilityai/sd-turbo/resolve/main/sd_turbo.safetensors
BIN=$(ls sdcpp/build/bin/sd-cli sdcpp/build/bin/sd 2>/dev/null | head -1)
python3 - "$BIN" <<'PY'
import json, sys, os
D = os.getcwd(); c = json.load(open('config.json'))
c['sd_bin'] = os.path.join(D, sys.argv[1]); c['sd_model'] = D + '/models/sd_turbo.safetensors'
json.dump(c, open('config.json', 'w'), indent=1)
PY
echo "Готово: картинки включены"
