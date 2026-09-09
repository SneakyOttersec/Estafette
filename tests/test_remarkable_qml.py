import shutil
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def test_qml_logic_contract():
    node = shutil.which("node")
    if not node:
        return
    subprocess.run(
        [
            node,
            ROOT / "remarkable/tests/test_qml_logic.js",
            ROOT / "remarkable/app/ui/logic.js",
        ],
        check=True,
    )


def test_qml_has_cached_startup_persistence_offline_and_close_contracts():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    for expected in (
        "endpoint.sendMessage(100",
        "endpoint.sendMessage(101",
        "import QtCore",
        "readStateJson",
        "pageStateJson",
        "toReadStateJson",
        "likeStateJson",
        "deletedStateJson",
        "type === 202",
        "type === 203",
        "type === 400",
        "image unavailable offline",
        "root.close()",
        "savePage()",
        "DisplayMethodArea.Fast",
        "SECTIONS",
        "SAVED",
        "Logic.categoryCount",
        'property int railWidth: 292',
        'property color paper: "#ffffff"',
        'property color softPaper: "#ffffff"',
        'property color accent: "#cc2a41"',
        'property color ink: "#22272a"',
        'property string monoFont: "monospace"',
    ):
        assert expected in qml


def test_article_tap_navigates_before_best_effort_state_persistence():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    function = qml[qml.index("function openArticle"):qml.index("function backOrClose")]
    assert function.index('screen = "article"') < function.index("setRead(id, true)")
    assert "root.openArticle(feedRow.modelData.id)" in qml
    assert "LocalStorage.openDatabaseSync" not in qml


def test_article_reader_uses_the_full_surface_with_a_top_right_exit():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert 'Layout.preferredHeight: screen === "feed" ? 144 : 0' in qml
    assert 'Layout.preferredWidth: screen === "feed" ? railWidth : 0' in qml
    article_visible = qml.index('visible: screen === "article"', qml.index("id: titleSearch"))
    article_surface = qml[qml.rfind("Rectangle {", 0, article_visible):]
    article_surface = article_surface[:article_surface.index("Flickable {")]
    assert "x: -parent.x" in article_surface
    assert "width: root.width" in article_surface
    assert "color: paper" in article_surface
    assert "id: articleToolbar" in qml
    exit_button = qml[qml.index("id: exitArticleButton"):]
    exit_button = exit_button[:exit_button.index("DisplayMethodArea")]
    assert 'text: "× EXIT"' in exit_button
    assert "onClicked: backOrClose()" in exit_button
    toolbar = qml[qml.index("id: articleToolbar"):qml.index("id: exitArticleButton")]
    assert 'model: ["compact", "standard", "large"]' not in toolbar


def test_feed_has_persistent_read_later_and_like_actions():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert 'key: "to-read", label: "To Read"' in qml
    assert 'key: "liked", label: "Like"' in qml
    assert 'root.toggleFlag(feedRow.modelData.id, "to-read")' in qml
    assert 'root.toggleFlag(feedRow.modelData.id, "liked")' in qml
    assert 'text: likeMap[modelData.id] ? "♥" : "♡"' in qml
    assert qml.count("width: 64") >= 2
    assert qml.count("height: 64") >= 2


def test_feed_has_title_search_and_filled_liked_hearts():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert 'property string searchQuery: ""' in qml
    assert 'placeholderText: "Search article titles..."' in qml
    assert "Logic.filterTitle(categoryArticles, searchQuery)" in qml
    heart = qml[qml.index('text: likeMap[modelData.id] ? "♥" : "♡"'):]
    heart = heart[:heart.index("MouseArea")]
    assert "displayMethod: DisplayMethodArea.Fast" in heart


def test_feed_is_grayscale_and_article_images_have_a_zoom_viewer():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert "displayMethod: DisplayMethodArea.Fast" in qml
    assert "DisplayMethodArea.Content" not in qml
    assert "property var appRoot: root" in qml
    image_block = qml[qml.index("id: imageBlock"):]
    image_area = image_block[image_block.index("MouseArea {"):image_block.index("Rectangle {")]
    assert 'onDoubleClicked: appRoot.openImageViewer(block.url, block.caption || "")' in image_area
    assert "onClicked: appRoot.openImageViewer" not in image_area
    assert 'text: "DOUBLE-TAP IMAGE TO ZOOM"' in image_block
    assert "id: imageViewer" in qml
    assert "id: imageZoomFlick" in qml
    assert "root.setImageZoom(root.imageZoom - 0.5)" in qml
    assert "root.setImageZoom(root.imageZoom + 0.5)" in qml
    assert "Logic.clampZoom(value)" in qml
    assert 'text: "RESET"' in qml


def test_scrolling_uses_short_pixel_aligned_fixed_refresh_modes():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert "property real scrollDeceleration: 24000" in qml
    assert "property real scrollMaximumVelocity: 1800" in qml
    assert qml.count("flickDeceleration: root.scrollDeceleration") == 3
    assert qml.count("maximumFlickVelocity: root.scrollMaximumVelocity") == 3
    assert qml.count("pixelAligned: true") >= 4
    assert "cacheBuffer: height" in qml
    assert "displayMethod: feedList.moving" not in qml
    assert "displayMethod: articleFlick.moving" not in qml
    assert "displayMethod: imageZoomFlick.moving" not in qml
    assert "DisplayMethodArea.Animate" not in qml
    assert "height: visible ? implicitHeight : 0" not in qml


def test_long_press_menu_persists_and_filters_custom_tags():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert 'property string tagStateJson: "{}"' in qml
    assert "pressAndHoldInterval: 2000" in qml
    assert "root.openFeedArticleMenu(feedRow.modelData)" in qml
    assert 'text: "ARTICLE OPTIONS"' in qml
    assert 'placeholderText: "Add a custom tag"' in qml
    assert 'text: "SAVE TAG"' in qml
    assert 'text: "CLEAR TAG"' in qml
    assert 'text: "DELETE ENTRY"' in qml
    assert 'text: "TAGS"' in qml
    assert "model: customTagEntries" in qml
    assert "readingSettings.tagStateJson = JSON.stringify(replacement)" in qml
    assert "tagMap = withoutKey(tagMap, id)" in qml


def test_news_precedes_all_writings_and_delete_is_persistent():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    news = qml.index('{ key: "news", label: "News" }')
    all_writings = qml.index('{ key: "all", label: "All writings" }')
    assert news < all_writings
    assert 'text: "DELETE FROM LIST"' in qml
    assert "readingSettings.deletedStateJson = JSON.stringify(deletedMap)" in qml
    assert "root.deleteArticle(root.currentArticleId)" in qml
    assert "font.bold: !!toReadMap[modelData.id]" in qml


def test_new_badge_uses_the_article_publication_or_first_seen_date():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert "Logic.isNew(" in qml
    assert "currentArticle.published_at || currentArticle.first_seen_at" in qml
    assert 'text: "NEW !"' in qml


def test_article_swipes_page_once_without_kinetic_scrolling():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    move_page = qml[qml.index("function movePage"):qml.index("AppLoad {")]
    assert "articleFlick.cancelFlick()" in move_page
    assert "Logic.isAtEnd(" in move_page
    assert "direction > 0 && Logic.isAtEnd(" in move_page
    assert "backOrClose()" in move_page
    assert "function finishArticleSwipe(deltaX, deltaY)" in qml
    assert "Math.abs(deltaX) > Math.abs(deltaY)" in qml
    assert "movePage(distance < 0 ? 1 : -1)" in qml
    assert "// Swiping left or up advances; swiping right or down goes back." in qml
    assert "id: articlePageSwipe" in qml
    assert "interactive: false" in qml
    assert "root.finishArticleSwipe(mouse.x - pressX, mouse.y - pressY)" in qml
    assert "onDoubleClicked: function(mouse)" in qml
    assert "mouse.accepted = penInput" in qml
    assert "onFlickStarted:" not in qml
    assert "? DisplayMethodArea.Fast : DisplayMethodArea.UFast" in qml
    assert 'text: "‹ PREVIOUS"' not in qml
    assert '"WRITINGS ›" : "NEXT ›"' not in qml


def test_stylus_annotations_are_persistent_and_separate_from_touch_navigation():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert 'property string annotationStateJson: "{}"' in qml
    assert "readingSettings.annotationStateJson = JSON.stringify(annotationMap)" in qml
    assert "id: articleInkCanvas" in qml
    assert "property bool penInput: false" in qml
    assert "mouse.source === Qt.MouseEventNotSynthesized" in qml
    assert "root.beginAnnotationStroke(" in qml
    assert "root.extendAnnotationStroke(" in qml
    assert "root.finishAnnotationStroke()" in qml
    assert "onPositionChanged: function(mouse)" in qml
    assert "if (penInput) root.finishAnnotationStroke()" in qml
    assert "else root.finishArticleSwipe(mouse.x - pressX, mouse.y - pressY)" in qml
    assert "PointHandler {" not in qml
    assert "cleanedAnnotationMap(storedMap(readingSettings.annotationStateJson))" in qml
    assert 'key: "pen", icon: "qrc:/icons/pen.svg"' in qml
    assert 'key: "highlighter", icon: "qrc:/icons/highlighter.svg"' in qml
    assert 'key: "eraser", icon: "qrc:/icons/eraser.svg"' in qml
    resources = (ROOT / "remarkable/app/application.qrc").read_text()
    for icon in ("pen.svg", "highlighter.svg", "eraser.svg"):
        assert f"<file>icons/{icon}</file>" in resources
        assert (ROOT / "remarkable/app/icons" / icon).is_file()
    assert 'text: "CLEAR ANNOTATIONS"' in qml
    assert "Number(y) + articleFlick.contentY" in qml
    assert "points[pointIndex][1] - articleFlick.contentY" in qml
    assert "function paintSegment(tool, from, to)" in qml
    assert "if (!paintScheduled && !inkPaintTimer.running)" in qml
    assert "id: inkPaintTimer" in qml
    assert "interval: 16" in qml
    assert "function flushSegments()" in qml
    assert "scheduledSegments = pendingSegments" in qml
    assert "property bool paintScheduled: false" in qml
    assert "requestPaint(region)" in qml
    assert "if (dx * dx + dy * dy < 25) return" in qml
    assert "if (!fullRepaintRequested)" in qml
    assert "articleInkCanvas.paintSegment(activeAnnotationStroke.tool, previous, next)" in qml
    assert "Estafette native pen start" not in qml
    assert "onContentYChanged: articleInkCanvas.redrawAll()" in qml
    assert 'displayMethod: screen === "article"' in qml


def test_bottom_corner_touch_zones_turn_pages():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    left = qml[qml.index("id: articleBottomLeftTap"):qml.index("id: articleBottomRightTap")]
    right = qml[qml.index("id: articleBottomRightTap"):qml.index("id: articleToolbar")]
    for zone in (left, right):
        assert "width: 190" in zone
        assert "height: 190" in zone
        assert "acceptedDevices: PointerDevice.TouchScreen" in zone
        assert "gesturePolicy: TapHandler.ReleaseWithinBounds" in zone
    assert "onTapped: root.movePage(-1)" in left
    assert "onTapped: root.movePage(1)" in right


def test_shared_bicorn_icon_is_a_transparent_monochrome_mask():
    icon_path = ROOT / "remarkable/app/icon.png"
    with Image.open(icon_path) as source:
        icon = source.convert("RGBA")
    assert icon.size == (512, 512)
    assert icon.getpixel((0, 0))[3] == 0
    assert icon.getpixel((256, 350)) == (0, 0, 0, 255)
    assert icon.getchannel("A").getextrema() == (0, 255)
    assert all(red == green == blue == 0 for red, green, blue, alpha in icon.getdata() if alpha)


def test_reader_branding_and_article_canvas_are_reset_between_articles():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert "OTTERSEC READER" not in qml
    assert "function clearForArticleChange()" in qml
    assert qml.count("articleInkCanvas.clearForArticleChange()") >= 2
    assert "property bool articleCleanRefresh: false" in qml
    assert "? DisplayMethodArea.Fast : DisplayMethodArea.UFast" in qml


def test_opening_an_article_restores_its_previous_page():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    open_article = qml[qml.index("function openArticle"):qml.index("function backOrClose")]
    article_reply = qml[qml.index("} else if (type === 201)"):qml.index("} else if (type === 202)")]
    assert "savedPage(id)" in open_article
    assert "Logic.positionForPage(" in open_article
    assert "savedPage(currentArticleId)" in article_reply
    assert "Logic.positionForPage(" in article_reply
