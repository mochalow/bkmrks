/*
 * Поведение страницы библиотеки.
 *
 * Загружает список статей через api.js и отрисовывает карточки.
 * Разметка через HTML шаблон в index.html. Скрипт клонирует его и
 * заполняет поля через textContent.
 */

import {listArticles} from "/js/api.js";

// Элементы страницы
const cardsContainer = document.getElementById("cards");
const cardTemplate = document.getElementById("card-template");
const statusLine = document.getElementById("cards-status");

// Количество символов содержания статьи для выдержки.
// Визуальную обрезку до двух строк делает CSS
const PREVIEW_LIMIT = 300;

/**
 * Собирает DOM-узел карточки из шаблона.
 * Данные попадают в разметку через textContent.
 * @param {Object} article - статья в формате API
 * @returns {HTMLElement} готовый узел <article class="card">
 */
function renderCard(article) {
    const card = cardTemplate.content.firstElementChild.cloneNode(true);

    // Если парсер не нашёл заголовок, то title = null
    card.querySelector(".card-title").textContent = article.title || "Без заголовка";

    const date = card.querySelector(".card-date");
    date.dateTime = article.saved_at;
    date.textContent = new Date(article.saved_at).toLocaleDateString("ru", {day: "numeric", month: "short"});

    card.querySelector(".card-domain").textContent = new URL(article.url).hostname;

    const excerpt = card.querySelector(".card-excerpt");
    if (article.content) {
        excerpt.textContent = article.content.slice(0, PREVIEW_LIMIT);
    } else {
        excerpt.remove();
    }

    // В шаблоне лежит один пустой прототип тега.
    // Удаляем его, потом клонируем и заполняем реальными тегами.
    const tagsBox = card.querySelector(".card-tags");
    const tagPrototype = tagsBox.querySelector(".tag");
    tagPrototype.remove();

    for (const name of article.tags) {
        const tag = tagPrototype.cloneNode(true);
        tag.textContent = name;
        tagsBox.append(tag);
    }
    if (article.tags.length === 0) {
        // Убирает пустой ряд тегов.
        // Атрибут hidden не работает, т. к. перекрывается display: flex из CSS
        tagsBox.remove();
    }

    return card;
}

/**
 * Ререндерит контейнер со списком статей.
 * @param {Object[]} articles - статьи, новые сверху
 */
function renderList(articles) {
    if (articles.length === 0) {
        cardsContainer.replaceChildren();
        showStatus("Библиотека пуста");
        return;
    }

    hideStatus();
    cardsContainer.replaceChildren(...articles.map(renderCard));
}

/**
 * Показывает строку состояния под списком.
 * @param {string} text
 */
function showStatus(text) {
    statusLine.textContent = text;
    statusLine.hidden = false;
}

/** Прячет строку состояния. */
function hideStatus() {
    statusLine.hidden = true;
}

/** Загружает список с сервера и отрисовывает его. */
async function loadArticles() {
    try {
        const articles = await listArticles();
        renderList(articles);
    } catch (err) {
        cardsContainer.replaceChildren();
        showStatus(err.message);
    }
}

loadArticles();
