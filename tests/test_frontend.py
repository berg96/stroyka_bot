"""Экраны мини-аппа прогоняются в настоящем DOM.

Питоновские тесты кроют API, но фронт они не видят вообще — а он уже успел
съесть кнопку «Гидроизоляция» в самом конце замеров: `save()` звался внутри
`run()`, тот видел `busy` и молча выходил. Мастер ввёл бы всю комнату и упёрся
в мёртвую кнопку, и ни один зелёный тест этого бы не показал.

Прогон живёт в `tests/frontend/smoke.js` — там jsdom, поддельный сервер и
клики по кнопкам. Нужен node и `npm install` в той папке; без них тест
пропускается, а не врёт зелёным.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).parent / "frontend"


@pytest.mark.skipif(shutil.which("node") is None, reason="нет node — фронт не прогнать")
@pytest.mark.skipif(
    not (FRONTEND / "node_modules" / "jsdom").is_dir(),
    reason="нет jsdom — прогнать: cd tests/frontend && npm install",
)
def test_miniapp_screens_work():
    result = subprocess.run(
        ["node", "smoke.js"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
