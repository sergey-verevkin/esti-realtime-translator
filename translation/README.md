# Локальный перевод

NLLB 600M и distilled 1.3B через CTranslate2 INT8 на CPU. В рабочем режиме перевод выполняется по предложениям, эстонский → русский. [Устройство потока](../docs/architecture.md).

Из этой папки:

```sh
./run.sh --text 'Ma õpin eesti keelt.'
./run.sh --translation-engine nllb-1.3b --text 'Ma õpin eesti keelt.'
.venv/bin/python compare.py --text 'Ma õpin eesti keelt.'
./listen.sh --asr-engine whisper --asr-interval 3
./run.sh --input /absolute/path/transcripts.jsonl --format jsonl
```

CLI по умолчанию использует 600M; оверлей передаёт сохранённый выбор. Для английского источника: `--source-lang en`. `--output` сохраняет JSONL с перезаписью указанного файла. `--translation-style block` оставлен для низкоуровневых экспериментов, в оверлее используется только sentences. Все параметры: `./run.sh --help`.

Установка 600M: `./setup.sh`. Установка 1.3B: `.venv/bin/python download_nllb13.py`. Загрузчики проверяют SHA256. Веса находятся в `models/nllb-600m-int8` и `models/nllb-1.3b-int8`; источники и ревизии — в provenance.json и коде загрузчиков. Лицензия обеих NLLB — CC-BY-NC-4.0.

Измерение подготовленных фраз: `.venv/bin/python benchmark.py --engine nllb` или `--engine nllb-1.3b`. Результаты сохраняются в output. На пользовательских проверках предпочтительна 600M. OPUS-MT и специальные правила преобразования часов не используются; их старые файлы — остатки экспериментов.

Законченные предложения теперь показываются отдельными карточками. Незавершённый хвост продолжает накапливаться; длинная речь дополнительно делится по лимиту 24 слов (48 в режиме «Больше контекста»). Длинный аудиоконтекст Whisper сохраняется.

Для системного звука с определением речи: `./listen.sh --asr-engine whisper --asr-interval 3 --vad silero`. Параметр передаётся компоненту захвата.

Английский поток: `./listen.sh --asr-engine zipformer-en --vad silero`. Этот ASR-движок автоматически выбирает `en` для NLLB; цель по умолчанию `ru`. Для подготовленного текста используйте `--source-lang en`; сравнение `compare.py` также поддерживает `--source-lang en`.
