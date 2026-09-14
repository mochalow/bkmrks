"""Проверки файла CI, для которых не нужен GitHub.

Браузерные сценарии выполняются по-настоящему только там, где окружение
объявило их обязательными: без переменной ``E2E_REQUIRED`` сбой запуска
браузера превращается в пропуск, а прогон остаётся зелёным, не проверив
в браузере ничего (``tests/e2e/conftest.py``, фикстура ``browser``).

Значит вся защита держится на одной строке в ``ci.yml``, которую легко
удалить при уборке - и заметить это будет негде: набор останется
зелёным, CI тоже, а браузерного слоя не станет. Сторож делает такое
удаление красным.

Имя переменной не дублируется, а вычитывается из фикстуры и сверяется со
стендом. Переименовать константу и забыть про ``ci.yml`` или про
``tools/mutations.py`` - тот же самый способ потерять проверку, только с
другой стороны: стенд, читающий переменную, которую никто не выставляет,
считает браузер недоступным и молча не проверяет браузерных мутантов.

Файл разбирается как YAML, а не ищется регуляркой.

Ищется значение, действующее на шаге, а не строка в файле.
"""

import ast
import re
import shlex
from pathlib import Path, PurePosixPath

import yaml

from tools.mutations import E2E_REQUIRED_ENV as BENCH_ENV

ROOT = Path(__file__).resolve().parent.parent
"""Корень репозитория."""

CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
"""Файл рабочего процесса, который запускает тесты."""

E2E_CONFTEST = ROOT / "tests" / "e2e" / "conftest.py"
"""Фикстуры браузерных сценариев - там объявлено имя переменной."""

E2E_DIR = ROOT / "tests" / "e2e"
"""Каталог браузерных сценариев целиком."""


def _declared_name():
    """Имя переменной, объявленное фикстурой браузерных сценариев."""
    declared = re.search(
        r'^E2E_REQUIRED_ENV = "([^"]+)"',
        E2E_CONFTEST.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert declared, (
        "в tests/e2e/conftest.py не найдено объявление E2E_REQUIRED_ENV: "
        "если константу переименовали, поправьте и этот сторож"
    )
    return declared.group(1)


def _environment_of(workflow, job, step):
    """Собирает окружение шага так же, как это делает GitHub Actions.

    Переменная действует на шаге, если объявлена на нём самом, на работе
    или на всём процессе; ближняя область перекрывает дальнюю. Проверять
    только шаг было бы строже правды: перенос объявления на работу
    ничего не ломает и краснеть не должен.
    """
    environment = {}
    for scope in (workflow, job, step):
        environment.update(scope.get("env") or {})
    return environment


def _runs_pytest(step):
    """Отвечает, вызывает ли шаг pytest, а не упоминает его.

    Разница та же, что и у переменной: «строка встречается в файле» и
    «команда выполняется» - разные утверждения.

    Команда разбирается ``shlex``, а не регулярным выражением: слово
    внутри кавычек становится одним значением, а не отдельным словом,
    и вопрос «pytest в позиции команды?» решается сам собой.
    """
    for line in (step.get("run") or "").splitlines():
        command = line.strip()
        if not command or command.startswith("#"):
            continue
        try:
            words = shlex.split(command)
        except ValueError:
            # Строка, которую shlex разобрать не может - непарная кавычка,
            # апостроф в слове, оборванное продолжение, - вызовом pytest не
            # является. Сторож спрашивает, что шаг запускает, а не корректен
            # ли скрипт целиком: без этой ветки первый же `echo don't` в
            # соседнем шаге ронял бы его сообщением про кавычки, то есть
            # отказом, не имеющим отношения к тому, что он стережёт.
            continue
        if not words:
            continue
        program = PurePosixPath(words[0]).name
        if program == "pytest":
            return True
        if program.startswith("python") and words[1:3] == ["-m", "pytest"]:
            return True
    return False


def test_ci_demands_that_browser_scenarios_actually_run():
    """На шаге, запускающем pytest, переменная действительно задана.

    Проверяется связь трёх файлов: имя берётся из фикстуры, шаг ищется по
    тому, что он в самом деле вызывает pytest, а значение - по правилам
    видимости GitHub Actions. Красным становится и удаление переменной,
    и её переименование в фикстуре без правки ``ci.yml``, и перенос
    объявления к шагу, который pytest не запускает, и пустое значение.

    Последнее проверяется значением, а не наличием ключа.
    """
    name = _declared_name()
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    testing_steps = [
        (job, step)
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if _runs_pytest(step)
    ]

    assert testing_steps, "в ci.yml не нашлось ни одного шага, запускающего pytest"
    for job, step in testing_steps:
        assert _environment_of(workflow, job, step).get(name), (
            f"на шаге «{step.get('name', '?')}» переменная {name} не задана "
            f"или пуста, поэтому не запустившийся браузер даст зелёный "
            f"прогон без единого браузерного сценария"
        )


def test_unparsable_shell_line_does_not_break_the_guard():
    """Строка, которую ``shlex`` не разбирает, не роняет сторожа.

    ``run`` - это скрипт оболочки, и сторож обходит его построчно. Апостроф, незакрытая
    кавычка, оборванное продолжение - и ``shlex.split`` поднимает ``ValueError``.

    Неразбираемая строка пропускается, а не прекращает
    обход. Иначе ``echo`` в начале шага прятал бы
    настоящий вызов pytest ниже, и шаг тестов перестал бы считаться
    шагом тестов.
    """
    assert _runs_pytest({"run": "echo don't"}) is False
    assert _runs_pytest({"run": "echo don't\n.venv/bin/pytest tests"}) is True


def _browser_scenarios():
    """Имена сценариев, объявленных в ``tests/e2e``."""
    found = []
    for path in sorted(E2E_DIR.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found += [
            f"{path.name}::{node.name}"
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
    return found


def test_browser_layer_still_has_scenarios():
    """В браузерном слое есть хотя бы один сценарий.

    Переменная выше превращает в отказ не запустившийся браузер, но не
    исчезнувший слой. Удалите ``tests/e2e`` - и фикстура не создастся ни
    разу, переменной нечего будет ловить, покрытие останется
    стопроцентным, а прогон зелёным.

    Пустая выборка неотличима от прохождения.

    Число сценариев не закрепляется намеренно: их объединяют и делят, и
    сторож, требующий ровно двенадцати, краснел бы на осмысленной
    правке, то есть быстро научил бы себя править не глядя.
    """
    assert _browser_scenarios(), (
        f"в {E2E_DIR.relative_to(ROOT)} не осталось ни одного сценария, "
        f"а {_declared_name()} этого не заметит: она делает отказом "
        f"не запустившийся браузер, а не отсутствующий слой"
    )


def test_the_bench_watches_the_same_variable():
    """Мутационный стенд читает ту же переменную, что объявлена фикстурой.

    Имя объявлено независимо в двух местах. После переименования одного
    из них стенд выставлял бы браузерным мутантам старую переменную,
    фикстура читала бы новую и пропускала сценарии как обычно - стенд
    сделал бы вывод «браузер недоступен» и объявил браузерных
    мутантов непроверенными при работающем браузере.
    """
    assert BENCH_ENV == _declared_name()
