import argparse
import json
import os
import random
import time
from datetime import datetime

import requests

import solver
from plario import DATA_DIR, DIAGNOSTIC_FILE, Plario, TokenExpired

PROGRESS_FILE = os.path.join(DATA_DIR, 'send_progress.json')
LOG_FILE = os.path.join(DATA_DIR, 'send_log.txt')
MIN_DELAY_SEC = 133
MAX_DELAY_SEC = 237


def log(msg):
    line = f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    print(line, flush=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_progress(progress):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def load_queue(path, only_module):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    queue = []
    for module in data['modules']:
        if only_module and module['moduleId'] != only_module:
            continue
        for task in module['tasks']:
            queue.append(task)
    return queue


def wait_for_fresh_token(api, activity_id):
    while True:
        log(f'activityId {activity_id}, токен протух, жду обновления token.txt, проверяю раз в 5 минут')
        time.sleep(5 * 60)
        try:
            api.modules()
            log('токен снова рабочий, продолжаю')
            return
        except TokenExpired:
            continue
        except Exception:
            return


def send_one(api, task, answer_id):
    submit_id = task.get('answerSubmitId') or api.diagnostic_open_attempt(task['activityId'])
    api.diagnostic_answer(submit_id, answer_id)
    return submit_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', default=DIAGNOSTIC_FILE, help='файл собранный через collect.py')
    parser.add_argument('--module', type=int, default=None, help='отправлять только один модуль')
    parser.add_argument('--limit', type=int, default=None, help='отправить не больше N задач за запуск')
    parser.add_argument('--dry-run', action='store_true', help='ничего не отправлять, только показать план')
    parser.add_argument('--min-delay', type=int, default=MIN_DELAY_SEC, help='минимальная пауза в секундах')
    parser.add_argument('--max-delay', type=int, default=MAX_DELAY_SEC, help='максимальная пауза в секундах')
    parser.add_argument('--no-cache', action='store_true', help='игнорировать готовые ответы и всегда спрашивать решатель')
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f'нет файла {args.file}, сначала запустите collect.py')
        return

    api = Plario()
    queue = load_queue(args.file, args.module)
    progress = load_progress()

    total = len(queue)
    done = sum(1 for t in queue if progress.get(str(t['activityId']), {}).get('status') == 'ok')
    log(f'старт, задач в очереди {total}, уже отправлено ранее {done}')
    if not args.dry_run:
        log(f'пауза между запросами от {args.min_delay} до {args.max_delay} секунд случайно')

    sent = 0
    current_module = None

    for index, task in enumerate(queue, 1):
        if args.limit is not None and sent >= args.limit:
            log(f'достигнут лимит {args.limit}, останавливаюсь')
            break

        key = str(task['activityId'])
        if progress.get(key, {}).get('status') == 'ok':
            continue

        if task['moduleId'] != current_module:
            current_module = task['moduleId']
            log(f'модуль {current_module}, {task["moduleName"]}')

        try:
            answer_id = solver.solve(task, use_cache=not args.no_cache)
        except solver.AnswerNotResolved as e:
            log(f'[{index}/{total}] activityId {task["activityId"]} пропущено, {e}')
            progress[key] = {'status': 'unresolved', 'reason': str(e)}
            save_progress(progress)
            continue

        if args.dry_run:
            log(f'[{index}/{total}] пробный прогон, activityId {task["activityId"]} answerId {answer_id}')
            sent += 1
            continue

        while True:
            try:
                submit_id = send_one(api, task, answer_id)
                break
            except TokenExpired:
                wait_for_fresh_token(api, task['activityId'])
            except requests.RequestException as e:
                log(f'[{index}/{total}] activityId {task["activityId"]} сетевая ошибка {e}, повтор через 60 секунд')
                time.sleep(60)
            except Exception as e:
                log(f'[{index}/{total}] activityId {task["activityId"]} ошибка {e}')
                submit_id = None
                break

        ok = submit_id is not None
        progress[key] = {
            'status': 'ok' if ok else 'failed',
            'answerId': answer_id,
            'answerSubmitId': submit_id,
            'timestamp': datetime.now().isoformat(timespec='seconds'),
        }
        save_progress(progress)
        sent += 1
        log(f'[{index}/{total}] activityId {task["activityId"]} answerId {answer_id} '
            f'{"отправлено" if ok else "не отправлено"}')

        remaining = total - index
        if remaining > 0 and not (args.limit is not None and sent >= args.limit):
            delay = random.uniform(args.min_delay, args.max_delay)
            log(f'пауза {delay / 60:.1f} минут, осталось задач {remaining}')
            time.sleep(delay)

    ok_count = sum(1 for v in progress.values() if v.get('status') == 'ok')
    unresolved = sum(1 for v in progress.values() if v.get('status') == 'unresolved')
    failed = sum(1 for v in progress.values() if v.get('status') == 'failed')
    log(f'готово, за этот запуск {sent}, всего успешно {ok_count}, без ответа {unresolved}, ошибок {failed}')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log('остановлено пользователем, прогресс сохранён')
