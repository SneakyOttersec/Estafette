import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.LocalStorage 2.0
import net.asivery.AppLoad 1.0
import net.asivery.ApploadUtils
import "logic.js" as Logic

Rectangle {
    id: root
    anchors.fill: parent
    color: paper

    signal close

    // Large e-ink surfaces must be true white. Off-white fills are rendered as
    // a field of dithered black dots on Paper Pro.
    property color paper: "#ffffff"
    property color softPaper: "#ffffff"
    property color panel: "#e1e1e1"
    property color ink: "#22272a"
    property color muted: "#666666"
    property color quiet: "#999999"
    property color accent: "#cc2a41"
    property color secondary: "#567c77"
    // The site uses JetBrains Mono with a generic monospace fallback. Using
    // the generic family keeps the same rhythm with fonts already on-device.
    property string monoFont: "monospace"
    property int railWidth: 292

    property string screen: "feed"
    property string selectedCategory: "all"
    property string textSize: "standard"
    property var allArticles: []
    property var visibleArticles: []
    property var readMap: ({})
    property var currentArticle: null
    property string currentArticleId: ""
    property string generatedAt: ""
    property string statusText: "Loading cached feed…"
    property bool syncing: false
    property int syncDone: 0
    property int syncTotal: 0
    property real typeScale: Logic.fontScale(textSize)
    property var database: null

    function unloading() {
        savePage()
    }

    function db() {
        if (database !== null) return database
        database = LocalStorage.openDatabaseSync("Estafette", "1.0", "Estafette reading state", 1048576)
        database.transaction(function(tx) {
            tx.executeSql("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            tx.executeSql("CREATE TABLE IF NOT EXISTS articles (id TEXT PRIMARY KEY, is_read INTEGER NOT NULL DEFAULT 0, page INTEGER NOT NULL DEFAULT 0)")
        })
        return database
    }

    function preference(key, fallback) {
        var value = fallback
        db().readTransaction(function(tx) {
            var result = tx.executeSql("SELECT value FROM preferences WHERE key = ?", [key])
            if (result.rows.length) value = result.rows.item(0).value
        })
        return value
    }

    function setPreference(key, value) {
        db().transaction(function(tx) {
            tx.executeSql("INSERT OR REPLACE INTO preferences(key, value) VALUES(?, ?)", [key, String(value)])
        })
    }

    function loadReadState() {
        var values = {}
        db().readTransaction(function(tx) {
            var result = tx.executeSql("SELECT id, is_read FROM articles")
            for (var index = 0; index < result.rows.length; index++) {
                var row = result.rows.item(index)
                values[row.id] = row.is_read === 1
            }
        })
        readMap = values
    }

    function setRead(id, value) {
        db().transaction(function(tx) {
            tx.executeSql("INSERT OR IGNORE INTO articles(id, is_read, page) VALUES(?, 0, 0)", [id])
            tx.executeSql("UPDATE articles SET is_read = ? WHERE id = ?", [value ? 1 : 0, id])
        })
        var replacement = {}
        for (var key in readMap) replacement[key] = readMap[key]
        replacement[id] = value
        readMap = replacement
    }

    function savedPage(id) {
        var page = 0
        db().readTransaction(function(tx) {
            var result = tx.executeSql("SELECT page FROM articles WHERE id = ?", [id])
            if (result.rows.length) page = result.rows.item(0).page
        })
        return page
    }

    function savePage() {
        if (!currentArticleId || screen !== "article") return
        var page = Logic.pageNumber(articleFlick.contentY, articleFlick.height)
        db().transaction(function(tx) {
            tx.executeSql("INSERT OR IGNORE INTO articles(id, is_read, page) VALUES(?, 1, 0)", [currentArticleId])
            tx.executeSql("UPDATE articles SET page = ? WHERE id = ?", [page, currentArticleId])
        })
    }

    function applyCategory() {
        visibleArticles = Logic.filterCategory(allArticles, selectedCategory)
    }

    function chooseCategory(category) {
        savePage()
        selectedCategory = category
        setPreference("category", selectedCategory)
        applyCategory()
        screen = "feed"
        currentArticle = null
        currentArticleId = ""
    }

    function acceptFeed(contents) {
        try {
            var feed = JSON.parse(contents)
            allArticles = Logic.newestFirst(feed.articles || [])
            generatedAt = feed.generated_at || ""
            applyCategory()
            statusText = syncing ? "Synchronizing offline library…" : "Updated " + Logic.relativeDate(generatedAt)
        } catch (error) {
            statusText = "Cached feed is damaged"
        }
    }

    function startRefresh() {
        if (syncing) return
        syncing = true
        syncDone = 0
        syncTotal = 0
        statusText = "Checking for new writings…"
        endpoint.sendMessage(101, "")
    }

    function openArticle(id) {
        savePage()
        currentArticleId = id
        currentArticle = null
        setRead(id, true)
        screen = "article"
        statusText = "Opening cached article…"
        endpoint.sendMessage(102, JSON.stringify({ id: id }))
    }

    function backOrClose() {
        if (screen === "article") {
            savePage()
            screen = "feed"
            currentArticle = null
            currentArticleId = ""
        } else {
            root.close()
        }
    }

    function movePage(direction) {
        articleFlick.contentY = Logic.pageTarget(
            articleFlick.contentY, direction, articleFlick.height, articleFlick.contentHeight
        )
        savePage()
    }

    AppLoad {
        id: endpoint
        applicationID: "estafette"
        onMessageReceived: function(type, contents) {
            if (type === 200) {
                acceptFeed(contents)
            } else if (type === 201) {
                try {
                    currentArticle = JSON.parse(contents)
                    Qt.callLater(function() {
                        articleFlick.contentY = Logic.positionForPage(
                            savedPage(currentArticleId), articleFlick.height, articleFlick.contentHeight
                        )
                    })
                    statusText = "Available offline"
                } catch (error) {
                    statusText = "Cached article is damaged"
                }
            } else if (type === 202) {
                var progress = JSON.parse(contents)
                syncing = true
                syncDone = progress.done || 0
                syncTotal = progress.total || 0
                statusText = "Sync " + syncDone + " / " + syncTotal
            } else if (type === 203) {
                syncing = false
                statusText = "Offline library is up to date"
            } else if (type === 400) {
                var problem = JSON.parse(contents)
                syncing = false
                if (allArticles.length) statusText = "Offline · " + problem.message
                else statusText = "No cached feed · " + problem.message
            }
        }
    }

    Component.onCompleted: {
        selectedCategory = preference("category", "all")
        textSize = Logic.normalizeTextSize(preference("text_size", "standard"))
        loadReadState()
        endpoint.sendMessage(100, "")
        startRefresh()
    }

    DisplayMethodArea {
        anchors.fill: parent
        displayMethod: DisplayMethodArea.Content
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 4
        color: ink
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: 4
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 144
            color: paper

            RowLayout {
                anchors.fill: parent
                spacing: 0

                Item {
                    Layout.preferredWidth: railWidth
                    Layout.fillHeight: true

                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 28
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 18

                        Image {
                            width: 66
                            height: 66
                            source: "../icon.png"
                            fillMode: Image.PreserveAspectFit
                            smooth: false
                        }
                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2
                            Text {
                                text: "Estafette"
                                color: ink
                                font.family: monoFont
                                font.bold: true
                                font.pixelSize: 29
                            }
                            Text {
                                text: "OTTERSEC READER"
                                color: accent
                                font.family: monoFont
                                font.pixelSize: 15
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.fillHeight: true
                    color: panel
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 42
                        anchors.rightMargin: 30
                        spacing: 18

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Text {
                                text: screen === "feed" ? "Writings" : "Reading"
                                color: accent
                                font.family: monoFont
                                font.bold: true
                                font.pixelSize: 38
                            }
                            Text {
                                text: screen === "feed"
                                      ? "security research · newest first · cached offline"
                                      : (currentArticle ? currentArticle.source : "opening cached article")
                                color: muted
                                font.family: monoFont
                                font.pixelSize: 18
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }

                        Text {
                            visible: screen === "feed"
                            text: Logic.unreadCount(allArticles, readMap) + " unread"
                            color: muted
                            font.family: monoFont
                            font.pixelSize: 19
                        }

                        Row {
                            visible: screen === "article"
                            spacing: 8
                            Repeater {
                                model: ["compact", "standard", "large"]
                                Rectangle {
                                    required property string modelData
                                    width: 52
                                    height: 52
                                    color: textSize === modelData ? panel : paper
                                    border.color: textSize === modelData ? ink : quiet
                                    border.width: 1
                                    Text {
                                        anchors.centerIn: parent
                                        text: modelData.charAt(0).toUpperCase()
                                        color: ink
                                        font.family: monoFont
                                        font.bold: textSize === modelData
                                        font.pixelSize: 21
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        onClicked: {
                                            textSize = modelData
                                            setPreference("text_size", textSize)
                                        }
                                    }
                                    DisplayMethodArea { anchors.fill: parent; displayMethod: DisplayMethodArea.Fast }
                                }
                            }
                            Rectangle {
                                width: 52
                                height: 52
                                color: paper
                                border.color: quiet
                                Text { anchors.centerIn: parent; text: "···"; color: ink; font.family: monoFont; font.pixelSize: 21 }
                                MouseArea { anchors.fill: parent; onClicked: articleMenu.open() }
                                DisplayMethodArea { anchors.fill: parent; displayMethod: DisplayMethodArea.Fast }
                            }
                        }

                        Rectangle {
                            width: screen === "article" ? 174 : 110
                            height: 54
                            color: paper
                            border.color: ink
                            border.width: 1
                            Text {
                                anchors.centerIn: parent
                                text: screen === "article" ? "‹ WRITINGS" : "× CLOSE"
                                color: ink
                                font.family: monoFont
                                font.pixelSize: 18
                            }
                            MouseArea { anchors.fill: parent; onClicked: backOrClose() }
                            DisplayMethodArea { anchors.fill: parent; displayMethod: DisplayMethodArea.Fast }
                        }
                    }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: panel
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Rectangle {
                Layout.preferredWidth: railWidth
                Layout.fillHeight: true
                color: softPaper

                ColumnLayout {
                    anchors.fill: parent
                    anchors.topMargin: 30
                    anchors.bottomMargin: 28
                    spacing: 0

                    Text {
                        Layout.leftMargin: 30
                        Layout.bottomMargin: 14
                        text: "SECTIONS"
                        color: muted
                        font.family: monoFont
                        font.pixelSize: 16
                    }

                    Repeater {
                        model: [
                            { key: "all", label: "All writings" },
                            { key: "offensive", label: "Offensive" },
                            { key: "vuln-dev", label: "Vuln Dev" },
                            { key: "threat-intel", label: "Threat Intel" },
                            { key: "general", label: "General" }
                        ]
                        Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 84
                            color: selectedCategory === modelData.key ? panel : softPaper

                            Rectangle {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                width: 5
                                visible: selectedCategory === modelData.key
                                color: accent
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 30
                                anchors.verticalCenter: parent.verticalCenter
                                text: (selectedCategory === modelData.key ? "# " : "  ") + modelData.label
                                color: selectedCategory === modelData.key ? accent : ink
                                font.family: monoFont
                                font.bold: selectedCategory === modelData.key
                                font.pixelSize: 20
                            }
                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 24
                                anchors.verticalCenter: parent.verticalCenter
                                text: Logic.categoryCount(allArticles, modelData.key)
                                color: muted
                                font.family: monoFont
                                font.pixelSize: 17
                            }
                            MouseArea { anchors.fill: parent; onClicked: chooseCategory(modelData.key) }
                            DisplayMethodArea { anchors.fill: parent; displayMethod: DisplayMethodArea.Fast }
                        }
                    }

                    Item { Layout.fillHeight: true }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.leftMargin: 28
                        Layout.rightMargin: 28
                        Layout.bottomMargin: 22
                        height: 1
                        color: quiet
                    }

                    Text {
                        Layout.fillWidth: true
                        Layout.leftMargin: 28
                        Layout.rightMargin: 28
                        Layout.bottomMargin: 8
                        text: statusText
                        color: muted
                        font.family: monoFont
                        font.pixelSize: 15
                        wrapMode: Text.Wrap
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.leftMargin: 28
                        Layout.rightMargin: 28
                        Layout.bottomMargin: 20
                        height: 5
                        color: panel
                        Rectangle {
                            width: syncing && syncTotal > 0 ? parent.width * syncDone / syncTotal : 0
                            height: parent.height
                            color: accent
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.leftMargin: 28
                        Layout.rightMargin: 28
                        Layout.preferredHeight: 62
                        color: syncing ? panel : softPaper
                        border.color: ink
                        border.width: 1
                        Text {
                            anchors.centerIn: parent
                            text: syncing ? "SYNCING…" : "↻ REFRESH"
                            color: syncing ? muted : accent
                            font.family: monoFont
                            font.bold: true
                            font.pixelSize: 18
                        }
                        MouseArea { anchors.fill: parent; enabled: !syncing; onClicked: startRefresh() }
                        DisplayMethodArea { anchors.fill: parent; displayMethod: DisplayMethodArea.Fast }
                    }

                    Text {
                        Layout.leftMargin: 28
                        Layout.topMargin: 16
                        text: generatedAt ? "updated " + Logic.relativeDate(generatedAt) : "daily · 06:00 UTC"
                        color: quiet
                        font.family: monoFont
                        font.pixelSize: 14
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 1
                    color: panel
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    visible: screen === "feed"
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 92
                        color: paper

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 42
                            anchors.rightMargin: 36
                            Text {
                                Layout.fillWidth: true
                                text: selectedCategory === "all" ? "Latest 100" : Logic.categoryLabel(selectedCategory)
                                color: secondary
                                font.family: monoFont
                                font.bold: true
                                font.pixelSize: 25
                            }
                            Text {
                                text: visibleArticles.length + (visibleArticles.length === 1 ? " post" : " posts")
                                color: muted
                                font.family: monoFont
                                font.pixelSize: 16
                            }
                        }
                        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: panel }
                    }

                    ListView {
                        id: feedList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: visibleArticles
                        spacing: 0
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            width: feedList.width
                            height: 230
                            color: paper

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: 42
                                anchors.rightMargin: 36
                                spacing: 28

                                Column {
                                    width: 180
                                    anchors.top: parent.top
                                    anchors.topMargin: 35
                                    spacing: 10
                                    Text {
                                        text: Logic.shortDate(modelData.published_at || modelData.first_seen_at)
                                        color: muted
                                        font.family: monoFont
                                        font.pixelSize: 17
                                    }
                                    Text {
                                        text: modelData.source
                                        color: secondary
                                        font.family: monoFont
                                        font.pixelSize: 15
                                        width: parent.width
                                        wrapMode: Text.WrapAnywhere
                                        maximumLineCount: 2
                                        elide: Text.ElideRight
                                    }
                                }

                                Column {
                                    width: parent.width - 208
                                    anchors.top: parent.top
                                    anchors.topMargin: 31
                                    spacing: 10

                                    Row {
                                        width: parent.width
                                        spacing: 12
                                        Rectangle {
                                            width: 11
                                            height: 11
                                            radius: 6
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: readMap[modelData.id] ? paper : accent
                                            border.color: readMap[modelData.id] ? quiet : accent
                                        }
                                        Text {
                                            width: parent.width - 23
                                            text: modelData.title
                                            color: ink
                                            font.family: monoFont
                                            font.bold: true
                                            font.pixelSize: 24
                                            maximumLineCount: 2
                                            wrapMode: Text.Wrap
                                            elide: Text.ElideRight
                                        }
                                    }
                                    Text {
                                        width: parent.width
                                        text: modelData.excerpt || ""
                                        color: ink
                                        opacity: 0.86
                                        font.family: monoFont
                                        font.pixelSize: 17
                                        lineHeight: 1.25
                                        maximumLineCount: 2
                                        wrapMode: Text.Wrap
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        width: parent.width
                                        text: "#" + modelData.category + ((modelData.topics || []).length ? "  ·  " + (modelData.topics || []).join("  #") : "")
                                        color: accent
                                        font.family: monoFont
                                        font.pixelSize: 14
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            Rectangle {
                                anchors.left: parent.left
                                anchors.leftMargin: 42
                                anchors.right: parent.right
                                anchors.rightMargin: 36
                                anchors.bottom: parent.bottom
                                height: 1
                                color: panel
                            }
                            MouseArea { anchors.fill: parent; onClicked: openArticle(modelData.id) }
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: visibleArticles.length === 0
                            text: allArticles.length ? "No writings in this section." : "No cached writings yet."
                            color: muted
                            font.family: monoFont
                            font.pixelSize: 21
                        }
                    }
                }

                Item {
                    anchors.fill: parent
                    visible: screen === "article"

                    Flickable {
                        id: articleFlick
                        anchors.fill: parent
                        anchors.bottomMargin: 94
                        clip: true
                        contentWidth: width
                        contentHeight: articleColumn.height + 96

                        Column {
                            id: articleColumn
                            x: 72
                            y: 54
                            width: articleFlick.width - 144
                            spacing: 28

                            Text {
                                width: parent.width
                                visible: currentArticle !== null
                                text: currentArticle ? currentArticle.title : "Opening article…"
                                color: accent
                                font.family: monoFont
                                font.bold: true
                                font.pixelSize: 42 * typeScale
                                lineHeight: 1.1
                                wrapMode: Text.Wrap
                            }
                            Text {
                                width: parent.width
                                visible: currentArticle !== null
                                text: currentArticle
                                      ? Logic.shortDate(currentArticle.published_at || currentArticle.first_seen_at)
                                        + "  |  " + currentArticle.source
                                        + "  |  #" + currentArticle.category
                                      : ""
                                color: muted
                                font.family: monoFont
                                font.pixelSize: 18 * typeScale
                                wrapMode: Text.Wrap
                            }
                            Text {
                                width: parent.width
                                visible: currentArticle !== null
                                text: currentArticle ? currentArticle.canonical_url : ""
                                color: secondary
                                font.family: monoFont
                                font.pixelSize: 15 * typeScale
                                wrapMode: Text.WrapAnywhere
                            }
                            Rectangle { width: parent.width; height: 1; color: quiet }

                            Repeater {
                                model: currentArticle ? currentArticle.content : []
                                delegate: Loader {
                                    required property var modelData
                                    width: articleColumn.width
                                    sourceComponent: {
                                        if (modelData.type === "heading") return headingBlock
                                        if (modelData.type === "paragraph") return paragraphBlock
                                        if (modelData.type === "list") return listBlock
                                        if (modelData.type === "code") return codeBlock
                                        if (modelData.type === "quote") return quoteBlock
                                        if (modelData.type === "image") return imageBlock
                                        if (modelData.type === "table") return tableBlock
                                        return dividerBlock
                                    }
                                    property var block: modelData
                                }
                            }
                        }
                    }

                    MouseArea { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: articleControls.top; width: parent.width * 0.20; onClicked: movePage(-1) }
                    MouseArea { anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: articleControls.top; width: parent.width * 0.20; onClicked: movePage(1) }

                    Rectangle {
                        id: articleControls
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 94
                        color: softPaper
                        border.color: panel
                        border.width: 1

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 24
                            anchors.rightMargin: 24
                            anchors.topMargin: 14
                            anchors.bottomMargin: 14

                            Rectangle {
                                Layout.preferredWidth: 230
                                Layout.fillHeight: true
                                color: softPaper
                                border.color: ink
                                Text { anchors.centerIn: parent; text: "‹ PREVIOUS"; color: ink; font.family: monoFont; font.pixelSize: 18 }
                                MouseArea { anchors.fill: parent; onClicked: movePage(-1) }
                                DisplayMethodArea { anchors.fill: parent; displayMethod: DisplayMethodArea.Fast }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: {
                                    var maximum = Math.max(1, articleFlick.contentHeight - articleFlick.height)
                                    return Math.round(100 * Math.min(1, articleFlick.contentY / maximum)) + "% READ"
                                }
                                color: muted
                                font.family: monoFont
                                horizontalAlignment: Text.AlignHCenter
                                font.pixelSize: 17
                            }
                            Rectangle {
                                Layout.preferredWidth: 230
                                Layout.fillHeight: true
                                color: softPaper
                                border.color: ink
                                Text { anchors.centerIn: parent; text: "NEXT ›"; color: ink; font.family: monoFont; font.pixelSize: 18 }
                                MouseArea { anchors.fill: parent; onClicked: movePage(1) }
                                DisplayMethodArea { anchors.fill: parent; displayMethod: DisplayMethodArea.Fast }
                            }
                        }
                    }
                }
            }
        }
    }

    Popup {
        id: articleMenu
        anchors.centerIn: parent
        width: 500
        height: 228
        modal: true
        padding: 0
        background: Rectangle { color: paper; border.color: ink; border.width: 2 }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14
            Text { text: "ARTICLE"; color: accent; font.family: monoFont; font.bold: true; font.pixelSize: 25 }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 58
                color: softPaper
                border.color: ink
                Text { anchors.centerIn: parent; text: "MARK UNREAD"; color: ink; font.family: monoFont; font.pixelSize: 18 }
                MouseArea { anchors.fill: parent; onClicked: { setRead(currentArticleId, false); articleMenu.close() } }
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "close"
                color: muted
                font.family: monoFont
                font.pixelSize: 16
                MouseArea { anchors.fill: parent; anchors.margins: -12; onClicked: articleMenu.close() }
            }
        }
    }

    Component {
        id: headingBlock
        Text {
            width: parent ? parent.width : 1000
            text: (block.level === 2 ? "# " : "") + (block.text || "")
            color: block.level <= 1 ? accent : secondary
            font.family: monoFont
            font.bold: true
            font.pixelSize: (block.level <= 2 ? 32 : 26) * typeScale
            wrapMode: Text.Wrap
            height: implicitHeight
        }
    }
    Component {
        id: paragraphBlock
        Text {
            width: parent ? parent.width : 1000
            text: block.text || ""
            color: ink
            font.family: monoFont
            font.pixelSize: 24 * typeScale
            lineHeight: 1.42
            wrapMode: Text.Wrap
            height: implicitHeight
        }
    }
    Component {
        id: listBlock
        Text {
            width: parent ? parent.width : 1000
            text: Logic.listText(block.items, block.ordered)
            color: ink
            font.family: monoFont
            font.pixelSize: 23 * typeScale
            lineHeight: 1.42
            wrapMode: Text.Wrap
            height: implicitHeight
        }
    }
    Component {
        id: codeBlock
        Rectangle {
            width: parent ? parent.width : 1000
            height: codeText.implicitHeight + 40
            color: paper
            border.color: muted
            Text {
                id: codeText
                anchors.fill: parent
                anchors.margins: 20
                text: block.text || ""
                color: ink
                font.family: monoFont
                font.pixelSize: 19 * typeScale
                wrapMode: Text.WrapAnywhere
            }
        }
    }
    Component {
        id: quoteBlock
        Rectangle {
            width: parent ? parent.width : 1000
            height: quoteText.implicitHeight + 34
            color: softPaper
            Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 5; color: accent }
            Text {
                id: quoteText
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 18
                anchors.topMargin: 17
                anchors.bottomMargin: 17
                text: block.text || ""
                color: ink
                font.family: monoFont
                font.italic: true
                font.pixelSize: 23 * typeScale
                wrapMode: Text.Wrap
            }
        }
    }
    Component {
        id: tableBlock
        Text {
            width: parent ? parent.width : 1000
            text: Logic.tableText(block.rows)
            color: ink
            font.family: monoFont
            font.pixelSize: 18 * typeScale
            wrapMode: Text.WrapAnywhere
            height: implicitHeight
        }
    }
    Component {
        id: dividerBlock
        Rectangle { width: parent ? parent.width : 1000; height: 1; color: muted }
    }
    Component {
        id: imageBlock
        Column {
            width: parent ? parent.width : 1000
            spacing: 10
            Image {
                id: localImage
                width: parent.width
                height: status === Image.Ready ? Math.min(sourceSize.height * width / Math.max(1, sourceSize.width), 960) : 180
                source: block.url || ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                smooth: false
            }
            Rectangle {
                width: parent.width
                height: 160
                visible: block.damaged || !block.url || localImage.status === Image.Error
                color: softPaper
                border.color: muted
                Text { anchors.centerIn: parent; text: "[ image unavailable offline ]"; color: muted; font.family: monoFont; font.pixelSize: 20 }
            }
            Text {
                width: parent.width
                visible: !!block.caption
                text: block.caption || ""
                color: muted
                font.family: monoFont
                font.italic: true
                font.pixelSize: 17 * typeScale
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                height: visible ? implicitHeight : 0
            }
        }
    }
}
