package protocol

import (
	"encoding/binary"
	"net"
	"path/filepath"
	"testing"
)

func TestTwoRecordFraming(t *testing.T) {
	path := filepath.Join(t.TempDir(), "appload.sock")
	listener, err := net.ListenUnix("unixpacket", &net.UnixAddr{Name: path, Net: "unixpacket"})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	done := make(chan error, 1)
	go func() {
		server, err := listener.AcceptUnix()
		if err != nil {
			done <- err
			return
		}
		defer server.Close()
		header := make([]byte, 8)
		binary.LittleEndian.PutUint32(header[:4], 100)
		binary.LittleEndian.PutUint32(header[4:], 2)
		if _, err = server.Write(header); err == nil {
			_, err = server.Write([]byte("{}"))
		}
		done <- err
	}()
	client, err := Dial(path)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	message, err := client.Receive()
	if err != nil {
		t.Fatal(err)
	}
	if message.Type != 100 || message.Contents != "{}" {
		t.Fatalf("unexpected message: %#v", message)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestOversizedHeaderIsRejected(t *testing.T) {
	path := filepath.Join(t.TempDir(), "appload.sock")
	listener, err := net.ListenUnix("unixpacket", &net.UnixAddr{Name: path, Net: "unixpacket"})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	go func() {
		server, acceptErr := listener.AcceptUnix()
		if acceptErr != nil {
			return
		}
		defer server.Close()
		header := make([]byte, 8)
		binary.LittleEndian.PutUint32(header[4:], MaxPayload+1)
		server.Write(header)
	}()
	client, err := Dial(path)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if _, err = client.Receive(); err == nil {
		t.Fatal("expected oversized packet error")
	}
}

func TestEmptySecondRecordIsConsumedBeforeTheNextHeader(t *testing.T) {
	path := filepath.Join(t.TempDir(), "appload-empty.sock")
	listener, err := net.ListenUnix("unixpacket", &net.UnixAddr{Name: path, Net: "unixpacket"})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	go func() {
		server, acceptErr := listener.AcceptUnix()
		if acceptErr != nil {
			return
		}
		defer server.Close()
		emptyHeader := make([]byte, 8)
		binary.LittleEndian.PutUint32(emptyHeader[:4], 100)
		server.Write(emptyHeader)
		server.Write([]byte{})
		nextHeader := make([]byte, 8)
		binary.LittleEndian.PutUint32(nextHeader[:4], 101)
		binary.LittleEndian.PutUint32(nextHeader[4:], 2)
		server.Write(nextHeader)
		server.Write([]byte("{}"))
	}()
	client, err := Dial(path)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	first, err := client.Receive()
	if err != nil || first.Type != 100 || first.Contents != "" {
		t.Fatalf("unexpected empty message: %#v %v", first, err)
	}
	second, err := client.Receive()
	if err != nil || second.Type != 101 || second.Contents != "{}" {
		t.Fatalf("empty record corrupted next message: %#v %v", second, err)
	}
}
