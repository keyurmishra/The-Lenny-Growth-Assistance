# =============================================================================
# Frontend Dockerfile — Vite React Dev Server
# =============================================================================
# DECISION: Node 20 LTS slim
#   LTS = long-term support, widely tested. Slim avoids bloat.
# =============================================================================

FROM node:20-slim

WORKDIR /app

# Copy package files first for layer caching
COPY package*.json ./
RUN npm install

# Copy source code
COPY . .

EXPOSE 5173

# Vite dev server with host binding for Docker
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
