/**
 * @fileoverview Логика главной страницы - библиотека статей.
 *
 * Vue 3 монтируется в ``#app`` на ``index.html``. Разметка в шаблоне
 * HTML. Этот модуль отвечает за состояние, запросы к API и синхронизацию
 * фильтров с адресной строкой.
 *
 * **Источник правды для фильтров** - query-параметры ``q`` и ``tag`` в URL.
 * При изменении поиска или выбора тега адрес обновляется через
 * ``history.replaceState``, чтобы не плодить записи в истории и можно было сохранить ссылку.
 *
 * @module library
 */

import {createApp, ref, watch, onMounted, onUnmounted, nextTick} from "vue";
import {createArticle, listArticles} from "/js/api.js";

/** @typedef {module:api~Article} Article */
import {dateShort, domainOf, excerptOf} from "/js/format.js";

/** Задержка для поля поиска, мс. */
const DEBOUNCE_MS = 300;

/** Максимальная высота свёрнутого ряда тегов, px. */
const CHIPS_COLLAPSED_MAX = 72;

/**
 * Инициализирует и монтирует Vue-приложение библиотеки.
 *
 * Состояние страницы:
 *
 * - ``articles`` - отфильтрованный список для отображения.
 * - ``allTags`` - уникальные теги всей библиотеки.
 * - ``q`` / ``activeTag`` - текущие фильтры.
 * - ``status`` - сообщение о загрузке, пустой библиотеке или ошибке.
 *
 * Защита от гонок. Каждый вызов {@link refreshList} получает
 * монотонно возрастающий ``requestId``. Устаревшие ответы отбрасываются, если
 * пользователь уже сменил фильтры.
 */
createApp({
    setup() {
        /** @type {Article[]} */
        const articles = ref([]);
        const allTags = ref([]);
        const q = ref("");
        const activeTag = ref("");
        const status = ref("Библиотека загружается...");
        const newUrl = ref("");
        const saving = ref(false);
        const saveError = ref("");
        const tagsExpanded = ref(false);
        const tagsOverflow = ref(false);
        const hiddenTagCount = ref(0);
        /** @type {HTMLElement|null} */
        const chipsEl = ref(null);

        const params = new URLSearchParams(location.search);
        q.value = params.get("q") || "";
        activeTag.value = params.get("tag") || "";

        /**
         * Записывает текущие фильтры в адресную строку без перезагрузки.
         * @returns {void}
         */
        function syncUrl() {
            const next = new URLSearchParams();
            if (q.value) next.set("q", q.value);
            if (activeTag.value) next.set("tag", activeTag.value);
            const query = next.toString();
            history.replaceState(null, "", query ? "?" + query : location.pathname);
        }

        /** Счётчик запросов для отсечения устаревших ответов. */
        let lastRequestId = 0;

        /**
         * Загружает список статей с учётом ``q`` и ``activeTag``.
         * @returns {Promise<void>}
         */
        async function refreshList() {
            const requestId = ++lastRequestId;
            try {
                const result = await listArticles({q: q.value, tag: activeTag.value});
                if (requestId !== lastRequestId) return;
                articles.value = result;
                const filtered = q.value || activeTag.value;
                status.value = result.length ? "" : filtered ? "Ничего не найдено" : "Библиотека пуста";
            } catch (err) {
                if (requestId !== lastRequestId) return;
                articles.value = [];
                status.value = err.message;
            }
        }

        /**
         * Применяет фильтры: обновляет URL и перезапрашивает список.
         * @returns {void}
         */
        function applyFilters() {
            syncUrl();
            refreshList();
        }

        /**
         * Выбирает тег-фильтр.
         * @param {string} tag - Имя тега.
         * @returns {void}
         */
        function selectTag(tag) {
            activeTag.value = tag;
            applyFilters();
        }

        let debounceTimer = null;
        watch(q, () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(applyFilters, DEBOUNCE_MS);
        });

        /**
         * Загружает полный список статей и строит ряд тегов.
         *
         * Активный тег из URL сохраняется в чипах даже если ни у одной
         * статьи его больше нет, иначе фильтр стал бы невидимым.
         * @returns {Promise<void>}
         */
        async function loadChips() {
            const full = await listArticles();
            const set = new Set();
            for (const a of full) {
                for (const t of a.tags) set.add(t);
            }

            const tags = Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
            if (activeTag.value && !tags.includes(activeTag.value)) {
                tags.push(activeTag.value);
            }
            allTags.value = tags;
            await nextTick();
            updateTagsOverflow();
        }

        /**
         * Определяет, помещается ли ряд чипов в свёрнутую высоту,
         * и считает скрытые теги для кнопки "Ещё N".
         * @returns {void}
         */
        function updateTagsOverflow() {
            const el = chipsEl.value;
            if (!el) {
                tagsOverflow.value = false;
                hiddenTagCount.value = 0;
                return;
            }

            const overflows = el.scrollHeight > CHIPS_COLLAPSED_MAX;
            tagsOverflow.value = overflows;
            if (!overflows) {
                tagsExpanded.value = false;
                hiddenTagCount.value = 0;
                return;
            }

            hiddenTagCount.value = [...el.querySelectorAll(".chip")]
                .filter((chip) => chip.offsetTop >= CHIPS_COLLAPSED_MAX)
                .length;
        }

        /**
         * Сохраняет статью по URL из поля ввода и обновляет список и чипы.
         * @returns {Promise<void>}
         */
        async function save() {
            const url = newUrl.value.trim();
            if (!url) return;
            saveError.value = "";
            saving.value = true;
            try {
                await createArticle(url);
                newUrl.value = "";
                await loadChips();
                await refreshList();
            } catch (err) {
                saveError.value = err.message;
            } finally {
                saving.value = false;
            }
        }

        /**
         * Формирует ссылку на страницу читалки для статьи.
         * @param {string} id - UUID статьи.
         * @returns {string} Путь вида ``/reader.html?id=...``
         */
        const readerHref = (id) => "/reader.html?id=" + encodeURIComponent(id);

        watch(activeTag, (tag) => {
            if (tag) tagsExpanded.value = true;
        }, {immediate: true});

        const onResize = () => updateTagsOverflow();

        onMounted(async () => {
            window.addEventListener("resize", onResize);
            try {
                await loadChips();
            } catch (err) {
                status.value = err.message;
                return;
            }
            await refreshList();
        });

        onUnmounted(() => window.removeEventListener("resize", onResize));

        return {
            articles, allTags, q, activeTag, status, newUrl, saving, saveError,
            tagsExpanded, tagsOverflow, hiddenTagCount, chipsEl,
            save, selectTag, domainOf, excerptOf, dateShort, readerHref,
        };
    }
}).mount("#app");