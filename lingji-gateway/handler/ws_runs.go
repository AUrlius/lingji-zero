package handler

import (
	"encoding/json"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

var runsUpgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
	CheckOrigin:     func(r *http.Request) bool { return true },
}

// RunWSHub 管理 H1 /v1/ws/runs 的 WebSocket 客户端
type RunWSHub struct {
	mu      sync.RWMutex
	clients map[*RunWSClient]struct{}
}

// RunWSClient 代表一个 /v1/ws/runs 连接
type RunWSClient struct {
	conn      *websocket.Conn
	send      chan []byte
	filterRun string // 可选：只接收此 run_id 的事件
	hub       *RunWSHub
}

// NewRunWSHub 创建 RunWSHub
func NewRunWSHub() *RunWSHub {
	return &RunWSHub{
		clients: make(map[*RunWSClient]struct{}),
	}
}

// Len 返回当前连接的 WS 客户端数
func (h *RunWSHub) Len() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}

// Broadcast 向所有 H1 WS 客户端广播事件
func (h *RunWSHub) Broadcast(event RunEvent) {
	data, err := json.Marshal(event)
	if err != nil {
		log.Printf("[RunWS] 序列化事件失败: %v", err)
		return
	}

	h.mu.RLock()
	defer h.mu.RUnlock()

	for client := range h.clients {
		// 如果客户端有 run_id 过滤，只发送匹配事件
		if client.filterRun != "" && event.RunID != client.filterRun {
			continue
		}
		select {
		case client.send <- data:
		default:
			log.Printf("[RunWS] 客户端 send buffer 满，断开")
			go h.remove(client)
		}
	}
}

func (h *RunWSHub) add(client *RunWSClient) {
	h.mu.Lock()
	h.clients[client] = struct{}{}
	h.mu.Unlock()
	log.Printf("[RunWS] 客户端连接 (当前: %d)", len(h.clients))
}

func (h *RunWSHub) remove(client *RunWSClient) {
	h.mu.Lock()
	delete(h.clients, client)
	h.mu.Unlock()
	log.Printf("[RunWS] 客户端断开 (当前: %d)", len(h.clients))
}

// ServeWS 处理 GET /v1/ws/runs
func (r *RunRegistry) ServeWS(w http.ResponseWriter, req *http.Request) {
	conn, err := runsUpgrader.Upgrade(w, req, nil)
	if err != nil {
		log.Printf("[RunWS] 升级失败: %v", err)
		return
	}

	filterRun := req.URL.Query().Get("run_id")

	client := &RunWSClient{
		conn:      conn,
		send:      make(chan []byte, 64),
		filterRun: filterRun,
		hub:       r.wsHub,
	}

	r.wsHub.add(client)

	// 回放最近 20 条事件
	go r.replayEvents(client)

	go r.runWritePump(client)
	go r.runReadPump(client)
}

// replayEvents 向新连接的客户端回放最近事件
func (r *RunRegistry) replayEvents(client *RunWSClient) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	var backlog []RunEvent
	if client.filterRun != "" {
		evs := r.events[client.filterRun]
		if len(evs) > 20 {
			evs = evs[len(evs)-20:]
		}
		backlog = evs
	} else {
		// 收集所有 run 的事件，按时间排序取最近 20 条
		for _, evs := range r.events {
			backlog = append(backlog, evs...)
		}
		if len(backlog) > 20 {
			backlog = backlog[len(backlog)-20:]
		}
	}

	for _, event := range backlog {
		data, err := json.Marshal(event)
		if err != nil {
			continue
		}
		select {
		case client.send <- data:
		default:
			return
		}
	}
}

func (r *RunRegistry) runReadPump(c *RunWSClient) {
	defer func() {
		c.hub.remove(c)
		c.conn.Close()
	}()

	c.conn.SetReadLimit(65536)
	c.conn.SetReadDeadline(time.Now().Add(60 * time.Second))
	c.conn.SetPongHandler(func(string) error {
		c.conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		return nil
	})

	for {
		_, _, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				log.Printf("[RunWS] 读错误: %v", err)
			}
			break
		}
	}
}

func (r *RunRegistry) runWritePump(c *RunWSClient) {
	ticker := time.NewTicker(10 * time.Second)
	defer func() {
		ticker.Stop()
		c.conn.Close()
	}()

	for {
		select {
		case data, ok := <-c.send:
			if !ok {
				c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := c.conn.WriteMessage(websocket.TextMessage, data); err != nil {
				log.Printf("[RunWS] 写错误: %v", err)
				return
			}

		case <-ticker.C:
			c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}
