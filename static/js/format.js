/** Общие форматтеры для библиотеки и читалки. */

const PREVIEW_LIMIT = 300;

export function domainOf(url) {
    return new URL(url).hostname;
}

export function excerptOf(content) {
    const text = (content || "").trim();
    if (text.length <= PREVIEW_LIMIT) return text;

    const cut = text.slice(0, PREVIEW_LIMIT);
    const lastSpace = cut.lastIndexOf(" ");
    const trimmed = lastSpace > PREVIEW_LIMIT * 0.6 ? cut.slice(0, lastSpace) : cut;
    return trimmed + "...";
}

export function dateShort(iso) {
    return new Date(iso).toLocaleDateString("ru", {day: "numeric", month: "short"});
}

export function dateLong(iso) {
    return new Date(iso).toLocaleDateString("ru", {
        day: "numeric", month: "long", year: "numeric",
    });
}