# Examples / Примеры

Copy any of these into your own data directory and edit. They are not loaded by `nn` — the bundled catalog lives in `providers/` and `hosts/`, your personal one in `$NN_HOME` (default `~/.claude/nn/data`).

Скопируй любой из них в свою директорию данных и правь. `nn` их не загружает: поставляемый каталог лежит в `providers/` и `hosts/`, твой личный — в `$NN_HOME` (по умолчанию `~/.claude/nn/data`).

```bash
mkdir -p ~/.claude/nn/data/providers
cp examples/providers/python-script-with-own-venv.json ~/.claude/nn/data/providers/my-tts.json
$EDITOR ~/.claude/nn/data/providers/my-tts.json
nn scan && nn ls
```

| file | what it shows / что показывает |
|---|---|
| `providers/python-script-with-own-venv.json` | a wrapper script that needs its own interpreter: pinned `vars.py` plus `detect.python` / скрипт-обёртка со своим интерпретатором |
| `providers/remote-comfyui.json` | a tool on another machine, printed instead of executed / инструмент на другой машине, команда печатается |
| `hosts/gpu-box.json` | an ssh host with `auto: false` and a secret by reference / ssh-хост с `auto: false` и секретом по ссылке |

The id inside the file must match its file name — that is how `nn` links them.

Значение `id` внутри файла обязано совпадать с именем файла — по нему `nn` их и связывает.
