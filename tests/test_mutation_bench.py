"""Проверки мутационного стенда ``tools/mutations.py``.

Стенд - тоже код, и ошибается он тем же способом, что и тесты, которые
он проверяет: выглядит работающим, пока не спросишь, по какой причине.

Проверяется :func:`tools.mutations.guards` - функция, на которой держится вся
разница между «мою мутацию поймали» и «в прогоне упало что-то ещё».
"""

import ast
import re

import pytest

from tools.mutations import MUTANTS, ROOT, _parse_node_output, failed_ident, guards

NODE_ID = "tests/test_search_api.py::test_search_ignores_case"
"""Цель, у которой в наборе есть тест с именем-продолжением."""


@pytest.mark.parametrize(
    ("ident", "expected"),
    [
        (NODE_ID, True),
        (NODE_ID + "[случай]", True),
        (NODE_ID + "_in_content", False),
        ("tests/test_search_api.py::test_filters_by_tag", False),
    ],
    ids=["та же цель", "параметризованный случай цели", "имя-продолжение", "чужой тест"],
)
def test_guards_distinguishes_target_from_its_neighbours(ident, expected):
    """Стерегущим считается только сама цель и её параметризация."""
    assert guards(NODE_ID, ident) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("FAILED tests/test_x.py::test_y - AssertionError: сломалось", "tests/test_x.py::test_y"),
        ("FAILED tests/test_x.py::test_y", "tests/test_x.py::test_y"),
        (
            r"FAILED tests/test_x.py::test_y[создание"
            r" - 201] - AssertionError",
            r"tests/test_x.py::test_y[создание - 201]",
        ),
    ],
    ids=["с сообщением", "без сообщения", "пробел и тире внутри случая"],
)
def test_failed_ident_reads_the_whole_node_id(line, expected):
    """Node id достаётся целиком, включая случай с пробелами внутри.

    Третий случай - не выдумка: pytest экранирует кириллицу в
    идентификаторах, но пробелы оставляет, и такие имена в наборе есть
    (``tests/test_openapi_contract.py``, случай «создание - 201»).
    """
    assert failed_ident(line) == expected


SPEC_OUTPUT = """\
✔ первый тест (1.234567ms)
✔ второй тест (0.5ms)
✖ третий тест (0.9ms)
ℹ tests 3
ℹ pass 2
ℹ fail 1
✖ failing tests:
✖ третий тест (0.9ms)
  AssertionError: строка подробностей
  ✖ ожидалось, получено другое
"""
"""Вывод репортёра ``spec``: имена с глифами, сводка и подробности после неё.

Подробности начинаются с глифа намеренно: на них видно, зачем разбор
останавливается на сводке. Повтора имени для этого мало - множество
схлопнуло бы его само.
"""

TAP_OUTPUT = """\
TAP version 13
# Subtest: первый тест
ok 1 - первый тест
  ---
  duration_ms: 1.234
  ...
# Subtest: третий тест
not ok 2 - третий тест
1..2
# fail 1
"""
"""Вывод репортёра ``tap``: те же тесты, ни одного глифа."""


def test_spec_output_gives_names_of_both_colours():
    """Имена разбираются, а подробности после сводки за имена не принимаются.

    Строка `` ✖ ожидалось, получено другое`` в образце - часть отчёта об
    ошибке, а не тест. Без остановки на ``failing tests`` она пополнила
    бы множество красных, и мутанта объявил бы убитым тест, которого нет.
    """
    passed, failed = _parse_node_output(SPEC_OUTPUT)

    assert passed == {"первый тест", "второй тест"}
    assert failed == {"третий тест"}


def test_tap_output_gives_no_names_at_all():
    """Вывод TAP не даёт ни одного имени - и стенд ломается на этом молча.

    Так выглядит прогон, если репортёр не задан явно: умолчание node
    зависит от версии и от того, пайп перед процессом или терминал, а
    стенд всегда читает пайп. Пустые множества превращаются в «node не
    выполнил цель», ``baseline`` обрывает прогон, и ни один из мутантов
    не получает вердикта - при полностью исправных тестах.

    Тест закрепляет не желаемое поведение разбора, а его цену: разбор
    привязан к формату, поэтому формат задаёт флаг в ``node_results``.
    """
    assert _parse_node_output(TAP_OUTPUT) == (set(), set())


def test_mutant_table_is_not_empty():
    """Таблица не пуста.

    Проверки ниже - циклы по таблице, а цикл по пустому списку проходит,
    не выполнив ни одного утверждения. Пустая выборка неотличима от
    прохождения.
    """
    assert MUTANTS


def test_every_mutant_names_a_target_and_a_runner():
    """Таблица не содержит записи без цели или с незнакомым движком.

    Опечатка в поле ``runner`` увела бы мутанта в ветку pytest молча:
    имя движка нигде больше не проверяется.
    """
    for mutant in MUTANTS:
        assert mutant.target, f"у мутанта «{mutant.name}» нет цели"
        assert mutant.runner in {"pytest", "e2e", "node"}, (
            f"у мутанта «{mutant.name}» незнакомый движок {mutant.runner!r}"
        )


def _declared_tests(path):
    """Имена тестов, объявленных в файле - хоть pytest, хоть node.

    У node нет node id: имя теста - это строка, переданная ``test()``,
    поэтому у двух движков разные способы прочитать одно и то же.
    """
    text = (ROOT / path).read_text(encoding="utf-8")
    if path.endswith(".mjs"):
        return set(re.findall(r'^\s*test\(\s*"([^"]+)"', text, re.MULTILINE))
    return {
        node.name
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def test_every_mutant_names_a_test_that_exists():
    """Цель и молчуны каждого мутанта разрешаются в объявленный тест.

    Сторож выше требует от ``target`` только непустоты, а сторож ниже
    сверяет с кодом второе поле записи - ``old``. Между ними
    щель: переименуйте тест, названный целью, и таблица останется
    зелёной в обычном прогоне, потому что строка по-прежнему непуста.

    Молчуны проверяются наравне с целями: они рвутся тем же способом и
    так же тихо.

    Случай в скобках отбрасывается: он задаётся ``ids`` параметризации,
    и чтобы узнать их, таблицу пришлось бы исполнить. Проверяется имя
    функции - то, что переименовывают.
    """
    for mutant in MUTANTS:
        for node_id in (mutant.target, *mutant.silent):
            path, _, name = node_id.partition("::")
            if not path.endswith(".mjs"):
                name = name.split("[", 1)[0]
            assert name in _declared_tests(path), (
                f"мутант «{mutant.name}» называет {node_id}, "
                f"а такого теста в {path} нет - поправьте таблицу под "
                f"переименованный тест"
            )


def test_every_mutant_still_finds_its_piece_of_source():
    """Кусок ``old`` каждого мутанта встречается в своём файле ровно один раз.

    То же самое проверяет ``apply_mutant``, но только когда человек
    запускает стенд руками.
    """
    for mutant in MUTANTS:
        found = (ROOT / mutant.path).read_text(encoding="utf-8").count(mutant.old)
        assert found == 1, (
            f"кусок из мутанта «{mutant.name}» встречается в {mutant.path} {found} раз, "
            "а должен ровно один - поправьте таблицу под изменившийся код"
        )
