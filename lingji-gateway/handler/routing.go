package handler

import (
	"strings"

	"github.com/AUrlius/lingji-gateway/protocol"
)

const DefaultAgentID = "lingji-pc"

// IsAgentDevice 判断 device_id 是否为 PC Agent（lingji-* 前缀，非 phone-*）
func IsAgentDevice(deviceID string) bool {
	return strings.HasPrefix(deviceID, "lingji-")
}

// resolveTargetAgentID 从上行消息 payload 解析目标 Agent，缺省为 lingji-pc
func resolveTargetAgentID(raw []byte) string {
	msg, err := protocol.ParseMessage(string(raw))
	if err != nil {
		return DefaultAgentID
	}
	if id, ok := msg.Payload["target_agent_id"].(string); ok && id != "" {
		return id
	}
	return DefaultAgentID
}
