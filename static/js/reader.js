/*
 * Поведение страницы читалки.
 *
 * Разметку делает Vue из шаблона в reader.html.
 */

import {createApp, ref, computed, nextTick, onMounted, onUnmounted} from "vue";
import {addTag, deleteArticle, getArticle, removeTag} from "/js/api.js";
import {dateLong, domainOf} from "/js/format.js";

const articleId = new URLSearchParams(location.search).get("id");

createApp({
    setup() {
        // Реактивное состояние страницы
        const article = ref(null);
        const status = ref("Статья загружается...");
        const showBackLink = ref(false);
        const deleting = ref(false);
        const tagFormOpen = ref(false);
        const newTag = ref("");
        const addingTag = ref(false);
        const removingTag = ref("");     // Имя тега, который сейчас удаляется

        // Ссылки на узлы для управления фокусом
        const tagInput = ref(null);
        const tagForm = ref(null);
        const addTagButton = ref(null);

        let clickOutsideListener = null;

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

        function disableClickOutside() {
            if (!clickOutsideListener) return;
            document.removeEventListener("mousedown", clickOutsideListener);
            clickOutsideListener = null;
        }

        const paragraphs = computed(() => {
            const content = (article.value && article.value.content) || "";
            return content.split("\n").map((s) => s.trim()).filter(Boolean);
        });

        async function load() {
            if (!articleId) {
                status.value = "В адресе не хватает идентификатора статьи";
                showBackLink.value = true;
                return;
            }
            try {
                const loaded = await getArticle(articleId);
                article.value = loaded;
                status.value = "";               // Прячем «Статья загружается...»
                document.title = "bkmrks — " + (loaded.title || "Без заголовка");
            } catch (err) {
                status.value = err.message;
                showBackLink.value = true;
            }
        }

        // Удаление статьи
        async function removeArticle() {
            if (!confirm("Удалить статью? Действие необратимо.")) return;
            deleting.value = true;               // Защита от повторного клика
            try {
                await deleteArticle(articleId);
                location.href = "/";             // Читать больше нечего - в библиотеку
            } catch (err) {
                deleting.value = false;
                status.value = err.message;
            }
        }

        // Управление тегами
        // Узел формы появляется только после перерисовки, поэтому фокус
        // ставим после nextTick.
        async function openTagForm() {
            tagFormOpen.value = true;
            await nextTick();
            tagInput.value?.focus();
            // После клика по «+ тег», иначе тот же клик сразу закроет форму
            setTimeout(enableClickOutside, 0);
        }

        async function closeTagForm() {
            disableClickOutside();
            newTag.value = "";
            tagFormOpen.value = false;
            await nextTick();
            addTagButton.value?.focus(); // Вернуть фокус на «+ тег»
        }

        async function submitTag() {
            const name = newTag.value.trim();
            if (!name) {
                closeTagForm(); // Пустой ввод - отмена
                return;
            }
            status.value = "";
            addingTag.value = true; // Защита от повторной отправки
            try {
                const updated = await addTag(articleId, name);
                article.value = updated; // Ряд тегов из ответа сервера
                closeTagForm();
            } catch (err) {
                await nextTick();
                tagInput.value?.focus(); // Возвращаем к правке
                status.value = err.message;
            } finally {
                addingTag.value = false;
            }
        }

        async function dropTag(name) {
            status.value = "";
            removingTag.value = name; // Крестик этого чипа выключается
            try {
                const updated = await removeTag(articleId, name);
                article.value = updated; // Чип уходит вместе с ответом
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