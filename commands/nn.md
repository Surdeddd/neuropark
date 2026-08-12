---
description: Neural park catalog — what exists, what can do the job, run a chain / каталог парка нейронок
---

Задействуй скилл `nn` для запроса: $ARGUMENTS
Use the `nn` skill for this request: $ARGUMENTS

Разбор запроса / request routing:

- пусто, «что есть», «покажи парк» · empty, "what do I have", "show the park" → `nn ls` (перед этим `nn scan`, если реестр просрочен)
- «чем сделать X», «какой моделью X» · "what can do X", "which model for X" → `nn why <capability>`
- «транскрибируй / озвучь / сгенери / переведи <файл>» · "transcribe / voice over / generate / translate <file>" → соответствующий `nn run`
- «сделай двуязычные сабы» и подобные цепочки · chains like bilingual subtitles → `nn recipe ls`, затем `nn recipe run`
- «прогони через несколько моделей», «сделай с ревью» · "run it through several models", "with review" → `nn orchestrate`
- «сколько квоты», «что простаивает» · "how much quota", "what is idle" → `nn quota`
- «что сломано» · "what is broken" → `nn doctor`

Итог покажи человеческим языком: какой провайдер сработал, где лежит результат, что пошло не так. JSON-конверт целиком не вываливай — из него нужны `provider`, `out`, `outcome`.
