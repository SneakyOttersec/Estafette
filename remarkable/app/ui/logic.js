.pragma library

var categories = ["all", "offensive", "vuln-dev", "threat-intel", "general"]

function timestamp(article) {
    var value = article.published_at || article.first_seen_at || "1970-01-01T00:00:00Z"
    var parsed = Date.parse(value)
    return isNaN(parsed) ? 0 : parsed
}

function newestFirst(articles) {
    return (articles || []).slice().sort(function(left, right) {
        var delta = timestamp(right) - timestamp(left)
        if (delta !== 0) return delta
        return String(right.id).localeCompare(String(left.id))
    })
}

function filterCategory(articles, category, toReadMap, likeMap) {
    var ordered = newestFirst(articles)
    if (!category || category === "all") return ordered
    if (category === "to-read") {
        return ordered.filter(function(article) { return !!(toReadMap && toReadMap[article.id]) })
    }
    if (category === "liked") {
        return ordered.filter(function(article) { return !!(likeMap && likeMap[article.id]) })
    }
    return ordered.filter(function(article) { return article.category === category })
}

function categoryCount(articles, category, toReadMap, likeMap) {
    if (!category || category === "all") return (articles || []).length
    if (category === "to-read") return flaggedCount(articles, toReadMap)
    if (category === "liked") return flaggedCount(articles, likeMap)
    return (articles || []).reduce(function(total, article) {
        return total + (article.category === category ? 1 : 0)
    }, 0)
}

function flaggedCount(articles, flagMap) {
    return (articles || []).reduce(function(total, article) {
        return total + (flagMap && flagMap[article.id] ? 1 : 0)
    }, 0)
}

function categoryLabel(category) {
    var labels = {
        "offensive": "Offensive",
        "vuln-dev": "Vuln Dev",
        "threat-intel": "Threat Intel",
        "general": "General",
        "to-read": "To Read",
        "liked": "Like"
    }
    return labels[category] || "All writings"
}

function unreadCount(articles, readMap) {
    return (articles || []).reduce(function(total, article) {
        return total + (readMap && readMap[article.id] ? 0 : 1)
    }, 0)
}

function normalizeTextSize(value) {
    return ["compact", "standard", "large"].indexOf(value) >= 0 ? value : "standard"
}

function fontScale(value) {
    value = normalizeTextSize(value)
    return value === "compact" ? 0.84 : value === "large" ? 1.22 : 1.0
}

function pageTarget(position, direction, viewport, contentHeight) {
    var step = Math.max(1, viewport * 0.9)
    var maximum = Math.max(0, contentHeight - viewport)
    return Math.max(0, Math.min(maximum, position + direction * step))
}

function pageNumber(position, viewport) {
    return Math.max(0, Math.round(position / Math.max(1, viewport * 0.9)))
}

function positionForPage(page, viewport, contentHeight) {
    var maximum = Math.max(0, contentHeight - viewport)
    return Math.max(0, Math.min(maximum, Number(page || 0) * viewport * 0.9))
}

function relativeDate(value, nowValue) {
    var when = Date.parse(value || "")
    if (isNaN(when)) return "date unavailable"
    var now = nowValue === undefined ? Date.now() : nowValue
    var days = Math.max(0, Math.floor((now - when) / 86400000))
    if (days === 0) return "today"
    if (days === 1) return "yesterday"
    if (days < 30) return days + " days ago"
    return new Date(when).toISOString().slice(0, 10)
}

function shortDate(value) {
    var when = Date.parse(value || "")
    if (isNaN(when)) return "---- -- --"
    return new Date(when).toISOString().slice(0, 10)
}

function isNew(value, nowValue) {
    var when = Date.parse(value || "")
    if (isNaN(when)) return false
    var now = nowValue === undefined ? Date.now() : nowValue
    var age = now - when
    return age >= 0 && age < 3 * 86400000
}

function listText(items, ordered) {
    return (items || []).map(function(item, index) {
        return (ordered ? (index + 1) + ". " : "• ") + item
    }).join("\n")
}

function tableText(rows) {
    return (rows || []).map(function(row) { return row.join("  |  ") }).join("\n")
}

function transition(state, event) {
    var next = { screen: state.screen, sync: state.sync, offline: state.offline, imageMissing: state.imageMissing }
    if (event === "cached-feed") { next.screen = "feed"; next.offline = false }
    else if (event === "sync-start") next.sync = "running"
    else if (event === "sync-complete") { next.sync = "complete"; next.offline = false }
    else if (event === "network-error") { next.sync = "error"; next.offline = true }
    else if (event === "open-article") next.screen = "article"
    else if (event === "back") next.screen = state.screen === "article" ? "feed" : "closed"
    else if (event === "image-error") next.imageMissing = true
    return next
}

if (typeof module !== "undefined") {
    module.exports = {
        newestFirst: newestFirst, filterCategory: filterCategory,
        categoryCount: categoryCount, categoryLabel: categoryLabel,
        flaggedCount: flaggedCount, unreadCount: unreadCount,
        normalizeTextSize: normalizeTextSize,
        fontScale: fontScale, pageTarget: pageTarget, pageNumber: pageNumber,
        positionForPage: positionForPage, relativeDate: relativeDate,
        shortDate: shortDate, isNew: isNew,
        listText: listText, tableText: tableText, transition: transition
    }
}
