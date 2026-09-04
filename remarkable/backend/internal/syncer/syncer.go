package syncer

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	SchemaVersion       = 1
	DefaultOrigin       = "https://sneakyottersec.github.io/Estafette"
	DefaultFeedPath     = "/remarkable/api/v1/feed.json"
	DefaultMaxCache     = int64(512 * 1024 * 1024)
	MaxSnapshotBytes    = int64(480 * 1024 * 1024)
	MaxFeedBytes        = int64(2 * 1024 * 1024)
	MaxArticleJSONBytes = int64(10 * 1024 * 1024)
)

var shaPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

type Feed struct {
	SchemaVersion int           `json:"schema_version"`
	GeneratedAt   string        `json:"generated_at"`
	TotalBytes    int64         `json:"total_bytes"`
	Articles      []FeedArticle `json:"articles"`
}

type FeedArticle struct {
	ID           string   `json:"id"`
	Title        string   `json:"title"`
	Source       string   `json:"source"`
	PublishedAt  *string  `json:"published_at"`
	FirstSeenAt  string   `json:"first_seen_at"`
	Category     string   `json:"category"`
	Topics       []string `json:"topics"`
	CanonicalURL string   `json:"canonical_url"`
	ArticleURL   string   `json:"article_url"`
	Excerpt      string   `json:"excerpt"`
	Bytes        int64    `json:"bytes"`
	SHA256       string   `json:"sha256"`
}

type Asset struct {
	URL       string `json:"url"`
	SHA256    string `json:"sha256"`
	Bytes     int64  `json:"bytes"`
	MediaType string `json:"media_type"`
}

type ContentBlock struct {
	Type     string     `json:"type"`
	Level    int        `json:"level,omitempty"`
	Text     string     `json:"text,omitempty"`
	Language string     `json:"language,omitempty"`
	Ordered  bool       `json:"ordered,omitempty"`
	Items    []string   `json:"items,omitempty"`
	Rows     [][]string `json:"rows,omitempty"`
	URL      string     `json:"url,omitempty"`
	Caption  string     `json:"caption,omitempty"`
	Damaged  bool       `json:"damaged,omitempty"`
}

type Article struct {
	SchemaVersion int            `json:"schema_version"`
	ID            string         `json:"id"`
	Title         string         `json:"title"`
	Source        string         `json:"source"`
	SourceURL     string         `json:"source_url"`
	CanonicalURL  string         `json:"canonical_url"`
	PublishedAt   *string        `json:"published_at"`
	FirstSeenAt   string         `json:"first_seen_at"`
	Category      string         `json:"category"`
	Topics        []string       `json:"topics"`
	Content       []ContentBlock `json:"content"`
	Assets        []Asset        `json:"assets"`
}

type Progress struct {
	Done    int    `json:"done"`
	Total   int    `json:"total"`
	Current string `json:"current"`
}

type Client struct {
	Origin        string
	FeedURL       string
	DataDir       string
	HTTPClient    *http.Client
	MaxCacheBytes int64
	cacheMu       sync.RWMutex
}

func New(dataDir string) *Client {
	origin := strings.TrimRight(DefaultOrigin, "/")
	return &Client{
		Origin: origin, FeedURL: origin + DefaultFeedPath, DataDir: dataDir,
		HTTPClient: &http.Client{Timeout: 30 * time.Second}, MaxCacheBytes: DefaultMaxCache,
	}
}

func (c *Client) origin() string {
	if c.Origin == "" {
		return DefaultOrigin
	}
	return strings.TrimRight(c.Origin, "/")
}

func (c *Client) httpClient() *http.Client {
	if c.HTTPClient == nil {
		return &http.Client{Timeout: 30 * time.Second}
	}
	return c.HTTPClient
}

func (c *Client) maximumCache() int64 {
	if c.MaxCacheBytes <= 0 {
		return DefaultMaxCache
	}
	return c.MaxCacheBytes
}

func (c *Client) feedURL() string {
	if c.FeedURL == "" {
		return c.origin() + DefaultFeedPath
	}
	return c.FeedURL
}

func (c *Client) SameOrigin(raw string) bool {
	want, err := url.Parse(c.origin())
	if err != nil || want.Scheme != "https" || want.Host == "" {
		return false
	}
	got, err := url.Parse(raw)
	return err == nil && got.Scheme == "https" && strings.EqualFold(got.Host, want.Host) && got.User == nil
}

func validCategory(category string) bool {
	switch category {
	case "offensive", "vuln-dev", "threat-intel", "general":
		return true
	}
	return false
}

func (c *Client) validateFeed(feed *Feed) error {
	if feed.SchemaVersion != SchemaVersion {
		return fmt.Errorf("unsupported feed schema %d", feed.SchemaVersion)
	}
	if feed.TotalBytes <= 0 || feed.TotalBytes > MaxSnapshotBytes {
		return errors.New("feed snapshot size is invalid")
	}
	if len(feed.Articles) == 0 || len(feed.Articles) > 100 {
		return errors.New("feed article count is invalid")
	}
	seen := map[string]bool{}
	for _, item := range feed.Articles {
		if item.ID == "" || item.Title == "" || item.Source == "" || seen[item.ID] {
			return errors.New("feed contains empty or duplicate IDs")
		}
		seen[item.ID] = true
		if !c.SameOrigin(item.ArticleURL) {
			return fmt.Errorf("article is not same-origin HTTPS: %s", item.ArticleURL)
		}
		if item.Bytes <= 0 || item.Bytes > MaxArticleJSONBytes || !shaPattern.MatchString(item.SHA256) {
			return fmt.Errorf("invalid article integrity metadata for %s", item.ID)
		}
		if _, err := time.Parse(time.RFC3339, item.FirstSeenAt); err != nil {
			return fmt.Errorf("invalid first-seen date for %s", item.ID)
		}
		if item.PublishedAt != nil {
			if _, err := time.Parse(time.RFC3339, *item.PublishedAt); err != nil {
				return fmt.Errorf("invalid publication date for %s", item.ID)
			}
		}
		if !validCategory(item.Category) {
			return fmt.Errorf("invalid category for %s", item.ID)
		}
	}
	return nil
}

func decodeStrict(data []byte, destination any) error {
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return err
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return errors.New("trailing JSON data")
	}
	return nil
}

func (c *Client) getBytes(raw string, maximum int64) ([]byte, error) {
	if !c.SameOrigin(raw) {
		return nil, errors.New("refused non-same-origin HTTPS URL")
	}
	response, err := c.httpClient().Get(raw)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.Request == nil || !c.SameOrigin(response.Request.URL.String()) {
		return nil, errors.New("refused cross-origin redirect")
	}
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP %d for %s", response.StatusCode, raw)
	}
	if response.ContentLength > maximum {
		return nil, errors.New("response exceeds size limit")
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, maximum+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) > maximum {
		return nil, errors.New("response exceeds size limit")
	}
	return data, nil
}

func digestFile(path string) (string, int64, error) {
	handle, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer handle.Close()
	hash := sha256.New()
	size, err := io.Copy(hash, handle)
	if err != nil {
		return "", 0, err
	}
	return hex.EncodeToString(hash.Sum(nil)), size, nil
}

func atomicWrite(path string, data []byte, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	temporary := path + ".tmp"
	handle, err := os.OpenFile(temporary, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	if _, err = handle.Write(data); err == nil {
		err = handle.Sync()
	}
	closeErr := handle.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		os.Remove(temporary)
		return err
	}
	if err = os.Rename(temporary, path); err != nil {
		return err
	}
	directory, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	err = directory.Sync()
	closeErr = directory.Close()
	if err != nil {
		return err
	}
	return closeErr
}

func (c *Client) cacheSize() (int64, error) {
	var total int64
	err := filepath.Walk(c.DataDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}
		if info.Mode().IsRegular() {
			total += info.Size()
		}
		return nil
	})
	return total, err
}

func (c *Client) ensureCapacity(additional int64) error {
	size, err := c.cacheSize()
	if err != nil {
		return err
	}
	maximum := c.maximumCache()
	if additional < 0 || size > maximum || additional > maximum-size {
		return fmt.Errorf("storage ceiling exceeded: %d + %d > %d", size, additional, maximum)
	}
	return nil
}

func (c *Client) ensureFile(raw, destination string, expectedBytes int64, expectedHash string) error {
	if !c.SameOrigin(raw) {
		return errors.New("refused non-same-origin HTTPS URL")
	}
	if digest, size, err := digestFile(destination); err == nil && size == expectedBytes && digest == expectedHash {
		return nil
	}
	os.Remove(destination)
	part := destination + ".part"
	if err := os.MkdirAll(filepath.Dir(destination), 0o700); err != nil {
		return err
	}
	var offset int64
	if info, err := os.Stat(part); err == nil {
		offset = info.Size()
		if offset > expectedBytes {
			os.Remove(part)
			offset = 0
		} else if offset == expectedBytes {
			digest, _, digestErr := digestFile(part)
			if digestErr == nil && digest == expectedHash {
				return os.Rename(part, destination)
			}
			os.Remove(part)
			offset = 0
		}
	}
	if err := c.ensureCapacity(expectedBytes - offset); err != nil {
		return err
	}
	request, err := http.NewRequest(http.MethodGet, raw, nil)
	if err != nil {
		return err
	}
	if offset > 0 {
		request.Header.Set("Range", fmt.Sprintf("bytes=%d-", offset))
	}
	response, err := c.httpClient().Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.Request == nil || !c.SameOrigin(response.Request.URL.String()) {
		return errors.New("refused cross-origin redirect")
	}
	flags := os.O_CREATE | os.O_WRONLY
	if offset > 0 {
		if response.StatusCode == http.StatusPartialContent {
			flags |= os.O_APPEND
		} else if response.StatusCode == http.StatusOK {
			offset = 0
			flags |= os.O_TRUNC
		} else {
			if response.StatusCode == http.StatusRequestedRangeNotSatisfiable {
				os.Remove(part)
			}
			return fmt.Errorf("HTTP %d for %s", response.StatusCode, raw)
		}
	} else {
		offset = 0
		flags |= os.O_TRUNC
		if response.StatusCode != http.StatusOK {
			return fmt.Errorf("HTTP %d for %s", response.StatusCode, raw)
		}
	}
	handle, err := os.OpenFile(part, flags, 0o600)
	if err != nil {
		return err
	}
	written, copyErr := io.Copy(handle, io.LimitReader(response.Body, expectedBytes-offset+1))
	if copyErr == nil {
		copyErr = handle.Sync()
	}
	closeErr := handle.Close()
	if copyErr != nil {
		return copyErr
	}
	if closeErr != nil {
		return closeErr
	}
	if offset+written != expectedBytes {
		return fmt.Errorf("download length mismatch for %s", raw)
	}
	digest, _, err := digestFile(part)
	if err != nil {
		return err
	}
	if digest != expectedHash {
		os.Remove(part)
		return fmt.Errorf("checksum mismatch for %s", raw)
	}
	return os.Rename(part, destination)
}

func basenameFromURL(raw string) (string, error) {
	parsed, err := url.Parse(raw)
	if err != nil {
		return "", err
	}
	name := filepath.Base(parsed.Path)
	if name == "." || name == "/" || strings.ContainsAny(name, `\\`) {
		return "", errors.New("invalid URL filename")
	}
	return name, nil
}

func (c *Client) validateArticle(article *Article, expected FeedArticle) error {
	if article.SchemaVersion != SchemaVersion || article.ID != expected.ID {
		return errors.New("article schema or ID mismatch")
	}
	if article.Title == "" || article.Source == "" || article.Title != expected.Title || article.Source != expected.Source || article.CanonicalURL != expected.CanonicalURL || article.FirstSeenAt != expected.FirstSeenAt || article.Category != expected.Category || !slices.Equal(article.Topics, expected.Topics) {
		return errors.New("article metadata does not match the feed")
	}
	if (article.PublishedAt == nil) != (expected.PublishedAt == nil) || (article.PublishedAt != nil && *article.PublishedAt != *expected.PublishedAt) {
		return errors.New("article publication date does not match the feed")
	}
	if _, err := time.Parse(time.RFC3339, article.FirstSeenAt); err != nil {
		return errors.New("article first-seen date is invalid")
	}
	if article.PublishedAt != nil {
		if _, err := time.Parse(time.RFC3339, *article.PublishedAt); err != nil {
			return errors.New("article publication date is invalid")
		}
	}
	for _, raw := range []string{article.SourceURL, article.CanonicalURL} {
		parsed, err := url.Parse(raw)
		if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" || parsed.User != nil {
			return errors.New("article attribution URL is invalid")
		}
	}
	if len(article.Content) == 0 {
		return errors.New("article has no content")
	}
	assets := map[string]bool{}
	assetURLs := map[string]bool{}
	for _, asset := range article.Assets {
		if !c.SameOrigin(asset.URL) || !shaPattern.MatchString(asset.SHA256) || asset.Bytes <= 0 || asset.Bytes > MaxSnapshotBytes || (asset.MediaType != "image/png" && asset.MediaType != "image/jpeg") {
			return errors.New("invalid article asset")
		}
		name, err := basenameFromURL(asset.URL)
		if err != nil || !strings.HasPrefix(name, asset.SHA256+".") {
			return errors.New("article asset URL does not match its checksum")
		}
		if (asset.MediaType == "image/png" && !strings.HasSuffix(name, ".png")) || (asset.MediaType == "image/jpeg" && !strings.HasSuffix(name, ".jpg")) {
			return errors.New("article asset type does not match its URL")
		}
		if assets[asset.SHA256] {
			return errors.New("duplicate article asset")
		}
		assets[asset.SHA256] = true
		assetURLs[asset.URL] = true
	}
	for _, block := range article.Content {
		switch block.Type {
		case "heading", "paragraph", "list", "code", "quote", "image", "table", "divider":
		default:
			return fmt.Errorf("unknown content block %q", block.Type)
		}
		if block.Type == "image" && !c.SameOrigin(block.URL) {
			return errors.New("image block is not same-origin HTTPS")
		}
		if block.Type == "image" && !assetURLs[block.URL] {
			return errors.New("image block is absent from the asset manifest")
		}
	}
	return nil
}

func (c *Client) Sync(report func(Progress)) (*Feed, error) {
	feedBytes, err := c.getBytes(c.feedURL(), MaxFeedBytes)
	if err != nil {
		return nil, err
	}
	var feed Feed
	if err = decodeStrict(feedBytes, &feed); err != nil {
		return nil, fmt.Errorf("malformed feed: %w", err)
	}
	if err = c.validateFeed(&feed); err != nil {
		return nil, err
	}
	if feed.TotalBytes > c.maximumCache() {
		return nil, errors.New("published snapshot exceeds tablet cache ceiling")
	}
	if report == nil {
		report = func(Progress) {}
	}
	total, done := len(feed.Articles), 0
	referencedArticles, referencedAssets := map[string]bool{}, map[string]bool{}
	for _, item := range feed.Articles {
		name, nameErr := basenameFromURL(item.ArticleURL)
		if nameErr != nil {
			return nil, nameErr
		}
		if !strings.HasPrefix(name, item.ID+"-") || !strings.HasSuffix(name, "-"+item.SHA256[:16]+".json") {
			return nil, errors.New("article URL does not match its ID and checksum")
		}
		path := filepath.Join(c.DataDir, "articles", name)
		if err = c.ensureFile(item.ArticleURL, path, item.Bytes, item.SHA256); err != nil {
			return nil, err
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return nil, readErr
		}
		var article Article
		if err = decodeStrict(data, &article); err != nil {
			return nil, fmt.Errorf("malformed article %s: %w", item.ID, err)
		}
		if err = c.validateArticle(&article, item); err != nil {
			return nil, err
		}
		referencedArticles[name] = true
		total += len(article.Assets)
		done++
		report(Progress{Done: done, Total: total, Current: item.Title})
		for _, asset := range article.Assets {
			assetName, assetErr := basenameFromURL(asset.URL)
			if assetErr != nil {
				return nil, assetErr
			}
			if !strings.HasPrefix(assetName, asset.SHA256+".") {
				return nil, errors.New("asset URL does not match its checksum")
			}
			assetPath := filepath.Join(c.DataDir, "assets", assetName)
			if err = c.ensureFile(asset.URL, assetPath, asset.Bytes, asset.SHA256); err != nil {
				return nil, err
			}
			referencedAssets[assetName] = true
			done++
			report(Progress{Done: done, Total: total, Current: item.Title})
		}
	}
	// Feed is the commit point. Until this succeeds, the prior feed and every
	// file it references remain untouched and readable.
	c.cacheMu.Lock()
	defer c.cacheMu.Unlock()
	currentSize, sizeErr := c.cacheSize()
	if sizeErr != nil {
		return nil, sizeErr
	}
	oldFeedSize := int64(0)
	if info, statErr := os.Stat(filepath.Join(c.DataDir, "feed.json")); statErr == nil {
		oldFeedSize = info.Size()
	}
	if currentSize-oldFeedSize > c.maximumCache()-int64(len(feedBytes)) {
		return nil, errors.New("storage ceiling exceeded before feed commit")
	}
	if err = atomicWrite(filepath.Join(c.DataDir, "feed.json"), feedBytes, 0o600); err != nil {
		return nil, err
	}
	c.prune("articles", referencedArticles)
	c.prune("assets", referencedAssets)
	if size, sizeErr := c.cacheSize(); sizeErr != nil || size > c.maximumCache() {
		if sizeErr != nil {
			return nil, sizeErr
		}
		return nil, errors.New("cache ceiling exceeded after synchronization")
	}
	return &feed, nil
}

func (c *Client) prune(directory string, keep map[string]bool) {
	root := filepath.Join(c.DataDir, directory)
	entries, err := os.ReadDir(root)
	if err != nil {
		return
	}
	for _, entry := range entries {
		if !entry.Type().IsRegular() {
			continue
		}
		name := entry.Name()
		if strings.HasSuffix(name, ".part") || strings.HasSuffix(name, ".tmp") || !keep[name] {
			os.Remove(filepath.Join(root, name))
		}
	}
}

func (c *Client) cachedFeedUnlocked() ([]byte, *Feed, error) {
	data, err := os.ReadFile(filepath.Join(c.DataDir, "feed.json"))
	if err != nil {
		return nil, nil, err
	}
	if int64(len(data)) > MaxFeedBytes {
		return nil, nil, errors.New("cached feed is oversized")
	}
	var feed Feed
	if err = decodeStrict(data, &feed); err != nil {
		return nil, nil, err
	}
	if err = c.validateFeed(&feed); err != nil {
		return nil, nil, err
	}
	return data, &feed, nil
}

func (c *Client) CachedFeed() ([]byte, *Feed, error) {
	c.cacheMu.RLock()
	defer c.cacheMu.RUnlock()
	return c.cachedFeedUnlocked()
}

func (c *Client) LoadArticle(id string) ([]byte, error) {
	c.cacheMu.RLock()
	defer c.cacheMu.RUnlock()
	_, feed, err := c.cachedFeedUnlocked()
	if err != nil {
		return nil, err
	}
	var selected *FeedArticle
	for index := range feed.Articles {
		if feed.Articles[index].ID == id {
			selected = &feed.Articles[index]
			break
		}
	}
	if selected == nil {
		return nil, errors.New("article is not present in the cached feed")
	}
	name, err := basenameFromURL(selected.ArticleURL)
	if err != nil {
		return nil, err
	}
	path := filepath.Join(c.DataDir, "articles", name)
	digest, size, err := digestFile(path)
	if err != nil || digest != selected.SHA256 || size != selected.Bytes {
		return nil, errors.New("cached article failed integrity verification")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var article Article
	if err = decodeStrict(data, &article); err != nil {
		return nil, err
	}
	if err = c.validateArticle(&article, *selected); err != nil {
		return nil, err
	}
	assetByURL := map[string]Asset{}
	for _, asset := range article.Assets {
		assetByURL[asset.URL] = asset
	}
	for index := range article.Content {
		block := &article.Content[index]
		if block.Type != "image" {
			continue
		}
		asset, ok := assetByURL[block.URL]
		if !ok {
			block.URL = ""
			block.Damaged = true
			continue
		}
		assetName, nameErr := basenameFromURL(asset.URL)
		assetPath := filepath.Join(c.DataDir, "assets", assetName)
		actual, actualSize, verifyErr := digestFile(assetPath)
		if nameErr != nil || verifyErr != nil || actual != asset.SHA256 || actualSize != asset.Bytes {
			block.URL = ""
			block.Damaged = true
			continue
		}
		block.URL = (&url.URL{Scheme: "file", Path: assetPath}).String()
	}
	return json.Marshal(article)
}

func (c *Client) DebugFiles() ([]string, error) {
	c.cacheMu.RLock()
	defer c.cacheMu.RUnlock()
	var result []string
	err := filepath.Walk(c.DataDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.Mode().IsRegular() {
			result = append(result, path)
		}
		return nil
	})
	sort.Strings(result)
	return result, err
}
