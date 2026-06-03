package hub

import (
	"sync"
	"testing"
	"time"
)

// newTestHub 创建测试 Hub，返回 hub + cleanup
func newTestHub(timeout time.Duration) (*Hub, func()) {
	h := New(timeout)
	go h.Run()
	return h, func() {
		h.Stop()
		h.Wait()
	}
}

func TestHubRegisterUnregister(t *testing.T) {
	h, cleanup := newTestHub(30 * time.Second)
	defer cleanup()

	c1 := &Client{DeviceID: "device-1", Send: make(chan []byte, 8), LastBeat: time.Now()}
	c2 := &Client{DeviceID: "device-2", Send: make(chan []byte, 8), LastBeat: time.Now()}

	h.Register(c1)
	h.Register(c2)
	time.Sleep(10 * time.Millisecond)

	if h.Len() != 2 {
		t.Errorf("Len() = %d, want 2", h.Len())
	}

	devices := h.OnlineDevices()
	if len(devices) != 2 {
		t.Errorf("OnlineDevices() = %d, want 2", len(devices))
	}

	h.Unregister(c1)
	time.Sleep(10 * time.Millisecond)

	if h.Len() != 1 {
		t.Errorf("Len() after unregister = %d, want 1", h.Len())
	}
	if c := h.GetClient("device-1"); c != nil {
		t.Error("GetClient(device-1) should be nil after unregister")
	}
	if c := h.GetClient("device-2"); c == nil {
		t.Error("GetClient(device-2) should still exist")
	}
}

func TestHubReplaceDuplicateDevice(t *testing.T) {
	h, cleanup := newTestHub(30 * time.Second)
	defer cleanup()

	send1 := make(chan []byte, 8)
	c1 := &Client{DeviceID: "dup-device", Send: send1, LastBeat: time.Now()}
	h.Register(c1)
	time.Sleep(10 * time.Millisecond)

	send2 := make(chan []byte, 8)
	c2 := &Client{DeviceID: "dup-device", Send: send2, LastBeat: time.Now()}
	h.Register(c2)
	time.Sleep(10 * time.Millisecond)

	if h.Len() != 1 {
		t.Errorf("Len() = %d, want 1", h.Len())
	}

	// 旧连接的 Send channel 应该被关闭
	select {
	case _, ok := <-send1:
		if ok {
			t.Error("old client's Send channel should be closed")
		}
	default:
		t.Error("old client's Send channel should be closed (not blocking)")
	}
}

func TestHubSendToDevice(t *testing.T) {
	h, cleanup := newTestHub(30 * time.Second)
	defer cleanup()

	send := make(chan []byte, 8)
	c := &Client{DeviceID: "target", Send: send, LastBeat: time.Now()}
	h.Register(c)
	time.Sleep(10 * time.Millisecond)

	if !h.SendToDevice("target", []byte("hello")) {
		t.Error("SendToDevice should succeed")
	}

	select {
	case data := <-send:
		if string(data) != "hello" {
			t.Errorf("received = %s, want hello", string(data))
		}
	default:
		t.Error("expected message on Send channel")
	}

	if h.SendToDevice("nobody", []byte("x")) {
		t.Error("SendToDevice(nobody) should return false")
	}
}

func TestHubBroadcastToAll(t *testing.T) {
	h, cleanup := newTestHub(30 * time.Second)
	defer cleanup()

	ch1 := make(chan []byte, 8)
	ch2 := make(chan []byte, 8)
	c1 := &Client{DeviceID: "a", Send: ch1, LastBeat: time.Now()}
	c2 := &Client{DeviceID: "b", Send: ch2, LastBeat: time.Now()}
	h.Register(c1)
	h.Register(c2)
	time.Sleep(10 * time.Millisecond)

	h.BroadcastToAll([]byte("broadcast"), "")

	for i, ch := range []chan []byte{ch1, ch2} {
		select {
		case data := <-ch:
			if string(data) != "broadcast" {
				t.Errorf("device %d: received %s, want broadcast", i, string(data))
			}
		default:
			t.Errorf("device %d: expected broadcast message", i)
		}
	}
}

func TestHubExcludeBroadcast(t *testing.T) {
	h, cleanup := newTestHub(30 * time.Second)
	defer cleanup()

	ch1 := make(chan []byte, 8)
	ch2 := make(chan []byte, 8)
	c1 := &Client{DeviceID: "a", Send: ch1, LastBeat: time.Now()}
	c2 := &Client{DeviceID: "b", Send: ch2, LastBeat: time.Now()}
	h.Register(c1)
	h.Register(c2)
	time.Sleep(10 * time.Millisecond)

	h.BroadcastToAll([]byte("secret"), "a")

	// a 不应收到
	select {
	case <-ch1:
		t.Error("device a should NOT receive excluded broadcast")
	default:
		// expected
	}

	// b 应收到
	select {
	case <-ch2:
		// expected
	default:
		t.Error("device b should receive broadcast")
	}
}

func TestHubHeartbeatCheck(t *testing.T) {
	h, cleanup := newTestHub(50 * time.Millisecond)
	defer cleanup()

	var wg sync.WaitGroup

	// 注册"活着"的设备
	alive := make(chan []byte, 8)
	c1 := &Client{DeviceID: "alive", Send: alive, LastBeat: time.Now()}
	h.Register(c1)

	// 注册"死了"的设备
	dead := make(chan []byte, 8)
	c2 := &Client{DeviceID: "dead", Send: dead, LastBeat: time.Now().Add(-100 * time.Millisecond)}
	h.Register(c2)
	time.Sleep(10 * time.Millisecond)

	// 心跳更新 goroutine 保持 alive 存活
	wg.Add(1)
	go func() {
		defer wg.Done()
		ticker := time.NewTicker(20 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				c1.UpdateHeartbeat()
			case <-h.done:
				return
			}
		}
	}()

	// 等待心跳检查踢出 dead
	time.Sleep(150 * time.Millisecond)

	if c := h.GetClient("alive"); c == nil {
		t.Error("alive device should still be connected")
	}
	if c := h.GetClient("dead"); c != nil {
		t.Error("dead device should be kicked by heartbeat check")
	}
}

func TestHubStop(t *testing.T) {
	h, cleanup := newTestHub(30 * time.Second)
	defer cleanup()

	send := make(chan []byte, 8)
	c := &Client{DeviceID: "test", Send: send, LastBeat: time.Now()}
	h.Register(c)
	time.Sleep(10 * time.Millisecond)

	h.Stop()
	h.Wait()
	time.Sleep(10 * time.Millisecond)

	select {
	case _, ok := <-send:
		if ok {
			t.Error("Send channel should be closed after Stop")
		}
	default:
		// expected
	}
}
