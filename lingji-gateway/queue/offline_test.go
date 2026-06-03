package queue

import (
	"testing"
)

func TestEnqueueDequeue(t *testing.T) {
	q := NewOfflineQueue(10)

	q.Enqueue("device-1", "msg-1")
	q.Enqueue("device-1", "msg-2")
	q.Enqueue("device-1", "msg-3")

	if l := q.Len("device-1"); l != 3 {
		t.Errorf("Len = %d, want 3", l)
	}

	msgs := q.DequeueAll("device-1")
	if len(msgs) != 3 {
		t.Errorf("DequeueAll length = %d, want 3", len(msgs))
	}
	if msgs[0] != "msg-1" || msgs[1] != "msg-2" || msgs[2] != "msg-3" {
		t.Errorf("message order wrong: %v", msgs)
	}

	// 取出后队列应空
	if l := q.Len("device-1"); l != 0 {
		t.Errorf("Len after dequeue = %d, want 0", l)
	}
}

func TestDequeueEmpty(t *testing.T) {
	q := NewOfflineQueue(10)
	msgs := q.DequeueAll("nobody")
	if msgs != nil {
		t.Errorf("DequeueAll on empty queue should return nil, got %v", msgs)
	}
}

func TestRingBufferOverflow(t *testing.T) {
	q := NewOfflineQueue(3) // max 3

	q.Enqueue("d", "1")
	q.Enqueue("d", "2")
	q.Enqueue("d", "3")
	q.Enqueue("d", "4") // should evict "1"
	q.Enqueue("d", "5") // should evict "2"

	msgs := q.DequeueAll("d")
	if len(msgs) != 3 {
		t.Errorf("got %d messages, want 3", len(msgs))
	}
	// 应该保留最新的 3 条: 3, 4, 5
	if msgs[0] != "3" || msgs[1] != "4" || msgs[2] != "5" {
		t.Errorf("overflow order wrong: %v (expected [3 4 5])", msgs)
	}
}

func TestMultiDevice(t *testing.T) {
	q := NewOfflineQueue(10)

	q.Enqueue("a", "a1")
	q.Enqueue("b", "b1")
	q.Enqueue("a", "a2")

	if l := q.Len("a"); l != 2 {
		t.Errorf("device a Len = %d, want 2", l)
	}
	if l := q.Len("b"); l != 1 {
		t.Errorf("device b Len = %d, want 1", l)
	}

	// 只取 a 的消息，b 不受影响
	msgsA := q.DequeueAll("a")
	if len(msgsA) != 2 {
		t.Errorf("a messages = %d, want 2", len(msgsA))
	}

	if l := q.Len("b"); l != 1 {
		t.Errorf("b should still have 1 message after a dequeue")
	}
}
