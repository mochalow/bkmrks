/**
 * Сторож раскладки фронтенда: какие модули покрыты юнитами, а какие нет.
 *
 * Раскладка объявлена здесь и обязана совпадать с
 * каталогом. Новый модуль красит набор и требует решения - покрыть
 * юнитами или отложить.
 *
 * Проверяется не только полнота списков, но и их честность: модуль,
 * объявленный покрытым, обязан импортироваться хотя бы одним тестом, а
 * отложенный - не импортироваться ни одним. Иначе список превращается
 * в декларацию о намерениях, которую никто не сверяет с фактом.
 *
 * Запуск: TZ=UTC node --test "tests/js/*.test.mjs"
 */

import assert from "node:assert/strict";
import {readdirSync, readFileSync} from "node:fs";
import path from "node:path";
import {test} from "node:test";

const HERE = import.meta.dirname;
const MODULES_DIR = path.join(HERE, "..", "..", "static", "js");

/** Модули, поведение которых закреплено юнит-тестами. */
const TESTED = ["api.js", "format.js"];

/** Модули без юнитов. */
const DEFERRED = ["library.js", "reader.js", "theme.js"];

/** Чужой код юнитами не покрывается. */
const VENDORED = ["vue.esm-browser.prod.js"];

const SELF = path.basename(new URL(import.meta.url).pathname);

/**
 * Исходники всех тестов фронтенда, кроме этого файла.
 *
 * Себя сторож исключает: имена модулей он и так перечисляет, и без
 * исключения любой отложенный модуль выглядел бы импортированным.
 *
 * @returns {string} Склеенные тексты тестовых файлов.
 */
function testSources() {
    return readdirSync(HERE)
        .filter((name) => name.endsWith(".test.mjs") && name !== SELF)
        .map((name) => readFileSync(path.join(HERE, name), "utf8"))
        .join("\n");
}

/**
 * Имена модулей, которые тесты действительно импортируют.
 *
 * Читается инструкция импорта, а не текст файла целиком: имя модуля,
 * упомянутое в комментарии или строковом литерале, покрытием не
 * является, а «строка встречается в файле» и «модуль импортирован» -
 * разные утверждения.
 *
 * @returns {Set<string>} Базовые имена импортированных модулей.
 */
function importedModules() {
    const pattern = /^\s*import\s+(?:[^"';]*?\sfrom\s+)?["']([^"']+)["']/gm;
    const imported = new Set();
    for (const match of testSources().matchAll(pattern)) {
        imported.add(path.basename(match[1]));
    }
    return imported;
}

const modules = readdirSync(MODULES_DIR)
    .filter((name) => name.endsWith(".js"))
    .sort();

test("каждый модуль фронтенда объявлен покрытым, отложенным или сторонним", () => {
    assert.deepEqual(
        modules,
        [...TESTED, ...DEFERRED, ...VENDORED].sort(),
        "раскладка static/js разошлась со списками: покройте новый модуль юнитами " +
            "или объявите отложенным, дописав в DEFERRED",
    );
});

test("модуль, объявленный покрытым, действительно импортируется тестом", () => {
    const imported = importedModules();
    for (const name of TESTED) {
        assert.ok(
            imported.has(name),
            `${name} объявлен покрытым, но его не импортирует ни один тест`,
        );
    }
});

test("отложенный модуль не импортируется ни одним тестом", () => {
    const imported = importedModules();
    for (const name of DEFERRED) {
        assert.ok(
            !imported.has(name),
            `${name} уже покрыт юнитами - перенесите его из DEFERRED в TESTED`,
        );
    }
});
