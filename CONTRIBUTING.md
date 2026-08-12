# Contributing · Как участвовать

Issues and pull requests in English or Russian — both are read. Commit messages and
branch names are English, always.
Ишью и пулл-реквесты — по-английски или по-русски, читаются оба. Коммиты и названия
ветвей — всегда по-английски.

## Adding a tool needs no code · Добавить инструмент можно без кода

**EN.** If `nn` should detect one more tool out of the box, that is an entry in
`priors.json`, not a code change. Open the *Add a tool* issue with a command you have
actually run, or send the entry yourself. Same for a machine (`hosts/`), a type bridge
(`bridges/`) or a chain (`recipes/`) — all of it is data.

**RU.** Если нужно, чтобы `nn` находил ещё один инструмент из коробки — это запись в
`priors.json`, а не правка кода. Заведи ишью «Добавить инструмент» с командой, которую
сам прогнал, либо пришли запись сразу. То же для машины (`hosts/`), мостика между типами
(`bridges/`) и цепочки (`recipes/`) — это всё данные.

## Setup · Установка

```bash
git clone https://github.com/Surdeddd/neuropark.git
cd neuropark && ./install.sh      # offers the git pre-commit hook
make hooks                        # or install the hook later
make help                         # every target
```

`nn` needs **python 3.11+ and nothing else** at run time. Dev tools (ruff, mypy, pytest)
come through `uv` and stay out of the product.

## Before a pull request · Перед пулл-реквестом

```bash
make check        # ruff + ruff format --check + mypy --strict + unit tests, ~10s
make smoke-fast   # live runs on your own hardware, offline (~30s)
```

The pre-commit hook runs the same checks, so a clean commit is usually a green CI.

## Rules that hold · Правила, которые не обсуждаются

**EN.**

- **Runtime is stdlib only.** No dependency gets added to what a user must install.
- **No `type: ignore` in `src`.** `mypy --strict` passes with zero suppressions.
- **Tests never touch the network and never spend a subscription.** Live runs live behind
  the `smoke` marker and are opt-in.
- **Every human-facing string goes through `nn.i18n.bi(en, ru)`.** A test walks the AST and
  fails on a literal that glues two languages into one string.
- **`exit 0` is not proof of success.** New failure modes get an outcome class, not a
  cheerful zero.
- **No new hardcoded lists in the engine.** Tools, machines and capabilities are data.
- **Comments explain why, never what.** Project knowledge belongs in the memory bank, not
  in narration above obvious code.

**RU.**

- **В рантайме только stdlib.** Ни одна зависимость не добавляется к тому, что должен
  поставить пользователь.
- **Никаких `type: ignore` в `src`.** `mypy --strict` проходит без подавлений.
- **Тесты не ходят в сеть и не тратят подписку.** Живые прогоны — за маркером `smoke`,
  запускаются вручную.
- **Каждая строка для человека идёт через `nn.i18n.bi(en, ru)`.** Тест обходит AST и падает
  на литерале, где два языка склеены в одну строку.
- **`exit 0` — не доказательство успеха.** Новый режим отказа получает класс исхода, а не
  бодрый нуль.
- **Новых захардкоженных списков в движке не бывает.** Инструменты, машины и capability —
  это данные.
- **Комментарии объясняют «почему», а не «что».** Знание о проекте живёт в мемори-банке,
  а не в пересказе очевидного кода.

## Verification is part of the change · Проверка — часть правки

**EN.** If you touched a live path (`scan`, `run`, `orchestrate`), paste the real output in
the pull request. An exit code on its own says nothing about whether the file it produced
has anything in it.

**RU.** Если трогал живой путь (`scan`, `run`, `orchestrate`) — приложи реальный вывод в
пулл-реквест. Код возврата сам по себе ничего не говорит о том, есть ли что-нибудь внутри
получившегося файла.

## License · Лицензия

Contributions go in under MIT, same as the project.
Вклад принимается под MIT — как и весь проект.
