FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev 2>/dev/null || npm install --omit=dev
COPY src ./src
ENV LINGJI_PORT=8766
EXPOSE 8766
CMD ["node", "src/index.js"]
