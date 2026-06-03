package protocol

import (
	"encoding/json"
	"testing"
)

func TestNewMessage(t *testing.T) {
	payload := map[string]any{"text": "hello"}
	msg := NewMessage(MsgCmdText, "test-device", payload)

	if msg.MsgID == "" {
		t.Error("msg_id should not be empty")
	}
	if msg.MsgType != MsgCmdText {
		t.Errorf("msg_type = %s, want CMD_TEXT", msg.MsgType)
	}
	if msg.DeviceID != "test-device" {
		t.Errorf("device_id = %s, want test-device", msg.DeviceID)
	}
	if msg.Timestamp == 0 {
		t.Error("timestamp should not be 0")
	}
	if text, ok := msg.Payload["text"].(string); !ok || text != "hello" {
		t.Errorf("payload.text = %v, want hello", msg.Payload["text"])
	}
}

func TestNewMessageNilPayload(t *testing.T) {
	msg := NewMessage(MsgHeartbeat, "dev", nil)
	if msg.Payload == nil {
		t.Error("payload should be initialized to empty map, not nil")
	}
}

func TestToJSON(t *testing.T) {
	msg := NewMessage(MsgAgentRes, "pc", map[string]any{"result": "ok"})
	jsonStr, err := msg.ToJSON()
	if err != nil {
		t.Fatalf("ToJSON error: %v", err)
	}

	// Verify all keys present
	var raw map[string]any
	if err := json.Unmarshal([]byte(jsonStr), &raw); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}

	required := []string{"msg_id", "msg_type", "device_id", "timestamp", "payload"}
	for _, key := range required {
		if _, ok := raw[key]; !ok {
			t.Errorf("missing key: %s", key)
		}
	}
	if raw["msg_type"] != "AGENT_RES" {
		t.Errorf("msg_type = %v, want AGENT_RES", raw["msg_type"])
	}
}

func TestFromJSON(t *testing.T) {
	raw := `{"msg_id":"abc-123","msg_type":"HEARTBEAT","device_id":"sensor-1","timestamp":1717000000.5,"payload":{}}`

	msg, err := FromJSON(raw)
	if err != nil {
		t.Fatalf("FromJSON error: %v", err)
	}
	if msg.MsgID != "abc-123" {
		t.Errorf("msg_id = %s, want abc-123", msg.MsgID)
	}
	if msg.MsgType != MsgHeartbeat {
		t.Errorf("msg_type = %s, want HEARTBEAT", msg.MsgType)
	}
	if msg.DeviceID != "sensor-1" {
		t.Errorf("device_id = %s, want sensor-1", msg.DeviceID)
	}
}

func TestFromJSONInvalid(t *testing.T) {
	_, err := FromJSON("not json")
	if err == nil {
		t.Error("expected error for invalid JSON")
	}
}

func TestParseMessage(t *testing.T) {
	raw := `{"msg_id":"xyz","msg_type":"AUTH_REQ","device_id":"phone","timestamp":1.0,"payload":{"token":"secret"}}`

	msg, err := ParseMessage(raw)
	if err != nil {
		t.Fatalf("ParseMessage error: %v", err)
	}
	if msg.MsgType != MsgAuthReq {
		t.Errorf("msg_type = %s, want AUTH_REQ", msg.MsgType)
	}
}

func TestRoundTrip(t *testing.T) {
	original := NewMessage(MsgHitlReq, "pc", map[string]any{
		"action": "delete",
		"path":   "/tmp/test",
	})

	jsonStr, err := original.ToJSON()
	if err != nil {
		t.Fatalf("ToJSON: %v", err)
	}

	parsed, err := FromJSON(jsonStr)
	if err != nil {
		t.Fatalf("FromJSON: %v", err)
	}

	if parsed.MsgID != original.MsgID {
		t.Error("msg_id mismatch after round-trip")
	}
	if parsed.MsgType != original.MsgType {
		t.Error("msg_type mismatch after round-trip")
	}
	if parsed.DeviceID != original.DeviceID {
		t.Error("device_id mismatch after round-trip")
	}
}

func TestAllMsgTypes(t *testing.T) {
	types := []MsgType{MsgAuthReq, MsgHeartbeat, MsgCmdText, MsgCmdListSessions, MsgHitlReq, MsgHitlRes, MsgAgentRes}
	for _, mt := range types {
		msg := NewMessage(mt, "test", nil)
		if msg.MsgType != mt {
			t.Errorf("MsgType round-trip failed: got %s, want %s", msg.MsgType, mt)
		}
	}
}
