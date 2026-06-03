package protocol

import (
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

// MsgType 消息类型枚举（与 Python protocol.py MsgType 对齐）
type MsgType string

const (
	MsgAuthReq  MsgType = "AUTH_REQ"
	MsgHeartbeat MsgType = "HEARTBEAT"
	MsgCmdText  MsgType = "CMD_TEXT"
	MsgCmdListSessions MsgType = "CMD_LIST_SESSIONS"
	MsgHitlReq  MsgType = "HITL_REQ"
	MsgHitlRes  MsgType = "HITL_RES"
	MsgAgentRes MsgType = "AGENT_RES"
)

// Message 协议消息（与 Python protocol.py Message 对齐）
// Python 侧: Pydantic BaseModel, 字段自动映射为 snake_case JSON key
type Message struct {
	MsgID     string         `json:"msg_id"`
	MsgType   MsgType        `json:"msg_type"`
	DeviceID  string         `json:"device_id"`
	Timestamp float64        `json:"timestamp"`
	Payload   map[string]any `json:"payload"`
}

// NewMessage 创建消息（自动填充 msg_id 和 timestamp）
func NewMessage(msgType MsgType, deviceID string, payload map[string]any) *Message {
	if payload == nil {
		payload = make(map[string]any)
	}
	return &Message{
		MsgID:     uuid.New().String(),
		MsgType:   msgType,
		DeviceID:  deviceID,
		Timestamp: float64(time.Now().UnixMilli()) / 1000.0,
		Payload:   payload,
	}
}

// ToJSON 序列化为 JSON 字符串（与 Python to_json() 对齐）
func (m *Message) ToJSON() (string, error) {
	data, err := json.Marshal(m)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

// FromJSON 从 JSON 字符串反序列化（与 Python from_json() 对齐）
func FromJSON(raw string) (*Message, error) {
	var msg Message
	if err := json.Unmarshal([]byte(raw), &msg); err != nil {
		return nil, err
	}
	return &msg, nil
}

// ParseMessage 多态反序列化（与 Python parse_message() 对齐）
func ParseMessage(raw string) (*Message, error) {
	return FromJSON(raw)
}
