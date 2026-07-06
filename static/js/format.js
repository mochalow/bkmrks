/** Общие форматтеры для библиотеки и читалки. */

const PREVIEW_LIMIT = 300;

export function domainOf(url) {
    return new URL(url).hostname;
}

export function excerptOf(content) {
    return (content || "").slice(0, PREVIEW_LIMIT);
}

export function dateShort(iso) {
    return new Date(iso).toLocaleDateString("ru", {day: "numeric", month: "short"});
}

export function dateLong(iso) {
    return new Date(iso).toLocaleDateString("ru", {
        day: "numeric", month: "long", year: "numeric",
    });
}