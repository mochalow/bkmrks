/**
 * Тесты клиентского доступа к REST API.
 *
 * Сеть подменяется: globalThis.fetch заменяется заглушкой, которая
 * записывает вызовы и отдаёт настоящий Response - так проверяется
 * ровно то, что модуль делает с ответом, без запущенного сервера.
 *
 * Запуск: TZ=UTC node --test "tests/js/*.test.mjs"
 */

import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import path from "node:path";
import {test} from "node:test";

import {
    addTag,
    createArticle,
    deleteArticle,
    exportLibrary,
    getArticle,
    listArticles,
    listTags,
    removeTag,
} from "../../static/js/api.js";

const realFetch = globalThis.fetch;

/**
 * Подменяет fetch заглушкой и возвращает журнал вызовов.
 *
 * @param {Function} respond - Что вернуть на запрос (Response или бросок).
 * @param {Object} t - Контекст теста node:test, для восстановления fetch.
 * @returns {Array} Журнал вызовов: {path, options}.
 */
function stubFetch(respond, t) {
    const calls = [];
    globalThis.fetch = async (path, options) => {
        calls.push({path, options});
        return respond(path, options);
    };
    t.after(() => {
        globalThis.fetch = realFetch;
    });
    return calls;
}

const json = (body, status = 200) =>
    new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}});

// --- Построение запросов ---

test("listArticles без фильтров не добавляет query-строку", async (t) => {
    const calls = stubFetch(() => json([]), t);

    await listArticles();

    assert.equal(calls[0].path, "/api/articles");
});

test("listArticles добавляет только заданные фильтры", async (t) => {
    const calls = stubFetch(() => json([]), t);

    await listArticles({q: "python"});
    await listArticles({tag: "news"});
    await listArticles({q: "python", tag: "news"});

    assert.equal(calls[0].path, "/api/articles?q=python");
    assert.equal(calls[1].path, "/api/articles?tag=news");
    assert.equal(calls[2].path, "/api/articles?q=python&tag=news");
});

test("listArticles экранирует спецсимволы в фильтрах", async (t) => {
    const calls = stubFetch(() => json([]), t);

    await listArticles({q: "a&b=c", tag: "тег"});

    assert.equal(calls[0].path, "/api/articles?q=a%26b%3Dc&tag=%D1%82%D0%B5%D0%B3");
});

test("listTags запрашивает счётчики отдельным путём", async (t) => {
    const calls = stubFetch(() => json({python: 2}), t);

    assert.deepEqual(await listTags(), {python: 2});
    assert.equal(calls[0].path, "/api/tags");
});

test("getArticle кодирует идентификатор в пути", async (t) => {
    const calls = stubFetch(() => json({id: "x"}), t);

    await getArticle("a/b");

    assert.equal(calls[0].path, "/api/articles/a%2Fb");
});

test("createArticle отправляет адрес телом POST", async (t) => {
    const calls = stubFetch(() => json({id: "x"}, 201), t);

    await createArticle("https://example.com/a");

    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(calls[0].options.body), {url: "https://example.com/a"});
});

test("addTag отправляет тег телом POST", async (t) => {
    const calls = stubFetch(() => json({tags: ["python"]}), t);

    await addTag("id-1", "Python");

    assert.equal(calls[0].path, "/api/articles/id-1/tags");
    assert.deepEqual(JSON.parse(calls[0].options.body), {tag: "Python"});
});

test("removeTag кодирует тег в пути", async (t) => {
    const calls = stubFetch(() => json({tags: []}), t);

    await removeTag("id-1", "машинное обучение");

    assert.equal(
        calls[0].path,
        "/api/articles/id-1/tags/%D0%BC%D0%B0%D1%88%D0%B8%D0%BD%D0%BD%D0%BE%D0%B5%20%D0%BE%D0%B1%D1%83%D1%87%D0%B5%D0%BD%D0%B8%D0%B5",
    );
    assert.equal(calls[0].options.method, "DELETE");
});

test("deleteArticle на 204 возвращает null, не пытаясь разобрать тело", async (t) => {
    stubFetch(() => new Response(null, {status: 204}), t);

    assert.equal(await deleteArticle("id-1"), null);
});

// --- Разбор ошибок ---

test("строковый detail показывается пользователю как есть", async (t) => {
    stubFetch(() => json({detail: "Статья не найдена"}, 404), t);

    await assert.rejects(getArticle("id-1"), {message: "Статья не найдена"});
});

test("список ошибок валидации склеивается в одну строку", async (t) => {
    stubFetch(
        () => json({detail: [{msg: "Строка слишком короткая"}, {msg: "Неверный формат"}]}, 422),
        t,
    );

    await assert.rejects(createArticle("не адрес"), {
        message: "Строка слишком короткая; Неверный формат",
    });
});

test("неразбираемое тело ошибки не мешает сообщить код", async (t) => {
    stubFetch(() => new Response("<html>502</html>", {status: 502}), t);

    await assert.rejects(listArticles(), {message: "Сервер вернул ошибку 502"});
});

test("сетевой сбой превращается в подсказку, а не в текст исключения", async (t) => {
    const cause = new TypeError("Failed to fetch");
    stubFetch(() => {
        throw cause;
    }, t);

    await assert.rejects(listArticles(), (err) => {
        assert.match(err.message, /Не удалось связаться с сервером/);
        assert.equal(err.cause, cause);
        return true;
    });
});

// --- Экспорт ---

/**
 * Подменяет браузерные глобалы, которых нет в Node, и возвращает журнал.
 *
 * @param {Object} t - Контекст теста node:test.
 * @returns {Object} {link, revoked} - созданная ссылка и факт освобождения.
 */
function stubDownload(t) {
    const state = {link: null, revoked: false, blob: null};
    const link = {href: "", download: "", click: () => (state.clicked = true)};
    state.link = link;

    // Сохраняем настоящие реализации: у URL это собственные свойства, и
    // delete после присваивания стёр бы их насовсем, а не вернул исходные.
    const realCreateObjectURL = URL.createObjectURL;
    const realRevokeObjectURL = URL.revokeObjectURL;

    globalThis.document = {createElement: () => link};
    // Тело запоминается: без него ни один тест не отличает выгрузку
    // библиотеки от выгрузки пустого файла с правильным именем.
    URL.createObjectURL = (blob) => {
        state.blob = blob;
        return "blob:тест";
    };
    URL.revokeObjectURL = () => (state.revoked = true);

    t.after(() => {
        delete globalThis.document;
        URL.createObjectURL = realCreateObjectURL;
        URL.revokeObjectURL = realRevokeObjectURL;
    });
    return state;
}

// Имя в заголовке намеренно не совпадает с именем по умолчанию.
test("exportLibrary берёт имя файла из Content-Disposition", async (t) => {
    const calls = stubFetch(
        () =>
            new Response("данные", {
                headers: {"Content-Disposition": "attachment; filename=bkmrks-2026-09.zip"},
            }),
        t,
    );
    const state = stubDownload(t);

    await exportLibrary("zip");

    assert.equal(calls[0].path, "/api/export?format=zip");
    assert.equal(state.link.download, "bkmrks-2026-09.zip");
    assert.ok(state.clicked);
});

test("exportLibrary отдаёт браузеру тело ответа, а не пустой файл", async (t) => {
    stubFetch(() => new Response("содержимое архива"), t);
    const state = stubDownload(t);

    await exportLibrary("zip");

    assert.equal(await state.blob.text(), "содержимое архива");
    assert.equal(state.link.href, "blob:тест", "ссылка должна вести на созданный объектный URL");
});

test("exportLibrary подставляет имя по умолчанию без заголовка", async (t) => {
    stubFetch(() => new Response("[]"), t);
    const state = stubDownload(t);

    await exportLibrary("json");

    assert.equal(state.link.download, "bkmrks-export.json");
});

test("exportLibrary освобождает объектный URL даже при сбое клика", async (t) => {
    stubFetch(() => new Response("данные"), t);
    const state = stubDownload(t);
    state.link.click = () => {
        throw new Error("клик не удался");
    };

    await assert.rejects(exportLibrary("zip"), {message: "клик не удался"});
    assert.ok(state.revoked, "objectURL должен освобождаться в finally");
});

test("exportLibrary сообщает об ошибке сервера человеческим текстом", async (t) => {
    stubFetch(() => json({detail: "Экспорт недоступен"}, 500), t);

    await assert.rejects(exportLibrary(), {message: "Экспорт недоступен"});
});

// Не дубль теста про сетевой сбой выше: тот проходит через request(),
// а exportLibrary ходит в сеть сам и ловит сбой своим catch.
test("exportLibrary при недоступной сети подсказывает, а не показывает текст исключения", async (t) => {
    const cause = new TypeError("Failed to fetch");
    stubFetch(() => {
        throw cause;
    }, t);

    await assert.rejects(exportLibrary("zip"), (err) => {
        assert.match(err.message, /Не удалось связаться с сервером/);
        assert.equal(err.cause, cause);
        return true;
    });
});

// --- Стык с опубликованной схемой ---

/**
 * Пути, объявленные схемой сервера.
 *
 * Файл порождает pytest из ``main.app.openapi()``; сверяет его со схемой
 * ``tests/test_openapi_contract.py::test_published_paths_match_the_shared_fixture``,
 * и он же печатает команду перегенерации, когда они разойдутся.
 */
const SCHEMA_PATHS = new Set(
    JSON.parse(
        readFileSync(path.join(import.meta.dirname, "..", "fixtures", "api-paths.json"), "utf8"),
    ),
);

const SAMPLE_ID = "11111111-2222-3333-4444-555555555555";
const SAMPLE_TAG = "работа";

/**
 * Сворачивает настоящий путь запроса в шаблон схемы.
 *
 * Подставленные значения известны заранее, поэтому заменяются буквально,
 * а не угадываются выражением: угадывание однажды сочло бы шаблоном то,
 * что им не является.
 *
 * @param {string} requested - Путь, который клиент передал в fetch.
 * @returns {string} Тот же путь с {article_id} и {tag} вместо значений.
 */
function shapeOf(requested) {
    return requested
        .split("?")[0]
        .replace("/" + encodeURIComponent(SAMPLE_ID), "/{article_id}")
        .replace("/" + encodeURIComponent(SAMPLE_TAG), "/{tag}");
}

test("каждый путь, который строит клиент, объявлен в схеме сервера", async (t) => {
    const calls = stubFetch(() => json({}), t);
    stubDownload(t);

    await listArticles({q: "запрос", tag: SAMPLE_TAG});
    await listTags();
    await getArticle(SAMPLE_ID);
    await createArticle("https://example.com/a");
    await deleteArticle(SAMPLE_ID);
    await addTag(SAMPLE_ID, SAMPLE_TAG);
    await removeTag(SAMPLE_ID, SAMPLE_TAG);
    await exportLibrary("zip");

    // Пустая фикстура или необойдённый клиент прошли бы цикл ниже,
    // ничего не проверив.
    assert.ok(SCHEMA_PATHS.size > 0, "фикстура схемы пуста");
    assert.equal(calls.length, 8, "обойдены не все функции клиента");

    for (const {path: requested} of calls) {
        assert.ok(
            SCHEMA_PATHS.has(shapeOf(requested)),
            `клиент просит ${requested} - в схеме сервера такого пути нет`,
        );
    }
});
