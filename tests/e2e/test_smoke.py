"""Дымовые E2E-сценарии: приложение целиком, в настоящем браузере.

Они про маршруты и про шов «данные - шаблон», а не про оформление:
цвета, отступы и точные формулировки форматтеров E2E не проверяют - это
делают юниты, которые на порядок дешевле и не мигают. Задача этих
сценариев одна: заметить, что связка «браузер - Vue - HTTP - хранилище»
разошлась.

Граница проведена так: E2E утверждает, что значение дошло и прошло через
нужный форматтер (проверяется форма результата), а точный вид строки
закреплён юнитом ``tests/js/format.test.mjs``. Поэтому смена версии ICU
в браузере красит юнит, а не девятнадцать сценариев сразу.

Сеть наружу не используется.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

import parser

pytestmark = pytest.mark.e2e


def test_console_listener_tells_a_script_call_from_browser_noise(live_server, page):
    """Различитель фикстуры ``browser_page`` работает в обе стороны.

    Фикстура считает ошибкой консоли только сообщение с непустыми
    аргументами. Утверждение держится на том, как Playwright строит
    события: настоящий вызов из страницы приходит с ручками аргументов, а
    запись самого браузера из домена ``Log`` - «Failed to load resource»
    на каждый неуспешный HTTP-ответ - создаётся с пустым списком, потому
    что пришедшие от CDP аргументы освобождаются.

    Без этой проверки зелёный прогон браузерного слоя одинаково
    согласуется с «различитель работает» и с «слушатель не срабатывает
    никогда»: обе половины дают ноль записей в списке.

    Берётся плагинная ``page``, а не ``browser_page``: сценарий намеренно
    зовёт ``console.error``, и утверждение фикстуры в разборке покрасило
    бы его на успехе.

    Форма вызова та же, что у Vue: ``console.error`` с объектом ошибки.
    Проверяется различитель, а не сам факт, что Vue гасит исключения.
    """
    page.goto(live_server)

    # Ожидание, а не чтение списка после вызова: запись домена `Log` про
    # неуспешный запрос приходит асинхронно, и голое `evaluate` с
    # последующей проверкой давало бы мигающий тест - он же зелёный,
    # когда сообщение просто не успело.
    with page.expect_console_message(lambda m: m.type == "error") as from_script:
        page.evaluate("() => console.error(new Error('вызов из скрипта'))")

    with page.expect_console_message(lambda m: m.type == "error") as from_browser:
        page.evaluate(
            "async () => { await fetch("
            "'/api/articles/00000000-0000-0000-0000-000000000000') }"
        )

    script_message = from_script.value
    browser_message = from_browser.value

    assert "вызов из скрипта" in script_message.text, (
        f"поймано не то сообщение: {script_message.text[:120]}"
    )
    assert script_message.args, (
        "вызов console.error из страницы пришёл с пустым списком аргументов, "
        "поэтому фикстура browser_page не заметила бы и исключение, "
        "погашенное Vue: различитель по непустоте аргументов неверен"
    )
    assert not browser_message.args, (
        f"запись браузера о неуспешном запросе ({browser_message.text[:80]}) "
        "пришла с непустым списком аргументов, поэтому фикстура browser_page "
        "красила бы сценарии на штатном показе ошибки: различитель по "
        "непустоте аргументов неверен"
    )


def test_library_shows_saved_articles(live_server, browser_page, stored_article):
    """Открыть библиотеку - карточки сохранённых статей видны и заполнены.

    Утверждается не только число карточек, но и то, что в них попало:
    заголовок статьи, дата, пропущенная через форматтер, и врезка из
    текста.

    Дата проверяется по форме, а не по точной строке: «1 янв.» против
    сырого ``2026-01-01T12:00:00Z`` - это и есть вопрос «работает ли
    форматтер»; конкретное написание месяца закреплено юнитом и от
    версии ICU в браузере здесь ничего не зависит.
    """
    stored_article(title="Первая")
    stored_article(title="Вторая")

    browser_page.goto(live_server)

    expect(browser_page.get_by_role("main").get_by_role("link")).to_have_count(2)
    # Новые статьи идут первыми, поэтому «Вторая» стоит выше.
    expect(browser_page.get_by_role("heading", level=2)).to_have_text(["Вторая", "Первая"])
    expect(browser_page.get_by_role("time").first).to_have_text(
        re.compile(r"^\d{1,2}\s+[а-я]+\.?$")
    )
    expect(
        browser_page.get_by_role("article").get_by_role("paragraph").first
    ).to_contain_text("Первый абзац.")


def test_card_opens_the_article_in_reader(live_server, browser_page, stored_article):
    """Клик по карточке открывает эту статью в читалке.

    Текст статьи проверяется здесь же: разбиение на абзацы - работа
    читалки, и оно видно только тому, кто дошёл до отрисованной
    страницы.
    """
    article = stored_article(title="Открываемая")
    browser_page.goto(live_server)

    browser_page.get_by_role("main").get_by_role("link").click()

    expect(browser_page).to_have_url(f"{live_server}/reader.html?id={article['id']}")
    expect(browser_page.get_by_role("heading", level=1)).to_have_text("Открываемая")
    expect(
        browser_page.get_by_role("region", name="Текст статьи").get_by_role("paragraph")
    ).to_have_text(["Первый абзац.", "Второй абзац."])


def test_hostile_markup_from_a_saved_page_is_not_executed(
    live_server, browser_page, stored_article
):
    """Разметка из сохранённой страницы показывается текстом, а не исполняется.

    Содержимое статьи приходит с чужого сайта, и единственное, что стоит между ним и
    исполнением в браузере пользователя, - способ вывода в шаблоне.

    Проверяется в обе стороны: текст виден буквально (значит вывод
    экранирован) и в DOM не появилось ни одного узла из полезной
    нагрузки (значит разметка не разобрана).
    """
    hostile_title = '<img src=x onerror="window.__xss = true">'
    hostile_content = "<script>window.__xss = true</script>"
    article = stored_article(title=hostile_title, content=hostile_content)

    browser_page.goto(f"{live_server}/reader.html?id={article['id']}")

    text = browser_page.get_by_role("region", name="Текст статьи")
    expect(browser_page.get_by_role("heading", level=1)).to_have_text(hostile_title)
    expect(text.get_by_role("paragraph")).to_have_text([hostile_content])
    # Имена узлов, а не классы оформления: перевёрстка их не трогает,
    # а разобранная разметка появилась бы именно такими узлами.
    expect(browser_page.get_by_role("heading", level=1).locator("img")).to_have_count(0)
    expect(text.locator("script")).to_have_count(0)
    assert browser_page.evaluate("window.__xss === undefined"), "полезная нагрузка исполнилась"


def test_saving_url_adds_card(live_server, browser_page, parsed_page):
    """Сохранить адрес - карточка появляется без перезагрузки страницы."""
    parsed_page(title="Новая статья")
    browser_page.goto(live_server)

    browser_page.get_by_label("Адрес статьи").fill("https://example.com/a")
    browser_page.get_by_role("button", name="Сохранить").click()

    expect(browser_page.get_by_role("main").get_by_role("link")).to_have_count(1)


def test_failed_save_is_shown_to_the_user(live_server, browser_page, monkeypatch):
    """Не удалось сохранить - человек видит причину, а не пустой экран.

    Не притворяется работающим, когда операция не удалась. Проверяется вся цепочка
    целиком: текст ошибки рождается в ``parser``, превращается в ``422``
    с ``detail``, разбирается клиентом и доходит до абзаца на странице.
    """
    def refuse(url):
        raise ValueError("Сайт не ответил за 15 секунд")

    monkeypatch.setattr(parser, "parse", refuse)
    browser_page.goto(live_server)

    browser_page.get_by_label("Адрес статьи").fill("https://example.com/a")
    browser_page.get_by_role("button", name="Сохранить").click()

    expect(browser_page.get_by_role("alert")).to_have_text("Сайт не ответил за 15 секунд")
    expect(browser_page.get_by_role("main").get_by_role("link")).to_have_count(0)


def test_search_narrows_list_and_survives_reload(live_server, browser_page, stored_article):
    """Поиск сужает список, состояние остаётся в адресе и переживает перезагрузку.

    Это исполняемая форма обещания «фильтрами можно поделиться»: ссылка
    должна открыть тот же отфильтрованный список, а не всю библиотеку.
    """
    stored_article(title="Машинное обучение")
    stored_article(title="Кулинария")
    browser_page.goto(live_server)

    browser_page.get_by_label("Поиск").fill("машинное")

    expect(browser_page.get_by_role("main").get_by_role("link")).to_have_count(1)
    expect(browser_page).to_have_url(re.compile(r"[?&]q="))
    browser_page.reload()
    expect(browser_page.get_by_role("main").get_by_role("link")).to_have_count(1)


def test_tag_filter_narrows_list_and_survives_reload(live_server, browser_page, stored_article):
    """То же обещание для фильтра по тегу: он в адресе и переживает перезагрузку.

    Отдельный сценарий, а не строчка в предыдущем: в браузере это разные
    пути. Поиск идёт через ``watch`` с отложенным запуском, тег - прямым
    вызовом ``selectTag``.
    """
    stored_article(title="Рабочая", tags=["работа"])
    stored_article(title="Домашняя", tags=["дом"])
    browser_page.goto(live_server)

    # Доступное имя чипа - это имя тега и счётчик статей: «работа 1».
    # Поэтому сопоставляется форма целиком, а не точная строка: число
    # зависит от данных. `\b` здесь не годится - Playwright исполняет
    # выражение как JS-RegExp, где граница слова только для ASCII, и
    # после кириллической «а» её нет.
    browser_page.get_by_role("button", name=re.compile(r"^работа\s+\d+$")).click()

    expect(browser_page.get_by_role("heading", level=2)).to_have_text(["Рабочая"])
    expect(browser_page).to_have_url(re.compile(r"[?&]tag="))
    browser_page.reload()
    expect(browser_page.get_by_role("heading", level=2)).to_have_text(["Рабочая"])


def test_empty_list_explains_why_it_is_empty(live_server, browser_page):
    """Пустой список объясняет причину, а причины две и они разные.

    «Библиотека пуста» и «Ничего не найдено» - не украшение: первое
    означает «добавьте статью», второе - «поменяйте запрос».
    """
    browser_page.goto(live_server)

    expect(browser_page.get_by_role("status")).to_have_text("Библиотека пуста")

    browser_page.get_by_label("Поиск").fill("такого-точно-нет")

    expect(browser_page.get_by_role("status")).to_have_text("Ничего не найдено")


def test_delete_asks_for_confirmation(live_server, browser_page, stored_article):
    """Удаление спрашивает подтверждение; отказ оставляет статью на месте."""
    article = stored_article(title="Одноразовая")
    browser_page.goto(f"{live_server}/reader.html?id={article['id']}")

    browser_page.once("dialog", lambda dialog: dialog.dismiss())
    browser_page.get_by_role("button", name="Удалить").click()

    # Перезагрузка обязательна. Без неё страница показывает статью из
    # памяти даже после удаления, а проверка адреса истинна сразу же и
    # не успевает заметить переход - утверждение проходило бы всегда.
    browser_page.reload()
    expect(browser_page.get_by_role("heading", level=1)).to_have_text("Одноразовая")

    browser_page.once("dialog", lambda dialog: dialog.accept())
    browser_page.get_by_role("button", name="Удалить").click()

    expect(browser_page).to_have_url(f"{live_server}/")
    expect(browser_page.get_by_role("main").get_by_role("link")).to_have_count(0)


def test_tag_added_in_reader_survives_reload(live_server, browser_page, stored_article):
    """Тег, проставленный в читалке, сохраняется на сервере.

    Перезагрузка обязательна. Без неё страница показывает тег из памяти
    браузера, и сценарий остаётся зелёным, даже если запрос до сервера
    не дошёл, - то есть проверял бы ровно ту часть, которая и так
    очевидна.
    """
    article = stored_article(title="Без тегов")
    browser_page.goto(f"{live_server}/reader.html?id={article['id']}")

    browser_page.get_by_role("button", name="+ тег").click()
    browser_page.get_by_label("Имя нового тега").fill("работа")
    browser_page.keyboard.press("Enter")

    # Сам тег - <span>, у которого роли нет. Зато у его кнопки удаления
    # есть подпись «Убрать тег <имя>», и она говорит ровно то же: сколько
    # кнопок - столько тегов, а подпись называет каждый.
    tags = browser_page.get_by_role("button", name=re.compile(r"^Убрать тег "))
    expect(tags).to_have_count(1)
    expect(browser_page.get_by_role("button", name="Убрать тег работа")).to_be_visible()
    browser_page.reload()
    expect(tags).to_have_count(1)
    expect(browser_page.get_by_role("button", name="Убрать тег работа")).to_be_visible()


def test_keyboard_reaches_save_button(live_server, browser_page):
    """С поля адреса ``Tab`` попадает на кнопку сохранения.

    Проверяется порядок обхода. Кнопка, выпавшая из
    обхода (``tabindex="-1"``, замена на ``div``), ломает работу с
    клавиатуры молча - на глаз этого не видно.
    """
    browser_page.goto(live_server)

    browser_page.get_by_label("Адрес статьи").focus()
    browser_page.keyboard.press("Tab")

    expect(browser_page.get_by_role("button", name="Сохранить")).to_be_focused()


def test_theme_choice_survives_reload(live_server, browser_page):
    """Выбор темы переживает перезагрузку страницы.

    Проверяется поведение, а не оформление: какая тема получилась -
    неважно, важно, что явный выбор сделан и не потерян. Тест не знает
    ни одного цвета.
    """
    browser_page.goto(live_server)
    html = browser_page.locator("html")
    # Без выбора тема идёт за системной, то есть атрибута нет вовсе.
    # Утверждение с ожиданием, а не снимок состояния: theme.js сегодня
    # успевает отработать к событию load, которого дожидается goto, но
    # перенеси применение темы за requestIdleCallback или динамический
    # import - и одноразовое чтение стало бы гонкой: зелёной на быстрой
    # машине, красной на загруженном раннере и с сообщением про тему
    # вместо сообщения про время.
    expect(html).not_to_have_attribute("data-theme", re.compile(r"."))

    browser_page.get_by_role("button", name=re.compile(r"^Включить (светлую|тёмную) тему$")).click()

    expect(html).to_have_attribute("data-theme", re.compile(r"^(light|dark)$"))
    chosen = html.get_attribute("data-theme")
    browser_page.reload()
    expect(html).to_have_attribute("data-theme", chosen)


def test_font_scale_survives_reload(live_server, browser_page, stored_article):
    """Выбранный размер шрифта переживает перезагрузку.

    Второе из поведений ``reader.js``, видимых снаружи целиком: выбор
    пишется в ``localStorage`` и применяется переменной
    ``--reader-font-scale`` на области текста. Как и с темой,
    браузер проверяет это дешевле поддельного DOM.

    Утверждается поведение: размер вырос и не потерялся.
    """
    article = stored_article(title="Читаемая")
    browser_page.goto(f"{live_server}/reader.html?id={article['id']}")

    text = browser_page.get_by_role("region", name="Текст статьи")
    before = text.evaluate("el => getComputedStyle(el).fontSize")

    browser_page.get_by_role("button", name="Увеличить шрифт").click()

    enlarged = text.evaluate("el => getComputedStyle(el).fontSize")
    assert float(enlarged.removesuffix("px")) > float(before.removesuffix("px")), (
        f"шрифт не вырос: было {before}, стало {enlarged}"
    )
    browser_page.reload()
    # Снимок, а не утверждение с ожиданием: размер применяется до
    # первой отрисовки, поэтому промежуточного состояния не бывает.
    assert text.evaluate("el => getComputedStyle(el).fontSize") == enlarged


def test_font_scale_stops_at_the_ends_of_its_range(live_server, browser_page, stored_article):
    """На краях диапазона кнопка размера выключается.

    Отдельный сценарий, а не утверждение в предыдущем: причины покраснеть
    разные - там теряется выбор, здесь размер уходит за границу списка
    шагов. Один сценарий на две причины сообщал бы не то, что сломалось.

    Число шагов не закрепляется: кнопка нажимается, пока не выключится,
    а сценарий утверждает, что край вообще наступает и что от него можно
    вернуться.
    """
    article = stored_article(title="Читаемая")
    browser_page.goto(f"{live_server}/reader.html?id={article['id']}")

    bigger = browser_page.get_by_role("button", name="Увеличить шрифт")
    smaller = browser_page.get_by_role("button", name="Уменьшить шрифт")

    # Потолок на случай, если край перестанет наступать: без него
    # сломанная граница дала бы вечный цикл вместо красного теста.
    for _ in range(10):
        if bigger.is_disabled():
            break
        bigger.click()
    expect(bigger).to_be_disabled()
    expect(smaller).to_be_enabled()

    for _ in range(10):
        if smaller.is_disabled():
            break
        smaller.click()
    expect(smaller).to_be_disabled()
    expect(bigger).to_be_enabled()


def test_export_button_hands_the_browser_a_file(live_server, browser_page, stored_article):
    """Кнопка экспорта отдаёт браузеру архив.

    Формат утверждается именем файла: оно приходит от сервера
    заголовком ``Content-Disposition``, поэтому называет ровно тот
    формат, который был запрошен.
    """
    stored_article(title="Вывозимая")
    browser_page.goto(live_server)

    # Кнопки форматов лежат в закрытом <details>: пока он закрыт,
    # браузер их не отрисовывает, и локатор ничего не найдёт.
    #
    # Меню адресуется ролью `group` - так Chromium показывает <details>.
    # Роли `button` у <summary> нет: браузер держит для него собственную
    # роль вне словаря ARIA. Имени у группы тоже нет - вычисление
    # доступного имени не берёт его из <summary>, - поэтому внутри
    # группы <summary> находится по видимому тексту, ровно как кнопки
    # в остальных сценариях.
    browser_page.get_by_role("group").get_by_text("Экспорт", exact=True).click()
    with browser_page.expect_download() as downloaded:
        browser_page.get_by_role("button", name="Архив ZIP").click()
    download = downloaded.value

    assert download.suggested_filename == "bkmrks-export.zip"
    # Первые байты, а не размер: пустой файл с правильным именем тоже
    # «скачался», а архив обязан начинаться сигнатурой zip.
    assert Path(download.path()).read_bytes()[:2] == b"PK", "браузер получил не архив"


def test_tag_removed_in_reader_stays_removed(live_server, browser_page, stored_article):
    """Снятый в читалке тег исчезает и не возвращается после перезагрузки.
    """
    article = stored_article(title="Помеченная", tags=["работа"])
    browser_page.goto(f"{live_server}/reader.html?id={article['id']}")

    browser_page.get_by_role("button", name="Убрать тег работа").click()

    tags = browser_page.get_by_role("button", name=re.compile(r"^Убрать тег "))
    # Без перезагрузки - значит ответ сервера доехал до разметки, а не
    # только до хранилища: перерисовку после успеха легко потерять.
    expect(tags).to_have_count(0)
    browser_page.reload()
    expect(tags).to_have_count(0)


@pytest.mark.browser_context_args(
    viewport={"width": 390, "height": 844}, reduced_motion="reduce"
)
def test_long_tag_list_collapses_and_expands(live_server, browser_page, stored_article):
    """Переполненный список тегов сворачивается и раскрывается кнопкой.

    Узкий экран здесь не декорация, а способ сделать сценарий
    неслучайным: переполнение ``library.js`` считает измерением вёрстки
    (``scrollHeight`` против свёрнутой высоты), а не числом тегов.
    На умолчательной ширине понадобились бы десятки тегов «на глаз»,
    и запас держался бы на удаче.

    Заодно это единственный сценарий, исполняющий узкую вёрстку
    (``@media (max-width: 640px)``) и ветку отключённой анимации
    (``prefers-reduced-motion``).
    """
    stored_article(title="Многотеговая", tags=[f"тема-{n:02d}" for n in range(1, 13)])
    browser_page.goto(live_server)

    more = browser_page.get_by_role("button", name=re.compile(r"^Ещё \d+$"))
    expect(more).to_have_attribute("aria-expanded", "false")

    more.click()

    expect(browser_page.get_by_role("button", name="Свернуть")).to_have_attribute(
        "aria-expanded", "true"
    )


def test_system_theme_applies_while_no_choice_is_made(live_server, browser_page):
    """Без явного выбора тема идёт за системной и меняется вместе с ней.

    Сценарий темы рядом проверяет обратное - что явный выбор переживает
    перезагрузку.

    Тема читается по подписи кнопки: она называет тему, в которую
    переключит, то есть противоположную действующей.
    """
    browser_page.emulate_media(color_scheme="dark")
    browser_page.goto(live_server)

    expect(browser_page.get_by_role("button", name="Включить светлую тему")).to_be_visible()

    # Смена системной настройки на живой странице: именно её слушает
    # обработчик в theme.js, и именно он до сих пор не исполнялся.
    browser_page.emulate_media(color_scheme="light")

    expect(browser_page.get_by_role("button", name="Включить тёмную тему")).to_be_visible()
    # Атрибута по-прежнему нет: он означает явный выбор, а его не было.
    expect(browser_page.locator("html")).not_to_have_attribute("data-theme", re.compile(r"."))


def test_explicit_theme_outlives_a_system_change(live_server, browser_page):
    """Явный выбор темы не отменяется сменой системной настройки.

    Сделанный выбор важнее системного.

    Сценарий дожидается, пока смена дойдёт до страницы, и только потом
    утверждает. Без этого он выигрывал гонку у события.

    Ожидание не пауза: страница сама сообщает о полученном событии. Свой
    слушатель добавлен после загрузки, то есть после слушателя
    ``theme.js``, и получает событие следом за ним.

    Утверждается атрибут, а не только вид страницы: обработчик снимает
    ``data-theme`` первой же строкой, поэтому потеря выбора видна даже
    тогда, когда системная настройка совпала с выбранной темой.
    """
    browser_page.emulate_media(color_scheme="light")
    browser_page.goto(live_server)

    browser_page.get_by_role("button", name="Включить тёмную тему").click()
    html = browser_page.locator("html")
    expect(html).to_have_attribute("data-theme", "dark")

    browser_page.evaluate(
        """() => {
            window.__systemChangeSeen = false;
            // Ссылка удержана: несохранённый MediaQueryList собирает
            // сборщик мусора вместе со слушателем.
            window.__watchedMedia = window.matchMedia("(prefers-color-scheme: dark)");
            window.__watchedMedia.addEventListener(
                "change", () => (window.__systemChangeSeen = true), {once: true}
            );
        }"""
    )
    browser_page.emulate_media(color_scheme="dark")
    browser_page.wait_for_function("() => window.__systemChangeSeen")

    expect(html).to_have_attribute("data-theme", "dark")
    expect(browser_page.get_by_role("button", name="Включить светлую тему")).to_be_visible()
