import html
import os
import re

import requests

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, 'data')
TOKEN_FILE = os.path.join(ROOT_DIR, 'token.txt')
BASE_URL = os.environ.get('PLARIO_BASE_URL', 'https://api.plario.ru')
DEFAULT_TEACHER_COURSE_ID = int(os.environ.get('TEACHER_COURSE_ID', '2734'))
CULTURE = 'ru'

DIAGNOSTIC_FILE = os.path.join(DATA_DIR, 'diagnostic.json')
ANSWERS_CACHE_FILE = os.path.join(DATA_DIR, 'answers_cache.json')


class TokenExpired(Exception):
    pass


class ApiError(Exception):
    pass


def clean_html(raw):
    text = re.sub(r'<[^>]+>', ' ', raw or '')
    return html.unescape(re.sub(r'\s+', ' ', text)).strip()


def images_from_html(raw):
    return re.findall(r'<img[^>]+src="([^"]+)"', raw or '')


class Plario:
    def __init__(self, teacher_course_id=DEFAULT_TEACHER_COURSE_ID):
        self.teacher_course_id = teacher_course_id
        self.session = requests.Session()

    def token(self):
        with open(TOKEN_FILE, encoding='utf-8') as f:
            return f.read().strip()

    def headers(self):
        return {
            'Authorization': self.token(),
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://my.plario.ru',
            'Referer': 'https://my.plario.ru/',
            'Content-Type': 'application/json',
        }

    def call(self, method, path, params=None, body=None):
        query = dict(params or {})
        query.setdefault('culture', CULTURE)
        resp = self.session.request(
            method,
            BASE_URL + path,
            headers=self.headers(),
            params=query,
            json=body,
            timeout=20,
        )
        if resp.status_code == 401:
            raise TokenExpired('токен протух, положите свежий в token.txt')
        if resp.status_code >= 400:
            raise ApiError(f'{method} {path} вернул {resp.status_code} {resp.text[:200]}')
        text = resp.text.strip()
        if not text:
            return None
        try:
            return resp.json()
        except ValueError:
            return text

    def courses(self):
        return self.call('GET', '/learner/course/available')

    def modules(self):
        return self.call('GET', '/learner/mastery/statistics/info')

    def mastery(self, module_id):
        return self.call('GET', '/learner/mastery/statistics', {'moduleId': module_id})

    def diagnostic_status(self, module_id):
        return self.call('GET', '/learner/diagnostic', {
            'moduleId': module_id,
            'teacherCourseId': self.teacher_course_id,
        })

    def diagnostic_begin(self, module_id):
        return self.call('POST', '/learner/diagnosticAttempt/start', {'moduleId': module_id}, {})

    def diagnostic_tasks(self, module_id):
        return self.call('GET', '/learner/diagnostic/start', {
            'moduleId': module_id,
            'teacherCourseId': self.teacher_course_id,
        })

    def diagnostic_open_attempt(self, activity_id):
        return self.call('POST', f'/learner/diagnostic/activities/{activity_id}/attempts')

    def diagnostic_answer(self, answer_submit_id, answer_id):
        return self.call('POST', f'/learner/attempt/answer/{answer_submit_id}/{answer_id}', None, {})

    def trainer_current(self, module_id):
        return self.call('GET', '/learner/adaptiveLearning', {
            'moduleId': module_id,
            'teacherCourseId': self.teacher_course_id,
        })

    def trainer_open_attempt(self, module_id, activity_id):
        return self.call(
            'POST',
            f'/learner/adaptiveLearning/modules/{module_id}/activities/{activity_id}/attempts',
        )

    def trainer_check_answer(self, module_id, activity_id, attempt_id, answer_id):
        return self.call('POST', '/learner/adaptiveLearning/checkAnswer', None, {
            'activityId': activity_id,
            'attemptId': attempt_id,
            'answerIds': [answer_id],
            'moduleId': module_id,
            'teacherCourseId': self.teacher_course_id,
        })

    def trainer_complete_lesson(self, module_id, activity_id, attempt_id):
        return self.call(
            'POST',
            f'/learner/adaptiveLearning/completeLesson/{activity_id}/{attempt_id}',
            {'moduleId': module_id, 'teacherCourseId': self.teacher_course_id},
            {},
        )

    def trainer_stop_attempt(self, attempt_id):
        return self.call('PATCH', f'/learner/adaptiveLearning/attempts/{attempt_id}/stop')
