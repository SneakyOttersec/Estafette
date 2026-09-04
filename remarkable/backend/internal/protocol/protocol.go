// Package protocol implements AppLoad's two-record SOCK_SEQPACKET protocol.
package protocol

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"sync"
)

const (
	SystemTerminate      uint32 = 0xffffffff
	SystemNewCoordinator uint32 = 0xfffffffe
	MaxPayload                  = 10 * 1024 * 1024
)

type Message struct {
	Type     uint32
	Contents string
}

type Connection struct {
	c       *net.UnixConn
	writeMu sync.Mutex
}

func Dial(path string) (*Connection, error) {
	connection, err := net.DialUnix("unixpacket", nil, &net.UnixAddr{Name: path, Net: "unixpacket"})
	if err != nil {
		return nil, err
	}
	return &Connection{c: connection}, nil
}

func (c *Connection) Close() error { return c.c.Close() }

func (c *Connection) Receive() (Message, error) {
	header := make([]byte, 8)
	n, _, err := c.c.ReadFromUnix(header)
	if err != nil {
		return Message{}, err
	}
	if n != len(header) {
		return Message{}, fmt.Errorf("short AppLoad header: %d", n)
	}
	typ := binary.LittleEndian.Uint32(header[:4])
	length := binary.LittleEndian.Uint32(header[4:])
	if length > MaxPayload {
		return Message{}, errors.New("AppLoad payload exceeds limit")
	}
	size := int(length)
	if size == 0 {
		size = 1 // force recvmsg to consume AppLoad's empty second record
	}
	payload := make([]byte, size)
	n, _, err = c.c.ReadFromUnix(payload)
	if err != nil {
		if length == 0 && errors.Is(err, io.EOF) && n == 0 {
			return Message{Type: typ}, nil
		}
		return Message{}, err
	}
	if n != int(length) {
		return Message{}, io.ErrUnexpectedEOF
	}
	return Message{Type: typ, Contents: string(payload[:length])}, nil
}

func (c *Connection) Send(typ uint32, contents string) error {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	payload := []byte(contents)
	if len(payload) > MaxPayload {
		return errors.New("AppLoad payload exceeds limit")
	}
	header := make([]byte, 8)
	binary.LittleEndian.PutUint32(header[:4], typ)
	binary.LittleEndian.PutUint32(header[4:], uint32(len(payload)))
	if _, err := c.c.Write(header); err != nil {
		return err
	}
	if len(payload) > 0 {
		_, err := c.c.Write(payload)
		return err
	}
	return nil
}
