import json
import os

from plario import ANSWERS_CACHE_FILE


class AnswerNotResolved(Exception):
    pass


def load_cache():
    if not os.path.exists(ANSWERS_CACHE_FILE):
        return {}
    with open(ANSWERS_CACHE_FILE, encoding='utf-8') as f:
        return json.load(f)


def save_cache(cache):
    os.makedirs(os.path.dirname(ANSWERS_CACHE_FILE), exist_ok=True)
    with open(ANSWERS_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def remember(activity_id, answer_id, source='manual', note=None):
    cache = load_cache()
    cache[str(activity_id)] = {'answerId': answer_id, 'source': source, 'note': note}
    save_cache(cache)


def from_cache(task):
    entry = load_cache().get(str(task['activityId']))
    if not entry:
        return None
    return entry['answerId']


def ask_ai(task):
    raise AnswerNotResolved(
        'решатель не подключён. сюда нужно вставить вызов ии. '
        'на вход приходит task с полями activityId, skill, condition, images и options, '
        'где каждый вариант это словарь с answerId, text и images. '
        'вернуть нужно answerId того варианта, который считается правильным'
    )


def solve(task, use_cache=True):
    if use_cache:
        cached = from_cache(task)
        if cached is not None:
            return cached
    answer_id = ask_ai(task)
    valid = {option['answerId'] for option in task.get('options', [])}
    if valid and answer_id not in valid:
        raise AnswerNotResolved(
            f'решатель вернул answerId {answer_id}, которого нет среди вариантов задачи {task["activityId"]}'
        )
    remember(task['activityId'], answer_id, source='ai')
    return answer_id
