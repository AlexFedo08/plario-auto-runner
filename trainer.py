import argparse
import json
import os
import time
from datetime import datetime

import solver
from plario import DATA_DIR, Plario, TokenExpired, clean_html, images_from_html

LOG_FILE = os.path.join(DATA_DIR, 'trainer_log.txt')


def log(msg):
    line = f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    print(line, flush=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def pack_exercise(module_id, raw, attempt_id=None):
    skills = raw.get('skills') or []
    return {
        'moduleId': module_id,
        'activityId': raw['activityId'],
        'attemptId': attempt_id,
        'type': raw.get('type'),
        'skill': skills[0]['name'] if skills else None,
        'condition': clean_html(raw.get('content')),
        'condition_html': raw.get('content'),
        'images': images_from_html(raw.get('content')),
        'options': [
            {
                'answerId': option['answerId'],
                'text': clean_html(option.get('text')),
                'text_html': option.get('text'),
                'images': images_from_html(option.get('text')),
            }
            for option in raw.get('possibleAnswers', [])
        ],
    }


def fetch_current(api, module_id, open_attempt=True):
    state = api.trainer_current(module_id)
    status = state.get('activityStatus')
    raw = state.get('exercise')
    if not raw:
        return status, None
    attempt_id = None
    if open_attempt:
        attempt_id = api.trainer_open_attempt(module_id, raw['activityId'])
    return status, pack_exercise(module_id, raw, attempt_id)


def show(task):
    print(f'activityId {task["activityId"]}')
    print(f'attemptId {task["attemptId"]}')
    print(f'type {task["type"]}')
    print(f'skill {task["skill"]}')
    print(f'условие {task["condition"]}')
    for image in task['images']:
        print(f'картинка условия {image}')
    for option in task['options']:
        print(f'  answerId {option["answerId"]} {option["text"]}')
        for image in option['images']:
            print(f'    картинка варианта {image}')
    if not task['options']:
        print('вариантов нет, это теория, закрывать через complete')


def cmd_next(api, args):
    status, task = fetch_current(api, args.module)
    if not task:
        print(f'заданий больше нет, статус {status}')
        return
    show(task)


def cmd_submit(api, args):
    result = api.trainer_check_answer(args.module, args.activity, args.attempt, args.answer)
    right = result.get('rightAnswerIds') or []
    ok = args.answer in right
    log(f'модуль {args.module} activityId {args.activity} answerId {args.answer} '
        f'{"верно" if ok else "неверно"} правильные {right}')
    if ok:
        solver.remember(args.activity, args.answer, source='confirmed')


def cmd_complete(api, args):
    api.trainer_complete_lesson(args.module, args.activity, args.attempt)
    log(f'модуль {args.module} activityId {args.activity} теория закрыта')


def cmd_stats(api, args):
    data = api.mastery(args.module)
    below = [s for s in data['skills'] if s['currentMastery'] < data['threshold']]
    print(f'модуль {args.module}, mastery {data["mastery"]}, порог {data["threshold"]}')
    print(f'верных ответов {data["correctAnswerCount"]}, неверных {data["inCorrectAnswerCount"]}')
    print(f'навыков ниже порога {len(below)} из {len(data["skills"])}')
    for skill in sorted(below, key=lambda s: s['currentMastery']):
        print(f'  {skill["currentMastery"]} {skill["knowledgeComponentName"]}')


def cmd_run(api, args):
    solved = 0
    for step in range(args.max_steps):
        try:
            status, task = fetch_current(api, args.module)
        except TokenExpired as e:
            log(str(e))
            return

        if not task:
            log(f'модуль {args.module} закончился, статус {status}')
            return

        if task['type'] != 'Task' or not task['options']:
            api.trainer_complete_lesson(args.module, task['activityId'], task['attemptId'])
            log(f'теория activityId {task["activityId"]} закрыта, навык {task["skill"]}')
            time.sleep(args.delay)
            continue

        try:
            answer_id = solver.solve(task, use_cache=not args.no_cache)
        except solver.AnswerNotResolved as e:
            log(f'остановка на activityId {task["activityId"]}, {e}')
            print()
            show(task)
            return

        result = api.trainer_check_answer(args.module, task['activityId'], task['attemptId'], answer_id)
        right = result.get('rightAnswerIds') or []
        ok = answer_id in right
        solved += 1
        log(f'задача activityId {task["activityId"]} навык {task["skill"]} '
            f'ответ {answer_id} {"верно" if ok else "неверно"} правильные {right}')
        if ok:
            solver.remember(task['activityId'], answer_id, source='confirmed')
        time.sleep(args.delay)

    log(f'достигнут лимит шагов {args.max_steps}, решено задач {solved}')


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('next', help='показать текущее задание и открыть по нему попытку')
    p.add_argument('module', type=int)
    p.set_defaults(func=cmd_next)

    p = sub.add_parser('submit', help='отправить ответ на задачу')
    p.add_argument('module', type=int)
    p.add_argument('activity', type=int)
    p.add_argument('attempt', type=int)
    p.add_argument('answer', type=int)
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser('complete', help='закрыть теоретическую карточку')
    p.add_argument('module', type=int)
    p.add_argument('activity', type=int)
    p.add_argument('attempt', type=int)
    p.set_defaults(func=cmd_complete)

    p = sub.add_parser('stats', help='показать mastery по модулю')
    p.add_argument('module', type=int)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser('run', help='крутить модуль автоматически через решатель')
    p.add_argument('module', type=int)
    p.add_argument('--max-steps', type=int, default=200, help='предохранитель от бесконечного цикла')
    p.add_argument('--delay', type=float, default=2.0, help='пауза между заданиями в секундах')
    p.add_argument('--no-cache', action='store_true', help='всегда спрашивать решатель')
    p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    api = Plario()
    try:
        args.func(api, args)
    except TokenExpired as e:
        print(e)


if __name__ == '__main__':
    main()
