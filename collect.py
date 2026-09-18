import argparse
import json
import os
from datetime import datetime

from plario import (DATA_DIR, DIAGNOSTIC_FILE, Plario, TokenExpired, clean_html,
                    images_from_html)


def pack_task(module, raw):
    return {
        'moduleId': module['moduleId'],
        'moduleName': module['moduleName'],
        'activityId': raw['activityId'],
        'condition': clean_html(raw.get('content')),
        'condition_html': raw.get('content'),
        'images': images_from_html(raw.get('content')),
        'alreadyChosenAnswerId': raw.get('chosenAnswerId') or None,
        'options': [
            {
                'answerId': option['answerId'],
                'text': clean_html(option.get('content')),
                'text_html': option.get('content'),
                'images': images_from_html(option.get('content')),
            }
            for option in raw.get('possibleAnswers', [])
        ],
    }


def collect(api, only_module=None, begin_if_needed=False):
    course = None
    try:
        available = api.courses()
        for group in available or []:
            for item in group.get('courses', []):
                if item['id'] == api.teacher_course_id:
                    course = {'id': item['id'], 'name': item['name'], 'subject': group.get('name')}
    except Exception as e:
        print('не удалось получить список курсов', e)

    modules = api.modules() or []
    result = {
        'collectedAt': datetime.now().isoformat(timespec='seconds'),
        'teacherCourseId': api.teacher_course_id,
        'course': course,
        'modules': [],
    }

    for module in sorted(modules, key=lambda m: m['moduleId']):
        module_id = module['moduleId']
        if only_module and module_id != only_module:
            continue

        entry = {
            'moduleId': module_id,
            'moduleName': module['moduleName'],
            'isMeta': module.get('isMeta'),
            'mastery': module.get('mastery'),
            'threshold': module.get('threshold'),
            'diagnosticWasFinished': module.get('diagnosticWasFinished'),
            'diagnosticStatus': None,
            'tasks': [],
        }

        try:
            status = api.diagnostic_status(module_id)
            entry['diagnosticStatus'] = status.get('status') if isinstance(status, dict) else status
        except Exception as e:
            print(f'модуль {module_id}, не удалось узнать статус диагностики, {e}')

        if begin_if_needed and entry['diagnosticStatus'] == 'TestNotStarted':
            try:
                api.diagnostic_begin(module_id)
                print(f'модуль {module_id}, диагностика запущена')
            except Exception as e:
                print(f'модуль {module_id}, не удалось запустить диагностику, {e}')

        try:
            tasks = api.diagnostic_tasks(module_id) or []
            entry['tasks'] = [pack_task(entry, raw) for raw in tasks]
        except Exception as e:
            print(f'модуль {module_id}, не удалось выгрузить задачи, {e}')

        print(f'модуль {module_id} {module["moduleName"]}, статус {entry["diagnosticStatus"]}, '
              f'задач {len(entry["tasks"])}')
        result['modules'].append(entry)

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--module', type=int, default=None,
                        help='выгрузить только один модуль по его номеру')
    parser.add_argument('--start-diagnostic', action='store_true',
                        help='запускать диагностику в модуле если она ещё не начата')
    parser.add_argument('--out', default=DIAGNOSTIC_FILE,
                        help='куда положить результат')
    args = parser.parse_args()

    api = Plario()
    try:
        data = collect(api, args.module, args.start_diagnostic)
    except TokenExpired as e:
        print(e)
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total = sum(len(m['tasks']) for m in data['modules'])
    print(f'готово, модулей {len(data["modules"])}, задач {total}, файл {args.out}')


if __name__ == '__main__':
    main()
