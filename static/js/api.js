/*
 * Модуль для доступа клиентов к API.
 *
 * Единственное место, где фронтенд знает про HTTP. Response и статус-коды не выходят
 * за пределы модуля, наружу идёт Error с человекочитаемым текстом.
 */

/**
 * Делает запрос к API. Выполняет fetch и переводит любую неудачу
 * в Error с человекочитаемым message.
 * @param {string} path - путь запроса, начиная с /api
 * @param {RequestInit} [options] - параметры fetch
 * @returns {Promise<any>} тело ответа или null для 204
 */
async function request(path, options = {}) {
    let response;
    try {
        response = await fetch(path, options);
    } catch (err) {
        // Сеть упала. Причину сохраняем в cause
        throw new Error("Не удалось связаться с сервером. Проверьте, что приложение запущено.",
            {cause: err});
    }

    if (!response.ok) {
        throw new Error(await extractDetail(response));
    }

    // Парсить нечего, т. к. 204 "No Content" приходит без тела
    if (response.status === 204) {
        return null;
    }

    return response.json();
}

/**
 * Достаёт человекочитаемый текст ошибки из ответа FastAPI.
 * @param {Response} response - ответ
 * @returns {Promise<string>} текст ошибки
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
 * Запрашивает список статей, новые сверху.
 * @param {Object} [filters]
 * @param {string} [filters.q] - подстрока для поиска в заголовке и тексте
 * @param {string} [filters.tag] - вернуть только статьи с этим тегом
 * @returns {Promise<Object[]>} массив статей
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
 * Запрашивает одну статью по id.
 * @param {string} id - id статьи
 * @returns {Promise<Object>} статья
 */
export async function getArticle(id) {
    return request("/api/articles/" + encodeURIComponent(id));
}

/**
 * Сохраняет статью.
 * @param {string} url - адрес страницы
 * @returns {Promise<Object>} созданная статья
 */
export async function createArticle(url) {
    return request("/api/articles", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url: url})
    });
}

/**
 * Удаляет статью.
 * @param {string} id - id статьи
 * @returns {Promise<null>} ответ 204 "No Content" приходит без тела
 */
export async function deleteArticle(id) {
    return request("/api/articles/" + encodeURIComponent(id), {method: "DELETE"});
}

/**
 * Добавляет тег к статье. Сервер нормализует тег и не создаёт дубликатов.
 * @param {string} id - id статьи
 * @param {string} tag - тег для добавления
 * @returns {Promise<Object>} обновлённая статья
 */
export async function addTag(id, tag) {
    return request("/api/articles/" + encodeURIComponent(id) + "/tags", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({tag: tag})
    });
}

/**
 * Удаляет тег у статьи. Если тега нет, статья вернётся без изменений.
 * @param {string} id - id статьи
 * @param {string} tag - тег для удаления
 * @returns {Promise<Object>} обновлённая статья
 */
export async function removeTag(id, tag) {
    return request("/api/articles/" + encodeURIComponent(id) + "/tags/" + encodeURIComponent(tag), {method: "DELETE"});
}
