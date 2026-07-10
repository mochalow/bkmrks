/**
 * @fileoverview Переключение между светлой и тёмной темой.
 *
 * Без явного выбора пользователя тема следует системной настройке
 * (``@media (prefers-color-scheme: dark)`` в app.css). Явный выбор,
 * сделанный кнопкой в шапке, хранится в localStorage и применяется
 * через атрибут ``data-theme`` на ``<html>``, который переопределяет
 * системную настройку. Инлайн-скрипт в
 * ``<head>`` каждой страницы применяет сохранённый выбор синхронно, до
 * отрисовки, чтобы избежать мигания темой при загрузке.
 *
 * Экспортирует реактивный ``theme`` (ref) и функцию ``toggleTheme``.
 *
 * @module theme
 */

import {ref} from "vue";

const THEME_KEY = "bkmrks:theme";
const media = window.matchMedia("(prefers-color-scheme: dark)");

/**
 * Загружает явный выбор пользователя из localStorage.
 * @returns {"light"|"dark"|null}
 */
function loadExplicit() {
    const saved = localStorage.getItem(THEME_KEY);
    return saved === "light" || saved === "dark" ? saved : null;
}

/**
 * Текущая действующая тема ("light" или "dark").
 *
 * Реактивный ref из Vue. Vue-компоненты автоматически обновляются.
 */
export const theme = ref(loadExplicit() || (media.matches ? "dark" : "light"));

media.addEventListener("change", (event) => {
    if (loadExplicit()) return; // явный выбор пользователя важнее системного
    theme.value = event.matches ? "dark" : "light";
    delete document.documentElement.dataset.theme;
});

/**
 * Переключает тему и запоминает выбор как явный (переживает системные изменения).
 *
 * Устанавливает ``data-theme`` на ``<html>`` и сохраняет в localStorage.
 * @returns {void}
 */
export function toggleTheme() {
    const next = theme.value === "dark" ? "light" : "dark";
    theme.value = next;
    localStorage.setItem(THEME_KEY, next);
    document.documentElement.dataset.theme = next;
}
