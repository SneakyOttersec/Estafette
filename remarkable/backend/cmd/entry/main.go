package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/SneakyOttersec/Estafette/remarkable/backend/internal/protocol"
	"github.com/SneakyOttersec/Estafette/remarkable/backend/internal/syncer"
)

const (
	requestFeed      = 100
	requestRefresh   = 101
	requestArticle   = 102
	responseFeed     = 200
	responseArticle  = 201
	responseProgress = 202
	responseComplete = 203
	responseError    = 400
)

func payload(value any) string { data, _ := json.Marshal(value); return string(data) }

func sendError(connection *protocol.Connection, code string, err error) {
	connection.Send(responseError, payload(map[string]string{"code": code, "message": err.Error()}))
}

func errorCode(err error) string {
	message := strings.ToLower(err.Error())
	if strings.Contains(message, "storage") || strings.Contains(message, "ceiling") || strings.Contains(message, "no space") || strings.Contains(message, "permission denied") || strings.Contains(message, "read-only file system") {
		return "storage"
	}
	for _, marker := range []string{"schema", "malformed", "checksum", "integrity", "same-origin", "cross-origin", "invalid", "mismatch"} {
		if strings.Contains(message, marker) {
			return "validation"
		}
	}
	return "network"
}

func dataDirectory() string {
	if value := os.Getenv("ESTAFETTE_DATA_DIR"); value != "" {
		return value
	}
	home, err := os.UserHomeDir()
	if err != nil {
		home = "/home/root"
	}
	return filepath.Join(home, ".local", "share", "estafette")
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "AppLoad socket argument is required")
		os.Exit(2)
	}
	connection, err := protocol.Dial(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer connection.Close()
	client := syncer.New(dataDirectory())
	var refreshMu sync.Mutex
	refreshing := false
	for {
		message, receiveErr := connection.Receive()
		if receiveErr != nil {
			return
		}
		switch message.Type {
		case protocol.SystemTerminate:
			return
		case protocol.SystemNewCoordinator:
			continue
		case requestFeed:
			data, _, loadErr := client.CachedFeed()
			if loadErr != nil {
				sendError(connection, "offline", loadErr)
			} else {
				connection.Send(responseFeed, string(data))
			}
		case requestArticle:
			var request struct {
				ID string `json:"id"`
			}
			if json.Unmarshal([]byte(message.Contents), &request) != nil || request.ID == "" {
				sendError(connection, "validation", fmt.Errorf("article ID is required"))
				continue
			}
			data, loadErr := client.LoadArticle(request.ID)
			if loadErr != nil {
				sendError(connection, "validation", loadErr)
			} else {
				connection.Send(responseArticle, string(data))
			}
		case requestRefresh:
			refreshMu.Lock()
			if refreshing {
				refreshMu.Unlock()
				continue
			}
			refreshing = true
			refreshMu.Unlock()
			go func() {
				defer func() { refreshMu.Lock(); refreshing = false; refreshMu.Unlock() }()
				feed, syncErr := client.Sync(func(progress syncer.Progress) { connection.Send(responseProgress, payload(progress)) })
				if syncErr != nil {
					sendError(connection, errorCode(syncErr), syncErr)
					return
				}
				data, _ := json.Marshal(feed)
				connection.Send(responseFeed, string(data))
				connection.Send(responseComplete, payload(map[string]any{"generated_at": feed.GeneratedAt, "articles": len(feed.Articles)}))
			}()
		default:
			sendError(connection, "validation", fmt.Errorf("unsupported message type %d", message.Type))
		}
	}
}
