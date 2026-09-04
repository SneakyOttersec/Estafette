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
        "DisplayMethodArea.Content",
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


def test_feed_has_persistent_read_later_and_like_actions():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert 'key: "to-read", label: "To Read"' in qml
    assert 'key: "liked", label: "Like"' in qml
    assert 'root.toggleFlag(feedRow.modelData.id, "to-read")' in qml
    assert 'root.toggleFlag(feedRow.modelData.id, "liked")' in qml
    assert 'text: likeMap[modelData.id] ? "♥" : "♡"' in qml
    assert qml.count("width: 64") >= 2
    assert qml.count("height: 64") >= 2


def test_feed_has_title_search_and_color_quality_for_liked_hearts():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    assert 'property string searchQuery: ""' in qml
    assert 'placeholderText: "Search article titles..."' in qml
    assert "Logic.filterTitle(categoryArticles, searchQuery)" in qml
    heart = qml[qml.index('text: likeMap[modelData.id] ? "♥" : "♡"'):]
    heart = heart[:heart.index("MouseArea")]
    assert "displayMethod: DisplayMethodArea.Content" in heart


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


def test_next_at_article_end_returns_to_the_feed():
    qml = (ROOT / "remarkable/app/ui/Estafette.qml").read_text()
    move_page = qml[qml.index("function movePage"):qml.index("AppLoad {")]
    assert "Logic.isAtEnd(" in move_page
    assert "backOrClose()" in move_page
    assert '"WRITINGS ›" : "NEXT ›"' in qml


def test_shared_bicorn_icon_is_a_transparent_monochrome_mask():
    icon_path = ROOT / "remarkable/app/icon.png"
    with Image.open(icon_path) as source:
        icon = source.convert("RGBA")
    assert icon.size == (512, 512)
    assert icon.getpixel((0, 0))[3] == 0
    assert icon.getpixel((256, 350)) == (0, 0, 0, 255)
    assert icon.getchannel("A").getextrema() == (0, 255)
    assert all(red == green == blue == 0 for red, green, blue, alpha in icon.getdata() if alpha)
