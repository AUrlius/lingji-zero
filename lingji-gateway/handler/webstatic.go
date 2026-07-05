package handler

import "net/http"

// NoCacheStatic wraps a file server so HTML/JS/CSS are not long-cached at CDN edges.
func NoCacheStatic(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-cache, must-revalidate")
		next.ServeHTTP(w, r)
	})
}
