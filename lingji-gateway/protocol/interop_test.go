package protocol

import (
	"encoding/json"
	"os"
	"testing"
)

// TestInteropParsePythonJSON Go 解析 Python 生成的 JSON
func TestInteropParsePythonJSON(t *testing.T) {
	// 文件由 Python 端生成: python -c "Message(...).to_json()"
	data, err := os.ReadFile("/tmp/py_msg.json")
	if err != nil {
		t.Skipf("skipping interop test: %v (run Python side first)", err)
	}

	msg, err := ParseMessage(string(data))
	if err != nil {
		t.Fatalf("Go failed to parse Python JSON: %v", err)
	}

	if msg.MsgID != "interop-test-001" {
		t.Errorf("msg_id = %s, want interop-test-001", msg.MsgID)
	}
	if msg.MsgType != MsgCmdText {
		t.Errorf("msg_type = %s, want CMD_TEXT", msg.MsgType)
	}
	if msg.DeviceID != "phone-001" {
		t.Errorf("device_id = %s, want phone-001", msg.DeviceID)
	}
	if msg.Timestamp != 1717000000.123 {
		t.Errorf("timestamp = %f, want 1717000000.123", msg.Timestamp)
	}

	text, ok := msg.Payload["text"].(string)
	if !ok || text != "hello from python" {
		t.Errorf("payload.text = %v, want 'hello from python'", msg.Payload["text"])
	}

	// seq 在 JSON 中是 number，Go 的 json.Unmarshal 默认解析为 float64
	seq, ok := msg.Payload["seq"].(float64)
	if !ok || int(seq) != 42 {
		t.Errorf("payload.seq = %v (type=%T), want 42", msg.Payload["seq"], msg.Payload["seq"])
	}

	t.Logf("✅ Go ↔ Python interop: msg_id=%s msg_type=%s device_id=%s",
		msg.MsgID, msg.MsgType, msg.DeviceID)
}

// TestInteropGoJSONForPython Go 生成 JSON，写入文件供 Python 验证
func TestInteropGoJSONForPython(t *testing.T) {
	msg := NewMessage(MsgAgentRes, "lingji-pc", map[string]any{
		"text":   "hello from go",
		"status": "success",
	})
	msg.MsgID = "go-interop-001"
	msg.Timestamp = 1717000001.456

	jsonStr, err := msg.ToJSON()
	if err != nil {
		t.Fatalf("ToJSON error: %v", err)
	}

	// Verify it's valid JSON
	var raw map[string]any
	if err := json.Unmarshal([]byte(jsonStr), &raw); err != nil {
		t.Fatalf("Go generated invalid JSON: %v", err)
	}

	// Write for Python side to read
	if err := os.WriteFile("/tmp/go_msg.json", []byte(jsonStr), 0644); err != nil {
		t.Fatalf("failed to write /tmp/go_msg.json: %v", err)
	}

	t.Logf("✅ Go → Python JSON: %s", jsonStr)
}
