import json


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def dumps_records(records):
    return "[\n" + ",\n".join(compact(record) for record in records) + "\n]"


def dumps_task(task):
    fields = [compact(key) + ":" + (dumps_records(value) if isinstance(value, list) else compact(value)) for key, value in task.items()]
    return "{\n" + ",\n".join(fields) + "\n}"

