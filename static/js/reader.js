/**
 * @fileoverview Логика страницы чтения одной статьи.
 *
 * Vue 3 на ``reader.html``. Идентификатор статьи берётся из
 * query-параметра ``id``. Текст разбивается на абзацы для отображения
 * в шаблоне. Теги можно добавлять и удалять без перезагрузки страницы.
 *
 * @module reader
 */

import {createApp, ref, computed, nextTick, onMounted, onUnmounted} from "vue";
import {addTag, deleteArticle, getArticle, removeTag} from "/js/api.js";

/** @typedef {module:api~Article} Article */
import {dateLong, domainOf} from "/js/format.js";

/** UUID статьи из адресной строки (?id=...). */
const articleId = new URLSearchParams(location.search).get("id");

/**
 * Инициализирует Vue-приложение читалки.
 *
 * Основные сценарии:
 *
 * - загрузка статьи при открытии страницы.
 * - удаление статьи с подтверждением и редиректом в библиотеку.
 * - inline-форма добавления тега с закрытием по клику вне формы.
 * - удаление отдельного тега с индикацией на кнопке-крестике.
 */
createApp({
    setup() {
        /** @type {Article|null} */
        const article = ref(null);
        const status = ref("Статья загружается...");
        const showBackLink = ref(false);
        const deleting = ref(false);
        const tagFormOpen = ref(false);
        const newTag = ref("");
        const addingTag = ref(false);
        /** Имя тега, который сейчас удаляется. */
        const removingTag = ref("");

        /** @type {HTMLInputElement|null} */
        const tagInput = ref(null);
        /** @type {HTMLElement|null} */
        const tagForm = ref(null);
        /** @type {HTMLButtonElement|null} */
        const addTagButton = ref(null);

        /** @type {function(MouseEvent): void|null} */
        let clickOutsideListener = null;

        /**
         * Регистрирует обработчик события на клики вне формы тега для её закрытия.
         * @returns {void}
         */
        function enableClickOutside() {
            disableClickOutside();
            clickOutsideListener = (event) => {
                const form = tagForm.value;
                if (form && !form.contains(event.target)) {
                    closeTagForm();
                }
            };
            document.addEventListener("mousedown", clickOutsideListener);
        }

        /**
         * Снимает обработчик клика вне формы.
         * @returns {void}
         */
        function disableClickOutside() {
            if (!clickOutsideListener) return;
            document.removeEventListener("mousedown", clickOutsideListener);
            clickOutsideListener = null;
        }

        /** Разбивает ``content`` статьи на непустые абзацы для ``v-for``. */
        const paragraphs = computed(() => {
            const content = (article.value && article.value.content) || "";
            return content.split("\n").map((s) => s.trim()).filter(Boolean);
        });

        /**
         * Загружает статью по ``articleId`` из URL.
         * @returns {Promise<void>}
         */
        async function load() {
            if (!articleId) {
                status.value = "В адресе не хватает идентификатора статьи";
                showBackLink.value = true;
                return;
            }
            try {
                const loaded = await getArticle(articleId);
                article.value = loaded;
                status.value = "";
                document.title = "bkmrks — " + (loaded.title || "Без заголовка");
            } catch (err) {
                status.value = err.message;
                showBackLink.value = true;
            }
        }

        /**
         * Удаляет текущую статью после подтверждения пользователя.
         * @returns {Promise<void>}
         */
        async function removeArticle() {
            if (!confirm("Удалить статью? Действие необратимо.")) return;
            deleting.value = true;
            try {
                await deleteArticle(articleId);
                location.href = "/";
            } catch (err) {
                deleting.value = false;
                status.value = err.message;
            }
        }

        /**
         * Открывает форму добавления тега и ставит фокус в поле ввода.
         *
         * Обработчик "клик снаружи" включается через ``setTimeout(0)``,
         * чтобы тот же клик по кнопке «+ тег» не закрыл форму сразу.
         * @returns {Promise<void>}
         */
        async function openTagForm() {
            tagFormOpen.value = true;
            await nextTick();
            tagInput.value?.focus();
            setTimeout(enableClickOutside, 0);
        }

        /**
         * Закрывает форму тега и возвращает фокус на кнопку «+ тег».
         * @returns {Promise<void>}
         */
        async function closeTagForm() {
            disableClickOutside();
            newTag.value = "";
            tagFormOpen.value = false;
            await nextTick();
            addTagButton.value?.focus();
        }

        /**
         * Отправляет новый тег на сервер.
         *
         * Пустой ввод трактуется как отмена (форма закрывается).
         * @returns {Promise<void>}
         */
        async function submitTag() {
            const name = newTag.value.trim();
            if (!name) {
                closeTagForm();
                return;
            }
            status.value = "";
            addingTag.value = true;
            try {
                const updated = await addTag(articleId, name);
                article.value = updated;
                closeTagForm();
            } catch (err) {
                await nextTick();
                tagInput.value?.focus();
                status.value = err.message;
            } finally {
                addingTag.value = false;
            }
        }

        /**
         * Удаляет тег у статьи. Обновляет локальное состояние из ответа API.
         * @param {string} name - Имя тега для удаления.
         * @returns {Promise<void>}
         */
        async function dropTag(name) {
            status.value = "";
            removingTag.value = name;
            try {
                const updated = await removeTag(articleId, name);
                article.value = updated;
            } catch (err) {
                status.value = err.message;
            } finally {
                removingTag.value = "";
            }
        }

        onMounted(load);
        onUnmounted(disableClickOutside);

        return {
            article, status, showBackLink, deleting,
            tagFormOpen, newTag, addingTag, removingTag,
            tagInput, tagForm, addTagButton,
            paragraphs, domainOf, dateLong,
            removeArticle, openTagForm, closeTagForm, submitTag, dropTag,
        };
    }
}).mount("#app");