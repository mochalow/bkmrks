/**
 * Тесты форматтеров библиотеки и читалки.
 *
 * Запуск: TZ=UTC node --test "tests/js/*.test.mjs"
 *
 * Пояс задаётся снаружи и проверяется здесь, а не назначается здесь.
 *
 * Пояс уже задан в обоих способах запуска - в CI и в мутационном
 * стенде, - поэтому проверка ничего не ломает, а разрыв между ними
 * делает видимым сразу.
 */

import assert from "node:assert/strict";
import {test} from "node:test";

import {dateLong, dateShort, domainOf, excerptOf, readingTimeOf} from "../../static/js/format.js";

// Спрашивается действующий пояс, а не переменная окружения: на машине,
// живущей в UTC, переменной нет, а даты форматируются верно - красный
// там был бы ложным.
assert.equal(
    Intl.DateTimeFormat().resolvedOptions().timeZone,
    "UTC",
    "запускайте с TZ=UTC: даты форматируются в поясе машины, и полуденная метка UTC " +
        "уезжает на следующие сутки у всех восточнее +12",
);

test("domainOf вынимает домен из адреса", () => {
    assert.equal(domainOf("https://example.com/path/article"), "example.com");
    assert.equal(domainOf("https://sub.example.com:8443/a?b=1"), "sub.example.com");
});

test("domainOf не бросает исключений на битом адресе", () => {
    // Вызывается прямо из шаблона: исключение уронило бы рендер всей карточки.
    assert.equal(domainOf("не адрес"), "не адрес");
    assert.equal(domainOf(""), "");
    assert.equal(domainOf(null), "");
});

test("excerptOf оставляет короткий текст как есть", () => {
    assert.equal(excerptOf("Короткий текст."), "Короткий текст.");
    assert.equal(excerptOf("  с пробелами  "), "с пробелами");
});

test("excerptOf обрезает длинный текст по границе слова", () => {
    const text = "слово ".repeat(100);

    const result = excerptOf(text);

    assert.ok(result.endsWith("..."));
    assert.ok(result.length <= 303);
    assert.ok(!result.slice(0, -3).endsWith(" "));
});

test("excerptOf режет по символам, если пробел слишком далеко от конца", () => {
    // Пробел на второй позиции - обрезка по слову съела бы почти весь текст.
    const text = "а б" + "в".repeat(400);

    const result = excerptOf(text);

    assert.equal(result.length, 303);
});

test("excerptOf принимает пустое значение", () => {
    assert.equal(excerptOf(null), "");
    assert.equal(excerptOf(undefined), "");
});

test("readingTimeOf оценивает время чтения по числу слов", () => {
    assert.equal(readingTimeOf("слово ".repeat(180)), "≈1 мин");
    assert.equal(readingTimeOf("слово ".repeat(360)), "≈2 мин");
});

test("readingTimeOf никогда не показывает меньше минуты", () => {
    assert.equal(readingTimeOf("одно"), "≈1 мин");
    assert.equal(readingTimeOf(""), "≈1 мин");
    assert.equal(readingTimeOf(null), "≈1 мин");
});

test("dateShort даёт короткую русскую дату", () => {
    assert.equal(dateShort("2026-07-06T12:00:00+00:00"), "6 июл.");
});

test("dateLong даёт полную русскую дату", () => {
    assert.equal(dateLong("2026-07-06T12:00:00+00:00"), "6 июля 2026 г.");
});
