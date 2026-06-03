# lingji-gateway — Sprint 6 / 三期 3.3 本地 compose 镜像
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /lingji-gateway .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates wget
COPY --from=build /lingji-gateway /usr/local/bin/lingji-gateway
ENV LINGJI_PORT=8765
EXPOSE 8765
HEALTHCHECK --interval=5s --timeout=3s --retries=6 \
  CMD wget -qO- "http://127.0.0.1:${LINGJI_PORT}/health" | grep -q ok || exit 1
CMD ["lingji-gateway"]
