/**
 * @fileoverview Клиентский доступ к REST API приложения bkmrks.
 *
 * Единственное место, где фронтенд знает про HTTP. Ответы ``fetch``,
 * статус-коды и формат ошибок FastAPI не выходят за пределы модуля.
 * Наружу передаётся только {@link Error} с человекочитаемым ``message``.
 *
 * Все пути начинаются с ``/api`` (префикс роутера в ``main.py``).
 *
 * @module api
 */

/**
 * Статья, как её возвращает сервер (модель Pydantic ``Article``).
 *
 * @typedef {Object} Article
 * @property {string} id - UUID4 в строковом виде.
 * @property {string} url - Исходный адрес сохранённой страницы.
 * @property {string} saved_at - Момент сохранения в UTC (ISO 8601).
 * @property {string|null} title - Заголовок из метаданных страницы.
 * @property {string|null} content - Очищенный plain text с переносами ``\\n``.
 * @property {string[]} tags - Теги в нижнем регистре, без дубликатов.
 */

/**
 * Параметры фильтрации списка статей (query-string ``GET /api/articles``).
 *
 * @typedef {Object} ArticleFilters
 * @property {string} [q] - Подстрока для поиска в заголовке и тексте.
 * @property {string} [tag] - Вернуть только статьи с этим тегом.
 */

/**
 * Выполняет запрос к API и разбирает ответ.
 *
 * Сетевые сбои оборачиваются в понятное сообщение. HTTP-ошибки
 * переводятся через {@link extractDetail}. Успешный ответ ``204``
 * возвращает ``null`` без попытки парсить JSON.
 *
 * @param {string} path - Путь запроса, начиная с ``/api``.
 * @param {RequestInit} [options] - Параметры ``fetch`` (method, headers, body).
 * @returns {Promise<Article|Article[]|null>} Тело ответа или ``null`` для 204.
 * @throws {Error} Сеть недоступна или сервер вернул статус >= 400.
 * @private
 */
async function request(path, options = {}) {
    let response;
    try {
        response = await fetch(path, options);
    } catch (err) {
        throw new Error("Не удалось связаться с сервером. Проверьте, что приложение запущено.",
            {cause: err});
    }

    if (!response.ok) {
        throw new Error(await extractDetail(response));
    }

    if (response.status === 204) {
        return null;
    }

    return response.json();
}

/**
 * Извлекает человекочитаемый текст ошибки из тела ответа FastAPI.
 *
 * FastAPI для ошибок валидации возвращает ``detail`` как массив объектов
 * с полем ``msg``. Для логических ошибок - строку в ``detail``.
 *
 * @param {Response} response - Ответ с ``ok === false``.
 * @returns {Promise<string>} Текст для показа пользователю.
 * @private
 */
async function extractDetail(response) {
    const data = await response.json().catch(() => null);
    const detail = data ? data.detail : null;

    if (typeof detail === "string") {
        return detail;
    }
    if (Array.isArray(detail)) {
        return detail.map((item) => item.msg).join("; ");
    }

    return "Сервер вернул ошибку " + response.status;
}

/**
 * Запрашивает список статей. Сервер сортирует по дате (новые сверху).
 *
 * @param {ArticleFilters} [filters] - Опциональные фильтры поиска и тега.
 * @returns {Promise<Article[]>} Массив статей (может быть пустым).
 *
 * @example
 * // Все статьи
 * const all = await listArticles();
 *
 * @example
 * // Поиск + фильтр по тегу
 * const filtered = await listArticles({ q: "python", tag: "news" });
 */
export async function listArticles({q, tag} = {}) {
    const params = new URLSearchParams();
    if (q) {
        params.set("q", q);
    }
    if (tag) {
        params.set("tag", tag);
    }

    const query = params.toString();
    return request("/api/articles" + (query ? "?" + query : ""));
}

/**
 * Загружает одну статью по идентификатору.
 *
 * @param {string} id - UUID статьи.
 * @returns {Promise<Article>} Полная статья с текстом.
 * @throws {Error} ``404`` - статья не найдена.
 */
export async function getArticle(id) {
    return request("/api/articles/" + encodeURIComponent(id));
}

/**
 * Сохраняет новую статью. Сервер скачивает URL и извлекает текст.
 *
 * @param {string} url - Адрес страницы для парсинга.
 * @returns {Promise<Article>} Созданная статья (статус 201 на сервере).
 * @throws {Error} ``422`` - не удалось скачать или распарсить страницу.
 */
export async function createArticle(url) {
    return request("/api/articles", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url: url})
    });
}

/**
 * Безвозвратно удаляет статью с сервера.
 *
 * @param {string} id - UUID статьи.
 * @returns {Promise<null>} Успех - ``null`` (ответ 204 без тела).
 * @throws {Error} ``404`` - статья не найдена.
 */
export async function deleteArticle(id) {
    return request("/api/articles/" + encodeURIComponent(id), {method: "DELETE"});
}

/**
 * Добавляет тег к статье.
 *
 * Сервер нормализует тег (удаление пробелов в начала и конце,
 * перевод в нижний регистр) и не создаёт дубликатов.
 * Повторный вызов с тем же тегом безопасен.
 *
 * @param {string} id - UUID статьи.
 * @param {string} tag - Имя тега (регистр на клиенте не важен).
 * @returns {Promise<Article>} Статья с обновлённым массивом ``tags``.
 * @throws {Error} ``404`` - статья не найдена; ``422`` - пустой тег.
 */
export async function addTag(id, tag) {
    return request("/api/articles/" + encodeURIComponent(id) + "/tags", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({tag: tag})
    });
}

/**
 * Удаляет тег у статьи.
 *
 * Если тега нет, сервер возвращает статью без изменений (идемпотентно).
 *
 * @param {string} id - UUID статьи.
 * @param {string} tag - Имя тега для удаления.
 * @returns {Promise<Article>} Статья с актуальным списком тегов.
 * @throws {Error} ``404`` - статья не найдена.
 */
export async function removeTag(id, tag) {
    return request("/api/articles/" + encodeURIComponent(id) + "/tags/" + encodeURIComponent(tag), {method: "DELETE"});
}