"""Мутационный стенд: проверяет, что тесты ловят порчу кода.

Покрытие говорит, какие строки исполнились, а не проверил ли кто-нибудь
хоть что-то. Честный ответ даёт мутация: портим
строку кода и смотрим, покраснел ли тест, который обязан её стеречь.

Стенд не заменяет прогон мутаций по всему коду и не претендует на
полноту. В таблице ниже стоят только мутанты, которые **когда-то
выживали**, и те, что закрепляют неочевидное утверждение - например,
что тест на регистр в заголовке и тест на регистр в тексте статьи не
дубли: каждый краснеет на своей мутации и молчит на чужой. Такой список
защищает от возврата уже найденных дыр и не превращается в налог на
каждый рефакторинг.

--- Устройство ---

Мутации применяются к копии рабочего дерева во временном каталоге:
исходники проекта не открываются на запись ни на секунду, поэтому
прерванный прогон не оставляет репозиторий испорченным.

Убийство определяется по коду возврата pytest, а не по наличию строки
``FAILED`` в выводе: pytest различает «тест упал» (1) и «тест не найден»
(5), и второе - поломка стенда, а не успех. У ``node --test`` кода с
таким смыслом нет, поэтому там разбираются имена тестов из вывода, и
цель, не встретившаяся ни среди зелёных, ни среди красных, тоже считается
поломкой стенда.

Перед мутациями идёт контрольный прогон целей на неиспорченном коде.
Без него любая внешняя поломка - не тот интерпретатор, не поднявшийся
сервер, не стартовавший браузер - выглядела бы как «все мутанты убиты»:
тесты падают, коды возврата ненулевые, отчёт зелёный. Это ровно тот
класс дефекта, ради которого стенд и написан.

Браузерные мутанты подчиняются той же переменной ``E2E_REQUIRED``, что и
сами сценарии: без браузера они не проверяются и об этом
сказано отдельной строкой, а с переменной - непроверенный мутант делает
прогон красным.

Запуск::

    python3 tools/mutations.py           # весь стенд
    python3 tools/mutations.py тег       # только мутанты с этой подстрокой в имени
    python3 tools/mutations.py --list    # показать таблицу и выйти

Коды возврата: 0 - все проверенные мутанты убиты; 1 - есть выжившие;
2 - сломан сам стенд (мутант не применяется, цель не найдена, контроль
красный, не запускается git, pytest или node).
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
"""Корень репозитория."""

PYTEST = ROOT / ".venv" / "bin" / "pytest"
"""Интерпретатор тестов: тот же, что и у разработчика, а не системный."""

E2E_REQUIRED_ENV = "E2E_REQUIRED"
"""Переменная, объявляющая браузерный слой обязательным."""

TIMEOUT = 300
"""Потолок на один прогон, секунды. Зависший сервер не вешает стенд."""


@dataclass(frozen=True)
class Mutant:
    """Одна порча кода и тест, который обязан её заметить.

    Attributes:
        name: Что именно сломано, человеческими словами.
        path: Файл относительно корня репозитория.
        old: Кусок исходника; обязан встречаться ровно один раз.
        new: Чем заменяется.
        target: Цель - node id для pytest либо ``файл::имя`` для node.
        runner: ``pytest``, ``e2e`` (тот же pytest, но нужен браузер)
            или ``node``.
        silent: Тесты, которые на этой мутации обязаны остаться
            зелёными. Так записывается утверждение «эти два теста не
            дубли»: без него стенд доказывал бы только половину -
            что каждый краснеет на своей мутации, но не что он молчит
            на чужой.
    """

    name: str
    path: str
    old: str
    new: str
    target: str
    runner: str
    silent: tuple = ()


MUTANTS = [
    Mutant(
        "редиректы больше не проверяются на публичность",
        "parser.py",
        "_opener = urllib.request.build_opener(_GuardedRedirectHandler)",
        "_opener = urllib.request.build_opener()",
        "tests/test_resilience.py::test_redirect_guard_is_wired_into_the_opener",
        "pytest",
    ),
    # Порча, которую нашла матрица CI: на 3.12 незакрытый ответ никого
    # не беспокоит, на 3.14 приходит ResourceWarning из деструктора и
    # красит тест, до которого доехал сборщик мусора, - то есть чужой.
    # Поэтому закрытие проверяется явно, а не по цвету прогона.
    Mutant(
        "отказ в редиректе оставляет ответ открытым",
        "parser.py",
        "            fp.close()\n            raise",
        "            raise",
        "tests/test_resilience.py::test_rejects_redirect_to_private_address",
        "pytest",
    ),
    Mutant(
        "проверяется только первый разрешённый адрес",
        "parser.py",
        "    for info in infos:",
        "    for info in infos[:1]:",
        "tests/test_resilience.py::test_all_resolved_addresses_are_checked",
        "pytest",
    ),
    # Цель - вся параметризация, а не строка «зарезервированный блок
    # IPv6», которая одна и краснеет: pytest экранирует не-ASCII в
    # идентификаторах, и точный node id пришлось бы писать в таблице
    # как \u0437\u0430\u0440... - нечитаемо и ломается при правке текста.
    Mutant(
        "зарезервированные блоки IPv6 считаются публичными",
        "parser.py",
        "        if not ip.is_global or ip.is_reserved:",
        "        if not ip.is_global:",
        "tests/test_resilience.py::test_rejects_non_public_address",
        "pytest",
    ),
    Mutant(
        "поиск по заголовку стал чувствителен к регистру",
        "main.py",
        '    title = (article.get("title") or "").lower()',
        '    title = article.get("title") or ""',
        "tests/test_search_api.py::test_search_ignores_case",
        "pytest",
        ("tests/test_search_api.py::test_search_ignores_case_in_content",),
    ),
    Mutant(
        "поиск по тексту статьи стал чувствителен к регистру",
        "main.py",
        '    content = (article.get("content") or "").lower()',
        '    content = article.get("content") or ""',
        "tests/test_search_api.py::test_search_ignores_case_in_content",
        "pytest",
        ("tests/test_search_api.py::test_search_ignores_case",),
    ),
    Mutant(
        "фильтр по тегу стал поиском подстроки",
        "main.py",
        '            if needle in a.get("tags", [])',
        '            if any(needle in t for t in a.get("tags", []))',
        "tests/test_search_api.py::test_filters_by_tag",
        "pytest",
    ),
    Mutant(
        "список тегов отдаётся в случайном порядке",
        "main.py",
        "    return dict(sorted(counts.items(), key=lambda item: item[0]))",
        "    return dict(counts.items())",
        "tests/test_tags_api.py::test_lists_tags_with_counts_sorted",
        "pytest",
    ),
    Mutant(
        "шаблон вставляет заголовок как разметку (XSS)",
        "static/index.html",
        '<h2 class="card-title">{{ article.title || "Без заголовка" }}</h2>',
        '<h2 class="card-title" v-html="article.title"></h2>',
        "tests/test_templates.py::test_template_does_not_render_foreign_markup[index.html]",
        "pytest",
    ),
    # Замок снимается целиком - это и есть проверяемый инвариант. Записей
    # две, потому что стенд запускает только цель мутанта: одна порча,
    # проверенная одним тестом, ничего не говорит про второй.
    Mutant(
        "замок записи снят, дедупликация остаётся без защиты",
        "main.py",
        "_write_lock = threading.Lock()",
        '_write_lock = __import__("contextlib").nullcontext()',
        "tests/test_concurrency.py::test_concurrent_creation_of_one_url_yields_one_article",
        "pytest",
    ),
    Mutant(
        "замок записи снят, теги затирают друг друга",
        "main.py",
        "_write_lock = threading.Lock()",
        '_write_lock = __import__("contextlib").nullcontext()',
        "tests/test_concurrency.py::test_concurrent_tag_additions_do_not_lose_each_other",
        "pytest",
    ),
    # Три мутанта про контракт REST.
    Mutant(
        "в контракт добавился маршрут, которого нет в списке",
        "main.py",
        "router = APIRouter()",
        'router = APIRouter()\n\n\n@router.get("/stats")\ndef stats() -> dict[str, int]:\n    return {}',
        "tests/test_openapi_contract.py::test_published_set_of_routes_is_frozen",
        "pytest",
    ),
    Mutant(
        "поле tags получает право быть пустым",
        "main.py",
        "    tags: list[str] = Field(",
        "    tags: list[str] | None = Field(",
        "tests/test_openapi_contract.py::test_article_schema_matches_the_frozen_record",
        "pytest",
    ),
    # Экспорт - единственное место, где тело ответа собирается руками и
    # без return-аннотации, поэтому именно он показывает, что проверка
    # тел не повторяет проверку схемы. Поле выбрано не `content`: его уже
    # стережёт tests/test_export_api.py, и мутант задел бы лишнее.
    Mutant(
        "экспорт молча теряет поле записи",
        "main.py",
        '        return [a.model_dump(mode="json") for a in articles]',
        '        return [a.model_dump(mode="json", exclude={"sitename"}) for a in articles]',
        "tests/test_openapi_contract.py::test_article_body_carries_exactly_the_frozen_fields",
        "pytest",
    ),
    # Хранилище решает, что попадёт в модель ответа и в ключ
    # дедупликации. Мутант возвращает проверку к одному isinstance -
    # тому виду, в котором одна запись с непарсимым адресом роняла шесть
    # ручек сразу, включая сохранение любой новой статьи.
    Mutant(
        "хранилище снова верит любой строке в поле url",
        "storage.py",
        '            and _is_usable_url(data["url"])\n',
        "",
        "tests/test_resilience.py::test_unusable_url_does_not_break_list",
        "pytest",
    ),
    # Защита стоит в _fetch, а обложку качает fetch_image - через него.
    # Мутант уводит обложку мимо _fetch, оставив саму защиту на месте:
    # это ровно та регрессия, которая не даёт ни исключения, ни другого
    # кода ответа, потому что fetch_image глотает любой ValueError.
    Mutant(
        "обложка качается мимо защиты",
        "parser.py",
        "        content, content_type = _fetch(resolved, timeout=timeout, max_bytes=MAX_IMAGE_BYTES)",
        '        with urllib.request.urlopen(resolved, timeout=timeout) as r:\n'
        '            content, content_type = r.read(MAX_IMAGE_BYTES), r.headers.get("Content-Type", "")',
        "tests/test_resilience.py::test_cover_is_not_downloaded_from_private_address",
        "pytest",
    ),
    Mutant(
        "CI больше не требует, чтобы браузер запустился",
        ".github/workflows/ci.yml",
        "        env:\n          E2E_REQUIRED: '1'\n",
        "",
        "tests/test_ci_workflow.py::test_ci_demands_that_browser_scenarios_actually_run",
        "pytest",
    ),
    # Шаг остаётся на месте вместе с переменной, меняется только
    # команда: слово pytest в ней есть, вызова нет.
    Mutant(
        "шаг тестов только упоминает pytest",
        ".github/workflows/ci.yml",
        "        run: >-\n"
        "          .venv/bin/pytest -rs --cov=main --cov=parser --cov=storage\n"
        "          --cov-branch --cov-report=term-missing --cov-fail-under=100\n"
        "          --tracing=on\n",
        '        run: echo "шаг тестов переехал, а слово pytest осталось"\n',
        "tests/test_ci_workflow.py::test_ci_demands_that_browser_scenarios_actually_run",
        "pytest",
    ),
    # Ключ остаётся объявленным, пустеет только значение. Фикстура читает
    # переменную через `os.environ.get`, для которой пустая строка ложна,
    # то есть браузерный слой отключается целиком - а сторож, проверявший
    # вхождение ключа в окружение шага, оставался зелёным. Ни мутант выше
    # (уносит блок `env` вместе с ключом), ни соседний (ломает команду,
    # и шаг перестаёт считаться шагом тестов) этот случай не покрывают.
    Mutant(
        "E2E_REQUIRED объявлена пустой",
        ".github/workflows/ci.yml",
        "          E2E_REQUIRED: '1'\n",
        "          E2E_REQUIRED: ''\n",
        "tests/test_ci_workflow.py::test_ci_demands_that_browser_scenarios_actually_run",
        "pytest",
    ),
    # Правило «предупреждение - ошибка» уже однажды удалили из pytest.ini,
    # оставив комментарий над ним и два докстринга описывать его как
    # действующее. Мутант убирает ровно ту строку; файл остаётся валидным
    # INI, поэтому pytest в копии дерева запускается и выносит вердикт, а
    # не объявляет стенд сломанным. Цель утверждает о действии правила, а
    # не о тексте конфига, поэтому переезд настройки её не покрасит.
    Mutant(
        "предупреждения больше не становятся ошибками",
        "pytest.ini",
        "filterwarnings = error\n",
        "",
        "tests/test_service.py::test_warnings_are_errors",
        "pytest",
    ),
    # Мутант по самому стенду: возвращает прежний разбор строки
    # по первому пробелу. На целях-функциях он безвреден, поэтому и жил
    # незамеченным; красным его делает только случай с пробелом внутри
    # скобок - тот самый, из-за которого разбор и переписан.
    # Кусок захватывает и заголовок следующей функции по той же причине,
    # что и мутант ниже: портимая строка встречается дважды - в
    # failed_ident() и здесь, в собственном описании мутанта.
    Mutant(
        "стенд снова режет node id по первому пробелу",
        "tools/mutations.py",
        "    return match.group(1)\n\n\ndef guards",
        "    return line.split()[1]\n\n\ndef guards",
        "tests/test_mutation_bench.py::test_failed_ident_reads_the_whole_node_id",
        "pytest",
    ),
    # Ещё один мутант по самому стенду. Стоит здесь потому, что
    # подстрочное сравнение в стенде однажды уже было и молча засчитывало
    # чужой красный тест за свой. Кусок захватывает и следующую строку
    # файла: сама портимая строка встречается дважды - в guards() и вот
    # здесь, в собственном описании мутанта.
    Mutant(
        "стенд снова считает цель по вхождению подстроки",
        "tools/mutations.py",
        '    return ident == target or ident.startswith(target + "[")\n\n\nKILLED',
        "    return target in ident\n\n\nKILLED",
        "tests/test_mutation_bench.py::test_guards_distinguishes_target_from_its_neighbours",
        "pytest",
    ),
    # Третий мутант по самому стенду. Без остановки на сводке строки
    # отчёта об ошибке, начинающиеся с глифа, становятся именами тестов,
    # и мутанта объявляет убитым тест, которого нет, - то есть стенд
    # снова врёт молча, ради чего он и написан.
    Mutant(
        "стенд читает подробности падения как имена тестов",
        "tools/mutations.py",
        '        if stripped.startswith("✖ failing tests:"):\n            break\n',
        "",
        "tests/test_mutation_bench.py::test_spec_output_gives_names_of_both_colours",
        "pytest",
    ),
    Mutant(
        "в файл экспорта уходит пустое тело",
        "static/js/api.js",
        "    const blob = await response.blob();",
        "    const blob = new Blob([]);",
        "tests/js/api.test.mjs::exportLibrary отдаёт браузеру тело ответа, а не пустой файл",
        "node",
    ),
    Mutant(
        "ссылка скачивания не ведёт на данные",
        "static/js/api.js",
        "        link.href = url;",
        '        link.href = "";',
        "tests/js/api.test.mjs::exportLibrary отдаёт браузеру тело ответа, а не пустой файл",
        "node",
    ),
    Mutant(
        "имя файла из Content-Disposition игнорируется",
        "static/js/api.js",
        "    if (match) {\n        filename = match[1];\n    }\n",
        "",
        "tests/js/api.test.mjs::exportLibrary берёт имя файла из Content-Disposition",
        "node",
    ),
    Mutant(
        "сетевой сбой при экспорте показывается сырым исключением",
        "static/js/api.js",
        '    } catch (err) {\n'
        '        throw new Error("Не удалось связаться с сервером. '
        'Проверьте, что приложение запущено.",\n'
        "            {cause: err});\n"
        "    }\n"
        "\n"
        "    if (!response.ok) {\n"
        "        throw new Error(await extractDetail(response));\n"
        "    }\n"
        "\n"
        "    const blob = await response.blob();",
        "    } catch (err) {\n"
        "        throw err;\n"
        "    }\n"
        "\n"
        "    if (!response.ok) {\n"
        "        throw new Error(await extractDetail(response));\n"
        "    }\n"
        "\n"
        "    const blob = await response.blob();",
        "tests/js/api.test.mjs::"
        "exportLibrary при недоступной сети подсказывает, а не показывает текст исключения",
        "node",
    ),
    Mutant(
        "в карточке вместо заголовка выводится адрес",
        "static/index.html",
        '<h2 class="card-title">{{ article.title || "Без заголовка" }}</h2>',
        '<h2 class="card-title">{{ article.url }}</h2>',
        "tests/e2e/test_smoke.py::test_library_shows_saved_articles",
        "e2e",
    ),
    Mutant(
        "дата в карточке выводится сырой, без форматтера",
        "static/index.html",
        "{{ dateShort(article.saved_at) }}",
        "{{ article.saved_at }}",
        "tests/e2e/test_smoke.py::test_library_shows_saved_articles",
        "e2e",
    ),
    Mutant(
        "ссылка карточки ведёт не на ту статью",
        "static/js/library.js",
        'const readerHref = (id) => "/reader.html?id=" + encodeURIComponent(id);',
        'const readerHref = () => "/reader.html?id=чужой";',
        "tests/e2e/test_smoke.py::test_card_opens_the_article_in_reader",
        "e2e",
    ),
    Mutant(
        "ошибка сохранения не доходит до страницы",
        "static/js/library.js",
        "                saveError.value = err.message;",
        '                saveError.value = "";',
        "tests/e2e/test_smoke.py::test_failed_save_is_shown_to_the_user",
        "e2e",
    ),
    Mutant(
        "фильтр по тегу не попадает в адресную строку",
        "static/js/library.js",
        '            if (activeTag.value) next.set("tag", activeTag.value);',
        "",
        "tests/e2e/test_smoke.py::test_tag_filter_narrows_list_and_survives_reload",
        "e2e",
    ),
    # Два мутанта ниже закрепляют неочевидное: сторож `v-html` в
    # tests/test_templates.py ищет подстроку, а `:innerHTML` даёт тот же
    # результат, её не содержа. Vue трактует `innerHTML` как DOM-свойство
    # наравне с `textContent`, поэтому порча настоящая, а не выдуманная.
    # Если бы браузерный сценарий дублировал строковый сторож, эти двое
    # выжили бы - и о дубле стало бы известно сразу.
    # Утверждение «атрибута нет» проходит и на несуществующем элементе,
    # и на невыполненном скрипте - то есть само по себе не доказывает
    # ничего. Мутант выставляет тему без явного выбора: сценарий обязан
    # покраснеть на первом же утверждении, до единого клика.
    Mutant(
        "тема применяется без явного выбора пользователя",
        "static/js/theme.js",
        'export const theme = ref(loadExplicit() || (media.matches ? "dark" : "light"));',
        'export const theme = ref(loadExplicit() || (media.matches ? "dark" : "light"));\n'
        "document.documentElement.dataset.theme = theme.value;",
        "tests/e2e/test_smoke.py::test_theme_choice_survives_reload",
        "e2e",
    ),
    Mutant(
        "заголовок статьи выводится разметкой мимо строкового сторожа",
        "static/reader.html",
        '<h1 class="reader-title">{{ article.title || "Без заголовка" }}</h1>',
        '<h1 class="reader-title" :innerHTML="article.title"></h1>',
        "tests/e2e/test_smoke.py::test_hostile_markup_from_a_saved_page_is_not_executed",
        "e2e",
    ),
    Mutant(
        "текст статьи выводится разметкой мимо строкового сторожа",
        "static/reader.html",
        '<p v-for="(para, i) in paragraphs" :key="i">{{ para }}</p>',
        '<p v-for="(para, i) in paragraphs" :key="i" :innerHTML="para"></p>',
        "tests/e2e/test_smoke.py::test_hostile_markup_from_a_saved_page_is_not_executed",
        "e2e",
    ),
    Mutant(
        "край диапазона не выключает кнопку размера",
        "static/js/reader.js",
        "const canDecreaseFontSize = computed(() => fontScale.value !== FONT_SCALE_STEPS[0]);",
        "const canDecreaseFontSize = computed(() => true);",
        "tests/e2e/test_smoke.py::test_font_scale_stops_at_the_ends_of_its_range",
        "e2e",
    ),
    Mutant(
        "выбранный размер шрифта никуда не записывается",
        "static/js/reader.js",
        "            localStorage.setItem(FONT_SCALE_KEY, String(next));\n",
        "",
        "tests/e2e/test_smoke.py::test_font_scale_survives_reload",
        "e2e",
    ),
    Mutant(
        "кнопка архива просит у сервера другой формат",
        "static/index.html",
        "@click=\"downloadExport('zip')\"",
        "@click=\"downloadExport('json')\"",
        "tests/e2e/test_smoke.py::test_export_button_hands_the_browser_a_file",
        "e2e",
    ),
    Mutant(
        "снятый тег остаётся на экране до перезагрузки",
        "static/js/reader.js",
        "                const updated = await removeTag(articleId, name);\n"
        "                article.value = updated;\n",
        "                await removeTag(articleId, name);\n",
        "tests/e2e/test_smoke.py::test_tag_removed_in_reader_stays_removed",
        "e2e",
    ),
    Mutant(
        "список тегов не объявляет, раскрыт он или свёрнут",
        "static/index.html",
        ':aria-expanded="tagsExpanded"',
        ':aria-expanded="false"',
        "tests/e2e/test_smoke.py::test_long_tag_list_collapses_and_expands",
        "e2e",
    ),
    Mutant(
        "системная тема перебивает явный выбор пользователя",
        "static/js/theme.js",
        "    if (loadExplicit()) return; // явный выбор пользователя важнее системного\n",
        "",
        "tests/e2e/test_smoke.py::test_explicit_theme_outlives_a_system_change",
        "e2e",
    ),
    Mutant(
        "смена системной темы не доходит до страницы",
        "static/js/theme.js",
        '    theme.value = event.matches ? "dark" : "light";\n',
        "",
        "tests/e2e/test_smoke.py::test_system_theme_applies_while_no_choice_is_made",
        "e2e",
    ),
    # Стык клиента и схемы. Мутируется путь удаления, а не любой другой:
    # остальные семь функций клиента закреплены литералами внутри
    # api.test.mjs, и порча их пути краснит соседний тест заодно с целью.
    # У deleteArticle своего утверждения о пути нет - его единственный
    # сторож и есть сверка со схемой.
    Mutant(
        "клиент удаляет статью не по тому пути",
        "static/js/api.js",
        '    return request("/api/articles/" + encodeURIComponent(id), {method: "DELETE"});',
        '    return request("/api/article/" + encodeURIComponent(id), {method: "DELETE"});',
        "tests/js/api.test.mjs::каждый путь, который строит клиент, объявлен в схеме сервера",
        "node",
    ),
]
"""Таблица мутантов: только выжившие когда-то и закрепляющие неочевидное."""


class BenchError(Exception):
    """Сломан стенд, а не проверяемый код."""


class BenchTimeout(BenchError):
    """Программа не уложилась в потолок.

    Отдельный подвид нужен ровно одному месту - :func:`baseline`, где
    сорвавшийся браузерный прогон разбирается на «браузера нет» и
    «сломано что-то ещё». Зависание относится ко второму, а
    неотличимое от прочих поломок оно уезжало бы в первое: стенд
    повторял бы прогон, по пустому списку заключал «браузера нет» и
    объявлял браузерных мутантов непроверенными.

    :func:`main` ловит базовый класс, поэтому код возврата прежний.
    """


def run_tool(command, timeout=TIMEOUT, **kwargs):
    """Запускает внешнюю программу, переводя срыв запуска в ``BenchError``.

    О двух бедах ``subprocess.run`` сообщает не кодом возврата, а
    исключением: программы нет (``FileNotFoundError``) и программа
    зависла (``TimeoutExpired``). Оба пролетают мимо единственного
    обработчика в :func:`main` и выходят трассой с кодом 1 - тем самым,
    которым стенд сообщает о выживших мутантах.

    Args:
        command: Команда списком, первым элементом - программа.
        timeout: Потолок в секундах.
        **kwargs: Уходит в ``subprocess.run`` без изменений.

    Returns:
        Завершённый процесс.

    Raises:
        BenchError: программу не запустить или она не уложилась в
            потолок.
    """
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, **kwargs)
    except FileNotFoundError as error:
        raise BenchError(f"не запустить {command[0]}: программа не найдена") from error
    except subprocess.TimeoutExpired as error:
        raise BenchTimeout(f"{command[0]} не уложился в {error.timeout:g} с и снят") from error


def copy_worktree(destination):
    """Копирует отслеживаемые git-ом файлы рабочего дерева.

    Копируется именно рабочее дерево, а не коммит: стенд должен видеть
    правки, которые ещё не закоммичены. Список берётся у git, чтобы не
    тащить ``.venv``, ``data`` и кэши.

    Неотслеживаемый файл не копируется, поэтому цель в новом, ещё не
    добавленном тесте останавливает стенд («pytest не нашёл цель»), а
    не тихо считается выжившей или убитой. Лечится ``git add``.

    Args:
        destination: Каталог-приёмник, уже существующий.

    Raises:
        BenchError: git недоступен или дерево пустое.
    """
    listing = run_tool(["git", "ls-files", "-z"], cwd=ROOT)
    if listing.returncode:
        raise BenchError(f"git ls-files не отработал: {listing.stderr.strip()}")

    names = [name for name in listing.stdout.split("\0") if name]
    if not names:
        raise BenchError("git не назвал ни одного файла - стенду нечего копировать")

    for name in names:
        source = ROOT / name
        if not source.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def run_pytest(targets, cwd, browser_required=False):
    """Запускает pytest по списку целей и возвращает упавшие тесты.

    Возвращаются именно строки ``FAILED``, а не код возврата: единица
    означает всего лишь «что-то пошло не так», и сорвавшаяся фикстура
    (не запустился браузер, не поднялся сервер) дала бы её с тем же
    успехом, что и пойманная мутация. Такой отчёт объявлял бы мутантов
    убитыми, не проверив ни одного.

    Args:
        targets: node id тестов.
        cwd: Каталог, в котором запускать (копия дерева).
        browser_required: Объявить браузер обязательным - тогда его
            отсутствие превращается в ``ERROR``, а не в тихий пропуск.

    Returns:
        Список строк ``FAILED`` (пустой, если всё зелено).

    Raises:
        BenchError: цель не найдена, pytest не запустился, сломался
            или сорвалась фикстура - то есть прогон не состоялся и
            судить по нему нельзя.
        BenchTimeout: pytest не уложился в потолок.
    """
    # Байткод не пишется на диск намеренно. Python считает .pyc годным,
    # если совпали размер и время правки источника с точностью до
    # секунды, - а два мутанта в одном файле запросто дают одинаковый
    # размер (у «регистр в заголовке» и «регистр в тексте» из таблицы он
    # совпадает до байта) и укладываются в одну секунду. Тогда pytest
    # исполняет предыдущую мутацию вместо текущей, и стенд врёт молча,
    # причём по-разному от прогона к прогону.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if browser_required:
        env[E2E_REQUIRED_ENV] = "1"
    else:
        env.pop(E2E_REQUIRED_ENV, None)
    process = run_tool(
        [str(PYTEST), *targets, "-p", "no:randomly", "-p", "no:cacheprovider", "--no-header"],
        cwd=cwd,
        env=env,
    )
    if process.returncode == 5:
        raise BenchError(f"pytest не нашёл цель: {' '.join(targets)}")
    if process.returncode not in (0, 1):
        raise BenchError(
            f"pytest вернул {process.returncode} на {' '.join(targets)}:\n"
            f"{process.stdout[-1500:]}{process.stderr[-1500:]}"
        )
    lines = [line.strip() for line in process.stdout.splitlines()]
    errors = [line for line in lines if line.startswith("ERROR ")]
    if errors:
        raise BenchError(f"прогон не состоялся: {errors[0][:200]}")
    return [line for line in lines if line.startswith("FAILED ")]


def _parse_node_output(stdout):
    """Разбирает вывод репортёра ``spec`` в пару множеств имён.

    Разбор останавливается на сводке ``failing tests``. Повтор имени сам
    по себе безвреден - складывается в множество, - но после сводки идут
    подробности падения, и любая их строка, начинающаяся с глифа
    (например, разница ожидаемого и полученного), попала бы в множество
    как имя теста. Мутанта тогда объявил бы убитым тест, которого нет.

    Разбор привязан к формату, поэтому формат задаётся флагом, а не
    умолчанием node. Умолчание зависит от версии и от того, пайп перед
    процессом или терминал: в не-TTY node печатает TAP, где ``ok 1 -
    имя`` и ни одного глифа. Разбор вернул бы два пустых множества,
    :func:`check_target` сообщил бы «node не выполнил цель», а
    :func:`baseline` оборвала бы весь прогон - стенд объявил бы себя
    сломанным вместо того, чтобы судить мутанта.

    Args:
        stdout: Стандартный вывод ``node --test``.

    Returns:
        Пару множеств ``(зелёные, красные)``.
    """
    passed, failed = set(), set()
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("✖ failing tests:"):
            break
        for mark, bucket in (("✔ ", passed), ("✖ ", failed)):
            if stripped.startswith(mark):
                bucket.add(stripped[len(mark) :].rsplit(" (", 1)[0])
    return passed, failed


def node_results(test_file, cwd):
    """Возвращает имена зелёных и красных тестов одного файла node.

    У ``node --test`` нет кода возврата со смыслом «цель не найдена»,
    поэтому имена разбираются из вывода - :func:`_parse_node_output`.

    Сам флаг репортёра тестом не закреплён: node в задании
    ``lint-and-test`` нет, а запуск node из pytest сделал бы вердикт
    зависимым от чужого окружения. Закреплён разбор.

    Args:
        test_file: Путь к файлу тестов относительно корня.
        cwd: Каталог, в котором запускать.

    Returns:
        Пару множеств ``(зелёные, красные)``.

    Raises:
        BenchError: node не запускается или не уложился в потолок.
    """
    process = run_tool(
        ["node", "--test", "--test-reporter=spec", test_file],
        cwd=cwd,
        env={**os.environ, "TZ": "UTC"},
    )
    return _parse_node_output(process.stdout)


_FAILED_LINE = re.compile(r"^FAILED ([^\s\[]+(?:\[[^\]]*\])?)")
"""Node id в строке сводки pytest: путь до теста и, если есть, случай в скобках."""


def failed_ident(line):
    """Достаёт node id из строки ``FAILED путь::тест[случай] - сообщение``.

    Резать строку по первому пробелу нельзя. pytest экранирует не-ASCII в
    идентификаторах параметризации, но пробелы внутри них оставляет как
    есть, поэтому у случая вроде ``[создание - 201]`` в сводке будет
    настоящий пробел, и обрезок окажется без закрывающей скобки. Резать
    по « - » тоже нельзя: этот разделитель встречается и внутри такого
    идентификатора.

    Скобочная часть поэтому разбирается отдельно: до неё пробелов не
    бывает, внутри - сколько угодно, а кончается она первой ``]``.

    Args:
        line: Строка сводки pytest, начинающаяся с ``FAILED``.

    Returns:
        Node id упавшего теста.

    Raises:
        BenchError: Строку не удалось разобрать - это поломка стенда,
            а не найденная мутация.
    """
    match = _FAILED_LINE.match(line)
    if match is None:
        raise BenchError(f"не разобрать строку об упавшем тесте: {line[:120]}")
    return match.group(1)


def guards(target, ident):
    """Отвечает, стережёт ли упавший тест ``ident`` цель ``target``.

    Сравнение точное, а не по вхождению подстроки: имена тестов бывают
    префиксами друг друга (``test_search_ignores_case`` и
    ``test_search_ignores_case_in_content``), и подстрочная проверка
    засчитывала чужой красный тест за свой - ровно тот молчаливый обман,
    ради которого стенд и написан. На этой функции держится вся разница
    между «мою мутацию поймали» и «в прогоне упало что-то ещё», поэтому
    она вынесена наружу и закреплена ``tests/test_mutation_bench.py``.

    Args:
        target: Цель мутанта: node id теста либо имя функции, если
            стережёт параметризованный случай.
        ident: Идентификатор упавшего теста.

    Returns:
        Истину, если упал именно стерегущий тест.
    """
    return ident == target or ident.startswith(target + "[")


KILLED, SURVIVED, COLLATERAL = "убит", "ВЫЖИЛ", "ЗАДЕЛ ЛИШНЕЕ"
"""Исходы одного мутанта.

``ЗАДЕЛ ЛИШНЕЕ`` - мутант убит, но покраснел и тест из ``silent``,
который обязан был промолчать. Это не победа: заявление, ради которого
мутант стоит в таблице, оказалось неверным.
"""


def check_target(mutant, cwd):
    """Прогоняет цель мутанта и тесты, обязанные промолчать.

    Args:
        mutant: Мутант.
        cwd: Каталог, в котором запускать.

    Returns:
        Пару ``(исход, подробность)``. Убит - когда упал именно
        стерегущий тест, а не что-нибудь ещё в том же прогоне.

    Raises:
        BenchError: цель не выполнялась.
    """
    if mutant.runner == "node":
        test_file, target_id = mutant.target.split("::", 1)
        passed, failed_names = node_results(test_file, cwd)
        if target_id not in passed | failed_names:
            raise BenchError(f"node не выполнил цель {target_id!r} из {test_file}")
        failed = [(name, name) for name in sorted(failed_names)]
    else:
        target_id = mutant.target
        failed = [
            (failed_ident(line), line)
            for line in run_pytest(
                [mutant.target, *mutant.silent], cwd, browser_required=mutant.runner == "e2e"
            )
        ]

    killed = [text for ident, text in failed if guards(target_id, ident)]
    noisy = [text for ident, text in failed if not guards(target_id, ident)]
    if killed and noisy:
        return COLLATERAL, f"вместе с целью покраснел {noisy[0][:90]}"
    if killed:
        return KILLED, killed[0]
    return SURVIVED, ""


def baseline(mutants, cwd):
    """Контрольный прогон целей на неиспорченном коде.

    Args:
        mutants: Проверяемые мутанты.
        cwd: Копия дерева.

    Returns:
        Истину, если браузерные цели зелёные. Ложь означает недоступный
        браузер: такие мутанты проверить нечем.

    Raises:
        BenchError: небраузерные цели красные - стенду верить нельзя.
    """
    targets = sorted(
        {m.target for m in mutants if m.runner == "pytest"}
        | {silent for m in mutants for silent in m.silent}
    )
    if targets:
        failed = run_pytest(targets, cwd)
        if failed:
            raise BenchError(f"контроль красный до всяких мутаций: {failed[0][:200]}")

    node_targets = [m.target for m in mutants if m.runner == "node"]
    for test_file in sorted({t.split("::", 1)[0] for t in node_targets}):
        passed, failed_names = node_results(test_file, cwd)
        for target in node_targets:
            path, name = target.split("::", 1)
            if path != test_file:
                continue
            if name not in passed | failed_names:
                raise BenchError(f"node не выполнил цель {name!r} из {test_file}")
            if name in failed_names:
                raise BenchError(f"контроль красный до всяких мутаций: {name}")

    e2e_targets = sorted({m.target for m in mutants if m.runner == "e2e"})
    if not e2e_targets:
        return True
    try:
        failed = run_pytest(e2e_targets, cwd, browser_required=True)
    except BenchTimeout:
        # Зависание - поломка стенда, и разбору ниже его отдавать
        # нельзя: повторный прогон без требования браузера пропустит
        # сценарии, вернёт пустой список, и стенд объявит браузер
        # недоступным. Мутанты остались бы непроверенными, а прогон
        # нулевым - при зависшем, а не отсутствующем браузере.
        raise
    except BenchError:
        # Прогон сорвался. Причин две, и они требуют разных ответов:
        # браузера нет (проверять нечем) или сломано что-то ещё (стенду
        # верить нельзя). Различаются они механикой, а не текстом
        # сообщения: без E2E_REQUIRED отсутствие браузера даёт чистый
        # пропуск, а любая другая поломка остаётся поломкой.
        if run_pytest(e2e_targets, cwd):
            raise
        return False
    if failed:
        raise BenchError(f"контроль красный до всяких мутаций: {failed[0][:200]}")
    return True


def apply_mutant(mutant, cwd):
    """Портит один файл и возвращает исходный текст для отката.

    Args:
        mutant: Мутант.
        cwd: Копия дерева.

    Returns:
        Исходное содержимое файла.

    Raises:
        BenchError: кусок не найден или найден не один раз. Молчаливый
            пропуск здесь недопустим: непримененный мутант выглядел бы
            выжившим или убитым в зависимости от везения.
    """
    path = cwd / mutant.path
    source = path.read_text(encoding="utf-8")
    found = source.count(mutant.old)
    if found != 1:
        raise BenchError(
            f"кусок из мутанта «{mutant.name}» встречается в {mutant.path} {found} раз, "
            "а должен ровно один - поправьте таблицу под изменившийся код"
        )
    path.write_text(source.replace(mutant.old, mutant.new), encoding="utf-8")
    return source


def main(argv):
    """Точка входа.

    Args:
        argv: Аргументы командной строки без имени программы.

    Returns:
        Код возврата процесса.
    """
    if "--list" in argv:
        for mutant in MUTANTS:
            print(f"[{mutant.runner:6}] {mutant.name}")
        return 0

    needle = argv[0] if argv else ""
    mutants = [m for m in MUTANTS if needle.lower() in m.name.lower()]
    if not mutants:
        print(f"Ни один мутант не подошёл под «{needle}»")
        return 2
    if not PYTEST.exists():
        print(f"Не найден {PYTEST}: активируйте окружение или поправьте путь")
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="bkmrks-mut-"))
    failures, unchecked = [], []
    try:
        copy_worktree(workdir)
        browser_ready = baseline(mutants, workdir)
        if not browser_ready:
            print("Браузер недоступен: браузерные мутанты не проверяются\n")

        for mutant in mutants:
            if mutant.runner == "e2e" and not browser_ready:
                unchecked.append(mutant)
                print(f"{'НЕ ПРОВЕРЕН':<11} | {mutant.name}")
                continue
            source = apply_mutant(mutant, workdir)
            try:
                outcome, detail = check_target(mutant, workdir)
            finally:
                (workdir / mutant.path).write_text(source, encoding="utf-8")
            if outcome != KILLED:
                failures.append((mutant, outcome))
            print(f"{outcome:<11} | {mutant.name}")
            if detail:
                print(f"{'':<11} | {detail[:110]}")
    except BenchError as error:
        print(f"\nСтенд сломан: {error}")
        return 2
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    checked = len(mutants) - len(unchecked)
    print(f"\nПроверено {checked} из {len(mutants)}, не убито {len(failures)}")
    for mutant, outcome in failures:
        print(f"  {outcome.lower()}: {mutant.name} (стерёг {mutant.target})")
    if unchecked and os.environ.get(E2E_REQUIRED_ENV):
        print(f"  {len(unchecked)} мутантов не проверено, а {E2E_REQUIRED_ENV} требует обратного")
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
