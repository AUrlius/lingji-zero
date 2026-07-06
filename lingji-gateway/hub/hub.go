package hub

import (
	"log"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// Client 代表一个已连接的设备
type Client struct {
	DeviceID  string // Web: conn-* 连接 ID；Agent: lingji-*
	UserID    string // Web: user-* 账号（多连接共享）；Agent 为空则同 DeviceID
	Conn      *websocket.Conn
	Send      chan []byte
	Hub       *Hub
	LastBeat  time.Time
	mu        sync.Mutex
}

// Hub 管理所有 WebSocket 连接
type Hub struct {
	mu       sync.RWMutex
	clients  map[string]*Client // deviceID → Client

	register   chan *Client
	unregister chan *Client

	heartbeatTimeout time.Duration
	stopCh           chan struct{}
	done             chan struct{}
	stopOnce         sync.Once
}

// New 创建 Hub
func New(heartbeatTimeout time.Duration) *Hub {
	return &Hub{
		clients:          make(map[string]*Client),
		register:         make(chan *Client, 32),
		unregister:       make(chan *Client, 32),
		heartbeatTimeout: heartbeatTimeout,
		stopCh:           make(chan struct{}),
		done:             make(chan struct{}),
	}
}

// Run 启动 Hub 主循环（阻塞，应作为 goroutine 运行）
func (h *Hub) Run() {
	// 心跳检查定时器
	heartbeatTicker := time.NewTicker(h.heartbeatTimeout / 2)
	defer heartbeatTicker.Stop()

	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			// 如果已有同 deviceID 的连接，踢掉旧的
			if old, exists := h.clients[client.DeviceID]; exists {
				log.Printf("[Hub] 踢掉旧连接: %s", client.DeviceID)
				close(old.Send)
				if old.Conn != nil {
					old.Conn.Close()
				}
			}
			h.clients[client.DeviceID] = client
			h.mu.Unlock()
			log.Printf("[Hub] 设备注册: %s (当前在线: %d)", client.DeviceID, len(h.clients))

		case client := <-h.unregister:
			h.mu.Lock()
			if c, ok := h.clients[client.DeviceID]; ok && c == client {
				delete(h.clients, client.DeviceID)
				log.Printf("[Hub] 设备注销: %s (当前在线: %d)", client.DeviceID, len(h.clients))
			}
			h.mu.Unlock()

		case <-heartbeatTicker.C:
			h.checkHeartbeats()

		case <-h.stopCh:
			h.mu.Lock()
			for id, c := range h.clients {
				close(c.Send)
				if c.Conn != nil {
					c.Conn.Close()
				}
				delete(h.clients, id)
			}
			h.mu.Unlock()
			log.Println("[Hub] 已停止")
			close(h.done)
			return
		}
	}
}

// Stop 停止 Hub（幂等，可多次调用）
func (h *Hub) Stop() {
	h.stopOnce.Do(func() {
		close(h.stopCh)
	})
}

// Wait 等待 Hub 完全停止
func (h *Hub) Wait() {
	<-h.done
}

// Register 将客户端注册到 Hub
func (h *Hub) Register(c *Client) {
	h.register <- c
}

// ReRegister 更换设备 ID（先删旧 key 再加新 key，原子操作）
func (h *Hub) ReRegister(c *Client, oldDeviceID string) {
	h.mu.Lock()
	// 删除旧 key
	delete(h.clients, oldDeviceID)
	// 如果新 key 已有旧连接，踢掉
	if old, exists := h.clients[c.DeviceID]; exists {
		close(old.Send)
		if old.Conn != nil {
			old.Conn.Close()
		}
	}
	h.clients[c.DeviceID] = c
	h.mu.Unlock()
	log.Printf("[Hub] 设备重注册: %s → %s (当前在线: %d)", oldDeviceID, c.DeviceID, len(h.clients))
}

// Unregister 从 Hub 注销客户端
func (h *Hub) Unregister(c *Client) {
	h.unregister <- c
}

// Len 返回当前在线设备数
func (h *Hub) Len() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}

// GetClient 获取指定设备的连接
func (h *Hub) GetClient(deviceID string) *Client {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return h.clients[deviceID]
}

// SendToDevice 向指定设备连接发送消息
func (h *Hub) SendToDevice(deviceID string, data []byte) bool {
	h.mu.RLock()
	c, ok := h.clients[deviceID]
	h.mu.RUnlock()
	if !ok {
		return false
	}
	select {
	case c.Send <- data:
		return true
	default:
		// Send buffer 满，视为断线
		log.Printf("[Hub] 设备 %s Send buffer 满，强制断开", deviceID)
		h.Unregister(c)
		return false
	}
}

// SendToUser 向同一 user_id 的所有 Web 连接广播（Fleet 多入口）
func (h *Hub) SendToUser(userID string, data []byte) int {
	if userID == "" {
		return 0
	}
	h.mu.RLock()
	targets := make([]*Client, 0)
	for _, c := range h.clients {
		uid := c.UserID
		if uid == "" {
			uid = c.DeviceID
		}
		if uid == userID {
			targets = append(targets, c)
		}
	}
	h.mu.RUnlock()

	sent := 0
	for _, c := range targets {
		select {
		case c.Send <- data:
			sent++
		default:
			log.Printf("[Hub] 用户 %s 连接 %s buffer 满", userID, c.DeviceID)
		}
	}
	return sent
}

// BroadcastToAll 向所有在线设备广播消息
func (h *Hub) BroadcastToAll(data []byte, excludeDevice string) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for id, c := range h.clients {
		if id == excludeDevice {
			continue
		}
		select {
		case c.Send <- data:
		default:
			log.Printf("[Hub] 广播失败: %s (buffer full)", id)
		}
	}
}

// ForwardMessage 转发消息：A → B
// 如果 B 在线则直接发送，不在线则返回 false
func (h *Hub) ForwardMessage(fromDevice, toDevice string, data []byte) bool {
	return h.SendToDevice(toDevice, data)
}

// checkHeartbeats 检查心跳超时，踢出僵尸连接
func (h *Hub) checkHeartbeats() {
	now := time.Now()
	h.mu.RLock()
	var zombies []*Client
	for _, c := range h.clients {
		c.mu.Lock()
		last := c.LastBeat
		c.mu.Unlock()
		if now.Sub(last) > h.heartbeatTimeout {
			zombies = append(zombies, c)
		}
	}
	h.mu.RUnlock()

	for _, c := range zombies {
		log.Printf("[Hub] 心跳超时踢出: %s", c.DeviceID)
		go h.Unregister(c)
	}
}

// UpdateHeartbeat 更新客户端心跳时间
func (c *Client) UpdateHeartbeat() {
	c.mu.Lock()
	c.LastBeat = time.Now()
	c.mu.Unlock()
}

// OnlineDevices 返回所有在线设备 ID 列表
func (h *Hub) OnlineDevices() []string {
	h.mu.RLock()
	defer h.mu.RUnlock()
	ids := make([]string, 0, len(h.clients))
	for id := range h.clients {
		ids = append(ids, id)
	}
	return ids
}
