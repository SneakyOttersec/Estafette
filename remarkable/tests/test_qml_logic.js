const fs = require("fs")
const vm = require("vm")
const assert = require("assert")

const source = fs.readFileSync(process.argv[2], "utf8").replace(/^\.pragma library\s*/m, "")
const context = { module: { exports: {} }, Date: Date, Math: Math, String: String, isNaN: isNaN }
vm.createContext(context)
vm.runInContext(source, context)
const logic = context.module.exports

const articles = [
  { id: "old", title: "Security Engineering Notes", category: "general", published_at: "2026-09-01T00:00:00Z" },
  { id: "new", title: "Breaking the Perimeter", category: "offensive", published_at: "2026-09-04T00:00:00Z" },
  { id: "fallback", title: "Weekly Security Review", category: "general", first_seen_at: "2026-09-03T00:00:00Z" }
]
assert.deepStrictEqual(Array.from(logic.newestFirst(articles), x => x.id), ["new", "fallback", "old"])
assert.deepStrictEqual(Array.from(logic.filterCategory(articles, "general"), x => x.id), ["fallback", "old"])
assert.deepStrictEqual(Array.from(logic.filterCategory(articles, "news", {}, {}, {}, {}, Date.parse("2026-09-04T00:00:00Z")), x => x.id), ["new", "fallback"])
assert.deepStrictEqual(Array.from(logic.filterCategory(articles, "to-read", { fallback: true }), x => x.id), ["fallback"])
assert.deepStrictEqual(Array.from(logic.filterCategory(articles, "liked", {}, { old: true, new: true }), x => x.id), ["new", "old"])
assert.deepStrictEqual(Array.from(logic.filterCategory(articles, "all", {}, {}, { fallback: true }), x => x.id), ["new", "old"])
assert.deepStrictEqual(Array.from(logic.filterTitle(articles, "SECURITY"), x => x.id), ["old", "fallback"])
assert.deepStrictEqual(Array.from(logic.filterTitle(articles, " perimeter "), x => x.id), ["new"])
assert.deepStrictEqual(Array.from(logic.filterTitle(articles, ""), x => x.id), ["old", "new", "fallback"])
assert.deepStrictEqual(Array.from(logic.filterTitle([{ id: "missing-title" }], "security"), x => x.id), [])
const tags = { old: "  Deep   Dive  ", new: "deep dive", fallback: "Later" }
assert.strictEqual(logic.normalizeTag("  Deep   Dive  "), "Deep Dive")
assert.strictEqual(logic.normalizeTag("123456789012345678901234567890123456"), "12345678901234567890123456789012")
assert.strictEqual(logic.tagKey("Deep Dive"), "deep dive")
assert.deepStrictEqual(Array.from(logic.filterCategory(articles, "tag:deep dive", {}, {}, {}, tags), x => x.id), ["new", "old"])
assert.deepStrictEqual(Array.from(logic.filterCategory(articles, "tag:later", {}, {}, { fallback: true }, tags), x => x.id), [])
assert.deepStrictEqual(Array.from(logic.tagEntries(articles, tags), x => [x.key, x.label, x.count]), [
  ["tag:deep dive", "Deep Dive", 2], ["tag:later", "Later", 1]
])
assert.deepStrictEqual(Array.from(logic.tagEntries(articles, tags, { old: true }), x => [x.key, x.label, x.count]), [
  ["tag:deep dive", "deep dive", 1], ["tag:later", "Later", 1]
])
assert.strictEqual(logic.categoryLabel("tag:deep dive", logic.tagEntries(articles, tags)), "# Deep Dive")
assert.strictEqual(logic.categoryCount(articles, "all"), 3)
assert.strictEqual(logic.categoryCount(articles, "general"), 2)
assert.strictEqual(logic.categoryCount(articles, "news", {}, {}, {}, {}, Date.parse("2026-09-04T00:00:00Z")), 2)
assert.strictEqual(logic.categoryCount(articles, "to-read", { old: true }), 1)
assert.strictEqual(logic.categoryCount(articles, "liked", {}, { new: true }), 1)
assert.strictEqual(logic.categoryCount(articles, "liked", {}, { old: true, new: true }, { new: true }), 1)
assert.strictEqual(logic.categoryCount(articles, "tag:deep dive", {}, {}, {}, tags), 2)
assert.strictEqual(logic.categoryLabel("news"), "News")
assert.strictEqual(logic.categoryLabel("threat-intel"), "Threat Intel")
assert.strictEqual(logic.categoryLabel("to-read"), "To Read")
assert.strictEqual(logic.categoryLabel("liked"), "Like")
assert.strictEqual(logic.shortDate("2026-09-04T00:00:00Z"), "2026-09-04")
assert.strictEqual(logic.isNew("2026-09-02T00:00:01Z", Date.parse("2026-09-04T00:00:00Z")), true)
assert.strictEqual(logic.isNew("2026-09-01T00:00:00Z", Date.parse("2026-09-04T00:00:00Z")), false)
assert.strictEqual(logic.isNew("not-a-date", Date.parse("2026-09-04T00:00:00Z")), false)
assert.strictEqual(logic.unreadCount(articles, { old: true }), 2)
assert.strictEqual(logic.unreadCount(articles, { old: true }, { new: true }), 1)
assert.strictEqual(logic.normalizeTextSize("huge"), "standard")
assert.strictEqual(logic.fontScale("large"), 1.22)
assert.strictEqual(logic.pageTarget(0, 1, 1000, 3000), 900)
assert.strictEqual(logic.pageTarget(1900, 1, 1000, 2500), 1500)
assert.strictEqual(logic.positionForPage(2, 1000, 5000), 1800)
assert.strictEqual(logic.isAtEnd(1500, 1000, 2500), true)
assert.strictEqual(logic.isAtEnd(1498, 1000, 2500), false)
assert.strictEqual(logic.isAtEnd(0, 1000, 800), true)

let state = { screen: "empty", sync: "idle", offline: false, imageMissing: false }
state = logic.transition(state, "cached-feed")
assert.strictEqual(state.screen, "feed")
state = logic.transition(state, "sync-start")
assert.strictEqual(state.sync, "running")
state = logic.transition(state, "network-error")
assert.strictEqual(state.offline, true)
state = logic.transition(state, "open-article")
state = logic.transition(state, "image-error")
assert.strictEqual(state.imageMissing, true)
state = logic.transition(state, "back")
assert.strictEqual(state.screen, "feed")
state = logic.transition(state, "back")
assert.strictEqual(state.screen, "closed")
console.log("QML logic tests: ok")
