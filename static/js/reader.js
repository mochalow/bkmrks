/*
 * Поведение страницы читалки.
 *
 * Разметку делает Vue из шаблона в reader.html.
 */

import {createApp, ref, computed, nextTick, onMounted} from "vue";
import {addTag, deleteArticle, getArticle, removeTag} from "/js/api.js";

// Забираем id статьи из адреса (?id=...).
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
        const addTagButton = ref(null);

        const paragraphs = computed(() => {
            const content = (article.value && article.value.content) || "";
            return content.split("\n").map((s) => s.trim()).filter(Boolean);
        });

        // Помощники шаблона
        const domainOf = (url) => new URL(url).hostname;
        const dateLong = (iso) =>
            new Date(iso).toLocaleDateString("ru", {
                day: "numeric", month: "long", year: "numeric",
            });

        // Загрузка статьи
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
            tagInput.value.focus();
        }

        async function closeTagForm() {
            newTag.value = "";
            tagFormOpen.value = false;
            await nextTick();
            addTagButton.value.focus();          // Вернуть фокус на «+ тег»
        }

        async function submitTag() {
            const name = newTag.value.trim();
            if (!name) {
                closeTagForm();                  // Пустой ввод - отмена
                return;
            }
            status.value = "";
            addingTag.value = true;              // Защита от повторной отправки
            try {
                const updated = await addTag(articleId, name);
                addingTag.value = false;
                article.value = updated;         // Ряд тегов из ответа сервера
                closeTagForm();
            } catch (err) {
                addingTag.value = false;
                await nextTick();
                tagInput.value.focus();          // Возвращаем к правке
                status.value = err.message;
            }
        }

        async function dropTag(name) {
            status.value = "";
            removingTag.value = name;            // Крестик этого чипа выключается
            try {
                const updated = await removeTag(articleId, name);
                article.value = updated;         // Чип уходит вместе с ответом
            } catch (err) {
                removingTag.value = "";
                status.value = err.message;
            }
        }

        onMounted(load);

        return {
            article, status, showBackLink, deleting,
            tagFormOpen, newTag, addingTag, removingTag,
            tagInput, addTagButton,
            paragraphs, domainOf, dateLong,
            removeArticle, openTagForm, closeTagForm, submitTag, dropTag,
        };
    }
}).mount("#app");
