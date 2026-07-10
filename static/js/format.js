/**
 * @fileoverview Общие форматтеры для библиотеки и читалки.
 *
 * Функции принимают данные из API
 * и возвращают строки для отображения в шаблонах Vue.
 *
 * Используются в {@link module:library} и {@link module:reader}.
 *
 * @module format
 */

/** Максимальная длина превью текста статьи в списке библиотеки. */
const PREVIEW_LIMIT = 300;

/**
 * Извлекает доменное имя из URL для отображения под заголовком статьи.
 *
 * Вызывается прямо из шаблонов (карточки библиотеки, шапка читалки),
 * поэтому не бросает исключений: на некорректном или нестандартном
 * ``url`` из сохранённой записи возвращает сам ``url``, чтобы битые
 * данные не роняли рендер всей карточки/страницы.
 *
 * @param {string} url - Полный адрес страницы (как в поле {@link Article#url}).
 * @returns {string} Hostname, например ``example.com``; исходный ``url``
 *     (или пустая строка), если разобрать адрес не удалось.
 *
 * @example
 * domainOf("https://example.com/path/article");
 * // => "example.com"
 */
export function domainOf(url) {
    try {
        return new URL(url).hostname;
    } catch {
        return url || "";
    }
}

/**
 * Формирует короткое превью текста статьи для карточки в библиотеке.
 *
 * Обрезает длинный текст до {@link PREVIEW_LIMIT} символов, стараясь
 * не рвать слово посередине. Ищет последний пробел в обрезанном фрагменте.
 * Если пробел слишком далеко от конца (меньше 60% лимита), режет по символам.
 *
 * @param {string|null|undefined} content - Полный текст статьи или пустое значение.
 * @returns {string} Превью с многоточием или исходный короткий текст.
 *
 * @example
 * excerptOf("Очень длинный текст статьи...");
 * // => "Очень длинный текст статьи..."  (до 300 символов + "...")
 */
export function excerptOf(content) {
    const text = (content || "").trim();
    if (text.length <= PREVIEW_LIMIT) return text;

    const cut = text.slice(0, PREVIEW_LIMIT);
    const lastSpace = cut.lastIndexOf(" ");
    const trimmed = lastSpace > PREVIEW_LIMIT * 0.6 ? cut.slice(0, lastSpace) : cut;
    return trimmed + "...";
}

/** Слов в минуту для оценки времени чтения. */
const WORDS_PER_MINUTE = 180;

/**
 * Оценивает время чтения статьи по количеству слов.
 *
 * @param {string|null|undefined} text - Текст статьи (поле {@link Article#content}).
 * @returns {string} Строка вида ``"≈7 мин"``. Минимум ``"≈1 мин"``.
 *
 * @example
 * readingTimeOf("слово ".repeat(360));
 * // => "≈2 мин"
 */
export function readingTimeOf(text) {
    const words = (text || "").trim().split(/\s+/).filter(Boolean).length;
    const minutes = Math.max(1, Math.round(words / WORDS_PER_MINUTE));
    return `≈${minutes} мин`;
}

/**
 * Короткая дата для списка статей. День и сокращённый месяц на русском.
 *
 * @param {string} iso - Дата в формате ISO 8601 (поле {@link Article#saved_at}).
 * @returns {string} Локализованная строка, например ``6 июл.``
 */
export function dateShort(iso) {
    return new Date(iso).toLocaleDateString("ru", {day: "numeric", month: "short"});
}

/**
 * Полная дата для страницы читалки. День, месяц и год на русском.
 *
 * @param {string} iso - Дата в формате ISO 8601.
 * @returns {string} Локализованная строка, например ``6 июля 2026 г.``
 */
export function dateLong(iso) {
    return new Date(iso).toLocaleDateString("ru", {
        day: "numeric", month: "long", year: "numeric",
    });
}