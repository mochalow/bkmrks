/*
 * Поведение страницы библиотеки.
 *
 * Разметку делает Vue из шаблона в index.html.
 * URL - источник правды о фильтрах (изменение пишется в адрес,
 * состояние читается оттуда).
 */

import {createApp, ref, watch, onMounted, onUnmounted, nextTick} from "vue";
import {createArticle, listArticles} from "/js/api.js";
import {dateShort, domainOf, excerptOf} from "/js/format.js";

const DEBOUNCE_MS = 300;
const CHIPS_COLLAPSED_MAX = 72;

createApp({
    setup() {
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
        const chipsEl = ref(null);

        // Фильтры из адреса
        const params = new URLSearchParams(location.search);
        q.value = params.get("q") || "";
        activeTag.value = params.get("tag") || "";

        function syncUrl() {
            const next = new URLSearchParams();
            if (q.value) next.set("q", q.value);
            if (activeTag.value) next.set("tag", activeTag.value);
            const query = next.toString();
            history.replaceState(null, "", query ? "?" + query : location.pathname);
        }

        // Поздний ответ на устаревшие фильтры отбрасываем
        let lastRequestId = 0;

        async function refreshList() {
            const requestId = ++lastRequestId;
            try {
                const result = await listArticles({q: q.value, tag: activeTag.value});
                if (requestId !== lastRequestId) return;   // Фильтры уже сменились
                articles.value = result;
                status.value = result.length ? "" : q.value || activeTag.value ? "Ничего не найдено" : "Библиотека пуста";
            } catch (err) {
                if (requestId !== lastRequestId) return;
                articles.value = [];
                status.value = err.message;
            }
        }

        // Новое состояние фильтров
        function applyFilters() {
            syncUrl();
            refreshList();
        }

        function selectTag(tag) {
            activeTag.value = tag;
            applyFilters();
        }

        // Поиск. q меняется на каждый ввод, запрос
        // уходит после паузы.
        let debounceTimer = null;
        watch(q, () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(applyFilters, DEBOUNCE_MS);
        });

        // Ряд чипов строится из тегов всей библиотеки
        async function loadChips() {
            const full = await listArticles();
            const set = new Set();
            for (const a of full) {
                for (const t of a.tags) set.add(t);
            }

            const tags = Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
            // Тег из старой ссылки мог исчезнуть из библиотеки. Показываем его
            // чип всё равно, иначе активный фильтр стал бы невидимым.
            if (activeTag.value && !tags.includes(activeTag.value)) {
                tags.push(activeTag.value);
            }
            allTags.value = tags;
            await nextTick();
            updateTagsOverflow();
        }

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

        // Сохранение статьи
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

        const readerHref = (id) => "/reader.html?id=" + encodeURIComponent(id);

        // Активный тег из ссылки должен быть виден сразу
        watch(activeTag, (tag) => {
            if (tag) tagsExpanded.value = true;
        }, {immediate: true});

        const onResize = () => updateTagsOverflow();

        // Первая загрузка. Чипы, потом список по фильтрам
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