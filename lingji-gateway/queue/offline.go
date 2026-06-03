package queue

import (
	"log"
	"sync"
)

// OfflineQueue 离线消息环形缓冲区（按设备隔离）
type OfflineQueue struct {
	mu       sync.RWMutex
	buffers  map[string]*RingBuffer
	maxSize  int
}

// RingBuffer 单设备环形缓冲区
type RingBuffer struct {
	data    []string
	head    int
	tail    int
	size    int
	maxSize int
	mu      sync.Mutex
}

// NewOfflineQueue 创建离线队列
func NewOfflineQueue(maxSize int) *OfflineQueue {
	return &OfflineQueue{
		buffers: make(map[string]*RingBuffer),
		maxSize: maxSize,
	}
}

// Enqueue 向指定设备的队列添加消息
func (q *OfflineQueue) Enqueue(deviceID string, msg string) {
	q.mu.Lock()
	buf, ok := q.buffers[deviceID]
	if !ok {
		buf = newRingBuffer(q.maxSize)
		q.buffers[deviceID] = buf
	}
	q.mu.Unlock()

	buf.enqueue(msg)
}

// DequeueAll 取出指定设备的所有离线消息（取出后清空）
func (q *OfflineQueue) DequeueAll(deviceID string) []string {
	q.mu.RLock()
	buf, ok := q.buffers[deviceID]
	q.mu.RUnlock()
	if !ok {
		return nil
	}

	msgs := buf.dequeueAll()
	if len(msgs) > 0 {
		log.Printf("[Queue] 设备 %s: 取出 %d 条离线消息", deviceID, len(msgs))
	}
	return msgs
}

// Len 返回某设备的队列长度
func (q *OfflineQueue) Len(deviceID string) int {
	q.mu.RLock()
	buf, ok := q.buffers[deviceID]
	q.mu.RUnlock()
	if !ok {
		return 0
	}
	return buf.len()
}

// newRingBuffer 创建环形缓冲区
func newRingBuffer(maxSize int) *RingBuffer {
	return &RingBuffer{
		data:    make([]string, maxSize),
		maxSize: maxSize,
	}
}

func (r *RingBuffer) enqueue(msg string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if r.size == r.maxSize {
		// 队列满，覆盖最旧的消息
		log.Printf("[Queue] 队列满(%d)，覆盖旧消息", r.maxSize)
		r.head = (r.head + 1) % r.maxSize
		r.size--
	}

	r.data[r.tail] = msg
	r.tail = (r.tail + 1) % r.maxSize
	r.size++
}

func (r *RingBuffer) dequeueAll() []string {
	r.mu.Lock()
	defer r.mu.Unlock()

	if r.size == 0 {
		return nil
	}

	result := make([]string, 0, r.size)
	for i := 0; i < r.size; i++ {
		idx := (r.head + i) % r.maxSize
		result = append(result, r.data[idx])
	}

	// 清空
	r.head = 0
	r.tail = 0
	r.size = 0

	return result
}

func (r *RingBuffer) len() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.size
}
