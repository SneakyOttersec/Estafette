package syncer

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func sum(data []byte) string { value := sha256.Sum256(data); return hex.EncodeToString(value[:]) }

type fixture struct {
	server                 *httptest.Server
	client                 *Client
	feed, article, image   []byte
	articleName, imageName string
	rangeSeen              atomic.Bool
	articleRequests        atomic.Int32
}

type roundTripperFunc func(*http.Request) (*http.Response, error)

func (function roundTripperFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	image := []byte("deterministic-image-content")
	imageName := sum(image) + ".png"
	fixture := &fixture{image: image, imageName: imageName}
	fixture.server = httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/remarkable/api/v1/feed.json":
			w.Write(fixture.feed)
		case "/remarkable/api/v1/articles/" + fixture.articleName:
			fixture.articleRequests.Add(1)
			w.Write(fixture.article)
		case "/remarkable/api/v1/assets/" + fixture.imageName:
			if header := r.Header.Get("Range"); header != "" {
				fixture.rangeSeen.Store(true)
				var offset int
				fmt.Sscanf(header, "bytes=%d-", &offset)
				w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", offset, len(image)-1, len(image)))
				w.WriteHeader(http.StatusPartialContent)
				w.Write(image[offset:])
				return
			}
			w.Write(image)
		default:
			http.NotFound(w, r)
		}
	}))
	origin := fixture.server.URL
	article := Article{
		SchemaVersion: 1, ID: "article-id", Title: "Article", Source: "source.test",
		SourceURL: "https://source.test", CanonicalURL: "https://source.test/article",
		FirstSeenAt: "2026-09-04T00:00:00Z", Category: "general", Topics: []string{"test"},
		Content: []ContentBlock{{Type: "paragraph", Text: "Body"}, {Type: "image", URL: origin + "/remarkable/api/v1/assets/" + imageName}},
		Assets:  []Asset{{URL: origin + "/remarkable/api/v1/assets/" + imageName, SHA256: sum(image), Bytes: int64(len(image)), MediaType: "image/png"}},
	}
	fixture.article, _ = json.Marshal(article)
	fixture.articleName = "article-id-" + sum(fixture.article)[:16] + ".json"
	feed := Feed{
		SchemaVersion: 1, GeneratedAt: "2026-09-04T06:00:00Z", TotalBytes: int64(len(fixture.article) + len(image) + 400),
		Articles: []FeedArticle{{ID: "article-id", Title: "Article", Source: "source.test", FirstSeenAt: "2026-09-04T00:00:00Z", Category: "general", Topics: []string{"test"}, CanonicalURL: "https://source.test/article", ArticleURL: origin + "/remarkable/api/v1/articles/" + fixture.articleName, Excerpt: "Body", Bytes: int64(len(fixture.article)), SHA256: sum(fixture.article)}},
	}
	fixture.feed, _ = json.Marshal(feed)
	fixture.client = &Client{
		Origin: origin, FeedURL: origin + DefaultFeedPath, DataDir: t.TempDir(),
		HTTPClient: fixture.server.Client(), MaxCacheBytes: DefaultMaxCache,
		Now: func() time.Time { return time.Date(2026, 9, 8, 0, 0, 0, 0, time.UTC) },
	}
	t.Cleanup(fixture.server.Close)
	return fixture
}

func TestRecentArticlesUsesPublishedDateAndIncludesCutoff(t *testing.T) {
	client := &Client{Now: func() time.Time {
		return time.Date(2026, 9, 8, 0, 0, 0, 0, time.UTC)
	}}
	exact := "2026-08-25T00:00:00Z"
	old := "2026-08-24T23:59:59Z"
	items := []FeedArticle{
		{ID: "cutoff", PublishedAt: &exact, FirstSeenAt: "2026-08-01T00:00:00Z"},
		{ID: "published-old", PublishedAt: &old, FirstSeenAt: "2026-09-08T00:00:00Z"},
		{ID: "fallback-recent", FirstSeenAt: "2026-09-01T00:00:00Z"},
		{ID: "fallback-old", FirstSeenAt: old},
	}

	recent := client.recentArticles(items)
	if len(recent) != 2 || recent[0].ID != "cutoff" || recent[1].ID != "fallback-recent" {
		t.Fatalf("unexpected retained articles: %#v", recent)
	}
}

func TestSyncDoesNotDownloadOrRetainExpiredArticles(t *testing.T) {
	fx := newFixture(t)
	var feed Feed
	if err := json.Unmarshal(fx.feed, &feed); err != nil {
		t.Fatal(err)
	}
	old := "2026-08-24T23:59:59Z"
	feed.Articles[0].PublishedAt = &old
	feed.Articles[0].FirstSeenAt = "2026-09-08T00:00:00Z"
	fx.feed, _ = json.Marshal(feed)

	for _, directory := range []string{"articles", "assets"} {
		if err := os.MkdirAll(filepath.Join(fx.client.DataDir, directory), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(fx.client.DataDir, directory, "stale"), []byte("stale"), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	synced, err := fx.client.Sync(nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(synced.Articles) != 0 || fx.articleRequests.Load() != 0 {
		t.Fatalf("expired article was synchronized: articles=%d requests=%d", len(synced.Articles), fx.articleRequests.Load())
	}
	_, cached, err := fx.client.CachedFeed()
	if err != nil {
		t.Fatal(err)
	}
	if len(cached.Articles) != 0 {
		t.Fatal("expired article remained in cached feed")
	}
	for _, path := range []string{
		filepath.Join(fx.client.DataDir, "articles", "stale"),
		filepath.Join(fx.client.DataDir, "assets", "stale"),
	} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("expired cache file was not pruned: %s", path)
		}
	}
}

func TestSyncPrefetchesEveryAssetAndPrunes(t *testing.T) {
	fx := newFixture(t)
	os.MkdirAll(filepath.Join(fx.client.DataDir, "assets"), 0o700)
	os.WriteFile(filepath.Join(fx.client.DataDir, "assets", "orphan.png"), []byte("orphan"), 0o600)
	var last Progress
	if _, err := fx.client.Sync(func(progress Progress) { last = progress }); err != nil {
		t.Fatal(err)
	}
	if last.Done != 2 || last.Total != 2 {
		t.Fatalf("unexpected progress: %#v", last)
	}
	if _, err := os.Stat(filepath.Join(fx.client.DataDir, "assets", fx.imageName)); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(fx.client.DataDir, "assets", "orphan.png")); !os.IsNotExist(err) {
		t.Fatal("orphan was not pruned")
	}
	data, err := fx.client.LoadArticle("article-id")
	if err != nil {
		t.Fatal(err)
	}
	var loaded Article
	if err = json.Unmarshal(data, &loaded); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(loaded.Content[1].URL, "file://") || loaded.Content[1].Damaged {
		t.Fatalf("image was not localized: %#v", loaded.Content[1])
	}
}

func TestInterruptedAssetDownloadResumes(t *testing.T) {
	fx := newFixture(t)
	part := filepath.Join(fx.client.DataDir, "assets", fx.imageName+".part")
	os.MkdirAll(filepath.Dir(part), 0o700)
	os.WriteFile(part, fx.image[:8], 0o600)
	if _, err := fx.client.Sync(nil); err != nil {
		t.Fatal(err)
	}
	if !fx.rangeSeen.Load() {
		t.Fatal("asset download did not use Range")
	}
}

func TestCompletedPartialFileIsPromotedWithoutDownloadingAgain(t *testing.T) {
	fx := newFixture(t)
	part := filepath.Join(fx.client.DataDir, "assets", fx.imageName+".part")
	if err := os.MkdirAll(filepath.Dir(part), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(part, fx.image, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := fx.client.Sync(nil); err != nil {
		t.Fatal(err)
	}
	if fx.rangeSeen.Load() {
		t.Fatal("completed partial asset was downloaded again")
	}
	if digest, size, err := digestFile(strings.TrimSuffix(part, ".part")); err != nil || digest != sum(fx.image) || size != int64(len(fx.image)) {
		t.Fatalf("completed partial asset was not promoted: %s %d %v", digest, size, err)
	}
}

func TestChecksumMismatchPreservesLastValidFeed(t *testing.T) {
	fx := newFixture(t)
	old := []byte(`{"old":true}`)
	os.MkdirAll(fx.client.DataDir, 0o700)
	os.WriteFile(filepath.Join(fx.client.DataDir, "feed.json"), old, 0o600)
	var feed Feed
	json.Unmarshal(fx.feed, &feed)
	feed.Articles[0].SHA256 = strings.Repeat("0", 64)
	fx.feed, _ = json.Marshal(feed)
	if _, err := fx.client.Sync(nil); err == nil {
		t.Fatal("expected checksum error")
	}
	actual, _ := os.ReadFile(filepath.Join(fx.client.DataDir, "feed.json"))
	if string(actual) != string(old) {
		t.Fatal("last valid feed was replaced")
	}
}

func TestMetadataMismatchDoesNotDeleteAnArticleUsedByTheOldFeed(t *testing.T) {
	fx := newFixture(t)
	if _, err := fx.client.Sync(nil); err != nil {
		t.Fatal(err)
	}
	oldFeed := append([]byte(nil), fx.feed...)
	var changed Feed
	if err := json.Unmarshal(fx.feed, &changed); err != nil {
		t.Fatal(err)
	}
	changed.Articles[0].Title = "Inconsistent title"
	fx.feed, _ = json.Marshal(changed)
	if _, err := fx.client.Sync(nil); err == nil {
		t.Fatal("expected article metadata mismatch")
	}
	fx.feed = oldFeed
	if _, err := fx.client.LoadArticle("article-id"); err != nil {
		t.Fatalf("old feed article was not preserved: %v", err)
	}
}

func TestMalformedAndOversizedJSONAreRejected(t *testing.T) {
	fx := newFixture(t)
	fx.feed = []byte(`{"schema_version":1,"unexpected":true}`)
	if _, err := fx.client.Sync(nil); err == nil {
		t.Fatal("expected malformed feed rejection")
	}
	fx.feed = make([]byte, MaxFeedBytes+1)
	if _, err := fx.client.Sync(nil); err == nil {
		t.Fatal("expected oversized feed rejection")
	}
}

func TestSameOriginAndTLSFailures(t *testing.T) {
	fx := newFixture(t)
	if fx.client.SameOrigin("http://" + strings.TrimPrefix(fx.server.URL, "https://") + "/remarkable/a") {
		t.Fatal("HTTP was accepted")
	}
	if fx.client.SameOrigin("https://attacker.test/remarkable/a") {
		t.Fatal("foreign origin was accepted")
	}
	untrusted := New(fx.client.DataDir)
	untrusted.Origin, untrusted.FeedURL = fx.server.URL, fx.server.URL+DefaultFeedPath
	if _, err := untrusted.Sync(nil); err == nil {
		t.Fatal("expected certificate verification failure")
	}
}

func TestCrossOriginRedirectResponseIsRejected(t *testing.T) {
	client := New(t.TempDir())
	client.HTTPClient = &http.Client{Transport: roundTripperFunc(func(request *http.Request) (*http.Response, error) {
		foreign, _ := http.NewRequest(http.MethodGet, "https://attacker.test/feed.json", nil)
		return &http.Response{StatusCode: http.StatusOK, Body: http.NoBody, Request: foreign}, nil
	})}
	if _, err := client.getBytes(client.FeedURL, MaxFeedBytes); err == nil || !strings.Contains(err.Error(), "redirect") {
		t.Fatalf("unexpected redirect result: %v", err)
	}
}

func TestCacheCeilingIsEnforced(t *testing.T) {
	fx := newFixture(t)
	fx.client.MaxCacheBytes = 20
	if _, err := fx.client.Sync(nil); err == nil || !strings.Contains(err.Error(), "ceiling") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestMissingImageBecomesOfflinePlaceholder(t *testing.T) {
	fx := newFixture(t)
	if _, err := fx.client.Sync(nil); err != nil {
		t.Fatal(err)
	}
	os.Remove(filepath.Join(fx.client.DataDir, "assets", fx.imageName))
	data, err := fx.client.LoadArticle("article-id")
	if err != nil {
		t.Fatal(err)
	}
	var loaded Article
	json.Unmarshal(data, &loaded)
	if !loaded.Content[1].Damaged || loaded.Content[1].URL != "" {
		t.Fatal("damaged image did not become a placeholder")
	}
}
