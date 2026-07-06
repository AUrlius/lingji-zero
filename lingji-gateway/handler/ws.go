package handler

import (
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/hub"
	"github.com/AUrlius/lingji-gateway/protocol"
	"github.com/AUrlius/lingji-gateway/queue"
	"github.com/AUrlius/lingji-gateway/store"
	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
	CheckOrigin:     func(r *http.Request) bool { return true },
}

type WSHandler struct {
	hub    *hub.Hub
	config *config.Config
	queue  *queue.OfflineQueue
	inbox  *store.InboxStore
	fleet  *FleetHandler
}

func NewWSHandler(h *hub.Hub, cfg *config.Config, q *queue.OfflineQueue, inbox *store.InboxStore, fleet *FleetHandler) *WSHandler {
	return &WSHandler{hub: h, config: cfg, queue: q, inbox: inbox, fleet: fleet}
}

func (h *WSHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// 支持两种鉴权方式：Authorization header（Agent）和 ?token= 查询参数（浏览器）
	authOK := h.config.AuthToken == "" // 未启用鉴权则放行
	if !authOK {
		if authHeader := r.Header.Get("Authorization"); authHeader == "Bearer "+h.config.AuthToken {
			authOK = true
		}
	}
	if !authOK {
		if tokenParam := r.URL.Query().Get("token"); tokenParam == h.config.AuthToken {
			authOK = true
		}
	}
	if !authOK {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("[WS] 升级失败: %v", err)
		return
	}

	conn.SetReadLimit(h.config.MaxMessageSize)

	pongWait := 60 * time.Second
	client := &hub.Client{
		DeviceID: "pending-" + r.RemoteAddr,
		Conn:     conn,
		Send:     make(chan []byte, 64),
		Hub:      h.hub,
		LastBeat: time.Now(),
	}

	conn.SetReadDeadline(time.Now().Add(pongWait))
	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(pongWait))
		client.UpdateHeartbeat()
		return nil
	})

	h.hub.Register(client)

	go h.writePump(client)
	go h.readPump(client)
}

func (h *WSHandler) readPump(c *hub.Client) {
	defer func() {
		h.hub.Unregister(c)
		c.Conn.Close()
	}()

	for {
		_, raw, err := c.Conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				log.Printf("[WS] 读错误: %v", err)
			}
			break
		}

		msg, err := protocol.ParseMessage(string(raw))
		if err != nil {
			log.Printf("[WS] 消息解析失败: %v", err)
			continue
		}

		c.UpdateHeartbeat()

		if msg.MsgType == protocol.MsgAuthReq {
			// Token 认证
			if h.config.AuthToken != "" {
				clientToken, _ := msg.Payload["token"].(string)
				if clientToken != h.config.AuthToken {
					log.Printf("[WS] 认证失败: token 不匹配 (device=%s)", msg.DeviceID)
					reply := protocol.NewMessage(protocol.MsgAgentRes, "gateway", map[string]any{
						"text":   "auth_failed",
						"status": "rejected",
					})
					if data, err := reply.ToJSON(); err == nil {
						c.Send <- []byte(data)
					}
					// 延迟关闭，让客户端收到拒绝消息
					go func() {
						time.Sleep(500 * time.Millisecond)
						c.Conn.Close()
					}()
					continue
				}
			}

			newID, ok := msg.Payload["device_id"].(string)
			if ok && newID != "" {
				userID, _ := msg.Payload["user_id"].(string)
				if userID == "" {
					userID = newID
				}
				oldID := c.DeviceID
				c.DeviceID = newID
				c.UserID = userID
				h.hub.ReRegister(c, oldID)
				log.Printf("[WS] 设备认证: %s → %s (user=%s)", oldID, newID, userID)

				h.deliverOfflineMessages(c)

				reply := protocol.NewMessage(protocol.MsgAgentRes, "gateway", map[string]any{
					"text":   "auth_ok",
					"status": "connected",
				})
				if data, err := reply.ToJSON(); err == nil {
					c.Send <- []byte(data)
				}
			}
			continue
		}

		if msg.MsgType == protocol.MsgHeartbeat {
			continue
		}

		h.routeMessage(msg.MsgType, msg.DeviceID, raw)
	}
}

func (h *WSHandler) writePump(c *hub.Client) {
	ticker := time.NewTicker(10 * time.Second)
	defer func() {
		ticker.Stop()
		c.Conn.Close()
	}()

	for {
		select {
		case data, ok := <-c.Send:
			if !ok {
				c.Conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			c.Conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := c.Conn.WriteMessage(websocket.TextMessage, data); err != nil {
				log.Printf("[WS] 写错误: %v", err)
				return
			}

		case <-ticker.C:
			c.Conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := c.Conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

func (h *WSHandler) routeMessage(msgType protocol.MsgType, fromDevice string, raw []byte) {
	CaptureWSMessage(h.inbox, string(msgType), fromDevice, raw)

	switch msgType {
	case protocol.MsgCmdText, protocol.MsgCmdListSessions:
		pcID := resolveTargetAgentID(raw)
		if !h.hub.SendToDevice(pcID, raw) {
			log.Printf("[Route] Agent %s 不在线，消息入离线队列", pcID)
			h.queue.Enqueue(pcID, string(raw))
			h.notifyDelayed(fromDevice, pcID)
		}

	case protocol.MsgAgentRes:
		DeliverDownstream(h.hub, h.queue, raw)

	case protocol.MsgHitlReq:
		DeliverDownstream(h.hub, h.queue, raw)

	case protocol.MsgHitlRes:
		pcID := resolveTargetAgentID(raw)
		if !h.hub.SendToDevice(pcID, raw) {
			log.Printf("[Route] HITL_RES 目标 Agent %s 不在线，入离线队列", pcID)
			h.queue.Enqueue(pcID, string(raw))
		}

	case protocol.MsgFleetAck:
		if h.fleet != nil {
			h.fleet.HandleAck(fromDevice, raw)
		}
	}
}

func (h *WSHandler) deliverOfflineMessages(c *hub.Client) {
	keys := []string{c.DeviceID}
	if c.UserID != "" && c.UserID != c.DeviceID {
		keys = append(keys, c.UserID)
	}
	seen := make(map[string]struct{})
	for _, key := range keys {
		if key == "" {
			continue
		}
		if _, dup := seen[key]; dup {
			continue
		}
		seen[key] = struct{}{}
		msgs := h.queue.DequeueAll(key)
		if len(msgs) == 0 {
			continue
		}
		log.Printf("[Queue] 投递 %d 条离线消息给 %s (conn=%s user=%s)", len(msgs), key, c.DeviceID, c.UserID)
		for _, msg := range msgs {
			select {
			case c.Send <- []byte(msg):
			default:
				log.Printf("[Queue] 离线消息投递失败 (buffer full): %s", key)
			}
		}
	}
}

func (h *WSHandler) notifyDelayed(toDevice, agentID string) {
	text := fmt.Sprintf("PC (%s) 当前不在线，消息已缓存，上线后将自动投递。", agentID)
	reply := protocol.NewMessage(protocol.MsgAgentRes, "gateway", map[string]any{
		"text":             text,
		"status":           "queued",
		"target_device_id": toDevice,
		"target_agent_id":  agentID,
	})
	if data, err := reply.ToJSON(); err == nil {
		h.hub.SendToDevice(toDevice, []byte(data))
	}
}

// deliverDownstream 将 AGENT_RES / HITL_REQ 投递到 target_user_id（多端）或 target_device_id（单连接）。
func (h *WSHandler) deliverDownstream(raw []byte) {
	DeliverDownstream(h.hub, h.queue, raw)
}
